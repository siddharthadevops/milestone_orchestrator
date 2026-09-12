# Slice 09 — Public ordering and presentation

## Register 1 — INTENT

This slice lets an operator order a creativity search from the ordinary task
form or task API, then follow it on the ordinary task page. The operator supplies
the problem, reference material and work limits, with optional choices about
the effort spent on each kind of model work. The existing search task does the
exploration.

The page explains what work has been saved, how exploration is progressing,
which models actually ran and what their recorded work cost. It presents the
shortlist with its components, explanations and assumptions, or clearly says
that no valid proposal was found. Scores are evaluations against the problem,
not forecasts of success. Existing task controls remain available.

### Dependencies and non-goals

This work depends on the preceding slices' completed task driver, configuration
contract, saved progress, results and call records. It owns discoverability,
ordering and presentation. Search decisions, recovery, routing and accounting
remain with their existing owners. Numeric defaults and the cross-domain
comparison remain the next slice's assignment; this slice supports explicit
work limits without choosing those defaults.

It adds no product integration, new search behavior or proposal execution. It
does not replace the form, task service or panel with another framework.

### Risks and acceptance

A page can lag work that has just completed. Reading it must neither advance
the search nor turn a prepared answer into a completed task. Unavailable scores
and incomplete cost evidence must remain visibly unknown. Model spend already
incurred cannot be reversed; the displayed proposals remain suggestions.

Acceptance uses small controlled searches and executable form/page checks. It
proves that an operator can order, inspect and control the existing task without
requiring a paid model run or a claim about creative quality.

## Register 2 — PINNED-FACTS TABLE

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| F1 — Public order | Publish exactly one standalone executor `creativity` in the shared catalogue, retaining its existing self-description schema. Its `execution_bindings` are `staffing: true`, `prompt_set: true`, `strategy_profile: false`, matching the completed driver. Use `GET /api/task-executors`, `GET/POST /api/tasks`, and `GET /api/tasks/<id>` with existing envelopes and access/work-area admission. A successful order returns HTTP 201 and the canonical task identity. | `implementation/milestones/creativity/skeleton.md:130,139`; `orchestrator/tasks.py:484-505,1245-1289`; `orchestrator/task_api.py:1839-1846,2631-2645`; `orchestrator/service.py:4882-4908,4936-4945,5148-5173,5859-5863,5870-5938,6170-6172`; `orchestrator/tests/test_tasks.py:387-409` | touch shared catalogue/configuration admission and existing service wiring; do-not-add a producer executor, per-type endpoint, public event or error vocabulary |
| F2 — One order configuration | The schema exposes exactly `population_size`, `generation_limit`, `max_evaluated_candidates`, `elite_count`, `diversity_count`, `mutation_rate`, `minimum_improvement`, `patience_generations`, `max_stagnation_expansions`, `evaluation_batch_size`, `evaluation_concurrency`, `shortlist_size`, and optional `rigor`. Public admission uses `resolve_creativity_configuration` unchanged in substance: its positive counts, finite rates in `(0,1]` and population/budget relationships remain binding, without clamping supplied values. `rigor` permits optional `default`, `create_genes`, `evaluate_candidates`, `expand_genes`, each `low`, `medium`, `high`; precedence remains job > task default > live session. Required numeric values are explicit in this slice; defaults belong to Slice 10. Invalid configuration is HTTP 400 `invalid_task_request`. The existing schema-generated form submits the same typed configuration and preserves omitted rigor choices as inheritance. | `implementation/milestones/creativity/skeleton.md:143-144`; `orchestrator/tasks.py:911-972`; `orchestrator/service.py:4714-4716,4882,4974-4975`; `orchestrator/static/panel.html:6158-6211,6307-6337,6354-6363` | touch catalogue schema and generic form support only as needed; do-not-copy validation/defaults into the service or a creativity editor, choose concrete models, add hidden ceilings or a score target |
| F3 — Saved progress projection | Detail adds the response member `creativity` beside canonical `task` and common `lifecycle`. It exposes saved current job/generation, best/reference scores, patience state, expansion count, accepted evaluated count/budget and best candidates. Counts include saved accepted batches; scores/candidates describe the last completed comparison, including its absence during reassessment. Before saved progress exists, report no progress available; an absent score is not zero. This is the public checkpoint-to-view contract, not publication of the private checkpoint layout. Reads and paints neither change search state nor dispatch work. Only the common task result establishes terminal outcome; a prepared checkpoint result alone does not. | `implementation/milestones/creativity/skeleton.md:63-68,97-98,148`; `orchestrator/task_api.py:60-65,2574-2628`; `orchestrator/creativity_search.py:165-179,223-257`; `orchestrator/creativity_evaluation.py:257-264`; `orchestrator/kvstore.py:340-346`; `orchestrator/service.py:5905-5938` | touch the existing detail projection/read seam and task-page renderer; do-not-change checkpoint ownership, recompute selection/progress or make display availability an execution gate |
| F4 — Readable terminal result and text | Present the existing `native_result`: `outcome`, `proposals`, `stop_reason`, `generations_completed`, `evaluated_candidates`, `expansion_interventions`. Show each proposal's ordered components, proposal text, reason, assumptions and score without reranking or semantic filtering. `proposals` and `no_valid_candidates` are both normal task `success`; the latter stays visibly empty. Display the recorded `generation_limit`, `evaluation_budget`, `persistent_stagnation` or `repertoire_exhausted` reason. Cancellation/failure retains the common failure explanation. Label scores as objective-relative evaluations, never probabilities. Model/source text is displayed as text through existing escaping, including markup-shaped text. | `implementation/milestones/creativity/skeleton.md:24-29,146,148,160`; `orchestrator/tasks.py:975-1005`; `orchestrator/task_api.py:2583-2587,2613-2626`; `orchestrator/static/panel.html:2517-2519,5692-5693,5721-5727` | touch creativity presentation within the shared page; do-not-change the native-result contract, revalidate trusted task JSON, invent results, execute proposals or add a sanitizer/rendering dependency |
| F5 — Actual calls and accounting | Show recorded physical attempts with job/generation/batch, actual family/model/effort, prompt-set fallback, duration, tokens and cost. Reuse common lifecycle `history` receipts (`call_id`, `physical_dispatch`, `attempt`) and lifecycle/terminal aggregate accounting. Accepted candidate evaluations and physical attempts remain distinct quantities. Preserve `token_usage_partial` and `cost_partial`; absent evidence does not become zero cost or inferred staffing. The page does not select staffing or calculate a second bill. | `implementation/milestones/creativity/skeleton.md:65-68,89-90,115,147-148`; `orchestrator/runners.py:2978-3002,3052-3056`; `orchestrator/task_api.py:200-220,228-256,480-496` | touch projection and existing cost/token presentation; do-not-change runner receipts, pricing, aggregation, live routers or create another ledger |
| F6 — Existing controls | Creativity receives common lifecycle metadata in detail/sidebar and the existing Pause, Resume, Cancel and terminal deletion presentation. Availability comes from `can_pause`, `can_resume`, lifecycle status and terminal result. Actions use existing `POST /api/tasks/<id>/pause`, `POST /api/tasks/<id>/resume`, `POST /api/tasks/<id>/stop` and `DELETE /api/tasks/<id>`. Resume carries the displayed `revision`; stale requests retain HTTP 409 and surface the service refusal. Projection must not invent resumability or automatic continuation. Existing access, reservation, quiescence and deletion rules remain owned by the task service. | `implementation/milestones/creativity/skeleton.md:63-68,112-116,139,147`; `orchestrator/task_api.py:1079-1101,1131-1154`; `orchestrator/service.py:4978-4989,5025-5039,5103-5145,5436-5460,6173-6189,6485-6489`; `orchestrator/static/panel.html:5615-5617,5655-5671,5774-5778,5842-5857` | extend existing creativity eligibility in lifecycle projection and panel controls; do-not-reimplement lifecycle enforcement, task retry or permissions |
| F7 — Guarantee posture and boundary | **Strict:** F1–F2 shared admission/configuration; F3 fidelity to saved search data and no search effects; F4 faithful results and inert text; F5 faithful recorded evidence/partial flags; F6 existing control authorization. **Optimistic:** checkpoint, lifecycle and result reads need not form one transaction; live prompt/staffing authorities retain their existing posture. **Eventual:** successful ordinary panel polling refreshes saved progress, with no fixed freshness deadline. **Best-effort:** availability of auxiliary usage/evidence, worker compliance and semantic quality. No stronger delivery promise is introduced. | `implementation/milestones/creativity/skeleton.md:78-116,149`; `orchestrator/kvstore.py:340-346`; `orchestrator/static/panel.html:5790-5815,7228-7243`; `orchestrator/README.md:46,631-634` | only the primary root, named shared surfaces and focused tests; do-not-change search/evaluation rules, routing/accounting authority, skeleton/goal or any additional root; no new runtime dependency, scheduler, cache, recovery service or exactly-once claim |

### Acceptance criteria and tests

T1–T5 are implementation obligations, not claims that tests already pass.
Extend the existing suites and fixtures; do not copy the preceding slices'
search, validator or process-race matrices.

1. **T1 — `test_creativity_public_catalogue_and_configuration`** in
   `orchestrator/tests/test_tasks.py` (F1–F2): the public catalogue contains the
   entry/bindings and exact configuration controls; the producer catalogue stays
   unchanged. Generic order resolution accepts complete configuration and
   preserves inheritance, rejects missing/invalid values and coupled-limit
   violations through the existing resolver. Update the preparatory assertions
   that creativity is absent in this suite and `test_creativity_task.py`.
2. **T2 — `test_creativity_public_order_and_controls`** in
   `orchestrator/tests/test_task_api.py` (F1–F2, F6): use the real catalogue and
   public POST with the existing controlled creativity runner. Observe the same
   task identity in list/detail, preserved request/context/reference order,
   prompt-set and per-job rigor reaching the worker boundary, and completion.
   Representative invalid configuration and inaccessible project/session cases
   refuse before admission. Exercise existing pause/resume/stop/deletion routes,
   including a stale Resume refusal; reuse lifecycle fixtures for their safety.
3. **T3 — `test_creativity_projection_tracks_saved_work`** in
   `orchestrator/tests/test_task_api.py` (F3–F5, F7): inspect ordinary fixtures
   before the first checkpoint, during evaluation after an accepted sibling
   batch, during reassessment/expansion, while paused, and after completion.
   Compare projected values and physical-call evidence with saved authority,
   including missing scores and partial accounting. Repeated reads dispatch no
   calls and leave search state unchanged. A saved answer awaiting terminal
   publication remains open; both nonempty and empty published results retain
   their recorded outcome and stop reason.
4. **T4 — `test_creativity_schema_form_submits_public_order`** in
   `orchestrator/tests/test_task_panel.py` (F1–F2): execute the existing form
   functions using the served catalogue; fill counts/rates and nested rigor,
   leave inherited choices blank, and observe the resulting typed POST body.
   Incomplete required controls cannot create an order. Submission errors are
   visible through existing form behavior. No creativity-specific form or
   browser-side numeric defaults are needed.
5. **T5 — `test_creativity_task_page_presents_progress_results_and_controls`** in
   `orchestrator/tests/test_task_controls_panel.py` (F3–F7): execute the real page
   renderer and escaping helper with the T3 states. Observe every required
   progress/result/call value, all four recorded stop reasons, evaluation labels,
   empty success, failure cause, partial charges and lifecycle-controlled buttons. A markup-shaped proposal
   remains escaped text. Feed updated poll responses to observe refreshed saved
   progress without control POSTs or locally synthesized completion; retain
   existing task-type presentation checks.

Acceptance requires these focused checks and the repository's normal milestone
checkpoint, including existing task/form/control regressions. A page inspection
with a controlled task confirms that progress and proposal text are readable;
source-string assertions alone do not establish presentation behavior. This
draft runs no implementation tests.

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator cannot order the completed driver publicly or inspect its search through the task page: current admission rejects its id and the page only offers generic result JSON. Exposure is every attempted public creativity order; omission blocks access and leaves progress unexplained. Publication/presentation edits are reversible; already incurred model spend is not. The independent need is the skeleton's explicit public-ordering assignment. | `implementation/milestones/creativity/skeleton.md:130,148`; `orchestrator/tasks.py:1260-1264`; `orchestrator/tests/test_tasks.py:153-155,370-375`; `orchestrator/static/panel.html:5721-5727` |
| machinery | Add one catalogue/schema entry, wire its existing configuration resolver into generic admission, expose a read projection, and extend the current form/page and lifecycle visibility. Each serves discoverability, valid ordering or inspection/control of the already implemented driver. No new execution module, API route, runtime dependency or persistent store is needed. | `orchestrator/tasks.py:484-494,560-584,911-972`; `orchestrator/task_api.py:1839-1846,2590-2603`; `orchestrator/service.py:5436-5460,5905-5938`; `orchestrator/static/panel.html:6167-6211` |
| consumers_touched | Verified consumers are generic service admission/detail/sidebar, the schema-generated order form, the task page and the existing host receiving public orders. Searches of all four additional roots found no implemented client of these task routes. Agent99's route reference is exploratory adoption documentation, not a runtime consumer; no product adapter is in scope. | `orchestrator/service.py:5148-5173,5870-5938`; `orchestrator/static/panel.html:5794-5805,6263-6284,6398-6416`; `orchestrator/task_api.py:1839-1846`; `/Users/siddhartha/Development/source/life_prod/agent_99/implementation/brainstorming/milestone-orchestrator-adoption/design.md:3-10,453-461` |
| cheaper_alternative | Extend the existing catalogue, form and presenters. Documentation alone cannot admit the executor; raw JSON does not provide the mandated progress/result presentation. Root/dependency searches found Phoenix form components in Life, Agent99 and Tutor and Phoenix dependencies in LPC, not a replacement for this existing plain-JavaScript panel. External [react-jsonschema-form](https://rjsf-team.github.io/react-jsonschema-form/docs/) also solves generated forms but requires React and packages; adoption would replace machinery that already suffices. | `orchestrator/static/panel.html:6167-6211`; `orchestrator/README.md:46`; `/Users/siddhartha/Development/source/life/apps/life_site/lib/life_site_web/components/core_components.ex:3-29`; `/Users/siddhartha/Development/source/life_prod/agent_99/apps/agent_99_workspace/lib/agent_99_workspace/components/core_components.ex:3-29`; `/Users/siddhartha/Development/source/life_prod/tutor/web/lib/tutor_web_web/components/core_components.ex:3-26`; `/Users/siddhartha/Development/source/life_prod/life_product_components/elixir/apps/life_product_live/mix.exs:30-41`; linked primary library documentation |
| cost | Build/review cost is the catalogue-to-page connection and five focused checks. No data migration or operating service is added. Ordinary polling reads existing saved data; display launches no extra model work. Maintenance stays with the existing schema/presenters. Omission leaves a completed task inaccessible; the small reversible integration is proportionate. | `implementation/milestones/creativity/skeleton.md:129-130,149`; `orchestrator/task_api.py:60-65`; `orchestrator/static/panel.html:7228-7243`; F1–F7 and T1–T5 above |
| threat_model | A source author or model can supply arbitrary proposal/component/explanation text, including markup, which reaches the page. F4 preserves existing text escaping at that boundary. The authorized operator, product code, catalogue, saved checkpoints/results and libraries are trusted; no hostile-self JSON tests, checkpoint repair or library hardening are introduced. Existing project/session access still governs callers and ordinary order validation catches input mistakes. | `implementation/milestones/creativity/skeleton.md:104-109,160`; `orchestrator/tasks.py:975-982`; `orchestrator/static/panel.html:2517-2519,5725-5727`; `orchestrator/service.py:4882-4885,4936-4945,5372-5380` |
| pinned_facts | F1–F7 are the complete pin set: public entry/routes, admitted configuration/inheritance, saved projection authority, terminal/text presentation, recorded accounting, existing controls and bounded guarantee posture. Search internals and private checkpoint layout are not new public contracts. | `implementation/milestones/creativity/skeleton.md:139,143-149`; F1–F7 above |
| verification | T1–T5 observe catalogue/order resolution, HTTP admission/controls and saved projections, submitted form data and executed rendering. Reuse the existing controlled search, HTTP server and Node presenter harness, plus the normal checkpoint; no paid run or benchmark is required here. | `orchestrator/tests/test_creativity_task.py:120-161`; `orchestrator/tests/test_task_api.py:35-68,319-333`; `orchestrator/tests/test_task_panel.py:18-49,168-181`; `orchestrator/tests/test_task_controls_panel.py:10-71`; `orchestrator/tests/README.md:3-19` |
| enforceability | F1–F2: catalogue-driven admission and the existing closed resolver express the order guarantees. F3: the checkpoint read API and owner-produced progress express projection without search writes; common result publication supplies terminal authority. F4: the producer's native result and existing text escape express faithful inert presentation. F5: recorded receipt/accounting APIs supply the evidence without a new bill. F6: host control availability and service guards express authorization/quiescence. F7: existing independent reads and polling support optimistic/eventual display only; no mechanism promises instantaneous freshness, complete usage or semantic quality. The missing wiring is this slice's work, not a governing-design gap. | `orchestrator/tasks.py:484-494,911-962`; `orchestrator/kvstore.py:340-346`; `orchestrator/task_api.py:200-256,480-496,1079-1101,1131-1154,2574-2628`; `orchestrator/service.py:4978-4989,5025-5039,5103-5145,5905-5938`; `orchestrator/static/panel.html:2517-2519,5842-5857,7228-7243` |
