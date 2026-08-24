# Slice 03 — Registered contracts, QUESTIONS, and plan boundary

## Register 1 — INTENT (lay language)

### What this slice builds

This slice builds two foundations that later calls can use without inventing
their own rules.

First, every shipped reply instruction is paired with the rule that can check
it. A caller may add only a known reply instruction. An operator-added unknown
instruction still reaches the worker, but it creates no hidden promise that the
orchestrator cannot check. The questions actually included in a prompt become
the checklist required in that reply, including replies that stop or ask for
help.

Second, the slice plan is read from the one plan block in the skeleton. A valid
block can become the run's plan and a repository revision becomes its anchor.
Before a later call starts, an exact comparison can distinguish the anchored
plan from unexplained editing and refuse the call without silently accepting or
rewriting the new bytes.

This slice exposes and proves those boundaries. It does not move a live worker,
discussion seat, service route, or panel onto them. The call-owning slices adopt
the boundaries in delivery order.

### Ownership and boundary

Owned here are the shipped reply-contract registry, composition of registered
validation, admission of consumer-added reply sections, mounted-question
validation, exact extraction and validation of the canonical plan, its run-state
projection, its repository anchor, and the pre-dispatch drift decision.

The contract boundary accepts the assembled prompt produced by the previous
slice. The plan boundary accepts the skeleton and a committed repository
revision. Both are directly testable without changing today's dispatch path.

Not owned here are worker dispatch, prompt recording, prompt-set run binding,
service or panel exposure, post-call repository acceptance or restoration,
read-only-seat exceptions, plan diff and wipe, accepted-range repair, or legacy
retirement.

### Guarantee posture

- **Strict — registered reply obligations.** Each shipped reply section selects
  its own checking rule. The combined reply must satisfy every registered
  section actually assembled or appended; an unregistered stored section adds no
  check, while an unregistered consumer append is refused.
- **Strict presence / best-effort brevity — QUESTIONS.** Every mounted question
  id has one non-empty answer in every reply status. The short-sentence limit is
  an instruction to the worker and a review concern; the deliberate machine
  check is presence and non-emptiness, not content or length judgment. A kind
  with no mounted questions owes no question array.
- **Strict — canonical plan.** Only one correctly placed canonical block with
  the closed slice shape is valid. Its order is delivery order; no missing
  producer, defaulted producer, configuration, duplicate plan, or parallel plan
  source is accepted.
- **Strict — anchor, projection, and drift refusal.** A first accepted block is
  projected and anchored to the repository revision that contains it. The
  anchor survives reload. An unchanged block passes without becoming a new
  baseline; unexplained inter-call drift refuses dispatch without re-anchoring
  or promising restoration. The sole allowance is an already-open accepted-
  range reconciliation.
- **Optimistic / eventual / delivery guarantees — none.** This slice has no
  live call consumer, queue, retry, convergence process, or cross-process
  delivery claim.

### Dependencies and consumers

The selected prompt set from Slice 1 and assembled prompt from Slice 2 are the
earlier-slice dependencies. Existing reply validators, the executor catalogue
and retired-name reader, run-state plan projection, and Git byte/revision
primitives are reused.

Focused tests are the only consumer introduced here. The first live author-call
consumer arrives in Slice 5; judgment calls, sessions, recovery, and checkpoints
adopt the same boundaries in their assigned slices. Current legacy prompt,
reply-plan, producer, and material paths remain together until those cutovers.

### Non-goals

- No current worker or Brainstorming call is routed or validated through the new
  boundary.
- No service route, panel field, public event, plan-writing control, or new
  operator action.
- No post-call snapshot restore, block-only reinsertion, commit, source-range
  isolation, plan diff, wipe, requeue, seal, or merge-repair completion.
- No removal of legacy `battery`, reply-plan, producer, or material behavior;
  their synchronized retirement belongs to the call-owning and activation
  slices.
- No general Markdown parser, second plan store, migration, cache, compatibility
  fallback, semantic question grader, or automatic drift repair.
- No change to staffing, rigor, model routing, standalone task orders, or any
  granted read-only repository.

### Acceptance and size

Acceptance is the focused contract below. It proves the complete shipped
section registry, section composition and append rules, every-reply mounted
questions, the exact canonical-block shape, read-only executor compatibility,
projection and durable anchoring, unchanged-byte behavior, and pre-dispatch
drift refusal. Existing router and task tests prove the input seams remain
compatible; existing worker traffic remains unchanged.

The implementation is expected to exceed the roughly 500-line aim because B1
deliberately assigns both the complete shipped reply registry—including session
and suite contracts—and the canonical-plan anchor with mutation tests to this
slice. Keep each coherent implementation part near the aim; generated corpus
census data remains mechanical and does not count.

### Risks

The material risks are leaving one shipped reply section unenforced, checking a
question the prompt did not mount, turning the 300-character instruction into a
forbidden content gate, accepting a second or almost-canonical plan, rewriting a
retired executor spelling, projecting configuration, or treating drift as a new
baseline. Census fixtures, one-fact mutations, legacy-name fixtures, committed
Git fixtures, reloads, and byte-different blocks pin those failures.

### Reuse Posture

Later callers, operators, and workers are affected: omission leaves reply prose
and validation able to drift apart, while an unanchored plan can schedule work
different from the reviewed skeleton. Before cutover the exposure is confined to
tests and is fully reversible; after cutover, a wrong reply can waste a call and
a wrong projection can select the wrong work.

The workspace, dependencies, and all granted roots were checked. No existing
canonical-plan extractor or prompt-section registry fits this contract. Reused
are the assembled section/question ids, current reply validators and merged-
validation pattern, exact-object extraction, exact-key and non-empty-text
checks, the one TaskExecutor catalogue and retired-name reader, the existing
run-state plan projection, atomic state persistence, and Git revision/byte
reads. The cheapest sufficient option is one closed registry over those
validators plus one narrow JSON-block boundary over the existing state and Git
seams. Documentation alone cannot reject a reply, malformed plan, or dispatch
drift; a general Markdown parser, second store, route, cache, migration, or
background watcher would add lifecycle cost without an authorised consumer.

The remaining new machinery is therefore limited to those two boundaries and
their table-driven tests. Its operating cost after adoption is one skeleton read
and exact comparison at a guarded dispatch, plus an anchor update only after an
accepted plan change. That cost is smaller than rework after an unchecked reply
or wrong plan and is reversible before consumer cutover.

### Planning-context disposition

**Adopts** the reviewed skeleton, accepted amendment B1, and the converted seed
corpus. **Revises** the older optional-planning, reply-plan, split-rethink, and
legacy-battery decisions only where the reviewed baseline already does so.
**Uses** the adapted-corpus README and older captures as evidence of ids and
conventions, never as independent authority. **Rejects** other brainstorming or
`_drafts` material as implementation authority.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Registered reply sections | The closed shipped registry contains exactly the output-section ids present in the converted seed: `common_fields`, `draft_skeleton_result`, `draft_slice_note_result`, `envelope_compact`, `envelope_verbose`, `implement_result`, `need_rethink_author`, `questions_output`, `review_blocked`, `review_contract`, `review_need_rethink`, `discussion_turn_envelope`, `fix_blocked`, `fix_need_rethink`, `fix_results`, `fix_retry`, `merge_repair_result`, `questioner_turn_envelope`, `reclassify_result`, and `suite_checkpoint_result`. Each id selects its assembled prose and its checking rule; validation is the union of registered assembled and registered consumer-appended ids. Stored unknown ids are served and ignored; consumer-appended unknown ids are refused. | `implementation/milestones/prompt-router/goal.md:93-109,111-145`; `implementation/brainstorming/prompt-router/adapted-kinds/shared/shared.json:481-615`; kind-local ids `implementation/brainstorming/prompt-router/adapted-kinds/milestone/fix_findings.json:186-252`, `implementation/brainstorming/prompt-router/adapted-kinds/milestone/reclassify.json:124-142`, `implementation/brainstorming/prompt-router/adapted-kinds/milestone/suite_checkpoint.json:85-130`, `implementation/brainstorming/prompt-router/adapted-kinds/milestone/merge_repair.json:92-108`; session ids `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/discussion_turn.json:146-165`, `implementation/brainstorming/prompt-router/adapted-kinds/brainstorming/questioner_turn.json:112-130` | touch one code registry and target validators; do-not-add a second resolver, expose validation rules through the prompt API, infer obligations from unknown prose, or cut over current callers |
| QUESTIONS reply contract | The expected set comes from the assembled prompt's mounted question ids. A kind with at least one requires top-level `questions` in every status, with one `{id, answer}` entry per mounted id and a non-empty string answer; a kind with none owes none. The authored answer bound is 300 characters, but machine acceptance checks presence and non-emptiness only. Retire `battery` only with the later caller/activation cutover. | `implementation/milestones/prompt-router/goal.md:116-132`; `implementation/brainstorming/prompt-router/adapted-kinds/shared/shared.json:574-581`; assembled ids `orchestrator/prompt_router.py:243-280`; later synchronized retirement `implementation/milestones/prompt-router/skeleton.md:149,153-154` | touch the target reply boundary; do-not-content-grade answers, enforce the prose length as a machine gate, invent questions, or remove the live legacy validator in this slice |
| Canonical block and slice schema | The skeleton has exactly one `## Canonical slice plan` heading immediately followed by one fenced `json` object with root exactly `{"slices":[...]}`. Array order is delivery. Every slice has exactly unique non-boolean integer `id`, non-empty `title` and `intent`, optional non-empty `material`, and `producer_task_executor` with exactly string ids `draft_slice_note` and `implement`; each id must be accepted by the one TaskExecutor catalogue. No other key or configuration is valid. | `implementation/milestones/prompt-router/skeleton.md:69-80,118-136,143-144`; catalogue `orchestrator/tasks.py:41-109,202-204`; exact-shape primitives `orchestrator/tasks.py:153-173` | touch one exact block extractor and activated-plan validator; do-not-add a Markdown parser, duplicate plan, default, configuration, reply plan, route authority, or state-authored plan |
| Executor compatibility and projection | On a retained slice id and producer kind, an executor spelling unchanged from the anchored prior block remains readable; `stored_task_executor` is applied only while projecting that retained spelling. A new or changed spelling is validated prospectively, so retired `worker` may project as `agent_call` but cannot be newly authored. Projection preserves the existing slice shape and emits each producer as exactly `{"task_executor": current_id}` with configuration omitted; the validated array replaces `state["milestone"]["slices"]` before plan enumeration or ordering. | `implementation/milestones/prompt-router/skeleton.md:71-80,143-144`; read compatibility `orchestrator/tasks.py:104-116`; current prospective/read split `orchestrator/tasks.py:302-316`; plan consumers `orchestrator/state.py:676-715,2770-2781` | touch compatibility-aware validation and the existing projection only; do-not-rewrite anchored spellings, accept a retired spelling as a new write, retain producer defaults, or create another plan representation |
| Git anchor and pre-dispatch drift | The first validated/projected block is anchored to the full committed Git revision containing those exact block bytes and survives state reload. Later dispatch admission compares the current block with the last validated/projected anchor: byte identity is unchanged and does not revalidate; any other inter-call drift blocks to the operator before dispatch, does not move the anchor or projection, and is not automatically restored. Only an already-open accepted-range reconciliation may dispatch from its repair base while the accepted-revision block remains anchor and plan. | `implementation/milestones/prompt-router/skeleton.md:69-80,86-92,144,151`; exact Git revision/bytes `orchestrator/gitops.py:797-824,1121-1140`; atomic state reload/save `orchestrator/state.py:233-240,435-450` | touch the mechanical anchor and callable pre-dispatch guard; do-not-rebaseline drift, add an admission flag, promise restoration, or implement reconciliation in this slice |
| Slice boundary | This slice adds directly testable registry and plan-boundary seams only. Current direct calls still validate through `contracts.validate_worker_output`; current sessions, driver plan updates, service/panel controls, post-call restore, diff/wipe, accepted-range isolation, and activation remain untouched. | assigned intent `implementation/milestones/prompt-router/skeleton.md:123-134`; current direct validator `orchestrator/runners.py:2860-2897`; current reply validator `orchestrator/contracts.py:898-1195`; current reply-plan projection `orchestrator/driver.py:4649-4695,8001-8015` | touch new seams and focused tests; do-not-wire a live consumer, remove legacy transport/control, edit external roots, or pull work from Slices 4-14 forward |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_prompt_contracts orchestrator.tests.test_canonical_plan orchestrator.tests.test_prompt_router orchestrator.tests.test_tasks`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Every shipped section has one enforceable identity | new `test_shipped_contract_section_registry_is_complete` | A corpus census equals the closed registry exactly; each id resolves one section/checking pair, and no validation rule appears on the served prompt wire. | strict |
| Registered validation composes; unknown handling depends on origin | new `test_registered_sections_compose_and_append_by_origin` | Table-driven valid and one-fact-invalid replies exercise every shipped section. A synthetic stored unknown remains served and adds no check; a registered consumer append adds prose and enforcement once; an unknown or duplicate consumer append is refused. | strict |
| Mounted QUESTIONS bind every reply status | new `test_mounted_questions_are_present_in_every_reply` | Direct and session fixtures derive ids from the assembled prompt. Missing, duplicate, wrong-id, non-string, or empty answers fail on `ok`, `blocked`, `retry`, and `need_rethink`; a non-empty answer over 300 characters is not rejected by the presence-only machine gate; no-question technical kinds owe no array. | strict presence / best-effort brevity |
| Only the canonical plan form validates | new `test_canonical_plan_block_and_closed_schema` | The reviewed block passes. Missing, duplicate, separated, wrongly fenced, malformed, wrong-root, extra-key, empty-text, boolean/duplicate-id, missing-producer, configuration, and unknown-executor mutations each fail without a projection or anchor. | strict |
| Retired executor compatibility is read-only | new `test_anchored_executor_spelling_is_read_compatible_only` | An unchanged anchored `worker` spelling projects to `agent_call`; the same spelling on a new slice or changed producer fails prospective validation; current spellings pass and every projection omits configuration. | strict |
| Projection and the Git anchor are one accepted boundary | new `test_first_anchor_projects_before_plan_use_and_survives_reload` | A committed valid block replaces the stale state projection before plan enumeration, records the full containing revision, reloads identically, and resolves its anchored bytes from Git. | strict |
| Drift never becomes a baseline by observation | new `test_predispatch_guard_refuses_unexplained_drift_without_rebaseline` | Exact current/anchor bytes pass without revalidation. A valid-looking or malformed changed block refuses before the dispatch probe and leaves anchor/projection unchanged; only the accepted-range fixture reaches its already-open repair call while retaining the accepted anchor. | strict |
| Existing inputs and consumers remain stable | existing `orchestrator.tests.test_prompt_router` and `orchestrator.tests.test_tasks` | Assembled prompt shapes, section/question ordering, TaskExecutor catalogue behavior, standalone order behavior, and current producer compatibility keep their reviewed results. | strict compatibility |

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
| consumers_touched | **Verified touched:** Slice 2's assembled section/question ids, the existing reply-validation primitives, the TaskExecutor catalogue/read alias, the run-state slice projection, and Git/state persistence seams; new focused tests are the only immediate consumer. **Verified untouched:** current runner, driver, Brainstorming execution, service, panel, standalone orders, and every granted external root. | assembled result `orchestrator/prompt_router.py:243-282`; validators `orchestrator/contracts.py:113-162,898-1195`; executors `orchestrator/tasks.py:41-116,202-204`; projection `orchestrator/state.py:676-715,2770-2781`; current dispatch `orchestrator/runners.py:2860-2897`; assigned cutovers `implementation/milestones/prompt-router/skeleton.md:123-134` |
| pinned_facts | The closed shipped section-id registry and origin-sensitive append rule; mounted, every-status, presence-only QUESTIONS validation; the sole exact canonical-block schema; retained-only executor compatibility and configuration-free projection; the full-revision Git anchor; and drift refusal with only the already-open reconciliation allowance. | `implementation/milestones/prompt-router/skeleton.md:69-92,123-134,143-154`; `implementation/milestones/prompt-router/goal.md:93-109,116-145`; converted ids `implementation/brainstorming/prompt-router/adapted-kinds/shared/shared.json:481-615` |
| verification | The seven new checks census every shipped section, mutate each contract class, distinguish stored from appended unknown ids, cover question-bearing statuses and no-question kinds, mutate every plan axis, prove retained-name compatibility, reload the anchor, and stop dispatch on both valid-looking and malformed drift. Existing router/task tests pin the reused inputs. | `implementation/milestones/prompt-router/slices/slice-03.md:168-188`; current section/route tests `orchestrator/tests/test_prompt_router.py:93-337`; current catalogue/producer tests `orchestrator/tests/test_tasks.py:1-120`; official suite `orchestrator/README.md:544-546` |
| reuse_posture | Wrong reply enforcement and wrong plan projection affect later callers; spent calls are irreversible but repository/state changes are reviewable and recoverable. All granted roots and dependencies were checked; no fitting registry or canonical-block boundary exists. Reused are assembled ids, current validators and merged-validation pattern, exact JSON selection, task exact-key/catalogue/alias logic, current plan projection, atomic state persistence, and Git byte/revision reads. Cheapest sufficient is one closed registry plus one narrow JSON-block boundary; no route, parser, store, cache, migration, or watcher is justified. | registry need `implementation/milestones/prompt-router/goal.md:93-109`; assembled ids `orchestrator/prompt_router.py:243-282`; validator composition `orchestrator/verifiers.py:486-560`; exact JSON `orchestrator/runners.py:961-1006`; plan reuse `orchestrator/tasks.py:104-116,153-204`; Git bytes `orchestrator/gitops.py:797-824,1121-1140` |
| enforceability | Registered sections reuse the sole-object selector, field validators, and merged-validation seam; QUESTIONS reuse the existing exactly-once/non-empty shape pattern but deliberately omit its evidence/length rules; plan shape uses existing exact-key/text/catalogue checks; compatibility uses `stored_task_executor`; projection feeds existing plan consumers; full revisions plus byte-exact `show_file` and atomic state persistence express anchoring and drift refusal. No semantic-answer, automatic-restore, runtime-delivery, optimistic, eventual, or migration guarantee is asserted. | `orchestrator/runners.py:892-906,961-1006`; `orchestrator/contracts.py:113-162,720-783,898-1195`; `orchestrator/verifiers.py:486-560`; `orchestrator/tasks.py:104-116,153-204,302-316`; `orchestrator/state.py:233-240,435-450,676-715`; `orchestrator/gitops.py:797-824,1121-1140` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Every shipped section id selects prose and one checking rule; appended unknown ids fail while stored unknown ids add no rule | The assembled section carries its id/text at `orchestrator/prompt_router.py:249-281`; existing kind checks live at `orchestrator/contracts.py:898-1195`; the compositional validation seam is `orchestrator/verifiers.py:486-560`. | Census the seed ids, exercise one valid and one invalid reply per rule, then inject the same synthetic unknown once from storage and once as an append. |
| Every mounted question has one non-empty answer in every applicable status, without content or length policing | The prompt exposes exact assembled ids at `orchestrator/prompt_router.py:243-280`; the existing exactly-once/non-empty list pattern is `orchestrator/contracts.py:720-783`; the target presence-only law is `implementation/milestones/prompt-router/goal.md:116-132`. | Mutate id, multiplicity, type, emptiness, status, and length; derive expected ids from the assembled prompt, not a second kind table. |
| Only one exact canonical block and closed slice schema can project | Existing exact-key/non-empty checks are at `orchestrator/tasks.py:153-173`; the sole live TaskExecutor catalogue is `orchestrator/tasks.py:41-109,202-204`; the authoritative block/schema is `implementation/milestones/prompt-router/skeleton.md:118-144`. | Mutate one heading, fence, root, slice field, producer, or id fact at a time and require no projection or anchor. |
| Retired executor spellings survive only unchanged reads | The single compatibility map/read is `orchestrator/tasks.py:104-116`, while prospective catalogue validation is `orchestrator/tasks.py:302-316`. | Compare each producer spelling to the anchored prior block before choosing read compatibility or prospective validation. |
| Projection is installed before plan use and remains configuration-free | Existing consumers enumerate and expose only `state["milestone"]["slices"]` at `orchestrator/state.py:676-715,2770-2781`. | Start from a contradictory stale projection, accept a committed block, then call the existing enumerator/summary and require the block-derived order and producer objects. |
| An anchor is a durable Git fact and unexplained drift cannot dispatch or rebaseline itself | Full revision and worktree-tree primitives are `orchestrator/gitops.py:797-824`; byte-exact committed reads are `orchestrator/gitops.py:1121-1140`; atomic reload/save is `orchestrator/state.py:233-240,435-450`. | Commit, anchor, reload, compare exact bytes, then edit only the block and assert the dispatch probe is untouched and the prior revision/projection remain. |

There is deliberately no enforcement row for live worker delivery, post-call
rollback, read-only preservation, plan diff/wipe, accepted-range completion,
service/panel behavior, semantic answer quality, or legacy retirement: this
slice asserts none of them.
