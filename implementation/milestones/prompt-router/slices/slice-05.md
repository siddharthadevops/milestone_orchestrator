# Slice 05 — Milestone author-call cutover

## Register 1 — INTENT (lay language)

### What this slice builds

This slice moves the milestone's three direct author jobs—drafting the
skeleton, drafting a slice note, and implementing a slice—onto the named prompt
set chosen for the run. Every actual author call receives a freshly assembled
prompt for that job. The provider input and recorded trace are exactly that
assembled, contract-bound charge, including on recovery attempts, and the reply
is checked against the contract and questions that charge carried.

The slice also makes the plan in the skeleton the only authoring surface for
slice order, producer, and material. A worker changes the plan by editing that
one block in the repository, not by returning another plan in its reply or by
using a panel control. A valid edit becomes the run's visible plan; an invalid
edit rejects that call and restores the governed Git-visible work-tree bytes,
index tree, HEAD identity/tip, and canonical anchor to their pre-call values.

### Ownership and boundary

Owned here are direct milestone calls for `draft_skeleton`,
`draft_slice_note`, and `implement`; their prompt rendering, registered reply
checking, exact prompt trace, and first live use of the canonical-plan boundary.
The boundary covers every provider dispatch made for one of those jobs,
including a later physical attempt in the same author episode.

This slice also removes the milestone's producer and material write routes,
their state mutations and live-driver replay, their panel editors, the
producer-freeze control result, and tests whose only purpose was to preserve
those controls. The plan remains visible in the panel, and its two producers and
optional material still drive future task admission.

Brainstorming seats do not move here. Reviews, delta reviews, fixes, ratings,
and suite checkpoints retain their current call and reply paths until their own
slices. This slice does not calculate plan-history divergence, wipe built work,
isolate an accepted direct-call range, reconcile that range, or activate the
new run schema.

### Guarantee posture

- **Strict per physical author call — prompt and reply.** Each dispatch for one
  of the three owned jobs resolves the run's bound prompt set afresh, uses the
  canonical job and admitted material, renders one complete prompt, binds its
  registered sections and questions, and sends and records exactly that final
  bound charge. Recovery context may enter only through that routed charge; no
  caller-owned prompt prefix, suffix, or replacement is permitted. The selected
  rung cannot mix with another rung. Prompt fallback stays beside the prompt
  rather than entering its text. Each implementation charge also preserves the
  unit's exact current part assignment: after an `implementation_cut`, the
  recorded remaining scope is the continuation's whole implementation
  assignment, while the reviewed note remains design context rather than
  permission to repeat completed or delegated work. When the live size meter is
  active, the charge's rendered soft and hard limits equal the effective
  per-run limits used by that same call's meter; 500/750 appear only when they
  are the effective defaults.
- **Strict — canonical-plan admission.** A successful skeleton draft is not
  accepted without one valid canonical block. Once anchored, every owned
  dispatch is withheld on unexplained pre-call block drift. After each physical
  call, byte-identical plan content remains unchanged without revalidation; a
  changed valid block is accepted and projected before plan-dependent work;
  missing, duplicate, malformed, or invalid changed content rejects the call
  and restores its governed pre-call worktree/index/HEAD/anchor boundary.
- **Strict — plan authority and retirement.** Reply status and fields neither
  grant nor suppress a plan edit. Author replies never carry `slices`, and the
  removed HTTP and panel controls cannot mutate the projected plan. The only
  successful authoring act is a valid repository-block edit.
- **Best-effort across calls — prompt edit visibility.** A completed prompt-set
  edit is eligible for the next physical call. There is no snapshot,
  notification, monotonicity, or convergence promise across calls; a dispatched
  prompt remains fixed for that call.
- **Optimistic / eventual delivery — none.** Author work completes synchronously
  through the existing worker result and Git review flow. This slice introduces
  no queue, retry promise, or delayed plan propagation.

### Dependencies and consumers

Slices 1 and 2 supply whole-set fallback, canonical charge resolution, the
converted author corpus, and assembled prompt JSON. Slice 3 supplies registered
reply contracts, exact canonical-block validation, projection, anchoring, and
the pre-dispatch drift guard. Slice 4 supplies the immutable run prompt-set
binding.

The direct worker runner, milestone task admission, implementation size control,
prompt tracing, run-state projection, service router, and panel are the live
consumers touched here. Existing operator amendments and project safeguards
remain paired with the author prompt and its enforcement. TaskExecutor
selection from the plan, staffing/model resolution, and caller-authored
standalone tasks remain consumers of their existing seams, not new prompt-plan
writers.

### Non-goals

- No Brainstorming producer or rethink seat cutover, repository-turn handling,
  readiness rule, or session close behavior.
- No review, delta-review, fixer, rating, reclassification, merge-repair, or
  suite-checkpoint prompt cutover; their reply transports remain until their
  owning slices.
- No plan id/order diff, historical-boundary selection, wipe, requeue, seal
  invalidation, accepted-range isolation, or reconciliation.
- No schema-version bump, legacy-run refusal, migration, fallback adapter, or
  dual runtime authority.
- No prompt CRUD, cache, watcher, version, snapshot, edit event, or consistency
  service.
- No new TaskExecutor, staffing role, model/effort rule, material catalogue, or
  unknown-material error.
- No change to standalone `/api/tasks` orders, staffing-session material,
  caller-authored standalone configuration, or any granted read-only root.

### Acceptance and size

Acceptance is the focused contract below. It proves all three direct author job
charges, render-to-provider-to-trace identity for every fresh physical attempt,
mounted reply enforcement, exact continuation-part assignment and live-meter
limits on implementation charges, the supplied skeleton path as the canonical
plan source, reply-independent first-plan establishment, pre- and post-call
plan handling, complete removal of the two mutation controls, and preservation
of plan-driven producer admission, project safeguards, and standalone tasks.

This cohesive cut is expected to exceed about 500 changed non-generated lines.
The reviewed amendment requires the three author paths, their physical-call
plan boundary, reply-plan retirement, and both legacy mutation controls to land
together; splitting at a successful runtime boundary would leave either a
second plan authority or a forbidden projection-only write. Straight deletion
of retired panel/control code and mechanical fixture conversion do not count
toward the target. Sequential implementation parts may be used for reviewability,
but none may claim a successful partial cutover.

### Risks

The material risks are resolving only once per logical task, sending a prompt
from the wrong job or material, losing an active project safeguard, validating
a reply against sections different from those served, recording a prompt other
than the provider input, widening a continuation back to the full slice,
rendering default size limits while a custom live meter enforces another pair,
adding recovery prose outside the routed charge,
following a reply-selected artifact path, suppressing a valid canonical-block
outcome because the reply is invalid, accepting a skeleton draft without a
valid plan, rebaselining pre-call drift, keeping part of an invalid plan-changing
call, or removing the shared standalone task form while deleting producer
editing. The focused tests force multiple physical attempts, rung fallback,
active safeguards, each plan delta class, dirty pre-call governed state, and
both milestone and standalone task surfaces.

### Reuse Posture

Operators and author workers are affected. A wrong prompt or wrongly accepted
reply spends an irreversible model call; a wrong plan can order or attribute
later work incorrectly. Repository and state bytes are locally reversible only
when the proportional pre-call boundary and validated anchor are trustworthy.
Unrelated refs, reflogs, stash, and other Git plumbing are outside this
guarantee. The reviewed
skeleton independently requires the author cutover and the single repository
plan.

This workspace and every granted read-only root were searched, and the existing
Python and Git seams needed by this cut were checked. None provides another
compatible milestone prompt or canonical-block boundary. Reused are the
prompt-set selector, charge resolver, converted corpus,
registered reply validators, canonical-plan validator/anchor/guard, current
worker/task admission, exact prompt recorder, the existing implementation-scope
projection and effective size-meter configuration, project-policy compiler and
checks, and ordinary Git worktree/index/HEAD/anchor capture and restore
primitives. The direct author adapter consumes
those existing scope and limit values; no second scope ledger or size policy is
needed. The cheapest sufficient option is to extend those live seams and delete
the old writers. Documentation,
configuration, or leaving either writer in place cannot enforce per-call prompt
freshness or one plan authority.

The remaining justified machinery is one thin direct-author adapter and one
post-physical-call plan boundary, consumed by the milestone driver and runner.
It adds fresh prompt reads and proportional repository capture only when a call
is actually dispatched. That build, test, and per-call cost is lower than the
omission cost of wrong instructions or governed plan drift; caches, services,
retries, migrations, parallel stores, and recovery for unrelated refs, reflogs,
stash, or other Git plumbing would add lifecycle cost without an authorised
consumer.

### Planning-context disposition

**Adopts** the reviewed skeleton, accepted amendment B1, and the converted
author corpus and goldens already delivered by Slice 2. **Uses** the original
goal only where the skeleton leaves the author material examples, served-only
consumer boundary, and prompt-trace intent concise. **Revises** older planning
material that granted plan authority through reply `slices`, producer controls,
material controls, or design-update flags. **Rejects** other brainstorming and
`_drafts` material as implementation authority.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Direct author charges | The owned direct charges are exactly `draft_skeleton@skeleton`, `draft_slice_note@slice_doc`, and `implement@slice_impl`, each with executor `agent_call` and the run's bound `prompt_set` (read-compatible `default` before activation when that legacy field is absent). Skeleton and slice-note calls use material `document`, implementation uses `code`, unless an admitted slice producer order carries a non-empty explicit material, which that note or implementation call retains. Only `draft_skeleton@skeleton` receives the TaskExecutor catalogue and plan-creation unit. Runtime prompt headers carry `KIND` and `WORKSPACE`, not family. | routing and binding `implementation/milestones/prompt-router/skeleton.md:64-68,124-125,142-147,153`; open material and binding-corpus authority `implementation/milestones/prompt-router/goal.md:24-59,73-91,111-145`; binding corpus examples `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:113-142`; binding reader `orchestrator/state.py:2784-2799`; admitted material `orchestrator/tasks.py:436-456,693-725` | touch the three direct milestone adapters and their tests; do-not-add raw route selectors, a material catalogue, plan configuration, or a caller-selected role |
| Implementation assignment and size | An `implement@slice_impl` charge mounts the exact current implementation-part scope whenever the unit has one. For a continuation after `implementation_cut`, its recorded remaining scope is the only assigned implementation work; completed and separately delegated scope is not reassigned merely because the worker can read the governing note. On every physically metered implementation call, rendered `soft_lines` and `hard_lines` equal the same effective per-run values used by that call's live meter; the corpus defaults 500/750 apply only when those are the meter's effective defaults. | strict variable assembly `implementation/milestones/prompt-router/skeleton.md:64-68,146-147`; per-run size authority `implementation/milestones/prompt-router/goal.md:144-145`; current scope projection `orchestrator/state.py:649-687`; current effective meter values `orchestrator/driver.py:1696-1735`; corpus variables `implementation/brainstorming/prompt-router/adapted-kinds/shared/shared.json:396-421` | touch the routed implementation charge and its focused cutover tests; reuse the existing scope projection and effective meter configuration; do-not-create another scope record, size policy, or implementation call |
| Physical prompt boundary | Before every provider dispatch belonging to an owned author job—including another attempt in the same episode—the current bound set is freshly resolved as one whole rung, substitutions are rendered, and registered sections/questions are bound. The provider input and immutable trace must byte-equal that final bound charge. Contract correction, cutoff stabilization, resume, and infrastructure recovery may supply context only through the routed charge; no code-owned prompt addition or replacement contributes to an owned call. `prompt_set_fallback` remains sidecar data. No legacy author builder, prompt-file read, cached assembled prompt, reply-derived planning unit, `producer_planning`, `_continuation_may_plan_slices`, `plan_authoring_authorized`, or `design_update` authority contributes; only the skeleton's catalogue-backed unit gives plan-creation instructions. | `implementation/milestones/prompt-router/skeleton.md:64-68,96-101,145-147,154`; `orchestrator/prompt_router.py:55-73,126-140,395-415`; `orchestrator/prompt_contracts.py:733-805`; exact trace `orchestrator/runners.py:1663-1676,1754-1757` | touch one reusable render/bind/dispatch seam and author-call recovery; do-not-cache prompt content, mix rungs, hand-stitch recovery instructions, put fallback text in the prompt, or route judgment/session calls early |
| Author reply contract | All three author replies answer every mounted question. On `ok`, skeleton returns the exact normalized workspace-relative skeleton path supplied to its charge; note returns its normalized workspace-relative `artifact`; implementation returns normalized workspace-relative `files_changed` and may return one valid `implementation_cut`. `blocked` requires `blocked_reason`; note and implementation may instead return `need_rethink` with exactly a non-empty `finding`, normalized `target_path`, and questions. Active registered project-safeguard fields may extend an `ok` reply. Author replies reject `slices`, `battery`, `suite_command`, planning flags, and other status-incompatible protocol fields. | target vocabulary `implementation/milestones/prompt-router/skeleton.md:143,147,149,154`; author sections `orchestrator/prompt_contracts.py:20-24,111-149,190-216,576-597,622-715`; question binding `orchestrator/prompt_contracts.py:341-368,733-805`; project enforcement seam `orchestrator/verifiers.py:486-563` | touch routed author validation and the existing project-extension merge; do-not-remove judgment reply transport before Slice 6 or weaken an active project safeguard |
| Canonical-plan call boundary | After every `draft_skeleton` physical call, the canonical block is read only from the skeleton path supplied to the charge and evaluated independently of reply status or fields. Its first valid committed block becomes the anchor and projection and refreshes ordered units before plan-dependent work. A returned `artifact` mismatch rejects draft recording only; it cannot suppress that valid block outcome or select another path. A successful draft result additionally requires an exact returned path and a valid block. Later owned calls require current block bytes to equal the anchor before dispatch. After each physical call, unchanged bytes keep the anchor without revalidation; a changed valid block survives and refreshes projection/anchor before plan-dependent work; a missing, duplicate, malformed, or invalid changed block rejects the call and restores only governed Git-visible work-tree bytes under existing exclusions, the index tree, HEAD identity/tip, the canonical anchor, and prior projection. Unrelated refs, reflogs, stash, and other Git plumbing are outside the guarantee. | `implementation/milestones/prompt-router/skeleton.md:69-95,121-139,128,146-147`; existing validator/anchor/guard `orchestrator/canonical_plan.py:99-133,185-267,285-353,375-540`; proportional repository restore `orchestrator/gitops.py:787-872`; operator amendment A1 | touch the first live direct-call boundary and focused tests; do-not-follow a reply-selected plan path, let reply validity suppress a valid block, rebaseline unexplained drift, implement plan diff/wipe, assign accepted-range identities here, or add recovery for unrelated Git state |
| Producer/material control retirement | `POST /api/runs/<id>/slices/<slice-id>/producer` and `POST /api/runs/<id>/slices/<slice-id>/material` are absent and make no state change; their producer/material state writers, live-driver replay/adoption, `TASK_SELECTION_FROZEN` result, panel dialogs/buttons/actions, and control-only tests are removed in this cut. Run detail and panel continue to display the canonical projection in array order. | assigned cut `implementation/milestones/prompt-router/skeleton.md:49-53,125,154`; current routes/writers `orchestrator/service.py:2893-2950,5084-5133`; current replay `orchestrator/driver.py:1493-1578`; current control code `orchestrator/tasks.py:17-25,459-658`; current panel editors `orchestrator/static/panel.html:824-845,5803-6013` | touch only these milestone mutation controls and their tests; do-not-remove projection, TaskExecutor catalogue/selection, admitted task material, staffing-session controls, or standalone task UI/API |
| Retained authority and later cutovers | Operator amendments and in-scope project safeguards remain present and mechanically paired with their author replies. Task admission still writes its actual milestone role last and preserves caller-authored standalone orders. Brainstorming seats, judgment calls, suite calls, plan diff/wipe, direct-call range isolation/reconciliation, and schema activation remain with Slices 6-14; their live reply transports are not retired here. | later ownership `implementation/milestones/prompt-router/skeleton.md:126-134,153-154`; current authority pairing `orchestrator/driver.py:2800-2897`; role-last admission `orchestrator/driver.py:2986-3082`; standalone store/admission `orchestrator/task_api.py:49-184`; current project checks `orchestrator/verifiers.py:398-483,486-563` | touch the author adapter without changing these seams; do-not-expand into staffing/model routing, session execution, judgment validation, recovery, activation, or standalone order semantics |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_author_call_cutover orchestrator.tests.test_prompt_router orchestrator.tests.test_prompt_contracts orchestrator.tests.test_canonical_plan orchestrator.tests.test_worker_tasks orchestrator.tests.test_malformed_observability orchestrator.tests.test_producer_selection orchestrator.tests.test_task_panel orchestrator.tests.test_service_api orchestrator.tests.test_e2e_fakecli`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Each owned job uses one canonical charge | new `test_direct_author_charge_matrix_uses_bound_set_and_admitted_material` | Skeleton/note/implementation dispatch as their exact `kind@unit` jobs with `agent_call`, bound prompt-set name (including the transitional absent-field `default`), document/document/code defaults, and an admitted explicit material when present. Only skeleton receives the executor catalogue; no routed prompt contains a family header, raw selector, or retired planning authority. | strict |
| Implementation assignment and live meter stay aligned | new `test_implement_charge_preserves_part_scope_and_live_size_thresholds` | An uncut implementation has no invented part assignment. A continuation charge renders exactly the predecessor's recorded remaining scope as its whole assigned work and marks completed or delegated work outside that assignment. With non-default per-run limits, both the final provider/trace prompt and the live meter use those exact soft/hard values and do not render 500/750; default values still render when they are the effective pair. Repeat the assertions on a later physical attempt. | strict per metered physical call |
| Every physical attempt is router-only, fresh, and exactly traced | new `test_every_author_physical_attempt_resolves_fresh_and_traces_exact_input` | A prompt-set edit between two provider attempts appears only in the second; initial, contract-correction, infrastructure-retry, resumed-author, and implementation-stabilizer fixtures each cross the resolver and plan guard. For every fixture, the final rendered and bound canonical charge byte-equals both the provider input and recorded trace; recovery context is present only when supplied by that charge, with no caller-owned addition or replacement, and fallback is sidecar-only. | strict per call / best-effort cross-call visibility |
| Served sections and enforcement cannot drift apart | new `test_author_reply_validation_is_bound_to_served_sections_and_safeguards` | Each valid author/status shape passes with all mounted answers; deleting or duplicating an answer, violating a served section, omitting an active safeguard field, or adding `slices`, `battery`, `suite_command`, a planning flag, or a status-incompatible field fails before draft/result recording. The safeguard prompt and compiled check are selected together. | strict |
| The first plan comes only from the supplied skeleton file | new `test_draft_skeleton_establishes_plan_without_reply_slices` | A valid block in the supplied skeleton path commits, anchors, projects, and creates work in array order independently of an exact, mismatched, non-`ok`, or malformed reply. Only the exact artifact reply records a successful draft. A mismatched artifact rejects that recording but leaves the valid plan outcome intact and never redirects to another path. A block only at another path, or missing/duplicate/malformed/invalid content at the supplied path, leaves no new anchor, projection, or planned slice units; reply `slices` is rejected. | strict |
| Every owned call enforces the anchored block | new `test_author_calls_guard_and_compare_the_plan_per_physical_dispatch` | Unexplained valid-looking, malformed, or missing pre-call drift stops before the runner without rebaseline or restoration. From a matching anchor, unchanged bytes skip validation; a valid delta survives and projects independently of an `ok`, non-`ok`, or malformed reply while reply handling keeps its own result, and each invalid delta restores governed Git-visible work-tree bytes under existing exclusions, the index tree, HEAD identity/tip, the prior canonical anchor, and prior projection and does not advance the author result. Unrelated refs, reflogs, stash, and other Git plumbing are not captured, restored, or asserted. Cases cover all three jobs and a second physical attempt. | strict |
| Removing controls leaves one plan writer and no collateral loss | new `test_legacy_plan_controls_are_absent_while_projection_and_tasks_remain` | Both former POST paths return the service's ordinary not-found response and append no event; retired writer/replay/error names and panel editor sentinels are absent. Detail/panel still render canonical producer/material values in delivery order, plan-selected producer admission still works, role-last configuration remains, and a standalone `/api/tasks` order behaves unchanged. | strict retirement / strict retained contracts |
| Existing router, contract, task, and trace behavior remains coherent | existing focused modules in the command above | Whole-rung fallback/freshness, canonical plan validation/guard, registered author contracts, task ownership and size controls, malformed-call accounting, read-only plan display, and the end-to-end fake-CLI author flow all retain their applicable results after obsolete control assertions are removed. | strict compatibility within owned seams |

The repository's official full suite remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:544-546`). It belongs to the scheduled checkpoint, not
this slice's focused implementation gate.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** the milestone driver's three direct author paths and worker-task recovery; physical runner dispatch/trace; prompt router and registered contracts; canonical-plan anchor/guard plus post-call adoption; project-extension validation; producer/material service writers, driver replay, and panel editors; focused fixtures. **Verified retained:** plan projection, producer task admission/material, implementation size control, role-last staffing configuration, and standalone tasks. **Verified untouched:** Brainstorming turns, judgment/suite calls, plan wipe/reconciliation, activation, and all external roots. | direct authors `orchestrator/driver.py:7563-8022`; physical runner `orchestrator/runners.py:2855-3185`; plan seams `orchestrator/canonical_plan.py:251-389`; controls `orchestrator/service.py:2893-2950,5084-5133`, `orchestrator/static/panel.html:5803-6013`; retained admission `orchestrator/driver.py:2986-3082`; later ownership `implementation/milestones/prompt-router/skeleton.md:126-134` |
| pinned_facts | The exact three author charges/material sources and skeleton-only catalogue; exact implementation-part assignment and per-run meter limits; per-physical fresh resolve/bind/trace with sidecar fallback; exact author/status reply vocabulary with mounted questions and project safeguards but no reply plan; initial and later canonical-plan boundaries; complete producer/material control retirement; and explicit retained/later consumers. | `implementation/milestones/prompt-router/skeleton.md:64-101,124-134,142-154`; binding intent `implementation/milestones/prompt-router/goal.md:24-109,144-145`; Pinned-Facts Table above |
| verification | Eight checks exercise the charge matrix, exact continuation scope and custom/default meter agreement, edit-between-attempt freshness, exact prompt traces, every author/status/section/question case, active project safeguards, first-plan establishment, pre-call drift, all post-call delta classes with proportional governed restoration, complete control absence, retained plan/task/standalone behavior, and applicable existing end-to-end behavior. The focused command names every touched test family; the official full suite remains the scheduled checkpoint. | Verification Contract above; current scope projection tests `orchestrator/tests/test_driver_implementation_size.py:2272-2371`; current freshness/fallback tests `orchestrator/tests/test_prompt_router.py:500-658`; current contract field tests `orchestrator/tests/test_prompt_contracts.py:657-700`; current anchor/guard and proportional restore tests `orchestrator/tests/test_canonical_plan.py:240-533`; official suite `orchestrator/README.md:544-546` |
| reuse_posture | Affected parties are operators and authors; wrong instructions, replies, scope, limits, or plan projection can waste an irreversible call or order wrong work, while governed worktree/index/HEAD/anchor rollback is locally reversible. Every granted root was searched and the relevant local/runtime seams were checked; no parallel fitting boundary exists. Reused are the prompt selector/router/corpus, existing implementation-scope projection and effective meter configuration, contract registry, canonical validator/anchor/guard, worker/task seams, project checks, trace recorder, and proportional repository capture/restore primitives. Cheapest sufficient is one author adapter plus the existing proportional post-call boundary and deletion of writers; no second scope record or size policy, cache, service, store, migration, notification, retry, or unrelated Git-state recovery is justified. | outcome authority `implementation/milestones/prompt-router/skeleton.md:106-119,128`; prompt reuse `orchestrator/prompt_sets.py:496-569`, `orchestrator/prompt_router.py:395-415`; scope/meter reuse `orchestrator/state.py:649-687`, `orchestrator/driver.py:1696-1735`; contract/plan reuse `orchestrator/prompt_contracts.py:733-805`, `orchestrator/canonical_plan.py:285-540`; repository reuse `orchestrator/gitops.py:787-872`; operator amendment A1 |
| enforceability | Each asserted invariant has an expressible seam: closed charge routing and fresh whole-rung selection; declaration-driven rendering and prompt-bound registered validation; existing compiled project checks; exact prompt recording; exact canonical-block extraction/anchor/guard; proportional worktree/index/HEAD/anchor capture and restoration; service/panel route absence tests; and existing task/standalone contracts. No unrelated-ref, reflog, stash, or Git-plumbing recovery, semantic prompt policing, cross-call consistency, automatic drift restoration, plan diff/wipe, range reconciliation, optimistic/eventual delivery, or legacy migration guarantee is asserted. | routes/resolution `orchestrator/prompt_router.py:28-140,395-415`; contracts `orchestrator/prompt_contracts.py:576-805`; project checks `orchestrator/verifiers.py:398-563`; trace `orchestrator/runners.py:1663-1676,1754-1757`; plan `orchestrator/canonical_plan.py:99-133,285-540`; restore `orchestrator/gitops.py:787-872`; operator amendment A1 |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Every owned physical dispatch uses only one fresh, complete canonical charge and the exact provider input is observable | Closed direct routes and forbidden caller controls are at `orchestrator/prompt_router.py:28-140`; fresh whole-rung resolution is at `orchestrator/prompt_router.py:395-415` and `orchestrator/prompt_sets.py:496-569`; exact input recording is at `orchestrator/runners.py:1663-1676,1754-1757`. | Change one stored prompt between physical attempts, vary job/material/prompt-set and recovery contexts, and byte-compare the final bound charge, runner input, and immutable trace; reject any caller-owned prompt addition or replacement and keep fallback sidecar-only. |
| Each implementation worker receives only its current part assignment and the size limits its live meter enforces | Existing durable cuts project the current part at `orchestrator/state.py:649-687`; effective per-run limits already drive the meter at `orchestrator/driver.py:1696-1735`; declared prompt variables render through `orchestrator/prompt_router.py:126-140,395-415`. | Create an uncut unit and a continuation with a recorded remainder, then dispatch with default and custom soft/hard pairs. Compare the assignment and rendered limits in the final provider/trace charge to the durable scope and the same call's meter values, including a later physical attempt. |
| Author replies satisfy exactly the served sections, mounted questions, and active project safeguard | Prompt binding/validation is at `orchestrator/prompt_contracts.py:733-805`; closed author fields are at `orchestrator/prompt_contracts.py:20-24,111-216,622-715`; project extensions compile and check at `orchestrator/verifiers.py:159-216,311-483,486-563`. | Bind the actual assembled prompt, mutate one section/question/status field at a time, and run one active project policy through prompt plus validation; reject every retired plan/output field. |
| The first valid block establishes the only plan at the supplied path before scheduling, independently of reply validity | The canonical path is supplied by the skeleton charge; reply validation is registered separately at `orchestrator/prompt_contracts.py:733-805`; exact extraction/schema/projection and committed anchoring are at `orchestrator/canonical_plan.py:99-133,185-267,308-338`; plan enumeration consumes state order at `orchestrator/state.py:690-715`. | Start from an empty/stale projection and vary the returned artifact path, reply status/shape, and every block/schema failure independently. Every valid committed block at the supplied path populates the ordered units; only the exact artifact reply records draft success, and no reply path can redirect or suppress the plan outcome. |
| No owned call dispatches over drift, and each physical call either preserves a valid block outcome or restores its governed pre-call boundary | Pre-dispatch comparison and the proportional repository capture/restore boundary are at `orchestrator/canonical_plan.py:317-353,375-540`; HEAD identity/tip, index/worktree tree capture, and governed restoration are at `orchestrator/gitops.py:787-872`; byte-exact committed reads are at `orchestrator/gitops.py:1137-1156`. | Seed dirty tracked, untracked, and index state, then exercise unchanged, valid-changed, malformed, missing, and duplicate blocks across first and later physical attempts; compare governed work-tree bytes, index tree, HEAD identity/tip, anchor, and projection after each. Do not snapshot or assert unrelated refs, reflogs, stash, or other Git plumbing. |
| Removed milestone controls cannot author state while canonical projection, producer admission, and standalone orders still work | Current removable route/writer/replay surfaces are at `orchestrator/service.py:2893-2950,5084-5133`, `orchestrator/tasks.py:459-658`, and `orchestrator/driver.py:1493-1578`; retained projection/admission are at `orchestrator/canonical_plan.py:217-267`, `orchestrator/tasks.py:436-456,693-725`, and `orchestrator/driver.py:2986-3082`; standalone admission is at `orchestrator/task_api.py:49-184`. | Assert ordinary 404/no event for both old URLs and static absence of editor/writer/replay symbols, then admit one plan-selected milestone producer and one caller-authored standalone task without changing their recorded semantics. |

There is deliberately no enforcement row for Brainstorming turns, judgment or
suite calls, plan-history diff/wipe, accepted-range isolation, reconciliation,
schema activation, semantic prompt quality, cross-call convergence, or legacy
migration: this slice asserts none of them.
