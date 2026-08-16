# Slice 04 — Brainstorming executor adapter

## Register 1 — INTENT (lay language)

### What this slice builds

This slice makes Brainstorming a real producer behind the common task contract.
A caller describes the work and its context without choosing an internal target
document. The adapter opens the existing independent discussion, lets the group
reach a bounded agreement, and has the lead carry out that agreement in the
writable work area. Finishing the private discussion document is not enough:
the production work must also complete before the task can report success.

The same adapter serves two staffing situations. A milestone-backed task uses
the profile that is current when its Brainstorming session starts and keeps the
existing current-profile authority for later participant calls. A directly
ordered task without that profile authority uses the complete staffing binding
frozen when it was admitted. Historical staffing remains visible in both cases,
but it is not silently promoted into a runtime fallback.

For slice-note drafting, the milestone decides the note's normal run-layout
path before ordering. The request tells Brainstorming to create that note, and a
successful handoff records the same path for review and implementation. It does
not depend on Brainstorming inventing a Worker-style artifact declaration.

### Ownership and boundary

This slice owns the thin translation between an admitted Brainstorming task and
the existing Brainstorming service, the one shared rule that resolves static
Brainstorming staffing, the production-effect completion boundary, truthful
native-result and accounting handoff, and the slice-note path handoff.

It does not choose which slice producer to use, schedule milestone production,
add public task routes or controls, project task chips, or change review and
fixing. Those are later slices. It also does not change Worker behavior,
Brainstorming's discussion rules, or milestone sequencing and acceptance law.

### Dependencies and consumers

This slice depends on the common TaskExecutor contracts and catalogue from
Slice 1, the durable task admission/result and destination primitives from
Slice 2, and the existing independent Brainstorming lifecycle. It does not
depend on Slice 3's Worker cutover.

Its immediate consumers are the generic task execution boundary, the existing
Brainstorming session service, and the milestone's note-path handoff. Later
slices consume the adapter for producer selection, milestone scheduling,
standalone ordering, and task projections.

### Guarantee posture

- **Strict — contract and authority:** only an admitted Brainstorming task may
  enter this adapter. Its frozen round limit, closure rule, work area,
  references, destination context, and native result cross the adapter without
  reinterpretation. The private target never becomes a caller choice.
- **Strict — staffing mode:** profile-backed launch uses the then-current
  profile and preserves its locator without using historical staffing as pins.
  Profile-independent launch uses the complete frozen binding without rotation,
  replacement, or fallback. Loss of availability never causes silent
  restaffing.
- **Strict — task completion:** agreement on the private target alone cannot
  produce task success. The lead's production-effect step must complete under
  the task request; a failed production step fails the task while preserving
  the Brainstorming-native outcome and all known accounting.
- **Strict — known routing:** an admitted destination is delivered unchanged to
  the adapter, and every path the adapter actually derives from it stays below
  it. Slice-note construction uses no destination or one containing the planned
  note path, and a successful note handoff records that planned path.
- **Optimistic — recovery:** one task retains the existing Brainstorming
  session's durable progress through native stop and recovery. A crash after an
  external effect but before task completion may cause that effect to be
  attempted again; later retry after terminal failure is a new task.
- **Best-effort — filesystem delivery:** full-access execution provides no
  causal proof that every arbitrary requested effect landed in the intended
  directory. A misplaced or undeclared effect may survive any outcome. There is
  no exactly-once, rollback, cleanup, or universal placement guarantee.
  Milestone review may reject observed noncompliance; a standalone caller owns
  any stronger acceptance it needs.
- **No eventual guarantee:** an admitted task may remain open while its session
  is waiting or recoverable. No timeout or liveness promise is added.

### Acceptance

- A common Brainstorming request launches through the existing service without
  exposing or requiring its private target.
- The ordered round limit and closure rule are exactly the values used by the
  session, including catalogue defaults.
- A profile-backed launch ignores a deliberately different historical staffing
  snapshot, uses the current profile at launch, and retains current authority
  for later calls.
- A profile-independent launch uses all frozen seats unchanged; inability to
  form that binding refuses the order before admission, while later loss of
  availability fails the admitted task without restaffing.
- Private-target success cannot complete the task until the production-effect
  step completes. Both successful and failed effect delivery preserve the
  Brainstorming-native result.
- Successful, failed, interrupted, repaired, and recovered internal calls
  contribute their known duration, token use, and both cost readings once;
  missing evidence remains explicitly partial.
- A supplied destination reaches the adapter unchanged, and the focused path
  checks prove only paths genuinely derived from it.
- Brainstorming slice-note drafting materializes the planned run-layout path and
  records that same path for ordinary review and later implementation, without
  inheriting a predecessor's declaration.
- Existing lifecycle tests remain green, and final closure still runs the
  repository's complete test suite once.

### Non-goals

- No producer-selection map or override, milestone production scheduler, public
  task API, panel control, task chip, or cross-surface compatibility proof.
- No alternative executor for skeleton drafting, review, or fixing.
- No second Brainstorming service, roster selector, configuration catalogue,
  session ledger, staffing ledger, profile version, or accounting ledger.
- No public target field, generic artifact member, artifact inventory,
  new output-placement failure code, placement gate, freshness check, or inferred
  actual-staffing projection.
- No new retry, timeout, liveness, idempotency, rollback, cleanup, permission,
  or sandbox policy.
- No writes to any additional read-only project root.

### Risks

- Reusing the historical staffing snapshot on a profile-backed launch would
  make the task look reproducible while executing under the wrong authority.
- Letting the existing service rotate a static order would rewrite the caller's
  frozen decision after admission.
- Treating agreement or transcript completion as production success would leave
  the requested work unapplied.
- Counting the discussion and production-effect calls through separate totals
  would duplicate cost; dropping failed or interrupted calls would understate
  it.
- A generic destination check can be overstated as confinement even though the
  executor has full workspace access.
- A note retry can accidentally retain a predecessor's path unless the current
  run-layout path is resolved anew for that scheduling decision.

### Reuse Posture

The affected party is the task caller or milestone operator. Without this
adapter, Brainstorming can discuss a production decision but cannot truthfully
be the producer; the realistic harm is missing work, wrong staffing, or hidden
model and human rework. It is visible at review for milestone work but more
exposed for a standalone caller, and it is usually reversible before sealing.
The reviewed milestone boundary independently requires Brainstorming production.

The existing common request/configuration/result validators, durable task
transition, destination canonicalization, derived-path check, independent
Brainstorming lifecycle, resolved-context creation seam, participant roster,
profile locator, per-call staffing evidence, native recovery, activity
accounting, private-target adapter, run-layout note resolver, and unit artifact
handoff were checked for reuse. The cheapest sufficient option is one thin
adapter, one shared static-staffing rule extracted from the existing roster
authority, and one bounded production-effect completion seam. The task layer,
Brainstorming service, and milestone note handoff are their only consumers.

The production-effect seam remains justified because current Brainstorming
deliberation intentionally permits edits only to its private target; prose or
configuration cannot turn that target-only discussion into target-free
production. The static resolver remains justified because a direct order has no
later profile authority. Both additions are local and testable. There is no data
migration or new operator service; maintenance is limited to the adapter and
focused tests. Omitting either addition produces a false success or silently
changes frozen staffing, while both remain reversible before later slices expose
the choice publicly.

### Size posture

The production adapter should remain small, but the complete slice is expected
to exceed about 500 non-mechanical changed lines because its focused proof must
cover two different staffing authorities, effect terminality and failure accounting,
destination propagation, and the note-path handoff together. Splitting those
proofs would leave an executable Brainstorming task with an unproved authority
or success boundary. Reuse of the existing lifecycle is required before adding
any further machinery.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's reuse of the independent Brainstorming
  lifecycle, private target, existing staffing evidence, and accounting.
- **Revise:** target-only discussion becomes target-free task production only
  through the bounded effect-completion seam, and static staffing is resolved
  once before direct profile-independent task admission rather than being
  selected later by session admission.
- **Reject:** brainstorming or `_drafts` material as authority, a caller-facing
  target, a second selector or ledger, and any claim that full-access success
  proves universal filesystem placement.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Adapter boundary | The adapter accepts an open admitted task whose `order.task_executor` is exactly `brainstorming`. The common request retains exact members `work_area`, `request`, `context`, ordered `reference_documents`, and optional `output_directory`; it has no `target_path`. The adapter privately satisfies the existing Brainstorming target requirement and passes the executor's terminal `result` unchanged as generic `native_result`. Brainstorming remains sole authority for any session reference; the task reason does not duplicate it in free text. | `implementation/milestones/tasks-2/skeleton.md:31-38,71-73,152-176,312,331-335`; `orchestrator/tasks.py:139-167,225-252,352-391,563-632`; `orchestrator/brainstorming.py:1188-1237,1892-1919` | touch the Brainstorming TaskExecutor adapter and its private target translation; do-not-add a public target, duplicate a session reference, reinterpret the native result, or alter the common request/result schemas |
| Brainstorming configuration | Exact resolved members are `max_rounds` and `closure_policy`; defaults are `10` and `unanimity`, and closure choices are `unanimity` or `majority`. The resolved values in the frozen order are passed unchanged to the existing service. | `implementation/milestones/tasks-2/skeleton.md:141-151,312,333,337`; `orchestrator/tasks.py:48-75,178-214`; `orchestrator/brainstorming_lifecycle.py:276-424` | touch adapter translation only; do-not-copy configuration authority, infer a tie-break, or change Brainstorming's create vocabulary |
| Profile-backed staffing | At session start, the adapter builds Initial Position, Contrary Position, and Dante seats from the then-current profile and forwards the current-profile locator. It does not forward or consume `resolved_staffing` as pins or fallback. Existing per-dispatch resolution remains authority and existing activity remains evidence of what each physical call used. | `implementation/milestones/tasks-2/skeleton.md:86-102,334`; `orchestrator/driver.py:650-703`; `orchestrator/brainstorming_milestone.py:268-370`; `orchestrator/brainstorming_lifecycle.py:686-701,1419-1475,2322-2424` | touch the profile-backed adapter launch seam; do-not-pin from the order snapshot, persist the profile locator as staffing history, or add a parallel actual-staffing projection |
| Profile-independent staffing | One Brainstorming-owned executable-aware rule resolves complete Initial Position, Contrary Position, and Dante pins from configured family order and model defaults before direct task admission. The frozen pins are supplied through existing participant fields and session admission validates/binds them without rotation or replacement. Task and session admission remain distinct, so an admitted task may wait before its session exists. No resolvable binding is `task_unavailable` before task admission; later loss or refusal is durable task failure without restaffing. | `implementation/milestones/tasks-2/skeleton.md:93-102,221-224,312,334,340`; `orchestrator/brainstorming_lifecycle.py:276-397,478-683,1419-1518` | touch one shared Brainstorming staffing rule, admission preparation, and adapter launch; do-not-use `available_agent_configurations` as a selector, add a public seat field, duplicate roster logic, or silently restaff |
| Production effects and terminality | The task request is target-free and may require multiple writable-primary effects. Brainstorming session success, private-target completion, or transcript completion alone cannot produce task success; the lead's agreed production-effect completion is required. If that step fails, the task fails, preserves the Brainstorming-native result and known accounting, and may leave partial effects. This is a completion gate, not causal placement proof. | `implementation/milestones/tasks-2/skeleton.md:152-176,206-220,258-265,312,341`; current target-only boundary `orchestrator/brainstorming_coordination.py:546-574,696-789,839-863`; one-way task result `orchestrator/tasks.py:376-391` | touch one bounded adapter-owned production-effect completion seam; do-not-weaken Brainstorming discussion ownership, treat its private target as production, add an artifact inventory, or claim exactly-once/rollback/confinement |
| Destination boundary | A supplied canonical `output_directory` reaches the Brainstorming adapter unchanged as inherited context. Every path the adapter derives from that field is resolved beneath it. An outside requested effect is contradictory but does not create `output_directory_violation`, a generic post-result failure, cleanup, or proof that all effects stayed inside. Additional roots remain read-only inputs. | `implementation/milestones/tasks-2/skeleton.md:177-196,215-220,296-301,312,341`; `orchestrator/tasks.py:255-311`; `orchestrator/README.md:508-511` | touch unchanged executor-context forwarding and reuse the shared derived-path primitive where applicable; do-not-add a placement gate, second destination transport, sandbox, causal evidence, or writes to additional roots |
| Slice-note handoff | For `draft_slice_note`, milestone construction resolves the current run-layout note path before ordering, names that path as a required effect in the target-free request, and supplies no `output_directory` or one containing it. Success materializes and records that same path as the unit artifact; it never reads a predecessor's Worker `artifact` declaration. No Brainstorming `artifact` result member or separate presence, byte-change, or freshness gate is added. | `implementation/milestones/tasks-2/skeleton.md:152-161,312,341`; `orchestrator/prompts.py:1415-1435`; `orchestrator/ledgers.py:68-75`; `orchestrator/state.py:819-880`; `orchestrator/driver.py:6206-6217,7455-7467` | touch the Brainstorming note request/handoff seam and current run-layout resolver; do-not-copy a predecessor path, synthesize a native artifact declaration, or bypass ordinary note review |
| Lifecycle and accounting | One Brainstorming production task spans its bounded session and native recovery until terminal success/failure; a later retry is a successor, and Worker `need_rethink` continuation does not apply. Every discussion, closure, recovery/classification, and production-effect call contributes known duration/tokens/cost once; missing evidence sets the corresponding partial flag. Internal calls remain evidence, not tasks. | `implementation/milestones/tasks-2/skeleton.md:42-52,162-176,335-336`; `orchestrator/brainstorming_lifecycle.py:1092-1248,1251-1269,1907-2014,2232-2300`; `orchestrator/tasks.py:563-632` | touch adapter recovery/result/accounting aggregation; do-not-create child tasks, a second accounting home, Worker continuation semantics, inferred zeroes, or a new retry/liveness rule |
| Slice boundary | Slice 4 adds the adapter and focused handoff proofs only. Producer planning/override is Slice 5; milestone Brainstorming scheduling and mixed production are Slice 6; standalone HTTP is Slice 7; panel/chips are Slices 8-9; cross-surface compatibility/cardinality is Slice 10. | `implementation/milestones/tasks-2/skeleton.md:305-323` | touch adapter, proportional staffing/effect seams, note handoff, and focused tests; do-not-add later-slice routes, selection, scheduling, panel, chips, or broad compatibility machinery |

### Verification Contract

Focused tests in `orchestrator/tests/test_brainstorming_tasks.py` must prove:

1. closed adapter admission, exact configuration forwarding, private-target
   isolation, opaque native-result mapping, and success/failure accounting;
2. profile-backed launch uses current seats plus the locator and never forwards
   a conflicting historical snapshot;
3. profile-independent resolution freezes complete pins, passes them unchanged,
   refuses unavailable admission with `task_unavailable`, and turns later
   session refusal into failure without restaffing;
4. private-target success does not terminalize the task before production-effect
   completion, effect failure preserves native evidence/partial effects, and a
   multi-file request is not reduced to the private target;
5. destination omission/forwarding and only genuinely derived-path containment;
   no universal placement assertion is tested; and
6. Brainstorming note drafting creates the pre-resolved run-layout note and
   records it, with no predecessor declaration or extra artifact/freshness gate.

The focused command is
`python3 -m unittest orchestrator.tests.test_brainstorming_tasks`.
Existing generic-task, Brainstorming API, execution, coordination, and
milestone-adapter tests remain lower-level lifecycle evidence. Final closure
runs exactly
`python3 -m unittest discover -s orchestrator/tests -t .`.

Authorities: `implementation/milestones/tasks-2/skeleton.md:312,320-323,343`;
existing focused precedents `orchestrator/tests/test_tasks.py:208-339,415-727`;
staffing/lifecycle precedents
`orchestrator/tests/test_brainstorming_milestone_adapter.py:746-1003,1405-1617`;
`orchestrator/tests/test_brainstorming_api.py:440-677`;
`orchestrator/tests/test_brainstorming_execution.py:515-605`;
full suite `orchestrator/README.md:522-532`.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These five entries are the slice-scoped remainder; enforceability is answered
again for the facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified immediate consumers:** the common admitted-task/result boundary; already-resolved Brainstorming creation, launch, terminal projection, activity accounting, and current-profile dispatch; and the milestone's run-layout note-path/unit-artifact handoff. **Verified untouched:** producer selection, service task routes, panel/chips, and review/fixer scheduling remain later slices. | `orchestrator/tasks.py:225-391,563-632`; `orchestrator/brainstorming_lifecycle.py:1329-1518,1907-2014,2322-2424`; `orchestrator/driver.py:6206-6217,7455-7467`; `orchestrator/ledgers.py:68-75`; `implementation/milestones/tasks-2/skeleton.md:305-323` |
| pinned_facts | The hard table pins the target-free adapter boundary; exact Brainstorming configuration; mutually exclusive profile-backed and static staffing authorities; pre-admission `task_unavailable`; production-effect terminality; bounded destination enforcement; Brainstorming note-path handoff; native result/accounting/recovery posture; and the later-slice boundary. | `implementation/milestones/tasks-2/skeleton.md:86-102,141-176,177-224,312,331-343`; `implementation/milestones/tasks-2/slices/slice-04.md:Pinned-Facts Table` |
| verification | One focused adapter matrix pins configuration/native/accounting parity, both staffing seams, unavailable-versus-late failure, effect completion and failure, destination propagation/derived paths, note materialization/recording, and recovery identity. Existing Brainstorming lifecycle tests remain lower-level proof; repository discovery is the unchanged final gate. | `implementation/milestones/tasks-2/skeleton.md:312,320-323,343`; `orchestrator/tests/test_tasks.py:208-339,415-727`; `orchestrator/tests/test_brainstorming_milestone_adapter.py:746-1003,1405-1617`; `orchestrator/README.md:522-532` |
| reuse_posture | **Affected party/harm:** callers otherwise receive discussion without production, stale/floating staffing, or incomplete accounting. **Checked/reused:** common validators/task transition/destination primitive; resolved Brainstorming creation, create-body seats, executable-aware roster, profile locator/per-dispatch resolver, native lifecycle/recovery/activity projection; private-target adapter; run-layout path and unit artifact handoff. **Cheapest sufficient option:** one thin adapter, one shared static-resolution seam based on the existing roster authority, and one effect-completion gate. **Remaining machinery/consumer:** the effect gate is required because current discussion explicitly forbids caller-path edits; the task layer and later milestone/direct callers consume it. **Lifecycle:** additive, no migration/service/ledger/scheduler, bounded maintenance and tests; omission is more costly and less reversible once public ordering ships. | `orchestrator/tasks.py:134-311,352-391,563-632`; `orchestrator/brainstorming_lifecycle.py:276-424,478-701,1329-1518,2322-2424`; target-only evidence `orchestrator/brainstorming_coordination.py:546-574,721-749`; note seams `orchestrator/ledgers.py:68-75`; `orchestrator/state.py:819-880`; authority `implementation/milestones/tasks-2/skeleton.md:226-286,312` |
| enforceability | **Closed request/config/result and immutable terminality:** existing task validators plus the one-way result transition. **Current staffing:** the current-profile resolver, launch-only locator, and per-dispatch resolver; a focused negative assertion proves the snapshot is not consumed. **Static staffing:** reuse one executable-aware roster authority before admission, then existing participant-pin validation/binding; unavailable admission is side-effect free. **Destination:** existing real-path admission and derived-path primitive. **Effects:** the one new enforceable boundary is an adapter-owned result gate: generic task success is unavailable until the lead's production operation returns a valid completion under the inherited execution boundary. Current target-only discussion cannot supply that fact, which is why this bounded seam is required. **Note handoff:** the run-layout resolver plus explicit unit-artifact recording. **Native/accounting:** terminal Brainstorming state/activity projection plus generic result validation. No existing or authorized mechanism proves universal causal placement, exactly-once effects, rollback, cleanup, or liveness, so this note asserts only best-effort delivery and no eventual guarantee there. | `orchestrator/tasks.py:178-311,352-391,563-632`; `orchestrator/driver.py:650-703`; `orchestrator/brainstorming_execution.py:35-134,500-620`; `orchestrator/brainstorming_lifecycle.py:276-424,478-701,1092-1248,1329-1518,2322-2424`; current target-only limit `orchestrator/brainstorming_coordination.py:546-574,721-749`; `orchestrator/ledgers.py:68-75`; `orchestrator/state.py:819-880`; bounded guarantee `implementation/milestones/tasks-2/skeleton.md:152-196,258-265,312,341` |
