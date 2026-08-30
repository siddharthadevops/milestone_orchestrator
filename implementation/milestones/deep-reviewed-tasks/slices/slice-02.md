# Slice 02 — Producer, review breadth, debt, and caps

## Register 1 — INTENT (lay language)

### What this slice builds

This slice lets one reviewed piece of work carry its own cost and rigor choices.
The person ordering the work can choose an available producer, the normal
two-family review or an explicitly cheaper one-family review, the existing debt
posture, the existing convergence limits, and—only for implementation—the
existing size controls.

Leaving every choice untouched preserves today's behavior: the normal producer
for the job, two distinct review families, current debt handling, and current
limits. A cheaper review never appears to be the default and never silently
becomes weaker because staffing is short. If two families were requested and
cannot be supplied, the work fails. If one family was requested, only one
family reviews it.

One-family review normally sends every finding to correction. Debt may be
deferred only when the operator deliberately asks for the established fresh,
same-family second look. That second look rates a finding; it does not let the
reviewer clear its own finding in the same call.

### Ownership and consumers

The reusable reviewed-work lifecycle from Slice 1 owns applying these choices to
one selected production. The existing milestone driver is still the only
runtime caller in this slice. Producer availability remains owned by the shared
task catalogue, and family, model, and effort remain owned by Staffing Router.
The order chooses breadth, not people or models.

This slice does not publish a new task type. Later slices can expose the same
choices through standalone reviewed tasks and deep-task children without
inventing another policy or review loop.

### Guarantee posture

- **Strict:** accepted choices govern only their order and survive restart;
  omitted choices preserve current defaults; two-family review completes on
  exactly two distinct current-content families or fails; one-family review
  completes on exactly one; debt and convergence limits retain their existing
  outcomes and reset rules.
- **Strict where observed:** an accepted implementation-size interruption keeps
  its configured thresholds and grace evidence and produces the existing
  coherent-cut outcome before successor work.
- **Best-effort:** physical-call uniqueness, the exact line at which a live size
  meter observes a threshold, and delivery of a size steer retain their current
  provider and polling limits. A configured hard threshold is not an absolute
  final line-count promise for a worker that completes between observations.
- **Optimistic / eventual:** none. This slice adds no compare-and-set workflow,
  queue, retry-delivery, replication, or eventual display promise.

### Dependencies

This slice depends on Slice 1's reusable lifecycle, the shared producer
catalogue and existing producer adapters, Staffing Router's review seats and
distinct-family refusal, current debt classification, current review/fix/delta
limits, and the Git-backed implementation-size meter. It adds no third-party
dependency, service process, store, parallel ledger, or migration lane.

### Non-goals

- No public reviewed-task or deep-task catalogue entry, generic order route,
  panel control, or Agent99 integration.
- No new producer implementation, semantic job, review family, model selector,
  staffing fallback, prompt route, or caller-built prompt.
- No change to review/fixer separation, finding validation, severity or risk
  vocabularies, debt rating, evidence invalidation, seal, Git gate, rethink, or
  recovery meaning.
- No new convergence limit and no absolute maximum-size promise. The existing
  size meter remains implementation-only and Git-backed.
- No deep-task child policy wiring, sibling verification cadence, public native
  result, compatibility migration, or edit in a granted read-only root.

### Acceptance criteria

The slice is accepted when one selected reviewed-work order demonstrably uses
its producer, breadth, debt posture, convergence limits, and applicable size
controls without mutating global defaults or a sibling order. Default parity
must remain exact. Focused tests must prove both breadths, staffing refusal,
single-family debt behavior with and without the explicit second look, each
existing limit, implementation-only size control, restart retention, and
producer eligibility. Existing lifecycle tests remain unchanged goldens.

### Risks

The main risks are policy leaking between orders, a two-family order sealing
after one review, a one-family order silently deferring debt, producer
configuration changing the semantic job, and a limit being read from mutable
global configuration after the order has begun. Size monitoring has a separate
risk: presenting a polling threshold as a mathematically hard final size would
promise more than the current mechanism can enforce. Exact outcome tests and
restart/isolation cases expose these failures.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Slice boundary and defaults | One selected reviewed-work order carries producer, review breadth, applicable debt posture, existing review/fix/delta caps, and implementation-only size controls. Omission preserves the current producer resolution, exactly two distinct review families, and current debt/cap/size behavior. The choices are durable before the first physical call and cannot alter another order. | `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-39,68-79,100`; durable scheduling precedent `orchestrator/tasks.py:560-581` | touch the reusable reviewed-work input and its durable selected-unit authority; do-not-publish `reviewed_task`, mutate run-wide defaults, or create a second policy store |
| Producer selection | Reuse the existing closed selection shape: required `task_executor`, optional `configuration`, validated against the shared catalogue and the selected semantic job. Current producer ids are exactly `agent_call` and `brainstorming`; absent selection resolves to `agent_call`. Unknown ids use `unknown_task_executor`; malformed or job-ineligible selections use `invalid_task_request`. Producer configuration cannot change the semantic job or select review/fix staffing. | selection and errors `orchestrator/tasks.py:18-25,41-100,253-389`; milestone job authority `orchestrator/driver.py:3864-3882`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:42-48` | touch the existing producer validator/adapters and lifecycle selection seam; do-not-add an executor, alternate catalogue, private producer path, or producer choice for review/fix/delta/classification calls |
| Review breadth | Default review breadth requires exactly two distinct families on current contents. Explicit cheaper breadth walks exactly one family. A requested two-family review that Staffing Router cannot supply fails with `distinct_families_unsatisfiable`; it never shrinks to one and never seals on one. The order names no family, model, effort, seat, or staffing fallback. | `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-39,68-79,100`; router refusal `orchestrator/staffing.py:1930-1987,2020-2063`; current cycle/seal seams `orchestrator/driver.py:9763-9838`; `orchestrator/state.py:1195-1236` | touch the family set requested by reviewed-work convergence; do-not-freeze provider identity, bypass Staffing Router, walk every configured family, or silently degrade a two-family request |
| Debt posture | Current debt behavior retains the applicable `doc_reclassify_from` or `impl_reclassify_from`, `p3_reclassify_debt`, and `p3_defer_max_risk` meanings. Double-family default keeps that behavior. Single-family default performs no debt deferral and sends findings to the fixer; only an explicit same-family-second-look choice permits a fresh classification call and possible tracked debt. Rating refusal or failure still fixes; accepted debt remains append-only and does not block closure. | defaults and vocabulary `orchestrator/driver.py:220-233`; phase scope `orchestrator/interpreter.py:149-175`; rating gate `orchestrator/driver.py:12165-12261`; debt record `orchestrator/state.py:1943-1960`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:46-55` | touch the per-order eligibility gate feeding existing classification; do-not-invent a rating algorithm, let the raising review self-clear, erase debt, or defend against trusted classifier metadata emitted by the orchestrator |
| Review/fix/delta caps | Per order, reuse exactly `max_rounds_per_family` (default `12`), `max_fix_loops` (default `20`), and `delta_full_review_after_fixes` (default `5`) as non-negative integers. Zero review/fix budget retains the existing fail-before-that-call outcome; zero delta threshold disables only the delta-to-full-review checkpoint. The review cap counts the family that dispatches on the current candidate; deliberate Resume grants review/fix amnesty. The delta checkpoint derives its count from immutable accepted dirty-delta history and is not reset by Resume. | defaults `orchestrator/driver.py:146-150,205-220`; review cap `orchestrator/driver.py:9935-9954`; fix cap `orchestrator/driver.py:10440-10470`; delta checkpoint `orchestrator/driver.py:11426-11491`; amnesty `orchestrator/state.py:1357-1371` | touch only where these existing limits are sourced for the selected order; do-not-add another counter, make a soft cap terminal forever, reset immutable delta history, or apply one order's values globally |
| Implementation size controls | Only implementation work may choose the existing `implementation_size_control` outcomes: `soft_lines` (default `500`), `hard_lines` (default `750`), `unconfirmed_grace_s` (default `180`), and `confirmed_grace_s` (default `600`), with positive thresholds, `hard_lines > soft_lines`, and positive finite graces. Control remains inactive without the established Git baseline. Polling is internal, and a valid completion between observations remains accepted with overflow evidence rather than being re-run. | settings and validation `orchestrator/driver.py:129-145,2342-2377`; Git gate and live control `orchestrator/driver.py:2379-2413,2772-2810`; completion jump `orchestrator/driver.py:2866-2888`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:42-48,70` | touch the selected implementation order's effective settings; do-not-expose polling as product policy, apply the meter to documentation/review, add a second meter, or claim an absolute final line cap |
| Downstream boundary | Slice 2 changes no public TaskExecutor ids or routes, no panel, no Prompt Router call identity, no reviewed-task native result/seal contract, no deep-task composition, and no verification cadence. The current milestone driver remains the only runtime consumer. | slice allocation `implementation/milestones/deep-reviewed-tasks/skeleton.md:99-110`; current lifecycle consumer `orchestrator/driver.py:8015-8027`; current public catalogue `orchestrator/tasks.py:41-100` | touch only policy resolution and consumption inside the Slice 1 boundary; do-not-implement Slices 3-12 early or edit Life, Agent99, life_product_components, or Tutor |

### Verification Contract

Focused commands:

`python3 -m unittest orchestrator.tests.test_reviewed_policy orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_producer_selection orchestrator.tests.test_staffing_driver_cutover orchestrator.tests.test_p3_debt orchestrator.tests.test_fix_loop orchestrator.tests.test_driver_implementation_size`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Omitted choices preserve current behavior and remain order-local | new `test_default_policy_matches_slice_one_golden_and_isolates_siblings`; retained `test_default_boundary_matches_milestone_lifecycle_golden` | The default boundary has the same producer/call, two-family review, debt, cap, size, seal, and gate evidence as Slice 1; a non-default sibling does not change it. | strict |
| Only a catalogue-supported producer performs the selected semantic job | new `test_selected_producer_is_validated_frozen_and_job_scoped`; retained `test_canonical_plan_validates_complete_producer_map_from_catalogue`; retained `test_brainstorming_note_waits_replaces_path_then_worker_implements`; retained `test_worker_note_then_target_free_brainstorming_implementation` | Both current producers work only for offered production jobs, catalogue defaults resolve once for the order, resume uses the same selection, and judgment calls never adopt it. | strict selection / best-effort call uniqueness |
| Breadth is exact and double-family never degrades | new `test_double_family_requires_two_distinct_current_reviews`; new `test_single_family_runs_one_current_review`; retained `test_a_split_review_the_machine_cannot_honour_stops_the_run` | Two-family work seals only from two distinct current-content reviews and surfaces `distinct_families_unsatisfiable` when unavailable; one-family work performs and cites one whole review. | strict |
| Single-family debt requires the explicit second look | new `test_single_family_defaults_to_fix_without_classification`; new `test_single_family_explicit_second_look_rates_fresh_on_same_family`; retained `test_single_family_homed_run_never_defers_either` | Without the exception no classifier runs and findings enter fixing; with it a separate same-family rating may create debt under the unchanged scope/threshold, while a refused rating still fixes. | strict outcome / best-effort call uniqueness |
| Existing convergence limits are per-order | new `test_order_caps_survive_resume_without_leaking`; retained `test_a_seats_round_number_and_cap_count_its_familys_rounds`; retained `test_non_converging_episode_hits_max_fix_loops`; retained `test_second_fix_skips_delta_and_restarts_reviews_from_codex` | Each configured limit governs only its order; review/fix Resume amnesty and immutable delta-checkpoint counting retain their existing outcomes. | strict |
| Size policy is implementation-only and promises no absolute final cap | new `test_size_choices_apply_only_to_implementation`; retained `test_delivered_soft_steer_records_metrics_on_part_a_cut`; retained `test_ack_during_unconfirmed_grace_extends_from_confirmation`; retained `test_valid_completion_between_polls_is_reviewed_without_stabilizer`; retained `test_failed_part_a_gate_is_retried_before_part_b_can_open` | Selected thresholds/graces appear in cutoff evidence; documentation cannot activate them; accepted interruption remains recoverable and sequential; a completion between polls is accepted and recorded. | strict persisted effects / best-effort observation |
| Invalid policy cannot start work | new `test_invalid_policy_fails_before_any_physical_call` | Unknown/ineligible producer, impossible breadth/debt combination, negative or non-integer caps, or invalid size settings are refused before a provider call or workspace edit. | strict |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They are the normal checkpoint and architectural complement
(`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and later standalone/deep-task callers need to trade cost for rigor per reviewed order without accidentally changing every other order. Without this slice, the reusable lifecycle still reads producer, review seats, debt, caps, and size settings from milestone/run context; a caller must accept the global posture or fork the lifecycle. Realistic harm is overspend, under-review, wrongly deferred debt, or a false seal. Configuration and repository bytes are reversible; spent calls and accepted weak evidence are not. | need `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-39,50-58,100`; current global/read sites `orchestrator/driver.py:9784-9819,9935-9954,10452-10470` |
| machinery | The slice introduces one validated, durable per-order policy input to the Slice 1 lifecycle and focused behavioral coverage. It reuses the existing producer-selection contract/adapters, Staffing Router, debt classifier, cap counters, size meter, state save, and gate path; no public route, new engine, dependency, store, or process is introduced. Each part serves the single authorised outcome of making existing choices order-local. | assigned outcome `implementation/milestones/deep-reviewed-tasks/skeleton.md:83-94,100`; lifecycle seam `orchestrator/driver.py:477-526`; reused producer/state seams `orchestrator/tasks.py:302-389,560-581` |
| consumers_touched | Verified direct consumer touched: the milestone driver calling the reusable reviewed-work lifecycle. Existing producer adapters, Staffing Router, state/debt, and size-control paths are dependencies whose inputs become order-local. The service, generic task routes, panel, direct task host, and granted product roots are not touched; searches found no product-root consumer of these policy choices or the new task ids. | current caller `orchestrator/driver.py:8015-8027`; producer dispatch `orchestrator/driver.py:8290-8336`; current public routes remain at `orchestrator/service.py:4581-4631` |
| cheaper_alternative | Reusing current settings globally is cheaper in code but insufficient because the mandate requires different orders—and later documentation/implementation children—to choose independently. Documentation alone cannot alter runtime calls; cloning the lifecycle or adding a policy service would duplicate solved machinery. Passing one validated order-local policy into the existing boundary is the cheapest sufficient option. | independence requirement `implementation/milestones/deep-reviewed-tasks/skeleton.md:50-58,100`; existing reusable boundary `orchestrator/driver.py:477-526`; existing settings `orchestrator/driver.py:129-150,205-233` |
| cost | Build cost is one policy-resolution/persistence seam plus focused matrix tests. Runtime cost is unchanged by default; explicit one-family work usually buys fewer reviews, while an explicit same-family second look adds only the existing classification call. There is no migration, daemon, dependency, or new operating loop; old state falls back to defaults. Review cost is moderate because producer, staffing, debt, three caps, restart, and live size-control edges must remain aligned. Omission blocks the mandated per-order economy and pushes duplication into later public/composite slices. | compatibility/exclusions `implementation/milestones/deep-reviewed-tasks/skeleton.md:68-94`; existing call and size mechanisms `orchestrator/driver.py:8290-8689,2379-2470` |
| threat_model | Untrusted inputs handled here are operator/caller policy values and model-authored canonical producer choices; existing worker/model result JSON and edits remain untrusted downstream. They need closed value, range, catalogue, and semantic-job validation before effects. Trusted inputs are the orchestrator-emitted selected unit kind, catalogue definitions, resolved Staffing Router answer, default constants, and persisted state machinery. The note adds no malformed-self-input defense around those trusted emitters; tests verify their observable outcomes instead. | untrusted producer contract `orchestrator/tasks.py:302-389`; worker validation boundary `orchestrator/runners.py:2922-2982`; trusted router answer `orchestrator/staffing.py:2020-2063`; task mandate `implementation/milestones/deep-reviewed-tasks/skeleton.md:89-94` |
| pinned_facts | The seven hard rows pin only deviations that change behavior or a cross-slice name already established by the mandate/code: order-local defaults, the existing producer selection and errors, exact breadth, debt exception, the three existing cap names, existing size-control names/outcomes, and downstream exclusions. No internal class, function, control flow, polling interval, or storage layout is pinned. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:96-110`; settled order behavior `implementation/milestones/deep-reviewed-tasks/goal.md:42-55`; existing names `orchestrator/tasks.py:18-25`; `orchestrator/driver.py:129-150,205-233` |
| verification | Seven verification rows combine one new policy matrix with retained Slice 1 parity, catalogue producer validation, real producer adapters, router split refusal, debt routing, convergence-cap behavior, and controlled-size recovery. The focused command pins this slice; checkpoint and extended suites remain the repository-level gates and must not be reported as run unless actually executed during implementation. | current parity test `orchestrator/tests/test_reviewed_lifecycle.py:68-170`; producer proof `orchestrator/tests/test_producer_selection.py:322-417`; breadth proof `orchestrator/tests/test_staffing_driver_cutover.py:1821-1865`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Producer validation, Staffing Router's surfaced split refusal, current-content seal predicate, debt scope/rating/recording, the three existing counters, Git size monitoring, atomic state saves, and frozen task-order precedent can enforce the claimed outcomes. Three seams do not yet exist and are therefore implementation gates, not assumed promises: durable policy attachment to reviewed work, exact one/two-family selection independent of a document's arbitrary seat count, and the explicit single-family second-look override. UI/public ordering remains deliberately absent. | existing mechanisms `orchestrator/tasks.py:302-389,560-581`; `orchestrator/staffing.py:1930-1987,2020-2063`; `orchestrator/state.py:1-17,1195-1236`; missing per-order reads `orchestrator/driver.py:9763-9838,9935-9954,10452-10470,12165-12261` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| One order's resolved choices survive restart and do not leak | Frozen scheduling records are detached and appended at `orchestrator/tasks.py:560-581`; state saves are atomic and history-guarded at `orchestrator/state.py:1-17`. | **Current design gap:** reviewed work has no durable order-policy attachment. Persist the selected values before its first physical call and prove restart plus sibling isolation without a parallel store. |
| Producer is eligible for the semantic job | The catalogue resolver and closed selection validator are at `orchestrator/tasks.py:202-316`; existing production order derivation is at `orchestrator/tasks.py:344-389`. | Reuse that authority for the selected production; fail before effects when the pair is not offered, and keep review/fix/delta/classification outside producer choice. |
| Breadth is exactly one or two distinct families | Staffing Router already detects an unsatisfied declared split at `orchestrator/staffing.py:1930-1987,2020-2063`; current-content sealing consumes an explicit family list at `orchestrator/state.py:1195-1236`. | **Current design gap:** the lifecycle walks every live assigned review seat at `orchestrator/driver.py:9763-9838`. Supply exactly the order's requested breadth to dispatch, advancement, and sealing, with no fallback from two to one. |
| Single-family debt never defers without the explicit second look | Current result policy freezes scope/threshold at `orchestrator/driver.py:3899-3939`; the rating gate and same-family exception are at `orchestrator/driver.py:12165-12261`; debt appends at `orchestrator/state.py:1943-1960`. | **Current design gap:** no order-level exception controls the homed single-family gate. Default it closed; when explicitly open, require a separate same-family rating call and retain existing threshold/refusal outcomes. |
| Review/fix/delta limits keep their established semantics per order | Enforcement exists at `orchestrator/driver.py:9935-9954,10440-10470,11426-11491`; Resume amnesty exists at `orchestrator/state.py:1357-1371`. | Source the existing counters from the durable order policy while leaving their counters, failure edges, amnesty, and immutable-history derivation unchanged. |
| Implementation size choices remain enforceable but not overstated | Settings validation and live Git monitoring exist at `orchestrator/driver.py:2342-2413`; accepted-interrupt persistence and completion-jump behavior exist at `orchestrator/driver.py:2534-2575,2866-2888`. | Source thresholds/graces from the implementation order only; retain the Git requirement and completion-between-polls behavior, and do not expose polling or promise an absolute final size. |
