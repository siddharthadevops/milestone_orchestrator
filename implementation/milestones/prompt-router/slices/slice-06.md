# Slice 06 — Milestone judgment-call cutover

## Register 1 — INTENT (lay language)

### What this slice builds

This slice moves milestone reviews, incremental reviews, fixing, and the small
per-finding rating call onto the prompt set selected for the run. Every actual
attempt receives the prompt for its exact job, the current operator amendments,
the complete scoped project context it may use, including active safeguards and
granted roots, and the reply rules that will judge its answer. The text sent to
the provider is also the text recorded for the operator.

These calls now share the skeleton's plan boundary. A fixer may edit ordinary
work and the one canonical plan block. A reviewer, incremental reviewer, or
rater remains read-only: ordinary work is discarded, but a valid change to the
plan block is kept by itself. A read-only call that changed governed state cannot
also count as the judgment that advances the milestone; a later unchanged call
must judge the resulting repository.

An invalid plan edit rejects the call and restores the governed repository
state from immediately before that attempt. This is a normal-path repository
boundary, not protection from arbitrary Git surgery. Damage outside the
declared boundary may require the operator to recover or restart the milestone.

### Ownership and boundary

Owned here are the direct review, incremental-review, fixer, and rating calls
for the skeleton, slice notes, and slice implementations. This includes every
physical attempt used by their ordinary reply-correction flow, exact prompt
traces, registered and project-extended reply checking, current-amendment and
project-authority consumption, and the post-call canonical-plan decision.

The call's reply does not grant plan authority. Judgment replies no longer
carry a second slice plan or correct the complete-suite command. Plan edits live
only in the skeleton block, while complete-suite discovery and execution stay
with the scheduled checkpoint.

Fixer consultations remain the one exception: the fixer conducts that narrow
dialogue itself and records its transcript through the existing scratch-path
contract. This slice neither routes nor turns consultations into milestone
sessions.

### Guarantee posture

- **Strict per physical judgment call — prompt, authority, trace, and reply.**
  Each attempt freshly resolves one complete prompt-set rung, assembles the
  exact job and material, includes one complete current mutable-amendment set,
  includes every active project safeguard scoped to that judgment with its
  exact granted-root universe, binds the served sections and questions plus
  those project contract extensions, and sends and records that same charge.
  On a completion status, a valid extension field is part of the reply contract,
  including on the otherwise closed rating envelope. `blocked`, `retry`, and
  `need_rethink` finish no artifact and validate only their routed base envelope;
  `retry` must not claim an extension field. A registered contract correction is
  another physical attempt and crosses the same boundary again. On the activated
  schema, a required input or scoped project authority that remains invalid at
  consumption stops before dispatch. If the ordinary correction is exhausted
  without a valid rating, the driver records one concise terminal failure,
  retains only the started attempts' accounting, and adopts neither the parent
  review nor a fixer decision for that finding.
- **Strict — editable fixer plan boundary.** A byte-identical plan is not
  revalidated. A valid changed block survives independently of reply validity
  and refreshes the anchor and projected plan. A missing, duplicate, malformed,
  or invalid changed block rejects the attempt, restores governed Git-visible
  work-tree bytes under existing exclusions, the index tree, HEAD identity/tip,
  and the prior canonical anchor, and records a terminal boundary failure.
- **Strict — read-only judgment boundary with one exception.** Review,
  incremental review, and rating calls preserve no governed mutation except one
  valid changed canonical block. When they mutate, their judgment cannot close
  a review, accept a delta, or defer a finding; a fresh unchanged judgment is
  required. Excluded tool-cache churn remains outside the governed bytes.
- **Strict — one plan and one suite authority.** Replies from these calls cannot
  carry `slices`, planning-control fields, or fixer suite-command corrections.
  The ordinary review/fix/debt lifecycle consumes only the registered routed
  result.
- **Best-effort across calls, strict whole-rung fallback.** A completed prompt
  edit is eligible for the next attempt. There is no cross-call snapshot,
  notification, monotonicity, or convergence promise; a dispatched prompt stays
  fixed, and an unreadable named rung falls as a whole to the stored default,
  then the in-code seed. Only failure remaining after that ladder stops dispatch.
- **Optimistic or eventual delivery — none.** These are synchronous direct
  calls. The slice adds no queue, background convergence, generic retry system,
  or delayed plan propagation.

### Dependencies and consumers

Slices 1–4 supply whole-set resolution, canonical charge assembly, registered
contracts, questions, plan extraction/anchoring/projection, pre-dispatch drift
blocking, and the immutable run prompt-set binding. Slice 5 supplies the shared
per-physical-call preparation/completion seam and the proportional repository
capture/restore primitives.

The live consumers touched are the milestone driver's full-review,
incremental-review, fixer, and per-finding rating paths; the direct worker
runner and prompt trace; the registered contract validator; canonical-plan
projection; and the existing review, fix, debt, task-accounting, and seal
lifecycle that consumes accepted results.

### Non-goals

- No Brainstorming producer/rethink seat cutover, repository-turn handling,
  readiness rule, or session close behavior.
- No suite-checkpoint call, suite discovery, checkpoint cadence, or failure
  repair; fixers do not become a second suite authority.
- No plan-history diff, wipe calculation, accepted-range isolation,
  reconciliation, merge repair, or semantic proof of a plan edit.
- No schema-version bump, legacy-run migration, fallback adapter, or final
  activation of pre-schema refusal.
- No new staffing role, family/model/effort rule, TaskExecutor, material
  catalogue, or Brainstorming route for judgments.
- No routing of fixer consultations and no guarantee over provider history from
  those sub-dialogues beyond the existing transcript/result contract.
- No prompt cache, version, watcher, edit event, amendment cache, retained
  last-known-good authority, generic worker-commit folding, or second recovery
  subsystem.
- No recursive/global prompt-set inspection for defaults or variables; only the
  currently resolved and mounted judgment charge is inspected.
- No protection for unrelated refs, reflogs, stash, configuration, object
  stores, packs, alternates, private submodule metadata, or adversarial Git
  states.

### Acceptance and size

Acceptance is the focused contract below. It covers every owned job and unit
type, every fresh physical attempt, whole-rung fallback, current-amendment
replacement and terminal invalid-source behavior, scoped project-safeguard and
granted-root enforcement, exact provider/trace bytes, registered reply and
question enforcement, editable-fixer plan outcomes,
read-only restoration plus block-only preservation, judgment invalidation after
mutation, reply-plan and suite-command retirement, and unchanged review/fix/
rating/consultation lifecycle behavior.
An exhausted rating correction is the terminal-failure exception to that
retained lifecycle.

This cohesive cut is expected to exceed about 500 changed non-generated lines.
Four live consumers must cross the same boundary before their old reply
transport can retire, and the read-only block-only exception needs end-to-end
proof distinct from the editable fixer path. Shared preparation code and a
parameterized test matrix should keep the excess in proof rather than create a
parallel runtime mechanism; generated corpus/seed refreshes and mechanical
legacy-field deletions do not count toward the target.

### Risks

The material risks are resolving once per logical episode instead of once per
physical attempt; routing a unit through the wrong job or material; retaining a
revoked amendment or trusting provider history after an invalid amendment
source; tracing text different from provider input; validating against sections
or questions different from those served; rendering a project safeguard without
enforcing its extension, rejecting a valid rating extension field, or validating
a path or citation outside the exact granted roots; allowing a reply plan or
fixer suite command; counting a mutating read-only judgment; discarding its
valid plan block; preserving its unrelated mutations; suppressing a valid fixer plan edit
because its reply is malformed; retrying an invalid plan boundary; losing the
parent review's accounting around a nested rating; accidentally routing the
fixer's private consultation; or continuing to fixing after a rating remains
invalid through its ordinary correction. The focused matrix pins each case
without global lexical or Cartesian tests.

### Reuse Posture

Operators, reviewers, fixers, and later builders are affected. Wrong judgment
instructions or a mismatched validator can spend an irreversible model call,
close bad work, or discard valid work; a wrong plan can reorder subsequent
delivery. Governed repository bytes are locally reversible, while unrelated Git
state and spent calls are not. The reviewed skeleton and operator amendments
independently require this cut.

The primary workspace and every granted read-only root were checked for an
existing judgment-call router or canonical-plan boundary. The fitting machinery
exists only in this workspace and is already used by author calls: fresh
whole-rung selection, canonical route assembly, prompt rendering, registered
reply binding, standing-law selection and compilation, merged extension/root
validation, exact prompt tracing, worker accounting, canonical block validation/
anchoring, and proportional work-tree/index/HEAD restoration. The existing
review/fix/debt/seal state machine and consultation command remain the consumers;
none needs a replacement.

The cheapest sufficient option is one shared judgment packaging seam composed
with the existing physical-call, project-extension, and plan primitives, plus
the narrow read-only completion behavior. Documentation or configuration alone
cannot make prompt freshness, merged reply enforcement, or repository
restoration observable. The remaining build and maintenance cost is a small
adapter and focused consumer tests, with fresh file reads and ordinary Git
operations only when a call is attempted.
That cost is lower than silent bad judgments; caches, migrations, backup
authority, generalized Git recovery, or another store would cost more than the
reversible omission risk and have no authorized consumer.

### Planning-context disposition

**Adopts** the reviewed skeleton and the converted judgment corpus as the route,
craft, question, and reply-contract source. **Revises** the corpus decision that
omitted mutable amendments from ratings, because the current operator amendment
requires one complete replacement set before every physical attempt. **Revises**
older fixer/review text that carries reply `slices`, suite-command correction,
planning controls, or incomplete-read retention. **Rejects** brainstorming,
`_drafts`, captured prompts, and legacy builders as independent authority. The
original goal is used only for the charge/material examples, required job
payloads, and the consultation exception that the skeleton leaves concise.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Owned route matrix | Direct `agent_call` routes are exactly `review_round@skeleton`, `review_round@slice_doc`, `review_round@slice_impl`; `delta_review@skeleton`, `delta_review@slice_doc`, `delta_review@slice_impl`; `fix_findings@skeleton`, `fix_findings@slice_doc`, `fix_findings@slice_impl`; and `reclassify@doc`. Skeleton/slice-document judgments default to `document`, slice-implementation judgments default to `code`, and `reclassify@doc` receives the rated unit's effective material. A non-empty slice material is that slice's exact overlay key instead of its default. Rating stays a direct job and is never Brainstorming. | `implementation/milestones/prompt-router/skeleton.md:137-138,153-157,161`; `implementation/milestones/prompt-router/goal.md:24-59,323-332`; `orchestrator/prompt_router.py:28-55`; existing unit-material rule `orchestrator/driver.py:1604-1617`; representative bindings `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:151-208` | touch the four direct driver consumers and shared route adapter; do-not-add raw route selectors, a material catalogue, a judgment session, or a new staffing role |
| Physical prompt and authority boundary | Before every physical attempt, resolve the bound prompt set afresh as one rung, inspect only the selected mounted charge for route defaults/variables, render the canonical charge, bind exactly its registered sections and mounted questions, compile every active project safeguard scoped to that judgment, retain the exact granted-root universe, and byte-match provider input to the immutable prompt trace. The reply contract is the routed base contract plus those extensions. Their required fields and root-bounded checks apply to completion statuses; `blocked`, `retry`, and `need_rethink` validate only the routed base envelope, and `retry` cannot claim extension work. A contract correction is a fresh routed attempt, not a caller-built suffix. The mutable source is fully parsed first and contributes one unconditional complete current-set block, including `none`, that replaces every earlier mutable set. An invalid source, project policy, root grant, or routed-field collision stops before dispatch; already-started call accounting alone is retained. | `implementation/milestones/prompt-router/skeleton.md:64-68,106-111,156,158-160`; operator amendments A1 and A4; standing project law; `orchestrator/prompt_sets.py:505-578`; mounted-route inspection `orchestrator/prompt_router.py:389-438`; existing compilation/merge seam `orchestrator/verifiers.py:211-216,486-565`; `orchestrator/runners.py:2767-2795,2890-2980,3251-3320` | touch judgment prompt packaging, amendment/project-authority consumption, trace, and merged bound validation; do-not-read prompt files in consumers, mix rungs, recursively scan unmounted routes, trust provider history, retain incomplete authority, or add a cache/retry lane |
| Mutable-amendment failure posture | One structurally valid `amendments.json` is required. Omission revokes normally because the valid list is complete. Missing, unreadable, malformed, wrong-shaped, or structurally invalid bytes make driver consumption record one concise terminal failure before dispatch. `amendment_seen` is audit-only; append-only accepted design authority cannot make an invalid mutable source usable. Strict refusal is exposed only with the final schema activation. | operator amendment A4, `Declared States or Terminal Failure` and `Mutable Operator Amendments`; activation boundary `implementation/milestones/prompt-router/skeleton.md:143-145,164`; current source/renderer seams to replace `orchestrator/driver.py:2811-2920,3064-3113`, `orchestrator/prompts.py:805-868` | touch the owned calls' consumption boundary and activation-ready tests; do-not-initialize/repair on read, retain COMPLETE/INCOMPLETE behavior, infer authority from history, or activate the schema here |
| Editable fixer plan boundary | Each fixer attempt begins only from the anchored block. Unchanged bytes keep the anchor without revalidation. A valid changed block is accepted and projected before reply consumption even when the reply is non-`ok` or malformed. Missing, duplicate, malformed, or invalid changed content restores the governed pre-call work-tree bytes under existing exclusions, index tree, HEAD identity/tip, prior anchor, and projection; the attempt ends with failure type `canonical_plan_boundary` and cannot enter contract or infrastructure retry. | `implementation/milestones/prompt-router/skeleton.md:69-83,89-102,155`; operator amendment A1; `orchestrator/canonical_plan.py:264-282,329-552`; `orchestrator/gitops.py:827-872`; `orchestrator/driver.py:4066-4134` | touch fixer preparation/completion and focused state adoption; do-not-add plan diff, accepted-range reconciliation, generic commit folding, or protection for unrelated Git plumbing |
| Read-only judgment exception | `review_round`, `delta_review`, and `reclassify` are read-only. Any governed mutation rejects that judgment and restores the pre-call boundary. If the mutation contains one valid changed canonical block, preserve and commit only that block, discard every other governed mutation, refresh plan projection, and require a later unchanged judgment. The mutating result cannot close a review, accept a delta, or decide deferral; already-reported review findings may remain input. | `implementation/milestones/prompt-router/skeleton.md:84-88,137,163`; accepted amendment B1, `Canonical slice plan`; `orchestrator/contracts.py:52-80,100-106`; rating corpus `implementation/brainstorming/prompt-router/adapted-kinds/milestone/reclassify.json:2-14`; block composition `orchestrator/canonical_plan.py:135-146,329-365` | touch report/rating completion and lifecycle invalidation; do-not-count the mutating judgment, retain other bytes, or add adversarial snapshot coverage |
| Routed reply vocabulary and retirements | Review and delta use the registered review result/blocked/rethink sections; fixer uses registered fix result/blocked/retry/rethink sections and must cover exactly the queued findings; `retry_reason` is exactly `consultation_unavailable`; rating is `status: ok`, `kind: reclassify`, `drift_risk` and `drift_damage` each one of `low`, `medium`, `high`, or `xhigh`, plus non-empty `reason`. Every mounted question id has exactly one non-empty answer of at most 300 characters. Active project-extension fields are admitted only through the merged contract and are not unexpected fields on the otherwise closed rating envelope; collisions with routed protocol fields fail before dispatch. After the ordinary registered correction, a still-missing, malformed, or contract-inconsistent rating is a terminal failure: only started-attempt accounting survives, and the parent review cannot advance into fixing or debt. Judgment replies reject `slices`, `suite_command`, `suite_command_finding_id`, `design_update`, `design_correction`, `brainstorming_application`, planning controls, and other status-incompatible protocol fields. | `implementation/milestones/prompt-router/skeleton.md:158-160`; operator amendment A4; `implementation/milestones/prompt-router/goal.md:93-145,294-310`; standing project law; `orchestrator/prompt_contracts.py:227-388,584-620,630-736,754-833`; merged contract `orchestrator/verifiers.py:486-565`; `orchestrator/contracts.py:49-67,1251-1262` | touch routed and merged validators and remove judgment-side adoption of retired fields; do-not-weaken project safeguards, queued coverage, contests/adjudication checks, question presence/length, or status-specific envelopes |
| Retained lifecycle and consultation exception | Accepted outputs continue through the existing review-family cycle, delta-to-fix loop, per-finding rating/debt decision, task accounting, seals, and `need_rethink` handoff. Fixer consultation remains the sole unserved worker-owned dialogue, with its existing transcript and `consultation.resolution`/retry contract. Suite checkpoints, sessions, plan recovery, and activation retain their later owners. | `implementation/milestones/prompt-router/skeleton.md:49-53,137-145,161-165`; `implementation/milestones/prompt-router/goal.md:323-333`; live consumers `orchestrator/driver.py:10223-10274,10276-11080,11331-11764,12058-12396,12398-12719`; consultation validation `orchestrator/prompt_contracts.py:260-345` | touch prompt/plan boundaries around these consumers; do-not-redesign their sequencing, debt threshold, consultation command, checkpoint, session, reconciliation, or seal semantics |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_judgment_call_cutover orchestrator.tests.test_prompt_router orchestrator.tests.test_prompt_contracts orchestrator.tests.test_canonical_plan orchestrator.tests.test_p3_debt orchestrator.tests.test_adversarial_fixes orchestrator.tests.test_producer_selection orchestrator.tests.test_worker_tasks`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Every owned target uses one canonical charge | new `test_judgment_charge_matrix_uses_bound_set_and_target_material` | All ten exact jobs dispatch only as `agent_call`, mount the correct document/implementation target law and non-empty material, reject raw selectors/session coordinates, and expose no caller-built prompt path. | strict |
| Every physical attempt is fresh, current, bound, and exactly traced | new `test_each_judgment_attempt_reloads_prompt_authority_and_contract` | Edit prompt text and valid mutable amendments between initial and contract-correction attempts; only the later attempt sees the new complete set, omission revokes an earlier amendment, each provider input byte-equals its trace, fallback remains sidecar-only, and each reply is checked by the sections/questions served on that attempt. A bad default on an unmounted route does not reject this charge. | strict per attempt / best-effort across calls |
| Scoped project contracts travel with every judgment attempt | new `test_judgment_attempts_merge_project_extensions_and_granted_roots` | The shared review, fixer, and rating boundary renders each active scoped safeguard and validates completion-status custom fields against the exact granted roots. A compliant custom rating field passes the otherwise closed envelope; on a completion status, a missing or malformed extension field and an out-of-grant path/citation enter ordinary contract correction. `blocked`, `retry`, and `need_rethink` validate their base envelopes without an extension field, while `retry` rejects an extension-work claim. An invalid policy, incomplete roots, or routed-field collision stops before a provider call. The route-matrix check proves all ten jobs use this shared boundary without a Cartesian policy matrix. | strict |
| Invalid mutable authority stops at consumption | new `test_invalid_amendments_source_stops_before_dispatch` | Missing, unreadable, malformed, wrong-shaped, and structurally invalid sources each produce one concise terminal failure and zero provider calls. If corruption occurs after one attempt, that attempt's accounting remains and no correction dispatch starts. No source is overwritten or reconstructed. | strict at activated boundary |
| Fixer plan outcomes are file-based and proportional | new `test_fixer_plan_boundary_is_reply_independent_and_terminal_on_invalid_change` | Across `ok`, non-`ok`, malformed, and repaired replies, a valid block delta survives and projects before reply handling. Every invalid block class restores only governed work-tree/index/HEAD/anchor observables, leaves no fixer result, records `canonical_plan_boundary`, and makes exactly one physical call. | strict |
| Read-only judgments preserve only a valid plan block | new `test_read_only_judgments_restore_everything_except_valid_plan_block` | Review, delta, and rating cases cover unchanged/no mutation; excluded cache churn; ordinary tracked/staged/untracked/HEAD mutation; valid block plus unrelated mutation; and invalid block. Only a valid plan block survives, all governed other bytes restore, the mutating result supplies no approval/delta/defer decision, and a later unchanged call is required. | strict |
| Routed outputs have one authority | new `test_judgment_replies_reject_legacy_plan_suite_and_design_fields` plus existing contract tests | Served review/fix/reclassify status matrices validate; every mounted question appears once, 300 characters passes and 301 fails; queued ids/severities, contests, adjudication refs, prevention paths, consultation resolution, and completion-status project-extension fields remain enforced; no-artifact statuses keep their base-envelope exemption and `retry` cannot claim extension work; every retired reply-plan, fixer-suite, and planning/design field fails before state adoption. | strict |
| Exhausted rating correction is terminal | new `test_exhausted_rating_contract_correction_is_terminal` | When both the initial rating and its ordinary correction remain missing, malformed, or contract-inconsistent, the run records one concise terminal failure, retains both physical attempts' accounting, does not record a rating or parent review, and does not queue the finding for fixing or debt. | strict |
| Existing judgment lifecycle remains coherent | new `test_cutover_preserves_review_fix_delta_rating_and_consultation_flow` plus existing debt/adversarial/task tests | Clean reviews still advance; findings enter the same fix/debt paths; delta findings return to fixing; a rating remains a graded input to the existing deterministic threshold; consultation retry remains worker-owned and unserved; prompt fallback/accounting evidence is retained; no judgment Brainstorming session is admitted. | strict within retained lifecycle |

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
| consumers_touched | **Verified touched:** the full-review, delta-review, fixer, and nested per-finding rating consumers; direct Worker dispatch and prompt traces; prompt router and registered-plus-project contracts; mutable-amendment and standing-project-law consumption; canonical plan boundary/projection; and focused fixtures. **Verified retained:** review/fix/debt/task/seal sequencing and the worker-owned consultation command. **Verified untouched:** Brainstorming seats, suite checkpoint, plan diff/reconciliation, schema activation, staffing/model policy, panel projection, and the bytes in all granted read-only roots. | consumers `orchestrator/driver.py:10223-10274,10276-11080,11331-11764,12058-12396,12398-12719`; project authority `orchestrator/driver.py:3016-3062`; runner `orchestrator/runners.py:2890-3320`; later owners `implementation/milestones/prompt-router/skeleton.md:138-145` |
| pinned_facts | The exact ten direct jobs and material source; per-attempt fresh prompt/current amendment/scoped project extensions and granted roots/bound contract/exact trace; terminal invalid-source or invalid-policy behavior; editable fixer and read-only plan outcomes; exact routed reply vocabulary and retired fields; and retained lifecycle/consultation boundary are the facts for which any deviation is a bug. | `implementation/milestones/prompt-router/skeleton.md:64-111,137-165`; standing project law; `orchestrator/prompt_router.py:28-55`; Pinned-Facts Table above |
| verification | Nine named checks cover the route matrix, edits between physical attempts, exact traces, current-set replacement, scoped project extensions and granted-root checks including ratings, invalid-authority failure, fixer plan deltas, every read-only mutation class, reply/status retirement, exhausted-rating terminal failure, and the end-to-end review/fix/delta/rating/consultation flow. Existing focused router, contract, canonical-plan, debt, adversarial, producer, and task modules remain in the command; the official full suite stays checkpoint-owned. | Verification Contract above; existing extension merge `orchestrator/tests/test_verifiers.py`; current route matrix `orchestrator/tests/test_prompt_router.py:234-318`; current reply gates `orchestrator/tests/test_prompt_contracts.py:304-390,469-583,688-760`; current proportional boundary `orchestrator/tests/test_canonical_plan.py:329-550`; official suite `orchestrator/README.md:544-546` |
| reuse_posture | Affected parties are operators and judgment workers; bad instructions, authority, validation, or restoration can waste a call or accept/discard the wrong work. The primary and all four read-only roots were checked; no second fitting boundary exists. Reuse the selected prompt set, router, registered validators, standing-law compiler, merged extension/root validator, exact trace, Worker accounting, canonical extractor/anchor/guard, proportional Git primitives, and current review/fix/debt/seal flow. Cheapest sufficient is one shared judgment adapter plus narrow read-only composition; no new validator, cache, store, migration, generic Git recovery/folding, or consultation router is justified. | outcome authority `implementation/milestones/prompt-router/skeleton.md:113-127,137`; reusable call seam `orchestrator/runners.py:2918-2925,3251-3320`; prompt/contract seams `orchestrator/prompt_router.py:410-438`, `orchestrator/prompt_contracts.py:754-833`, `orchestrator/verifiers.py:211-216,486-565`; repository seams `orchestrator/canonical_plan.py:329-552`, `orchestrator/gitops.py:827-872`; operator amendment A1 |
| enforceability | Fresh whole-rung resolution, declaration-driven rendering, registered prompt-bound plus scoped project-extension/root validation, per-attempt completion before reply validation, exact trace persistence, strict authority parsing at preparation, exact canonical-block comparison, proportional restore, block-only composition, and existing state transition gates can express every guarantee asserted here. Tests pin editable, read-only, and strict-rating consumers. No unrelated-Git recovery, semantic prompt policing, provider-history authority, cross-call consistency, optimistic/eventual delivery, plan-history repair, or schema activation guarantee is asserted. | resolution `orchestrator/prompt_sets.py:505-578`, `orchestrator/prompt_router.py:410-438`; validation `orchestrator/prompt_contracts.py:754-833`, `orchestrator/verifiers.py:211-216,486-565`; physical boundary `orchestrator/runners.py:2918-2980,3251-3320`; plan/restore `orchestrator/canonical_plan.py:135-146,329-552`, `orchestrator/gitops.py:827-872`; state failure/transition `orchestrator/driver.py:4066-4134`; operator amendments A1 and A4 |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Every owned physical attempt uses one fresh canonical charge, one current amendment set, one scoped project contract/root universe, and its own served reply contract | Closed direct routes are at `orchestrator/prompt_router.py:28-55`; fresh whole-rung reads are at `orchestrator/prompt_sets.py:505-578`; binding/validation is at `orchestrator/prompt_contracts.py:754-833`; existing project compilation/merge is at `orchestrator/verifiers.py:211-216,486-565`; per-attempt preparation is at `orchestrator/runners.py:2918-2980,3251-3320`. | Change prompt and amendment bytes between attempts, then compare the routed charge, provider input, trace, bound sections/questions/extensions/roots, and accepted reply for each attempt. An unreadable named prompt rung must fall whole to the stored default, then the in-code seed; only failure remaining after that ladder may stop dispatch. An invalid amendment, project policy, or root authority must fail before the provider starts. |
| Provider input and operator trace are identical and fallback is sidecar-only | Immutable trace creation is at `orchestrator/runners.py:2767-2795`; prepared fallback is attached outside prompt text at `orchestrator/runners.py:2941-2984`. | Byte-compare every dispatched prompt and trace across initial/correction attempts and all fallback rungs; assert no fallback marker enters prompt text. |
| Fixer plan edits are accepted or proportionally restored independently of reply validity | Exact extraction/validation/projection is at `orchestrator/canonical_plan.py:101-146,264-282`; guard/capture/complete is at `orchestrator/canonical_plan.py:329-552`; terminal classification is at `orchestrator/driver.py:4066-4134`. | Vary reply status/shape separately from unchanged, valid-changed, missing, duplicate, malformed, and invalid plan bytes; compare projection/anchor and governed repository observables after each. |
| Read-only judgments retain only a valid plan block and cannot advance from a mutating result | Block-only composition is at `orchestrator/canonical_plan.py:135-146`; capture/restore is at `orchestrator/canonical_plan.py:329-365` and `orchestrator/gitops.py:827-872`; review/delta/rating transition consumers are at `orchestrator/driver.py:11331-11764,12058-12396,12398-12719`. | Inject governed edits for each read-only kind, with and without a valid plan delta. Assert restored bytes, sole block survival when valid, no accepted judgment/defer decision, and one fresh unchanged successor call. |
| Judgment replies and questions obey the routed-plus-project contract and cannot re-author plan, suite, or retired design state | Question ids/answers are checked at `orchestrator/prompt_contracts.py:349-376`; the same validator can enforce the pinned 300-character limit. Allowed fields and forbidden protocol names are at `orchestrator/prompt_contracts.py:607-736`; project fields/checks are at `orchestrator/verifiers.py:486-565`; fixer coverage and rating scales are at `orchestrator/prompt_contracts.py:260-388`; contextual adoption sites are at `orchestrator/driver.py:10159-10221,10849-11030`. | Exercise missing, duplicate, empty, 300-character, and 301-character answers. On completion-status review, fix, and strict rating replies, prove a valid custom extension field is accepted and missing/malformed/out-of-root evidence is rejected. Prove `blocked`, `retry`, and `need_rethink` pass their base envelopes without an extension field and that `retry` rejects an extension-work claim. Add each retired or status-incompatible field to an otherwise valid routed reply and assert rejection before round, task, plan, suite, or debt state changes. |
| Existing review/fix/delta/debt and consultation behavior survives the cutover | Current lifecycle consumers are at `orchestrator/driver.py:10276-11080,11331-11764,12058-12396,12398-12719`; consultation result rules are at `orchestrator/prompt_contracts.py:260-345`. | Drive one clean cycle, one fixed finding, one rejected finding with consultation, one delta finding, one deferred rating, and one consultation-unavailable retry through the routed boundary without changing their state outcomes. |

There is deliberately no enforcement row for Brainstorming execution, suite
checkpoint, plan diff/wipe, accepted-range reconciliation, merge repair, schema
activation, semantic prompt quality, cross-call convergence, provider-history
reconstruction, unrelated Git plumbing, or legacy-run migration: this slice
asserts none of them.
