# Slice 02 — Charge resolver and assembled JSON

## Register 1 — INTENT (lay language)

### What this slice builds

This slice turns one complete charge into one prompt package. A caller names the
work, how it will run, and its material. The resolver chooses the matching job
and, for a discussion, the matching seat. It returns instructions, questions,
reply sections, and substitution requirements as one assembled JSON document.

This slice also converts the reviewed prompt corpus to accepted amendment B1.
Only `draft_skeleton` carries catalogue-backed plan-creation instructions.
`draft_slice_note` and `implement` have no optional producer-planning fragment,
planning discriminator, or reply `slices`: an ordinary call and one whose work
happens to edit the canonical plan resolve the same prompt law. The later
canonical-plan boundary observes the repository edit; routing does not grant it.
The single `rethink` job still mounts the existing document or implementation
craft units from the originating target's required artifact type; collapsing its
two former ids does not collapse their target-typed law.
The affected stored corpus, generated seed, renderer, and goldens are recaptured
together.

Missing information that belongs to a mounted job stops the request. Optional
run context may leave its complete framing unit out. Every non-empty material
name is accepted; the shipped set has no real material addition, while a
synthetic layer proves future data-only extension.

Nothing is sent to a worker yet. This slice provides a pure prompt-resolution
boundary for later validation, canonical-plan enforcement, service, milestone,
and discussion work.

### Ownership and boundary

Owned here are B1's corpus/seed/golden conversion, charge admission, canonical
job selection, executor and seat selection, storage-driven mounting, material
layering, fully inlined JSON assembly, and the variable-substitution contract.
The selected prompt-set fallback indication remains beside the answer.

Not owned here are canonical-plan extraction, validation, anchoring, projection,
or pre-dispatch drift blocking; Slice 3 owns that boundary. Also deferred are
reply validation, question-answer validation, run prompt-set binding, worker
dispatch, prompt traces, and replacement of current builders. This slice can
resolve a valid discussion charge but does not open, order, authorize, or run a
session.

### Guarantee posture

- **Strict — one charge, one assembled answer.** A successful request resolves
  one canonical job and emits one fully inlined prompt JSON. Callers cannot pass
  raw variants, fragment ids, optional-unit switches, or planning controls.
- **Strict — no routing-based plan authority.** `draft_skeleton` alone mounts
  catalogue-backed plan creation. `draft_slice_note`, `implement`, reviews,
  fixers, and seats never gain or lose prompt law from an intent to edit the
  plan, and no assembled output contract carries `slices`.
- **Strict — unified rethink, target-typed craft.** `rethink` is the sole rethink
  job. Its required orchestrator-derived artifact type mounts the existing
  document or implementation craft units; a seat cannot supply or override that
  type, the other target's units remain absent, and the type grants no edit or
  plan authority.
- **Strict — charge and substitution completeness.** Executor/material/seat
  coordinates must be valid; every mounted job-required value must be present;
  fixed route values cannot be overridden; a missing drop-enabled run value
  removes its whole unit; declared defaults remain available to the consumer.
- **Strict — material isolation.** The complete base mounts first. Only an exact
  material layer may add to it; no match is successful, note-free inheritance.
  Invalid layer data makes its prompt-set rung unreadable.
- **Strict — whole-rung provenance.** Assembly uses only the set selected by
  Slice 1 and preserves its fallback indication outside the prompt JSON.
- **Best-effort — edit visibility.** Each request inherits Slice 1's fresh-read
  and same-rung race posture. Once returned, that answer does not change.
- **Optimistic / eventual / delivery — none.** This slice stores no state,
  resolves no conflict, waits for no convergence, and dispatches no call.

### Dependencies and consumers

Slice 1's complete selected prompt set is the only earlier-slice dependency.
This slice updates the release corpus and seed as one reviewed representation;
the new assembled result is consumed here only by focused tests. Slice 3 is the
first contract and plan-boundary consumer. Current builders, service routes,
panel state, runner calls, and exact prompt recording remain unchanged.

### Non-goals

- No canonical-plan block parser, Git anchor, state projection, drift gate,
  recovery, or read-only mutation exception.
- No worker-output validator, registered section registry, or QUESTIONS answer
  enforcement.
- No prompt-set run binding, service route, panel control, worker dispatch, or
  trace write.
- No session state, turn ordering, readiness, or Git behavior.
- No real material-specific layer, material catalogue, staffing change,
  model/effort choice, or rigor rule.
- No cache, version, snapshot, migration, retry, notification, or second store.
- No edit in any granted read-only repository.

### Acceptance and size

Acceptance proves the converted corpus/seed/goldens, closed job matrix, preserved
target-typed craft under the single rethink id, uniform plan-editing posture,
route-derived direct and discussion composition, inlined JSON schema,
required/default/drop substitutions, exact material inheritance and synthetic
addition, whole-rung provenance, and reviewed render equivalence. Existing
prompt tests prove no current runtime consumer moved.

Table-driven routes and goldens should keep non-mechanical implementation near
the roughly 500 changed-line aim. Corpus conversion, generated seed updates, and
golden recapture are mechanical and do not count.

### Risks

The material risks are retaining an optional planning lane, mapping a valid job
to the wrong craft law, losing target-typed craft law when the rethink ids
collapse, letting a caller select a fragment, leaving reply `slices` in one
contract, leaking storage controls onto the wire, drawing a required payload
from a weaker rung, dropping only part of a run-context unit, or treating an
unknown material as failure. Exact corpus assertions, the route matrix, shape
traversal, defect fixtures, marked layers, and goldens pin these boundaries.

### Reuse Posture

Later prompt consumers and canonical-plan enforcement depend on one trustworthy
charge answer; wrong assembly can waste a call, while a planning discriminator
would recreate the dual authority B1 forbids. There is no runtime exposure yet
and the work is reversible before cutover. The reviewed skeleton and B1 are the
independent authority. Checked capabilities remain Slice 1's selector/validator,
the corpus assembler and goldens, existing executor/seat vocabulary and
target-type slots, current Git-backed document edits, and staffing's base/exact
layering precedent. The cheapest sufficient option is to remove optional
producer planning and reply `slices`, preserve the existing target-typed units
behind the single `rethink` job, keep ordinary document editing, recapture one
corpus/seed/golden set, and add no plan discriminator. The only remaining new
machinery is the stateless route/assembler consumed by later slices; it adds one
mapping surface and no migration, daemon, cache, history, or operating service.
Omitting the conversion preserves ambiguous prompt authority; a caller-authored
selector costs more and violates B1.

### Planning-context disposition

**Adopts** the reviewed skeleton and accepted amendment B1. **Revises** the
adapted corpus decisions that made producer planning optional, returned reply
`slices`, or split rethink routing. **Uses** earlier prompt captures only to
prove the recaptured observable text. **Rejects** other brainstorming and
`_drafts` material as authority.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Charge and route identity | A charge is `(job, executor, material)` with a non-empty open material key. Direct `agent_call` jobs are exactly `draft_skeleton@skeleton`, `review_round@skeleton`, `fix_findings@skeleton`, `delta_review@skeleton`, `draft_slice_note@slice_doc`, `review_round@slice_doc`, `fix_findings@slice_doc`, `delta_review@slice_doc`, `implement@slice_impl`, `review_round@slice_impl`, `fix_findings@slice_impl`, `delta_review@slice_impl`, `reclassify@doc`, `suite_checkpoint@workspace`, and `merge_repair@workspace`. `brainstorming` resolves only `draft_slice_note@slice_doc`, `implement@slice_impl`, or the single orchestrator-opened `rethink` session. That rethink context requires the originating target's artifact type, exactly `document` or `implementation`; it is not a second rethink id. Each seat supplies `(role, lead)`: roles are exactly `initial_position`, `contrary_position`, and `common_sense`; `lead` is true only for `initial_position`. The first two roles emit `discussion_turn`; `common_sense` emits `questioner_turn`. | `implementation/milestones/prompt-router/skeleton.md:142,150`; preserved target-type law `implementation/milestones/prompt-router/goal.md:133-148`; direct ids `implementation/brainstorming/prompt-router/prompt-content-milestone.md:37-44`; role ids `orchestrator/brainstorming.py:35-36`; accepted amendment B1 | touch one closed pure resolver, existing target-type slots, and storage selection metadata; do-not-let callers pass a kind fragment, raw variant, target-type override, planning flag, or session kind in place of the canonical job |
| Canonical-plan prompt posture | `draft_skeleton` alone mounts the required executor catalogue and plan-creation law. No other job or seat mounts `producer_planning`, accepts a planning discriminator, or emits reply `slices`. The same valid route coordinates and, for `rethink`, the same originating target type always assemble the same craft units regardless of whether the eventual repository edit changes the canonical block. | `implementation/milestones/prompt-router/skeleton.md:146-147,154`; accepted amendment B1 | touch the corpus, generated seed, renderer, and goldens; do-not-add replacement plan authority or pull Slice 3's block enforcement forward |
| Assembled prompt JSON | The prompt object has exactly `kind`, `instructions`, `questions`, and `output_contract`. Instruction parts and contract sections are ordered inline units with local variable declarations; questions are ordered intro lines and `{id,text}` items. Route-fixed values are applied. No ref, variant, optional, note, default-control, material-control, process, fallback, or plan-authority data reaches this object. | `implementation/milestones/prompt-router/skeleton.md:147`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:23-26,34-65` | touch assembly and its cross-slice result; do-not-return storage documents or rendered legacy strings |
| Mounting and variables | Canonical job and executor/seat coordinates derive route and role variants. For the single `rethink` job, the required orchestrator-derived target type mounts only the existing document or implementation craft units. Otherwise the charge supplies substitution values, not selection controls. A missing required value rejects, a missing `drop_unit_if_absent` run value removes the whole unit, a declared default keeps the unit, and unrelated values change nothing. QUESTIONS remain data until Slice 3. | `implementation/milestones/prompt-router/skeleton.md:142,146`; preserved target-type slots `implementation/milestones/prompt-router/goal.md:133-148`; `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:69-98`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:39-59` | touch route-derived mounting and substitution checks; do-not-expose validation code, hand-pick fragments, accept a target-type override, or infer plan authority from target type or payload presence |
| Material layering | Every non-empty material id resolves. Base mounts first; an exact stored layer appends its ordered instructions, questions, and sections. No exact layer returns unchanged base with no note. The release ships no real layer; a synthetic `code` layer works without route-code changes. Malformed layers or duplicate assembled ids make the rung unreadable. | `implementation/milestones/prompt-router/skeleton.md:146`; `implementation/milestones/prompt-router/goal.md:44-53,318-322` | touch the generic data seam and whole-set validation; do-not-add a catalogue, special-case `code`, or copy staffing admission semantics |
| Selected-set provenance and freshness | Each request assembles only the `PromptSet` returned by named → stored `default` → in-code seed selection. Route, corpus, or layer defects reject a rung before assembly. `prompt_set_fallback` stays beside the prompt and is unchanged by ordinary material inheritance. Each request reads afresh with Slice 1's consistency posture. | `orchestrator/prompt_sets.py:397-469`; `implementation/milestones/prompt-router/skeleton.md:96-101,145,147` | touch the existing selector and preserve its sidecar; do-not-mix rungs, retry a charge error against another rung, or store assembly history |
| Slice boundary and external vocabulary | This slice converts the corpus/seed/goldens and adds pure resolution plus focused tests. It adds no plan parser, HTTP route, event, state field, panel field, public error code, worker dispatch, trace, or output validator. Existing builders remain runtime authority until their assigned cutovers. | accepted amendment B1; current consumers `orchestrator/driver.py:7664-7714,9981-10035`; trace boundary `orchestrator/runners.py:1663-1676,1754-1757` | touch prompt corpus, seed, resolution/assembly, renderer, goldens, and focused tests only; do-not-edit current consumers or granted external roots |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_prompt_router orchestrator.tests.test_prompt_sets orchestrator.tests.test_prompts`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| B1 corpus, seed, and goldens are one representation | new `test_canonical_plan_corpus_seed_and_goldens_are_recaptured` | Parsed stored default and generated seed are equal; only `draft_skeleton` contains producer-planning law; no contract contains reply `slices`; split rethink or planning-control vocabulary is absent; reviewed goldens match the converted renderer. | strict |
| The canonical matrix alone chooses every route | new `test_canonical_charge_matrix_derives_routes_without_raw_controls` | Every listed direct and discussion charge resolves to its plain kind and declared units; the single rethink route accepts both required originating target types, while split rethink routes, missing or overridden rethink target type, unknown jobs/executors, empty material, invalid seat coordinates, and raw selection inputs fail without an answer. | strict |
| Plan-editing intent never changes mounted law | new `test_plan_editing_has_no_prompt_discriminator` | `draft_slice_note` and `implement` assemble without producer planning or reply `slices`; adding former plan-authority fields or option maps is rejected, and identical route coordinates produce identical mounted units. | strict |
| Seat and rethink-target context mount only applicable law | new `test_session_coordinates_and_rethink_target_type_mount_only_applicable_law` | Author, contrary, and questioner fixtures for document and implementation producers plus both target types of the single rethink job contain applicable shared and target-typed law with no law belonging to another seat or target; lead job questions mount where declared. | strict |
| The wire object is fully assembled and renders reviewed text | new `test_assembled_json_schema_and_reviewed_goldens` | Exact-key traversal finds only the canonical schema and no storage, fallback, or plan controls; representative substitutions render the reviewed direct and session examples byte-for-byte. | strict |
| Required, fixed, defaulted, and dropped substitutions differ | new `test_substitution_contract_required_default_and_drop` | Missing job payload fails; fixed values cannot change; missing defaulted value keeps its unit; missing drop-enabled run value removes the whole unit; unrelated supplied values do nothing. | strict |
| Material ids are open and exact layers are data-only | new `test_material_base_inheritance_and_synthetic_exact_layer` | Arbitrary no-match ids produce identical base and no note; only the synthetic exact `code` layer receives marked instruction, question, and section once in base-then-layer order. | strict |
| Invalid route or layer metadata loses one whole rung | new `test_invalid_route_or_material_layer_falls_as_one_set` | One bad selector, malformed layer, or duplicate assembled id falls named → default and default → seed without mixing or repairing bytes; no-match inheritance does not fall. | strict rung / best-effort visibility |
| Slice 1 provenance survives assembly | new `test_assembly_preserves_selected_set_and_fallback_sidecar` plus existing `test_fallback_selects_one_complete_rung` | Distinct rung markers prove every unit came from the selected set, the sidecar stays outside the prompt, and a completed edit appears on the next request. | strict rung / best-effort visibility |
| Current runtime consumers do not move | existing `orchestrator.tests.test_prompts` | Legacy builder outputs and dispatch-facing expectations pass unchanged; no service, driver, runner, trace, staffing, or contract assertion is rewritten for this slice. | strict compatibility |

The repository's official full suite remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:544-546`). It remains owned by the scheduled checkpoint,
not this focused implementation gate.

### Question Battery

The skeleton's Question Battery is **INHERITED**. These are the slice-scoped
remainder; enforceability is answered again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** Slice 1's selected `PromptSet`, corpus and seed representations, authoring renderer/goldens, existing target-type slots, and focused assembly tests. **Verified untouched:** current driver builders, dispatch, tracing, service/panel/state, output validators, and staffing; Slice 3 first consumes plan and reply ids. | `orchestrator/prompt_sets.py:346-469`; `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:69-98`; `orchestrator/driver.py:7664-7714,9981-10035`; `orchestrator/runners.py:1663-1676,1754-1757`; accepted amendment B1 |
| pinned_facts | Closed canonical routes and seats; one rethink id with required originating target type and preserved target-typed craft law; draft-skeleton-only plan creation with no plan discriminator or reply `slices`; exact four-key inlined JSON; route-derived mounting and substitution behavior; open material layering; one-rung provenance; and no runtime cutover. | `implementation/milestones/prompt-router/skeleton.md:142,145-147,150,154`; accepted amendment B1 |
| verification | Ten named checks pin synchronized conversion, plan-law uniformity, route/seat/target matrices, schema and goldens, substitutions, materials, invalid-data fallback, provenance/freshness, and unchanged runtime consumers. The focused command names the exact modules; full discovery remains checkpoint-owned. | this note, Verification Contract; `orchestrator/README.md:544-546` |
| reuse_posture | B1 requires one document-backed plan and forbids a routing authority. Reused are the selected-set validator, corpus renderer/goldens, executor/seat vocabulary, existing target-type slots, Git-backed edits, and staffing layering. Cheapest sufficient is synchronized removal/recapture plus one stateless assembler; no caller selector, migration, or service is justified. | accepted amendment B1; `orchestrator/prompt_sets.py:229-469`; `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:69-98`; `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-272`; `orchestrator/tasks.py:41-100`; `orchestrator/staffing.py:1655-1668,1763-1779` |
| enforceability | Closed routes reject raw selection inputs; required rethink target-type fixtures pin the preserved craft slots; exact corpus assertions prove the planning lane and reply field are absent; the whole-set validator and renderer enforce selection/assembly; marked layers pin material order; Slice 1 pins provenance. No reply, dispatch, plan-boundary, state, cache, snapshot, or convergence guarantee is asserted here. | `orchestrator/prompt_sets.py:229-469`; `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:69-98`; `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-266`; `orchestrator/tests/test_prompt_sets.py:67-241`; accepted amendment B1 |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Plan intent cannot select prompt law | Removing optional producer planning and reply `slices` from the current corpus, seed, route schema, and renderer leaves no accepted input or output lane; ordinary repository editing remains outside this resolver. | Reject former planning fields/options, compare identical route coordinates, and traverse all converted contracts for absence. |
| Only canonical charge/seat combinations assemble | A closed route map can reuse exact-map admission at `orchestrator/tasks.py:41-103,693-725`; the existing target-type slots mount document or implementation law for the single rethink id; the corpus validator closes stored selector structure. | Exercise the accepted matrix and one mutation of every input axis; require both rethink target types to remain isolated and reject a missing or caller-overridden type before assembly. |
| The answer is ordered inlined JSON with declared substitutions | The corpus renderer already performs ref expansion, selection, required/default/drop handling, and ordered rendering at `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-266`. | Exact-key traversal rejects every storage control; representative renders compare with recaptured goldens. |
| Invalid stored routes or layers cannot yield a partial prompt | The existing all-member corpus walk and whole-set eligibility boundary at `orchestrator/prompt_sets.py:346-469` validates all selection/layer data before assembly. | Corrupt one selection or layer fact at a time, mark every rung, and require whole-rung fallback with unchanged bytes. |
| Unknown materials inherit base; exact layers add once | Exact-key lookup over a weakest-first stack is already expressible by `orchestrator/staffing.py:1655-1668,1763-1779`; prompt admission omits catalogue membership. | Compare arbitrary no-match ids, then add only synthetic `code` markers and assert order and uniqueness. |
| Set provenance and fallback survive assembly | Slice 1's selected result and sidecar are produced afresh by `orchestrator/prompt_sets.py:397-469`; assembly consumes that one result and writes nothing. | Distinct rung/edit sentinels prove no mixing, unchanged sidecar location, no repair/history, and changed second answer after a completed edit. |

There is deliberately no enforcement row for reply correctness, worker delivery,
prompt tracing, canonical-plan anchoring, run binding, service availability,
session lifecycle, semantic prose meaning, or cross-call consistency: this slice
asserts none of them.
