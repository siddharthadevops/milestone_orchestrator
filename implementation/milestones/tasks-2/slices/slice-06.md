# Slice 06 — Brainstorming slice production

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes the two producer choices in a slice plan executable. A slice
may use Brainstorming to draft its note and the familiar single Worker to
implement it, or make the opposite choice. The milestone starts the selected
producer, waits while discussion-backed work is still open, and resumes the
ordinary review-and-fix flow only after production succeeds.

For a Brainstorming note, the milestone names the note's current planned
location before discussion begins. A successful handoff replaces any older
location remembered by the unit, so reviewers and the later implementer read
the note that this production task actually created. For implementation, the
group may agree work across several files; completing only its private
discussion document is not production. Brainstorming's opaque result is not a
suite-command declaration, so ordinary implementation review also closes any
otherwise-empty full-suite handoff before the unit can seal.

### Ownership and boundary

This slice owns the milestone's choice, waiting, and consumption of a
Brainstorming producer for the two slice-production stages. It owns the handoff
from successful task completion into the existing unit record, and the failure
boundary that lets an explicit milestone Resume try a new task without changing
the failed one. For implementation it reuses the milestone's existing
suite-command review/fixer contract; it does not add verification policy to the
TaskExecutor.

It does not redesign either executor, the plan selector, review or fixing,
public task ordering, or the panel. It does not translate Brainstorming into a
single-Worker response or make discussion internals part of milestone law.

### Dependencies and consumers

This slice depends on the durable common task record, the existing Worker
cutover, the Brainstorming adapter and production-effect boundary, the existing
authority-bound participant dispatch and per-call evidence, and the two
independent producer choices. Its immediate consumers are the milestone's note
and implementation stages, the unit's production history, and the ordinary
review flow. Later public-API and panel slices consume the same task history but
are not changed here.

### Guarantee posture

- **Strict — independent choice and freeze:** each production stage uses only
  its own current choice. Once its task is admitted, later plan or operator
  changes cannot alter that order or the sibling stage.
- **Strict — completion boundary:** an open discussion-backed task leaves the
  unit waiting. Only successful production completion records the unit's work
  and opens ordinary review. A failed task records no successful unit work and
  stops the run with its native outcome and known accounting intact.
- **Strict — production staffing and evidence:** applying an agreement through
  a model is a real Brainstorming dispatch, not an unstaffed callback. The
  profile-backed milestone path resolves the lead from the current profile for
  that dispatch; profile-independent execution uses its frozen lead pin. Every
  physical production or repair call records the actual agent, model, effort,
  and accounting through existing executor activity. The aggregate effect
  completion may summarize those calls but cannot replace their evidence.
- **Strict — note handoff:** successful Brainstorming drafting records the
  current planned note location, replacing any predecessor location before
  review. Review and implementation then consume that recorded location.
- **Strict — terminal history:** an open recoverable task keeps its identity.
  A terminal task is never reopened; an explicit Resume after terminal producer
  failure admits a distinct successor from the then-visible choice.
- **Strict — full-suite handoff:** configured or already-discovered commands
  remain authoritative. When a Brainstorming implementation leaves that list
  empty, ordinary review treats the absence as unknown: it either confirms the
  repository has no suite or queues the existing missing-command finding and
  fixer correction. A repository with an official suite cannot seal from an
  empty verification list.
- **Optimistic — recovery:** existing Brainstorming session recovery may finish
  an open task after interruption. Effects that landed before lost completion
  evidence may remain even when the task fails, and a successor may encounter
  them.
- **Best-effort — delivery and bookkeeping:** the production contract requires
  the requested effects, but full workspace access does not prove where every
  effect landed or provide rollback. Activity and chip visibility remain
  convenience views and do not govern acceptance.
- **No eventual guarantee:** waiting has no completion deadline. This slice adds
  no timeout, automatic retry, or liveness promise.

### Acceptance

- A discussion-backed note with single-Worker implementation completes through
  the existing note review, implementation, and review boundaries.
- A single-Worker note with discussion-backed implementation completes through
  the same ordinary boundaries; the implementation request may produce several
  named workspace effects without exposing a caller-selected discussion target.
- In both mixed flows, the post-agreement model work uses the selected
  Brainstorming lead authority and leaves actual per-call staffing evidence;
  changing the profile before that dispatch changes a profile-backed call but
  never rewrites the frozen order snapshot.
- Each mixed flow creates two separate production tasks from the two independent
  choices. Skeleton drafting, reviews, and fixers continue through the familiar
  Worker path.
- While Brainstorming remains open, repeated milestone progress checks neither
  advance the unit nor admit another production task.
- Successful Brainstorming note drafting records the current run-layout note
  location even when the unit carries a different predecessor location. The
  first ordinary reviewer and the implementer receive the replacement.
- Brainstorming failure preserves its task result and accounting, records no
  successful draft, and fails the run. Resume admits a different task identity
  under the then-visible choice; it never mutates or restarts the failed task.
- A successful Brainstorming producer contributes its aggregate duration,
  tokens, and cost once to the production record and existing run totals;
  unknown evidence stays partial.
- A zero-config Brainstorming implementation in a repository with an official
  suite reaches review with the empty handoff exposed, the existing fixer arms
  the official command, refreshed review evidence includes it, and the
  scheduled checkpoint runs it. A repository with no suite remains valid.
- Focused integration tests and the repository's complete suite pass once each
  at their respective gates.

### Non-goals

- No standalone task endpoints, producer controls, task chips, or freshness
  guarantee.
- No selectable producer for skeleton drafting, review, delta review, or fixing.
- No new scheduler, queue, supervisor, retry policy, task or session ledger,
  result schema, artifact inventory, staffing authority, or staffing ledger.
- No conversion of a Brainstorming-native result into single-Worker declarations
  and no new success, presence, byte-change, or freshness check for its effects.
- No durable slice identity, override replay, lost-override notice, pause, or
  acknowledgement.
- No filesystem confinement, universal placement proof, exactly-once effect,
  rollback, cleanup, or write to an additional read-only root.

### Risks

- Reading both producer choices as one decision could dispatch the wrong stage
  or freeze a choice that is still prospective.
- Treating an open task as a failed or absent one could create a second session
  and duplicate effects or cost.
- Re-entering a terminal failure under the old identity would rewrite history;
  silently reusing an open task's successor would fragment it.
- Keeping a predecessor note location would send ordinary review and
  implementation to stale material even though the new task succeeded.
- Treating private agreement as production would advance the milestone without
  the requested multi-file work.
- Treating the post-agreement model call as a generic effect callback could let
  an unselected model change the workspace while hiding the actual staffing.
- Treating an empty command list as proof that no suite exists would let a
  zero-config Brainstorming implementation seal without repository verification.
- Recording both session activity and its aggregate task result as independent
  work would charge the run twice.

### Reuse Posture

The affected party is the operator who selected Brainstorming for one production
stage. Without this slice, that visible selection reaches the current deliberate
stop instead of producing the slice. Without the suite handoff, a zero-config
run can instead seal an untested Brainstorming implementation. These harms are a
stopped run, stale handoff, or missing full-suite proof; they defeat the
independently required producer choice and verification boundary.

Checked and reused are the current two-key producer resolution and order builder,
durable task admission/result transition, Worker production path, Brainstorming
admission/session/effect adapter, authority-bound participant dispatch and
per-call activity, existing driver wait action, unit draft and Resume
transitions, run-layout note resolver and handoff, ordinary artifact lookup,
review entry, scheduled-command evidence, and the existing
`suite_command`/`suite_command_finding_id` fixer correction. The cheapest
sufficient option is one bounded producer-dispatch and terminal-consumption seam
at each existing production stage, with model-backed effect application routed
through the lead's existing authority and evidence path, plus reuse of that
correction when review finds an unarmed official suite. The driver and existing
unit flow are its only immediate consumers.

No second scheduler, result translator, suite-discovery task, Brainstorming
result field, retry controller, task ledger, artifact inventory, staffing
ledger, or accounting home is justified. The remaining machinery is local
integration, the existing lead-dispatch evidence path, exposure of existing
command evidence to ordinary review, and focused recovery evidence. It has no
migration or separate operating service; maintenance stays with the two
adapters and milestone driver. Omitting the staffing reuse would let the real
producer differ from the selected authority without auditable call evidence;
omitting the rest leaves an already-visible choice unusable or its verification
vacuous. The Worker default and immutable predecessor records keep the addition
reversible.

### Size posture

The integration should remain narrow, but the complete slice is expected to
exceed about 500 non-mechanical changed lines because its focused proof must run
both mixed producer orders through real milestone boundaries, exercise waiting
and terminal Resume, and verify note replacement plus multi-file effects. The
runtime change itself should reuse existing seams rather than grow a parallel
orchestrator.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's independent choices, existing task and
  Brainstorming lifecycles, current unit flow, and ordinary review ownership.
- **Revise:** the temporary pre-Slice-6 refusal becomes a real milestone
  production path; Brainstorming success is consumed through its native task
  result rather than a fabricated Worker result.
- **Reject:** `brainstorming` or `_drafts` planning material and run-local raw
  prompts as authority, plus any second scheduler, output schema, retry policy,
  or bookkeeping guarantee suggested there.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Eligible production choices | Only `draft_slice_note` and `implement` read `producer_task_executor`. Each reads its own effective member; an omitted map or member independently resolves to `worker`. The admitted order freezes only that task. | `implementation/milestones/tasks-2/skeleton.md:24-30,143-157,218-220,327-343`; `orchestrator/tasks.py:256-353,383-404` | touch the two existing production scheduling boundaries; do-not-combine the choices, select skeleton/review/delta/fixer work, or freeze the sibling member |
| Brainstorming admission and wait | A selected `brainstorming` production order enters the existing Brainstorming TaskExecutor admission and session lifecycle. While its durable task is open, the unit stays pending and repeated progress reuses that task rather than admitting another. Its frozen configuration and historical staffing remain unchanged; profile-backed dispatch keeps the adapter's current-profile authority. | `implementation/milestones/tasks-2/skeleton.md:43-52,88-104,143-180,334`; `orchestrator/tasks.py:449-597`; `orchestrator/brainstorming_tasks.py:105-155,435-605` | touch milestone dispatch/wait integration and the unit's task association; do-not-add a scheduler, duplicate session authority, restaff from the snapshot, or create child tasks |
| Post-agreement production authority | Any model call used to apply the agreement is a physical Brainstorming call. Profile-backed production resolves the lead from the current profile at that dispatch; profile-independent production uses the frozen lead pin. Existing executor activity records each actual agent, model, effort, attempt, and accounting. An aggregate `production_effect` completion is not staffing evidence and cannot substitute for those call records; genuinely deterministic non-model effect work needs no invented staffing identity. | `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,170-184,354`; accepted amendment B1; existing dispatch/evidence `orchestrator/brainstorming_execution.py:56-100,296-419` | touch the post-agreement model-production seam and focused evidence; do-not-pass raw staffing to the milestone, use the order snapshot as profile-backed pins, accept an unrestricted model callback, infer staffing onto an aggregate event, or add a staffing ledger |
| Terminal consumption | Brainstorming production advances a pending unit only when the task result is `success`, after the adapter's production-effect completion boundary. The unit's one production record links that task and carries its aggregate accounting once; `native_result` remains opaque. Brainstorming failure records no successful unit draft and fails the run with the terminal task intact. | `implementation/milestones/tasks-2/skeleton.md:18-22,43-53,160-184,334`; `orchestrator/brainstorming_tasks.py:893-1004`; `orchestrator/state.py:811-884,1906-1983,2060-2217`; `orchestrator/tasks.py:600-615` | touch terminal task-to-unit consumption and existing run accounting home; do-not-synthesize Worker-native fields, flatten the native result, add a second accounting record, or advance review on open/failure |
| Brainstorming note handoff | For `draft_slice_note`, resolve `ledgers.slice_note_path(state, slice_id)` before admission, name it as a required effect, and on success replace any predecessor `unit.artifact` with that same path before ordinary review. Review and later implementation consume the recorded path. Add no Brainstorming `artifact` result member or presence, byte-change, or freshness gate. | `implementation/milestones/tasks-2/skeleton.md:160-169,252-282,332-334`; `orchestrator/ledgers.py:68-75`; `orchestrator/brainstorming_tasks.py:1007-1053`; `orchestrator/driver.py:6356-6376,7622-7628,9984-10002` | touch current-path request construction, successful handoff, and focused review consumption; do-not-inherit a Worker declaration, retain a predecessor path, or change ordinary review |
| Full-suite handoff | Brainstorming `native_result` stays opaque and is never suite-command authority. A configured or previously discovered run command remains authoritative. If a Brainstorming implementation reaches ordinary review with no command, absence is unknown rather than proof of no suite: review must either confirm that the repository has no suite or report the missing official command; the existing bound fixer correction arms it, refreshed approvals include it in their evidence, and the scheduled checkpoint executes it before seal. | `implementation/milestones/tasks-2/skeleton.md:111,216-222,340-343,359,363`; `orchestrator/state.py:164-167,783-807`; `orchestrator/driver.py:1155-1199,2021-2039,6679-6680,8585-8604`; `orchestrator/contracts.py:1049-1071,1303-1309`; official suite `orchestrator/README.md:522-532` | touch ordinary review's scheduled-command evidence and focused Brainstorming-production coverage; do-not-parse the opaque result, add a Brainstorming result field, add a discovery task or task-specific verification policy, run the full suite during production/review, or allow a repository with a suite to seal vacuously |
| Effects and destination | The milestone order remains target-free and may name multiple writable-primary effects. Private-target or discussion completion alone is insufficient; the existing effect boundary must complete before task success. A supplied canonical `output_directory` remains inherited context and any path task machinery derives from it stays beneath it, but no universal placement failure, confinement, rollback, or cleanup is synthesized. | `implementation/milestones/tasks-2/skeleton.md:170-204,212-232,332-334`; `orchestrator/brainstorming_tasks.py:223-260,628-684,893-979`; `orchestrator/README.md:508-511` | touch only milestone request construction and reuse the adapter effect boundary; do-not-expose `target_path`, add `output_directory_violation`, infer placement from native claims, or write additional roots |
| Failure, recovery, and successor | An open Brainstorming production task spans native recovery. A terminal success or failure is immutable. Failure leaves the unit resumable but does not reopen the task; explicit milestone Resume re-enters the production point and admits a new task id from the then-visible selection. Worker `need_rethink` continuation is not applied to Brainstorming production. | `implementation/milestones/tasks-2/skeleton.md:54-75,143-180,334`; `orchestrator/tasks.py:383-404,600-615`; `orchestrator/brainstorming_tasks.py:402-578,893-1004`; `orchestrator/state.py:1205-1303` | touch producer-failure routing, task-reference release, and Resume re-entry; do-not-reopen a terminal task, mutate its order/result, add automatic retry/liveness, or reuse Worker continuation semantics |
| Slice boundary | Slice 6 replaces the temporary Brainstorming-selection refusal and adds focused milestone integration only. Standalone task HTTP is Slice 7, panel ordering is Slice 8, chips are Slice 9, and broad compatibility/cardinality conformance is Slice 10. | `implementation/milestones/tasks-2/skeleton.md:325-343`; temporary refusal `orchestrator/driver.py:2737-2751`; temporary proof `orchestrator/tests/test_producer_selection.py:689-724` | touch milestone production integration and its focused tests; do-not-pull public routes, panel/chips, or Slice 10's broad matrix forward |

### Verification Contract

Focused tests in `orchestrator/tests/test_brainstorming_slice_production.py`
must prove:

1. Brainstorming note plus Worker implementation follows the selected orders,
   records the planned note path, enters ordinary review on that path, and keeps
   both production tasks distinct;
2. Worker note plus Brainstorming implementation follows the opposite orders,
   keeps the Worker's declared note path, completes a target-free request with
   at least two named file effects, and enters ordinary implementation review;
3. model-backed agreement application reuses the lead's dispatch authority and
   existing per-call evidence: a profile-backed production call resolves the
   then-current lead after agreement, a static call uses the frozen lead pin,
   and neither can succeed with only a null-staffed aggregate effect event;
4. an open Brainstorming producer remains on one task across wait/re-entry and
   cannot advance the unit or dispatch a duplicate;
5. successful Brainstorming note consumption replaces a seeded predecessor path
   before the first review prompt and before implementation request construction;
6. native failure and effect failure preserve the terminal task's native result,
   partial/complete accounting, and partial effects while recording no successful
   unit draft;
7. after either production kind fails terminally, Resume admits a distinct
   successor from its then-visible choice and leaves the predecessor unchanged;
   and
8. task accounting enters the existing unit/run total once, while review,
   delta-review, fixer, and skeleton tasks remain Worker-owned; and
9. with no configured or discovered command, Brainstorming implementation in a
   repository with an official suite exposes the empty handoff to ordinary
   review, the existing bound fixer correction arms the official command,
   refreshed review evidence carries it, and the scheduled checkpoint runs it
   once rather than sealing vacuously. The no-suite case remains accepted.

The focused command is
`python3 -m unittest orchestrator.tests.test_brainstorming_slice_production`.
Existing producer-selection and Brainstorming-adapter tests remain lower-level
proof. The temporary refusal proof is replaced by positive integration coverage.
Final closure runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

Authorities: `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,170-184,334,340-343,354,363`;
selection/retry precedents
`orchestrator/tests/test_producer_selection.py:689-724,934-1041`;
adapter/effect/note precedents
`orchestrator/tests/test_brainstorming_tasks.py:431-645,647-906`;
Worker mixed-boundary precedents
`orchestrator/tests/test_worker_tasks.py:516-660`; full suite
`orchestrator/README.md:522-532`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified immediate consumers:** the two current production branches in the milestone driver; effective producer-order/admission and durable task history; the Brainstorming start/finish/effect adapter and authority-bound lead dispatch; unit production history and Resume; the run-layout note handoff; ordinary review artifact/governing lookup and scheduled-command evidence; and the existing suite-command fixer/checkpoint lane. **Verified untouched:** standalone task routes, panel/chips, and review/fixer/skeleton producer selection remain later or Worker-only. | `orchestrator/driver.py:1155-1199,2021-2039,6253-6702,7622-7628,8585-8604,9984-10002`; `orchestrator/tasks.py:271-353,449-615`; `orchestrator/brainstorming_tasks.py:435-605,893-1053`; `orchestrator/brainstorming_execution.py:56-100,296-419`; `orchestrator/state.py:164-167,783-884,1205-1303`; boundary `implementation/milestones/tasks-2/skeleton.md:325-343` |
| pinned_facts | The hard table pins the two eligible independent choices; one open Brainstorming task while waiting; current-profile or frozen-static lead authority and actual-call evidence for model-backed production; success-only unit consumption with opaque native result and single accounting home; current-path note replacement; non-vacuous full-suite handoff; target-free multi-file effects with bounded destination enforcement; immutable failure and Resume successor identity; and the later-slice boundary. | `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,111,143-204,216-222,325-343,354,359,363`; `orchestrator/tasks.py:271-353,383-404,600-615`; `orchestrator/brainstorming_execution.py:56-100,296-419`; `orchestrator/brainstorming_tasks.py:893-1053`; `orchestrator/driver.py:2021-2039,8585-8604` |
| verification | One focused integration module pins both mixed producer flows, authority-bound lead production with actual-call staffing evidence, wait identity, note-path replacement before review/implementation, target-free multi-file production, native/effect failure, Resume successors for both production kinds, single-home accounting, and the empty-command review/fixer handoff before a non-vacuous checkpoint. Existing selection, adapter, Worker, participant-execution, and full-discovery suites remain lower-level and closure proof. | `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,334,340-343,354,363`; `orchestrator/tests/test_producer_selection.py:689-724,934-1041`; `orchestrator/tests/test_brainstorming_execution.py:515-600`; `orchestrator/tests/test_brainstorming_tasks.py:431-645,647-906`; `orchestrator/tests/test_worker_tasks.py:516-660`; `orchestrator/tests/test_adversarial_fixes.py:316-405`; `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** an operator's valid Brainstorming choice currently stops at the deliberate Slice-5 refusal; an unrestricted model callback could instead apply work under an unselected, unaudited model; without a suite handoff, a later zero-config run may seal untested. **Checked/reused:** producer resolution/order, immutable task transition, Worker branch, Brainstorming admission/start/finish/effect and note handoff, authority-bound participant dispatch and per-call activity, driver wait, unit draft/Resume, note lookup, review entry, scheduled-command evidence, bound fixer correction, and current accounting homes. **Cheapest sufficient option:** one local producer dispatch/consume seam that routes model-backed application through the existing lead authority/evidence path, plus the existing review/fixer suite correction and focused tests. **Remaining machinery/consumer:** only the driver-to-adapter handoff, lead production dispatch, terminal projection, and exposure of existing command evidence to review. **Lifecycle:** additive, no migration/service/scheduler/schema/ledger/discovery task; Worker default keeps reversal cheap, while omission leaves the choice unusable, unauditable, or verification vacuous. | current refusal `orchestrator/driver.py:2737-2751`; `orchestrator/tasks.py:271-353,449-615`; `orchestrator/brainstorming_execution.py:56-100,296-419`; `orchestrator/brainstorming_tasks.py:105-155,435-605,893-1053`; `orchestrator/state.py:164-167,783-807,811-884,1205-1303`; `orchestrator/driver.py:2021-2039,8585-8604`; authority `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,252-306,334,343,354,363` |
| enforceability | **Independent freeze:** effective selection plus common immutable task admission. **Staffing:** the adapter-owned lead dispatch resolves current-profile authority or consumes the frozen static lead pin, and existing executor activity records each physical model call; an aggregate effect event cannot satisfy that evidence contract. **One wait identity:** the unit's task reference and adapter's one-task/one-session recovery boundary. **Success-only advance:** the adapter withholds task success until its effect completion returns valid completion, and the unit transition accepts one recorded production result. **Note replacement:** the run-layout resolver, required-effect request seam, successful-task handoff, and ordinary artifact lookup. **Full suite:** ordinary review receives the ordered scheduled-command evidence; empty evidence must establish no suite or produce the existing missing-command finding, whose bound fixer result arms run state and changes review/checkpoint evidence before seal. **Failure/successor:** one-way task terminality plus existing fail/Resume re-entry; a new admission supplies the new id. **Accounting:** physical-call evidence aggregates once through the adapter into the existing unit production home. No pinned mechanism proves universal effect placement, rollback, cleanup, or eventual completion, so this note promises only best-effort delivery and no liveness guarantee there. | `orchestrator/tasks.py:271-353,449-615`; `orchestrator/brainstorming_execution.py:56-100,296-419`; `orchestrator/brainstorming_tasks.py:318-383,435-605,628-684,893-1053`; `orchestrator/state.py:164-167,731-807,811-884,1205-1303,1906-2217`; `orchestrator/driver.py:1155-1199,2018-2039,8585-8604,9984-10002`; `orchestrator/contracts.py:1049-1071,1303-1309`; bounded authority `implementation/milestones/tasks-2/skeleton.md:43-53,88-104,160-204,216-222,334,343,354,359,363` |
