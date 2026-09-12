# Slice 10 — Cross-domain evidence and baseline comparison

## Register 1 — INTENT

This slice gives the operator a small, inspectable demonstration that the same
creativity task can explore a language problem and a business problem with clear
constraints. It places the resulting suggestions beside an ordinary direct
ideation answer to the same problem, showing what each approach actually used
and produced. The examples support a human judgment about usefulness; the
search's own scores cannot establish that it is better.

This slice owns the example problems, focused checks, comparison record and
evidence for modest default work limits. It depends on the existing search,
semantic jobs, task service, routers, call records and order form. Controlled
workers establish mechanical behavior; real model outputs provide the worked
comparison. Existing tests supply the detailed search and lifecycle coverage.

It does not build another search engine, evaluator, benchmark service or product
integration. It does not act on suggestions or turn the examples into domain
templates. The work limits remain choices the operator can change.

The main risks are an unrepresentative example, unequal spending and incomplete
usage records. Model outputs and prices can vary between runs; a small comparison
cannot establish general superiority or guaranteed feasibility. The evidence
must expose those limits. Defaults and examples can be revised; model work
already paid for cannot be undone.

Acceptance requires the focused mechanical checks, an inspectable comparison
for both problems and a justified set of defaults available through ordinary
ordering. An unfinished or unmatched model run remains an evidence gap.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Two domains, one contract | Use one language objective and one business objective with explicit resource constraints. Each supplies objective, context, facts, constraints and criteria; their dimensions differ in substance. Controlled task runs cover each with generic material `default` and its corresponding `literature` or `business` layer through executor `creativity`. Accepted fixed problem data stays unchanged; genomes use known variants; evaluator-reported invalid candidates cannot reach the unique, bounded final shortlist. Existing native-result and stop vocabularies remain binding, including empty success. | `implementation/milestones/creativity/skeleton.md:131,140-142,146,148`; `orchestrator/task_api.py:2624-2728`; `orchestrator/creativity_search.py:15-47,92-121` | touch example data and focused tests; reuse the existing driver and validators; do-not-add a domain schema or motor |
| F2 — Exercised job and batch boundaries | Evidence exercises `create_genes@creativity`, `evaluate_candidates@creativity` and `expand_genes@creativity`, different per-job family/rigor selections, and overlapping evaluation calls. Actual dispatches match the existing role bindings and job > task default > session rigor precedence. Batch size and simultaneous calls stay within the admitted bounds; accepted replies cover exactly their requested candidate IDs. Controlled evidence includes a full stagnant window followed by variant-only expansion with retained valid best candidates. Generic and layered prompts retain the same reply contracts. | `implementation/milestones/creativity/skeleton.md:131,140,143,145,147-148`; `orchestrator/tasks.py:390-393,997-1004`; `orchestrator/staffing.py:2045-2072`; `orchestrator/creativity_evaluation.py:95-138,230-275`; `orchestrator/prompt_contracts.py:579-625`; `orchestrator/creativity_search.py:294-336` | extend/reuse task, routing, staffing and wave fixtures; do-not-create new jobs, staffing roles or concurrency machinery |
| F3 — Direct comparison | Record one real-model creativity/direct-ideation pair for each objective. The baseline uses public `agent_call`; its request text contains the complete common problem, reference paths, requested shortlist size and exploration-only instruction because that text is what its runner receives. It receives no search-produced genes, proposals or scores. Declare a similar work allowance, accounting unit and numerical comparability tolerance before the measured pair; report actual totals against them. A matched comparison requires complete evidence for that unit and totals within the tolerance; other missing usage stays visibly partial. The allowance is an experimental target, not a new enforced token or dollar cap. | `implementation/milestones/creativity/skeleton.md:104-110,131,148`; `orchestrator/tasks.py:62-68,115-138`; `orchestrator/task_api.py:786-809,2787-2799,2822-2834` | use existing task ordering and staffing choices; do-not-add a baseline executor, budget controller, automatic reruns or judge call |
| F4 — Reviewable evidence | Write `implementation/milestones/creativity/evidence.md`, retaining the problem inputs, submitted/resolved orders, execution revision/date, task IDs, actual outputs and supporting call evidence. Record actual job/generation/batch where supplied, family/model/effort, material and prompt fallback where supplied, physical attempts, duration, tokens, cost and partial flags from existing records. Include search counters/outcome/stop reason and the F3 allowance comparison. Clearly separate controlled results from real runs. Scores remain objective-relative evaluations; neither those scores nor this small sample prove creative superiority. | `implementation/milestones/creativity/skeleton.md:99-102,131,147-148`; `orchestrator/runners.py:2978-3002,3052-3056`; `orchestrator/task_api.py:234-253,262-282,522-545,2822-2834` | touch the evidence document and necessary retained evidence files; do-not-create another ledger, infer missing usage/staffing or present synthetic outputs as model evidence |
| F5 — Evidenced catalogue defaults | Publish defaults for the twelve existing numeric controls in the shared creativity catalogue. Record the exact chosen values and workload/cost rationale in F4, grounded in the two examples; this draft does not decree unmeasured numbers. Omitted numeric inputs resolve to those defaults through `resolve_creativity_configuration`; the schema-generated form starts with the same values. Explicit inputs remain unchanged, all existing bounds/relationships still apply, and invalid inputs remain `invalid_task_request`. Omitted `rigor` stays inherited. Previously admitted configurations retain their values. | `implementation/milestones/creativity/skeleton.md:143-144`; `orchestrator/tasks.py:383-425,605-629,944-1004`; `orchestrator/static/panel.html:6231-6264`; `orchestrator/tests/test_tasks.py:68-85` | touch catalogue defaults, its existing resolver and their tests; do-not-copy defaults into the service/panel, promote boundary-fixture values by accident, add controls or migrate orders |
| F6 — Ownership and non-goals | Use the existing `GET /api/task-executors`, `POST /api/tasks` and `GET /api/tasks/<id>` contracts. Production scope is the default-admission change; search, prompt/staffing, lifecycle, accounting and presentation contracts retain their current owners. All four additional roots remain read-only. No new runtime dependency, API/event/error vocabulary, framework, scheduler, retry/recovery policy, sandbox or proposal execution. | `implementation/milestones/creativity/skeleton.md:63-76,139,149`; `orchestrator/service.py:4882-4908,5905-5940`; `orchestrator/README.md:43-46,631-634` | touch only the primary root's examples/evidence, focused tests and F5 seam; do-not-edit the skeleton, generated milestone ledgers, additional roots or unrelated work |
| F7 — Guarantee posture | **Strict:** F1–F2 inherited mechanical contracts, verified with controlled inputs; F4 fidelity to available authoritative records, including partial flags; F5 admission/default equivalence. **Optimistic:** live prompt, material and staffing reads keep their existing per-call semantics, without a transaction or reproducible future model answer. **Eventual:** ordinary panel polling only; this slice adds no delivery/freshness guarantee. **Best-effort:** provider availability, completeness of auxiliary usage evidence, semantic validity/quality, worker compliance and the F3 spend target. F3's matched-comparison label is an evidence-review decision using recorded totals, not a runtime spending guarantee. | `implementation/milestones/creativity/skeleton.md:78-116`; enforcement seams in F1–F5; `orchestrator/task_api.py:2772-2778,2836-2842`; `orchestrator/static/panel.html:7303-7318` | retain the existing consistency and trust posture; do-not-promise exact spend, deterministic real outputs, exactly-once calls, sandboxed workers or restoration of worker effects |

### Acceptance criteria and tests

These are implementation obligations, not results of this drafting task.

1. **T1 — `test_creativity_cross_domain_contracts`**, extending
   `orchestrator/tests/test_creativity_task.py` (F1–F2, F4): run the two problem
   fixtures with generic and corresponding layered material through the public
   order/host fixture. Observe all three jobs, the supplied problem data in later
   calls and readable terminal components from each problem's own dimensions.
   A high-scoring invalid reply stays out of the result. Observe an allowed
   expansion, different job staffing and actual concurrent batch overlap without
   exceeding either bound. Terminal counts and recorded attempts agree with the
   controlled work. Assert contracts, not one random population or exact prose.

2. **T2 — Defaults through ordinary ordering** (F5): extend
   `test_creativity_configuration_contract` and
   `test_creativity_public_catalogue_and_configuration` in
   `orchestrator/tests/test_tasks.py`, `test_creativity_public_order_and_controls`
   in `orchestrator/tests/test_task_api.py`, and
   `test_creativity_schema_form_submits_public_order` in
   `orchestrator/tests/test_task_panel.py`. Omitted configuration, `{}` and an
   untouched rendered form admit the catalogue defaults. Partial configuration
   receives defaults only for omitted controls. Valid explicit overrides and
   prior complete orders retain their values;
   invalid explicit or default/override combinations still refuse. Preserve rigor
   inheritance. Replace the earlier assertions that omission must fail and every
   numeric form field initially be blank; retain unrelated contract checks.

3. **T3 — Existing mechanism evidence** (F1–F2, F7): reuse, without duplicating
   their matrices, `test_creativity_jobs_and_materials` in `test_prompt_router.py`,
   `test_creativity_job_staffing_contract` in `test_tasks.py`,
   `test_wave_bounds_and_candidate_allowance`,
   `test_each_attempt_reads_live_authorities` and
   `test_rebaseline_without_progress_credit` in `test_creativity_evaluation.py`,
   plus `test_creativity_composes_search_and_results` in `test_creativity_task.py`.
   These pin material-contract parity, inheritance, serial/concurrent bounds,
   live dispatch, regime isolation and every normal stop including empty success.

4. **M1 — Recorded comparison and defaults review** (F3–F5, F7): inspect both
   real pairs against the retained inputs, outputs and common accounting. Verify
   equivalent problem information at the worker boundary, the declared allowance
   and observed comparability, all recorded charges including unsuccessful attempts,
   partial flags and the published default values/rationale. Record concrete
   observations against the supplied criteria without using search scores as an
   independent judge. Controlled tests establish expansion and concurrency even
   when a real example stops before expansion. Missing live access, missing
   outputs or unmatched budgets leave M1 incomplete; mocks or a skip cannot close
   it. No statistical study or repeated sampling is required.

Run the focused checks and the repository's normal checkpoint:
`python3 -m unittest orchestrator.tests.suite_checkpoint`. Run focused tests
explicitly even if they belong to the extended complement. Check the changed
files with `git diff --check`. Routine automated checks use controlled workers;
M1 is an explicitly run evidence exercise, not paid work on every test run.
Authority: `orchestrator/tests/README.md:5-19,35-42`.

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator and release reviewer lack cross-domain evidence and a cost-aware comparison for the published task; ordinary orders also require every numeric limit. Exposure is evaluation/adoption of creativity and each first order. The realistic harm is an unsupported choice or avoidable model spend, not corruption of a manuscript or business. Examples/defaults are reversible; incurred usage is not. The independently assigned need is Slice 10 in the reviewed skeleton. | `implementation/milestones/creativity/skeleton.md:131,144,148`; `orchestrator/tasks.py:944-980`; `orchestrator/tests/test_tasks.py:154-182` |
| machinery | Introduce problem fixtures, one task-level conformance test, a comparison record and numeric defaults at the existing admission seam. Fixtures/test serve the two-domain proof; the record serves human inspection; defaults make the evidenced work limits orderable. Reuse the task host and ordinary agent call for both approaches. No new production module, API, library, service or evaluator is needed. | `orchestrator/tests/test_creativity_task.py:27-110`; `orchestrator/task_api.py:1877-1880`; `orchestrator/tasks.py:383-425,944-994`; `implementation/milestones/creativity/skeleton.md:131,144` |
| consumers_touched | Runtime consumers affected by defaults are service admission, the schema-generated form and the host reading admitted configuration. Tests and the operator consume the new examples/evidence. Searches across the workspace and all granted roots found no additional-root executable client or reusable creativity/comparison engine; the task-route match in Agent99 is exploratory adoption documentation. No product consumer is created. | `orchestrator/service.py:4882-4908`; `orchestrator/static/panel.html:6231-6264,6435-6438`; `orchestrator/task_api.py:2624-2629`; `/Users/siddhartha/Development/source/life_prod/agent_99/implementation/brainstorming/milestone-orchestrator-adoption/design.md:3-10,476-484` |
| cheaper_alternative | Extend the existing standard-library fixtures and record the comparison as documentation. Existing single-problem tests cannot show two substantively different inputs or supply actual ideation outputs/costs; documentation alone cannot publish defaults. Dependency/root searches and the existing [Python unittest](https://docs.python.org/3/library/unittest.html) fixture/suite support leave no need for a benchmark framework or new runner. This is the cheapest sufficient extension. | `orchestrator/README.md:43-46`; `orchestrator/tests/test_creativity_task.py:27-110`; `orchestrator/tests/test_creativity_evaluation.py:548-588`; `implementation/milestones/creativity/skeleton.md:131,144,148`; linked primary library documentation |
| cost | Build/review work is two fixtures, focused extension of existing tests, default admission and one small evidence record. There is no migration or new operating service. Model comparison spend is explicit; routine checks remain controlled. Maintenance is keeping examples and defaults consistent with the existing contracts. Omission saves the example spend but leaves the mandated evidence/defaults absent; this bounded, reversible change is proportionate. | `implementation/milestones/creativity/skeleton.md:131,144,148-149`; `orchestrator/tests/test_creativity_task.py:39-79`; `orchestrator/tests/README.md:5-19`; F3–F6 |
| threat_model | A provider or source-material author can supply malformed replies or misleading/instruction-like text. Those inputs already cross the semantic boundary; existing contextual validators own structural rejection. Baseline prose is retained as an output for inspection. This slice adds no executable interpretation or new hostile-input boundary. The operator, fixture/report authors, catalogue, stored task records, product code and libraries are trusted; no corrupt-self fixtures, receipt validators or new sandbox are justified. | `implementation/milestones/creativity/skeleton.md:104-110,160`; `orchestrator/prompt_contracts.py:547-625`; `orchestrator/task_api.py:2787-2799`; `orchestrator/tests/test_creativity_task.py:86-110` |
| pinned_facts | F1–F7 are the pin set: domain/contract coverage, exercised job/batch boundaries, comparable direct ideation, faithful evidence, numeric-default equivalence, ownership and guarantee levels. Exact default numbers are an evidence-backed implementation deliverable, not existing fixture values. No internal checkpoint layout or new public vocabulary is pinned. | `implementation/milestones/creativity/skeleton.md:131,139-149`; `orchestrator/tests/test_tasks.py:68-85`; F1–F7 |
| verification | T1 observes the shared public task with two domains; T2 observes catalogue-to-admission/form equivalence; T3 reuses existing mechanical proofs. M1 checks the real outputs and declared budget comparison against task evidence and the published defaults. Neither a scripted score nor a passing mock proves semantic quality. Draft verification only checks this document and its citations; no implementation or paid comparison is claimed here. | `orchestrator/tests/test_task_api.py:335-405`; `orchestrator/tests/test_task_panel.py:21-44,75-113`; `orchestrator/tests/test_prompt_router.py:1084-1120`; `orchestrator/tests/README.md:5-19`; `implementation/milestones/creativity/skeleton.md:99-102,148` |
| enforceability | F1–F2 use existing reply validators, valid/unique selection, progress/expansion rules, fresh dispatch and bounded waves. F4 uses existing physical receipts and common aggregation; M1 checks transcription and comparability, not provider truth. F5 extends the existing strict configuration resolver; the form already consumes schema defaults. F6 is a changed-file/scope review. F7 retains the skeleton's weaker live-read/display/semantic postures. There is no existing exact spend cap or semantic-quality enforcement, so neither is asserted; no new guarantee requires an invented mechanism. | `orchestrator/prompt_contracts.py:547-625`; `orchestrator/creativity_search.py:92-121,268-336`; `orchestrator/creativity_evaluation.py:95-138,230-275`; `orchestrator/task_api.py:262-282,522-545`; `orchestrator/tasks.py:944-1004`; `orchestrator/static/panel.html:6231-6264`; `implementation/milestones/creativity/skeleton.md:78-116,149` |
