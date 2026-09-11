# Slice 01 — Order and per-job staffing contract

## Register 1 — INTENT

This slice gives the operator a precise way to describe how much exploration
to fund and what staffing level to request for each kind of work. Preparing
the search, judging proposals, and adding possibilities can use different
staffing settings while sharing the operator's existing session. Choosing a
setting for one request must leave other work under that session alone.

It owns the accepted configuration, the shape of a readable final result, and
the connection between each job and existing staffing choices. These contracts
are usable and testable before the search exists. They depend on the shared
task contracts and Staffing Router; they need no new service or dependency.

The slice does not run a search, call models, write prompts, create checkpoints,
or publish a creativity order form. It does not choose numeric defaults or
change task controls, access, or accounting. Those boundaries keep this a small
preparatory delivery. The main risks are accidentally changing existing
staffing behavior and making a well-shaped result look like proof that the
search ran correctly. Structural checks cannot prove creative quality or the
truth of a model's assumptions.

## Register 2 — PINNED-FACTS TABLE

The following are implementation acceptance contracts, not claims that the new
behavior already exists. T1–T6 below name their verification. Guarantees are
**strict** at these contract boundaries unless a row marks another posture.

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Delivery boundary | Independently callable creativity configuration, job-binding, and native-result contracts are this slice's handoff. Public executor id `creativity` remains deferred: the existing catalogue and generic task admission do not offer it in Slice 1. Numeric catalogue defaults remain a Slice 10 evidence decision; this slice accepts complete numeric configurations and does not manufacture defaults. T1, T6. | `implementation/milestones/creativity/skeleton.md:122,130-131,144`; existing catalogue guard `orchestrator/tasks.py:1085-1092`; catalogue test `orchestrator/tests/test_tasks.py:85-95` | touch the existing task-contract surface in `orchestrator/tasks.py`, Staffing Router, its existing resolve adapter, and focused tests; do-not-touch prompt registration/corpus, search execution, host lifecycle, panel, accounting, access, stored schemas, or any additional root; no new runtime dependency (`implementation/milestones/creativity/skeleton.md:63-76,123-130,149`) |
| F2 — Closed configuration | Exactly twelve numeric controls: `population_size`, `generation_limit`, `max_evaluated_candidates`, `elite_count`, `diversity_count`, `mutation_rate`, `minimum_improvement`, `patience_generations`, `max_stagnation_expansions`, `evaluation_batch_size`, `evaluation_concurrency`, `shortlist_size`; plus optional `rigor`. Reject missing required controls, unknown fields, or a non-object with `invalid_task_request`. Accepted supplied values retain their meaning without clamping. T1. | `implementation/milestones/creativity/skeleton.md:139,144`; closed-object/error seam `orchestrator/tasks.py:435-481`; specialized configuration precedent `orchestrator/tasks.py:897-932` | extend one creativity configuration contract; retain other executors' resolution behavior; no second configuration channel |
| F3 — Admissibility | Count controls are positive integers, excluding booleans; `population_size >= 2`; `elite_count + diversity_count <= population_size`; batch and shortlist sizes each do not exceed population; evaluation budget covers population. `mutation_rate` and `minimum_improvement` are finite numbers in `(0,1]`, excluding booleans. No additional process-global ceiling or score-target control. These are admission guarantees; enforcing work limits during execution is outside this slice. T1. | `implementation/milestones/creativity/skeleton.md:80-85,144`; integer distinction `orchestrator/tasks.py:589-596`; finite-number precedent `orchestrator/tasks.py:1649-1663`; JSON-number enforcement `orchestrator/kvstore.py:196-203` | reuse existing closed-value/numeric validation conventions; do-not-copy the generic resolver's integer-floor behavior into creativity |
| F4 — Per-job choice | `rigor` is a closed object with optional `default`, `create_genes`, `evaluate_candidates`, `expand_genes` entries, each `low`, `medium`, or `high`. Omission/empty object preserves inheritance. Precedence: job choice > task default > live session rigor. Job bindings are `create_genes`: `role="plan", index=1`; `evaluate_candidates`: `role="review", index=1, review_breadth=1`; `expand_genes`: `role="brainstorm", index=1`. Family/model/effort come from Staffing Router. T1, T3. | `implementation/milestones/creativity/skeleton.md:143`; available vocabulary `orchestrator/staffing.py:92-99`; one-family review mechanism `orchestrator/staffing.py:1990-2006,2076-2092` | add the job-to-request contract beside task configuration; do-not-add roles, model names, an ensemble, or an admission-time copy of session rigor |
| F5 — Scoped Staffing Router input | `staffing.resolve` accepts optional request `rigor` with those three choices. Omission retains existing behavior; a supplied choice selects only this resolution's tuning. Resolution changes no session/document and creates no session. Its answer remains exactly `{agent,model,effort}` with existing fallback metadata beside it in `Resolution`. Material/session overrides, availability, collapse, saturation, step-up, fallback and surfaced conditions retain their existing meanings. **Optimistic live reads:** completed saves affect subsequent resolution; no transaction across session/document authorities and no change to a returned answer. T3, T4. | `implementation/milestones/creativity/skeleton.md:91-96,143`; current signature/result `orchestrator/staffing.py:2045-2103`; layered tuning `orchestrator/staffing.py:1782-1798,1843-1856`; fresh reads `orchestrator/staffing.py:2019-2038`; existing no-write test `orchestrator/tests/test_staffing_sessions.py:946-980` | extend existing resolution, including its own input validation; do-not-wrap its trusted answer in a second validator, edit/copy sessions to simulate scope, or cache staffing |
| F6 — Existing staffing HTTP seam | `POST /api/staffing/sessions/<id>/resolve` admits the same optional `rigor` in addition to its current request fields. Successful HTTP response stays `{ok:true,staffing:{agent,model,effort}}`. Invalid supplied rigor uses `400 invalid_staffing_request`; existing conditions stay `503 staffing_unavailable` and `409 distinct_families_unsatisfiable`. Existing session access checks remain authoritative. T5, T6. | shared-request extension `implementation/milestones/creativity/skeleton.md:143`; current allowed fields `orchestrator/service.py:2145-2150`; adapter/errors `orchestrator/service.py:2133-2142,2299-2330`; route/response `orchestrator/service.py:6397-6404` | extend the existing field allowlist/adapter; do-not-add a route, event, error token, or authorization layer |
| F7 — Native result | Exactly `outcome`, `proposals`, `stop_reason`, `generations_completed`, `evaluated_candidates`, `expansion_interventions`. Counts are non-negative integers, excluding booleans; proposals are a list bounded by the supplied `shortlist_size`. Outcome is `proposals` iff the list is non-empty, otherwise `no_valid_candidates`. Stop vocabulary is exactly `generation_limit`, `evaluation_budget`, `persistent_stagnation`, `repertoire_exhausted`. Either normal outcome fits task `success`; operational failure/cancellation retain task `failure`. T2. | `implementation/milestones/creativity/skeleton.md:145-146`; common envelope `orchestrator/tasks.py:1621-1647,1677-1695` | add the producer-owned creativity native-result structural validator; retain generic `validate_result`'s executor-opaque `native_result`; no lifecycle transition or runtime stop-selection logic in this slice |
| F8 — Proposal record and proof limit | Each proposal is exactly `{candidate_id,components,proposal,reason,assumptions,score}`. IDs/text are non-empty strings; assumptions are a possibly empty list of non-empty strings; score is finite in `[0,1]`, excluding booleans. Components are an ordered list of exactly `{dimension_id,dimension,variant_id,variant}`, covering each supplied dimension once with its selected variant and readable material text; candidate IDs and genomes are unique in the shortlist. The producer supplies trusted dimension/variant context and the shortlist bound; their own schemas are not re-admitted here. These checks establish representation only. Valid-candidate selection and truthful counters/stop reasons require the later search producer. Semantic validity, feasibility and creative quality remain **best-effort**, and scores are evaluations, not probabilities. T2. | result-shape assignment `implementation/milestones/creativity/skeleton.md:122,141-142,146`; semantic limit `implementation/milestones/creativity/skeleton.md:99-110`; existing text/JSON helpers `orchestrator/tasks.py:452-475`; native opacity `orchestrator/tests/test_tasks.py:680-713` | validate at the creativity emitter's contract; do-not-add consumer-side defenses against internally emitted requests/results or claim semantic validation from JSON |

### Acceptance and tests

New test names below are implementation targets. Use the existing unittest
fixtures; no provider calls, new test framework, or standalone test service.
Each item passes only when its observable assertions hold.

1. **T1 — `TaskContractsTest.test_creativity_configuration_contract`** in
   `orchestrator/tests/test_tasks.py`: accept complete boundary-valid and larger
   configurations unchanged; refuse missing/extra keys, wrong types, booleans,
   non-finite/out-of-range numbers, each broken count relationship, and invalid
   rigor entries under F2–F4. Fixture numbers are not catalogue defaults.
2. **T2 — `TaskContractsTest.test_creativity_native_result_contract`** in the
   same module: accept a readable shortlist and an empty normal result inside
   the existing success envelope. Exercise all four stop tokens; reject shape,
   count, outcome/list, score, shortlist, duplicate-genome/ID and component
   coverage violations. Test the emitting contract with trusted material
   fixtures; retain the existing native-opacity test for the common envelope.
3. **T3 — `TaskContractsTest.test_creativity_job_staffing_contract`** in the
   same module: each job's request resolves through the real router with the
   F4 binding and each precedence level. An evaluator works on a one-family
   session even when the document assigns multiple review seats. No task-wide
   family/model choice is introduced.
4. **T4 — `StaffingResolutionTest.test_request_rigor_is_local_and_live`** in
   `orchestrator/tests/test_staffing_sessions.py`: distinguish all three rigor
   tables; overlapping differently scoped requests give their own answers;
   the session/document stores remain byte-identical, with no added records.
   A later unscoped call retains the
   session choice, and completed operator edits reach later resolutions.
   Exercise scoped tuning through material/session layers and existing fallback;
   retain the existing resolution, step-up, condition, and live-read cases.
5. **T5 — `StaffingResolveRoute.test_request_rigor_contract`** in
   `orchestrator/tests/test_staffing_api.py`: the authorized existing HTTP route
   accepts a scoped rigor, returns the unchanged wrapper/answer, leaves the
   stored selection alone, and maps an invalid choice to its existing error.
6. **T6 — compatibility:** retain
   `TaskContractsTest.test_catalogue_has_exact_builtins_and_self_description`,
   `test_configuration_schema_and_resolution`,
   `test_result_contract_and_native_opacity`, and
   `StaffingResolveRoute.test_resolve_answer_defaults_fallback_and_error_mapping`.
   Existing executor behavior and session access/error contracts remain intact.

Focused implementation command:
`python3 -m unittest orchestrator.tests.test_tasks orchestrator.tests.test_staffing_sessions orchestrator.tests.test_staffing_api`.
Normal milestone checkpoint remains
`python3 -m unittest orchestrator.tests.suite_checkpoint`
(`orchestrator/tests/README.md:5-19`). This documentation task does not claim
those implementation tests have run. Acceptance requires T1–T6 and a diff
confined to F1's touch surface. No eventual-delivery mechanism is introduced;
physical-call delivery and panel freshness are not this slice's guarantees.

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator needs independently staffed jobs; unrelated work sharing the staffing session is exposed if one job's choice changes the owner-wide rigor. Existing behavior is not an incident, but cannot express the requested combination. Editing configuration is reversible; mistaken model spend is not. The reviewed assignment establishes need, while the current resolver independently demonstrates that only session rigor chooses tuning. | `implementation/milestones/creativity/skeleton.md:122,143`; `orchestrator/staffing.py:2093-2103`; shared-session consumer `orchestrator/task_api.py:697-716` |
| machinery | Add creativity configuration/native-result contracts and a job-binding seam in the existing task-contract surface. Extend `staffing.resolve` and the existing service resolve adapter with one request field. These respectively provide accepted limits/readable output, independent job choices, and a consistent shared resolution API. No engine, dependency, process, store, or migration is needed. | `implementation/milestones/creativity/skeleton.md:122,143-146`; specialized contract precedent `orchestrator/tasks.py:897-932`; `orchestrator/service.py:2312-2330` |
| consumers_touched | Directly touched runtime consumer: the existing staffing resolve HTTP adapter. Existing Python callers in the direct-task host, Brainstorming, milestone driver and Git sync omit rigor and retain their answers. Creativity's future driver consumes the new contracts later; it is not a present runnable consumer. Searches across Life, Agent99, LPC and Tutor found no creativity/staffing API consumer to migrate. Their roots remain read-only. | `orchestrator/service.py:2316-2324`; `orchestrator/task_api.py:703-716`; `orchestrator/brainstorming_lifecycle.py:651-668`; verified caller inventory `orchestrator/tests/test_staffing_conformance.py:356-370`; future host boundary `orchestrator/task_api.py:1729-1759`; `implementation/milestones/creativity/skeleton.md:129-130,149` |
| cheaper_alternative | Extend the existing validators and tuning lookup. Doing nothing/documentation alone leaves rigor session-wide; temporarily editing or cloning sessions violates the requested isolation. The generic integer-floor resolver cannot express these fractional, nested and coupled controls. External [jsonschema validation](https://python-jsonschema.readthedocs.io/en/stable/validate/) was checked; adopting it would add a dependency while existing task validators already supply the sufficient seam. Granted-root contract searches found different domains: Agent99's text/artifact result, Life's planner output and LPC's product adapters, not reusable Python creativity/staffing contracts. | `orchestrator/tasks.py:584-605`; `orchestrator/staffing.py:1843-1856,2096-2097`; dependency standard `orchestrator/README.md:46`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99/lib/agent_99/body/execution_contract.ex:64-73`; `/Users/siddhartha/Development/source/life/apps/life_brain/lib/life_brain/llm/structured_output/contracts.ex:29-38`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_adapter_contracts/lib/life_product_adapter_contracts.ex:18-30`; Tutor's adopted components `/Users/siddhartha/Development/source/life_prod/tutor/web/mix.exs:68-79` |
| cost | Build/review cost is three small contract surfaces, a router/adapter extension and focused fixture tests, aiming at the repository's roughly 500-line slice scale. Migration cost is zero: no stored shape changes or public creativity admission. Operating cost remains ordinary resolution reads with no model spend added here; maintenance stays with existing task/staffing owners. Omission blocks later independent job choices or pressures callers to duplicate routing. The preparatory change is reversible before public activation. | `WORKSPACE.md:14-29`; `implementation/milestones/creativity/skeleton.md:122,130,143`; existing read-only resolution `orchestrator/staffing.py:2069-2103` |
| threat_model | This slice processes caller-supplied configuration and the rigor field on an authorized staffing request. The external adversary is a caller without session access who can send a request body; existing session access remains that boundary. The operator is trusted to choose budgets/staffing; malformed choices are contract mistakes, not grounds for new restrictions. Product code, stored staffing authorities and the native-result producer's context are trusted. No provider reply or third-party reference text is consumed here; those enter later semantic jobs. No new attacker-specific hardening or revalidation around trusted machinery is introduced. | caller contract `orchestrator/tasks.py:514-557`; existing access `orchestrator/service.py:2226-2233,2251-2263,6397-6404`; slice allocation `implementation/milestones/creativity/skeleton.md:122-124`; trust boundary `implementation/milestones/creativity/skeleton.md:104-110,160` |
| pinned_facts | F1 pins the preparatory boundary; F2–F3 the closed controls and admissibility; F4 the rigor vocabulary, precedence and role/seat mapping; F5–F6 the scoped resolver and existing wire/error contract; F7–F8 the native-result representation and proof limit. All exact names are in the hard register, not the lay intent. | `implementation/milestones/creativity/skeleton.md:122,143-146`; existing wire/error authority `orchestrator/service.py:2133-2150,6397-6404`; common result authority `orchestrator/tasks.py:1621-1695` |
| verification | T1–T3 verify the new cross-slice values without a search driver; T4 verifies isolation/live choice at the router itself; T5 exercises the existing HTTP boundary; T6 protects current callers and generic result opacity. Use the three named focused modules and normal checkpoint, not live-model quality claims. Draft verification is citation/scope inspection; implementation tests remain prospective. | existing harnesses `orchestrator/tests/test_tasks.py:79-95,281-330,680-713`; `orchestrator/tests/test_staffing_sessions.py:505-526,946-980`; `orchestrator/tests/test_staffing_api.py:523-546,584-609`; suite authority `orchestrator/tests/README.md:5-19` |
| enforceability | F2–F3/F7–F8 extend existing exact-key, text, finite-number/JSON and contextual collection-comparison mechanisms with creativity's fields/relationships; the generic configuration schema alone is insufficient. Existing contextual coverage compares output with trusted context without revalidating that context. F4–F5 use existing role/index/review-breadth inputs and rigor-indexed tuning; request-local rigor is the missing input this slice adds. Fresh session/document reads express only optimistic authority freshness. F6 reuses the error mapper/access route. F1 is checked by the unchanged catalogue test and scoped diff. Search history, evaluator validity and quality have no enforcement here and are not promised. | `orchestrator/tasks.py:435-475,584-605,709-749,1649-1663`; `orchestrator/kvstore.py:196-203`; contextual comparison precedent `orchestrator/contracts.py:471-479,1014-1025`; `orchestrator/staffing.py:1843-1856,2019-2038,2072-2103`; `orchestrator/service.py:2251-2263,2325-2330,6397-6404`; `orchestrator/tests/test_tasks.py:85-95`; guarantee limits `implementation/milestones/creativity/skeleton.md:91-110` |
