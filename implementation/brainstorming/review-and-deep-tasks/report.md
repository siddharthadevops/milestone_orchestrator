# Report: Reviewed Task and Deep Task Types

Status: **non-canonical brainstorming report — operator-driven need (2026-08-27)**.
This document analyses how to approach the change; after operator review it will
be rewritten as a goal and implemented through a milestone. It allocates nothing
and authorizes nothing.

## What was ordered

Two new task types, and a recomposition of milestone orchestration around them:

- **(a) A reviewed task.** What the milestone does today to produce any
  reviewable unit — skeleton, slice note, or implementation part — packaged as
  one orderable task: the main production call, then review rounds until
  convergence. Configurable per order: whether review runs double family (a
  checkbox that governs even when the staffing router declares two review
  seats), the debt posture, and the other cycle dials.
- **(b) A deep task.** What a slice does today, as one task: "implement
  such-and-such" → reviewed documentation via a
  reviewed-task child → on convergence, implementation via a reviewed-task
  child for each discovered part. Orderable standalone or per slice under a
  milestone.

Both are first-class TaskExecutor catalogue types. Either can be ordered
independently through the generic task API and the catalogue-generated panel,
without a milestone or parent task. Agent99 uses that same ordering contract
when integrated; it does not need a milestone-specific entry point. A parent
link describes only how one particular composite execution was ordered, never
a child-only variant of either task type. When a composite does order a child,
that link and the child's phase/part identity are durable execution authority:
after recovery the parent observes or resumes that exact child and never
silently places the same child order again.

End state for the milestone: skeleton = one reviewed-task order; each slice =
one deep order; after every five completed logical slices, the milestone orders
one separate reviewed-task verification. The current final-close verification
also remains required on current bytes. Verification is a first-class
milestone step and panel item, never activity inside the preceding slice or
deep task. Ratings, merge repair, and sync keep running as direct operations.
The staffing router and the prompt router serve every physical call in all of
it.

## Where the machinery stands today (verified)

- **Task layer.** A closed catalogue of exactly two TaskExecutors —
  `agent_call` and `brainstorming` — with self-describing entries, one generic
  request contract, one typed result envelope, and two lifecycle states
  (open → terminal) (`orchestrator/tasks.py:41-100`, `:446-480`, `:831-905`).
  Dispatch is a string branch in the two hosts, not a registry
  (`orchestrator/task_api.py:580-596`, `orchestrator/driver.py:8077-8081`).
  The steps a reviewed cycle is made of — draft/implement, review rounds,
  delta reviews, fix episodes — are already admitted and executed as
  `agent_call` tasks (`driver.py:3675-3702`, callers at `:8269`, `:10172`,
  `:10453`). Reclassify ratings, suite checkpoints, merge repair, and sync
  are NOT tasks today: they run as direct contracted calls outside the task
  layer (`driver.py:12108-12126`, `:11739-11751`), and the tasks goal
  explicitly kept reclassification out of the task layer.
- **The review cycle is milestone law inside the driver.** Per-unit state
  machine `pending → pre_review_verify → rounds → fixing → delta_review →
  pre_seal_verify → sealing → sealed`, with `repairing` as the one path that
  reopens a sealed unit (`orchestrator/state.py:52-79`, `:806-835`); loop
  shape fixed to
  `family_until_clean` (`orchestrator/interpreter.py:57-70`); the cycle walks
  the staffing document's `review` seats — the default document assigns two
  (`driver.py:9523-9538`); CLEAN is literal — an empty findings list
  (`orchestrator/contracts.py:1047-1049`); the seal is a deterministic
  predicate over the run's own review ledger, with zero seal calls
  (`state.py:1195-1236`); git discipline is part of the cycle — WIP commit
  after production, amend on clean delta, gate commit at seal
  (`driver.py:6967-6991`, `:11512-11537`, `:12633-12724`).
- **The call layer is already extracted.** `author_calls`, `judgment_calls`,
  and `session_calls` prepare physical calls; `contracts`/`verifiers` validate
  replies; the prompt router routes on the charge triple (job, executor,
  material); the staffing router resolves (role, index, round, material) →
  (agent, model, effort). Nothing in that layer knows about milestones. This
  is the load-bearing fact: the hard part of a reviewed task is not the
  calls, it is extracting the loop that sequences them.
- **"Double family" is not a term the code knows.** The reality is three
  cooperating pieces: the staffing document assigns the `review` seats (two by
  default), the router enforces the per-role `distinct_families` law when
  seats resolve (`orchestrator/staffing.py:1921-1968`), and the interpreter's
  `family_until_clean` walks one seat clean before the next. The consumer
  decides *when* a seat is used; the router only says *who* sits. But review
  breadth is not yet an order-level choice: convergence — every configured
  family clean on current bytes — is settled milestone law with an explicit
  non-goal "no relaxation of the seal predicate for implementations, in any
  profile" (build-driven-review §5). Making breadth an order-time checkbox is
  therefore a declared amendment, not a reading of existing doctrine.
- **Debt.** Findings within a configured severity scope may be independently
  rated and deferred as tracked debt instead of fixed: profile dials
  `p3_reclassify_debt`, `doc_reclassify_from`, `impl_reclassify_from`,
  `p3_defer_max_risk` (plus `drift_damage` gating on reform runs)
  (`driver.py:221-233`, `:12153-12171`); the rater only rates, a deterministic
  compare decides. Router-homed runs never defer single-family — no
  independent rater — while the legacy act path honours an explicit
  operator-chosen same-family rater as a deliberate second look
  (`driver.py:12015-12022`); debt is recorded per unit and fed back into
  review and fix prompts.
- **Implementation is size-controlled and can split.** The implement call
  runs under a reviewable-size meter (soft 500 / hard 750 reviewable lines,
  `driver.py:135-145`) and may return an `implementation_cut` that splits the
  slice into sequential parts — `slice_impl-NN-a`, `-b`, `-c` — each part a
  full unit with its own review cycle, convergence, and gate commit
  (`driver.py:8405-8416`; `state.py:606`, `:717-747`), against a frozen git
  attempt baseline (`driver.py:8166-8207`).
- **Gaps reopen sealed work; suite failures repair inside the cycle.** A
  builder's or fixer's `fits_remodel` gap reopens the SEALED skeleton for
  repair and reopens every sealed slice note as a re-documentation wave
  (`driver.py:8902-8934`, `:9037-9070`; `state.py:827-835` — the one
  sealed-reopen path). A failed suite checkpoint does not sit outside the
  cycle either: it becomes a synthetic P1 finding entering a fix episode that
  returns to the pre-seal gate (`driver.py:11893-11908`). Any design that
  extracts the cycle interior must account for both flows. The suite placement
  described here is current behavior, not the target: this report deliberately
  removes milestone-wide verification from the slice unit that happens to make
  the cadence due.
- **Prompt jobs are a closed grid.** 15 direct `kind@unit` jobs plus session
  jobs (`orchestrator/prompt_router.py:28-54`); a new kind or job is a code +
  corpus change (routes, canonical members, contracts, seed). The rethink job
  already shows the move a standalone target needs: an explicit
  `artifact_type` (document | implementation) selecting the target frame.

## Design sketch — (a) the reviewed task

**Definition.** One production brought to convergence under review law: a
producer call, then review rounds across the configured family breadth, fix and
delta episodes between rounds, terminating when every walked family is clean on
the current bytes. One task, one durable result.

- **The current cycle moves whole.** `reviewed_task` is not a simplified new
  review loop. It preserves the current authority and freshness boundaries for
  goal, skeleton/slice material, mutable operator amendments, accepted design
  amendments, project context, staffing, prompt set, and review ledger. It also
  preserves family ordering and restarts, whoever-detects-never-fixes, finding
  validation, fix and delta escalation, debt/reclassification, same-byte
  evidence invalidation, rethink continuation, deterministic sealing, and the
  existing recovery rules. Extraction changes which task owns the cycle, not
  what any review, fix, delta-review, amendment, or seal means.
  The one declared placement change is milestone-wide complete verification:
  it becomes its own cadence-driven `reviewed_task` instead of an exception
  inside a slice cycle; focused task verification remains unchanged.

- **Producer pluggability moves inside.** Today's per-slice producer choice
  (`agent_call` vs a Brainstorming production) becomes this type's `producer`
  configuration. The same visible knob applies to a skeleton-typed order, but
  that is not a free routing consequence: Prompt Router must explicitly serve
  the skeleton production job for every producer the catalogue offers there.
- **Configuration surface** (order-time; defaults armed from the run's
  strategy so an untouched order reproduces today's behavior):
  - **Double-family review** — a checkbox, checked by default. Checked: the
    order requires and walks exactly two distinct review families; admission
    or dispatch fails rather than silently degrading when staffing cannot
    supply both. Unchecked: the order walks exactly one review family. The
    router keeps owning who sits and enforcing `distinct_families`; the order
    owns breadth, and it governs even when the router declares two seats — the
    declaration is capability and default, never a mandate on a single-family
    order. A deliberate single-family order never trips
    `distinct_families_unsatisfiable` merely because it requested one family.
    This checkbox is a declared supersession of the every-family convergence
    rule (amendment 5 below): convergence becomes "every *walked* family
    clean", the walked set being the operator's order-time choice.
  - **Debt posture** ("tipo de deuda") — disabled, or a severity floor
    (P3/P2/P1, per artifact type) plus the maximum deferable risk; defaults
    from the strategy-profile dials. Surfaced implication, unchanged from
    today's router-homed rule: single-family review keeps deferral disabled
    unless the operator explicitly chooses a same-family rater — a fresh
    stateless call as a deliberate second look, the already-settled
    exception.
  - **Caps** — rounds per family, fix loops, delta-full-review escalation:
    the existing dials, settable per order.
- **Routing.** No new staffing roles: `plan`/`draft`/`implement` (producer),
  `review i` (rounds, with round index and `step_up` unchanged), `fix`,
  `classify` all exist. Every physical production, review, delta, fix, or
  classification call submits its whole semantic charge directly to Prompt
  Router. The task sequences those calls but never selects a prompt template,
  passes prompt fragments, or cascades prompt-building parameters. Prompt
  Router remains the sole authority that maps the job to the assembled prompt.
  Standalone document work therefore names its real semantic job (skeleton or
  slice document), not only a generic `document` artifact type; each offered
  job/executor combination must have an explicit Prompt Router route. The
  order boundary, not the Prompt Router job, determines whether execution is a
  task: an explicitly ordered `agent_call` remains a public task, while the
  same kind of physical call inside `reviewed_task` is routed evidence and
  creates no `agent_call` task record.
- **Git discipline stays cycle law.** Each `reviewed_task` preserves the
  current WIP commit after production, fix/delta amend behavior,
  review-evidence fingerprints bound to bytes, deterministic seal, and its own
  gate commit. The task cannot report success before that gate commit exists.
  A caller may retain a higher-level closure commit, but it never replaces,
  combines, or collapses the task's gate commit.
- **Convergence and seal belong together.** Convergence (every walked family
  clean on current bytes), the ledger-derived seal record, and the gate commit
  are all `reviewed_task` law and land in its native result with the review
  citations and commit identity. The predicate's mechanics — deterministic,
  same-byte, derived from the ledger, zero seal calls — are untouched; its
  family set becomes the order's walked set (amendment 5).
- **Verification is ordinary reviewed work.** Focused checks needed to produce
  or review an artifact remain part of that `reviewed_task`. A complete-suite
  verification is instead its own `reviewed_task`: its production runs the
  complete verification, failures enter its fix/re-run path, and any resulting
  repository changes are reviewed to convergence before it succeeds. It uses
  the same public type and can be ordered independently; no verification-only
  TaskExecutor is added. Like every `reviewed_task`, it seals its evidence and
  ends with its own gate commit, whether the production needed repairs or only
  certified the current bytes. The milestone, not a preceding slice or deep
  task, decides when to order it.
- **need_rethink is internal control, not a task result.** A physical call may
  return `need_rethink` with its repository-scoped problem, which pauses the
  still-open originating task and orders the ordinary Brainstorming work. If
  that work finishes successfully, the same originating task continues from
  the interrupted phase; if it fails, the originating task fails. The public
  result of `reviewed_task` remains only success or failure, exactly like every
  task result, and no terminal task record is reopened.

## Design sketch — (b) the deep task

**Definition.** What a slice does today, as one orderable task: documentation
reviewed to convergence → implementation, with every discovered implementation
part reviewed to convergence. "Implement such-and-such" as a single standalone
order, or one order per slice under a milestone.

- **Both legs are reviewed.** The documentation leg and the implementation leg
  are each `reviewed_task` children with their own configuration. There is no
  bare implementation variant. A cheaper order uses the doc leg's and impl
  leg's own family/debt knobs; it never removes the implementation review
  cycle.
- **The implementation cut is preserved.** The impl leg keeps today's size
  meter and cut semantics: when the work exceeds the reviewable-size limit,
  the leg becomes sequential parts (a, b, c… as today), each part exactly one
  `reviewed_task` child with its own convergence, materialized as the cut is
  discovered, never pre-planned. The meter's dials (soft/hard lines) join
  the reviewed-task configuration for implementation-typed orders, defaults
  unchanged. The documentation child and every implementation-part child own
  their separate seal and gate commit. `deep_task` neither collapses those
  commits nor adds an aggregate replacement commit.
- **Verification boundary.** A deep task ends when its documentation child and
  every implementation-part child have converged. Its children run the focused
  checks their work needs, but a deep task has no milestone-wide suite slot,
  cadence switch, or standalone suite posture. After the deep task finishes,
  milestone law may order a separate verification `reviewed_task`; a direct
  caller may order that same public task independently when complete
  verification is wanted.
- **Rethink and design repair.** New work uses the single `need_rethink`
  control path above; it is never a terminal leg or deep-task result. The
  originating `reviewed_task` remains open while its Brainstorming child
  resolves the repository-scoped contradiction, then continues the same leg
  on success or fails on error. When accepted work changes sealed milestone
  design, the milestone still owns the resulting reopen and re-documentation
  wave; a standalone deep order has no milestone design set to reopen and
  continues only against the accepted repository state returned by its
  Brainstorming work.

**Names.** The public ids are settled:

- **`deep_task`** — one reviewed documentation-and-implementation delivery;
  display name "Deep work".
- **`reviewed_task`** — one production reviewed to convergence. The historical
  phrase `review task` described the old `agent_call` scheduling record for one
  review invocation; it does not name an internal call after this cutover.
  Inside `reviewed_task`, `review call`, `fix call`, and `delta-review call`
  name routed physical evidence, never additional tasks.

## Composition — settled child orders

A deep task orders reviewed-task children for its documentation and
implementation legs; a milestone orders reviewed and deep tasks. Every child
is the same public catalogue type admitted through the same generic contract
as a standalone panel, API, or Agent99 order. Parentage changes no task
semantics and grants no private entry point.

The parent link, semantic phase, discovered implementation part, and admitted
child identity are durable execution authority. Once a parent has admitted a
child, restart or recovery observes or resumes that exact record and may not
place a duplicate order for the same phase/part. A terminal child remains
immutable; any lawful retry is a distinct successor under the existing task
rules. Physical Prompt Router calls inside a reviewed task remain evidence,
not additional tasks. A successful reviewed child exposes its own seal and
gate-commit identity to the parent; parent completion never substitutes a
combined commit for those child boundaries.

Children carry their own result and accounting. A parent aggregates those
records without counting any child charge again; run totals continue to count
each physical charge once. Chips and convenience projections remain
best-effort, but losing them never loses or changes the authoritative
parent-child execution relation.

## The milestone after the change

- Skeleton unit → one reviewed-task order (job `draft_skeleton`).
- Each slice → one deep order (doc leg + impl leg).
- Every reviewed-task order above — skeleton, slice documentation, each
  implementation part, and verification — runs the full current review
  apparatus and closes with its own seal and gate commit. No slice-level or
  deep-task commit replaces those boundaries.
- Every five completed logical slices → one verification reviewed-task order.
  The final milestone boundary also requires verification on the current bytes;
  an already-current five-slice verification need not be duplicated.
- Verification is a sibling milestone step, not a child or activity of the
  slice that made it due. It does not count as a slice. Its durable task record,
  status, duration, cost, findings, and review evidence appear in their own
  panel row/card, and the next slice waits for its success.
- Reclassify ratings remain direct calls inside reviewed work; merge repair and
  sync remain driver- and service-side direct calls. Every physical LLM call
  goes directly through Prompt Router and retains its existing evidence and
  accounting home.

Milestone law **keeps**: unit and slice sequencing; canonical plan
establishment from the reviewed task's sealed skeleton; higher-level closure
commits and ledgers; the five-slice and final verification cadence; the
accepted-design repair and re-documentation wave (reopening as new orders over
affected artifacts); plan reconciliation; aggregate accounting; stop,
liveness, and deploy discipline. Milestone law **sheds**: the interior of each
review cycle — authority/amendment handling, rounds, fix and delta episodes,
debt, convergence, seal, and gate commit — which becomes indivisible
`reviewed_task` law shared by every consumer. Milestone verification is
composed from that same task law rather than embedded in a slice cycle.

## Canon amendments this requires (each stated self-containedly in the goal)

1. Tasks goal: "the enclosing review-and-fix cycle is not a task and contains
   no nested task accounting" — superseded. The cycle becomes a task *type*;
   the milestone still owns when cycles happen and what follows them. The
   entire existing cycle moves together, including its authority/amendment
   boundaries, delta-review behavior, recovery, seal, and git discipline; only
   the separately declared milestone-wide verification placement moves out.
2. Same goal's old sense of "review task" as one review invocation is
   superseded at the new composite boundary. `reviewed_task` is the public
   production-plus-review task. Its physical review/fix/delta calls are routed
   evidence, not tasks; `agent_call` remains a public task type only when a
   caller explicitly orders one.
3. "One task = one scheduling decision" — amended so a composite scheduling
   decision may place first-class child orders. Their parent/phase identity is
   durable execution authority; the physical-call rule stands.
4. Seal doctrine restated: convergence, the deterministic same-byte seal, and
   the gate commit are `reviewed_task` law. Every documentation,
   implementation-part, and verification task closes with its own gate commit;
   callers may add higher-level closure commits but never collapse or replace
   a reviewed task's commit. Seals continue to bind decisions.
5. Build-driven-review §5's every-family convergence rule and its non-goal
   "no relaxation of the seal predicate for implementations, in any profile"
   — superseded where the operator selects single-family review at ordering:
   convergence is every *walked* family clean on current bytes, and the
   walked set is the operator's order-time choice. A double-family order,
   which remains the default, requires two distinct families and never
   degrades to one. The predicate's mechanics (deterministic, same-byte,
   ledger-derived, zero seal calls) stand.
6. Task terminality is unchanged at the public boundary: success and failure
   are terminal. `need_rethink` is an internal call-control signal; the
   originating task remains open while Brainstorming runs, resumes the same
   phase on success, and fails on Brainstorming error.
7. The current in-slice, direct suite checkpoint is superseded. After every
   five completed logical slices, and at final close when current bytes are not
   already certified, the milestone orders a first-class verification
   `reviewed_task`. It is a sibling milestone step, never part of the preceding
   slice or `deep_task`, does not increment the slice count, has its own durable
   record and panel item, and gates scheduling of the next slice.

Untouched: report-only reviewers and "whoever detects never fixes";
presence-only validation with surplus pruning; the seal predicate's mechanics;
adjudication and contest law; the milestone's sealed-design reopen effect;
staffing-router and prompt-router authority; material as the run's theme;
operator amendments and authority injection. Legacy persisted gap state keeps
only the compatibility needed to finish under the law it started with; new
tasks use `need_rethink`.

## Ordering and delivery

- **Builds on the delivered Prompt Router boundary.** These task types add the
  explicit job/executor cells they need (including any offered skeleton
  producer); they do not add a prompt-building or parameter-cascading path.
- **Composes with** `milestone-material` (these types add no material channel;
  a standalone order takes its session's material) and
  `brainstorming-is-a-task` (child records give every session a natural
  owning task; the rethink egress aligns). Their delivery ordering is milestone
  implementation planning, not an open product decision in this report.
- **Suggested milestone sequence:**
  1. *Extract the cycle engine.* Factor the review-cycle interior — existing
     authority/amendment boundaries, rounds, fix/delta episodes, debt,
     convergence, WIP/amend moves, deterministic seal, and gate commit — out
     of the driver into an engine the driver consumes, behind byte-identical
     behavior. No new surface; the equivalence is the deliverable.
  2. *Reviewed task type.* Catalogue entry and configuration surface
     (the config-schema vocabulary gains a boolean for the checkbox; the
     panel form stays catalogue-generated), standalone API/panel ordering,
     Agent99-ready generic admission, required Prompt Router cells, and
     skeleton unit cutover.
  3. *Deep task type.* Composition over the cycle type, slice cutover,
     implementation-part integration with one preserved reviewed-task gate per
     documentation/part child, and retirement of the in-driver unit interior.
     Compatibility: resumable runs finish under the law they started with.
  4. *Milestone verification cutover.* Replace the in-slice direct checkpoint
     with a sibling verification `reviewed_task`, change periodic cadence from
     four to five completed slices, preserve final-current-byte verification,
     and project each verification separately in the milestone panel.
- **Risks.** The extraction is the big one — the cycle interior threads
  through a 13k-line driver, state transitions, debt bookkeeping, and gitops;
  the equivalence gate of step 1 exists to contain it. Deploy skew: drain
  live drivers before activating (established doctrine). Double accounting
  across parent/child: one rule — children carry their own, parents aggregate,
  totals count children once. Recovery must preserve the authoritative
  parent/phase/child binding so a crash cannot admit duplicate work.

## Boundaries (anti-cementing)

- No event bus, notifications, or delivery guarantees for composite progress.
  Child records suffice. Their parent/phase/part identity is durable execution
  authority; only chips, display grouping, and convenience projections are
  best-effort.
- No domain taxonomy on either type; artifact type is a routing fact, not a
  domain.
- Defaults ship armed: an untouched reviewed order reproduces today's
  double-family and debt behavior; the checkbox exists to reduce, never to
  arm. Milestone-wide suite cadence is not a deep-task option.
- The extraction may relocate the current review state machine but may not
  simplify, replace, or split its amendment authority, review/fix/delta
  semantics, evidence invalidation, recovery, deterministic seal, or
  WIP/amend/gate commit discipline. Equivalence is the boundary.
- Review of this design must not harden loose display behavior (chips,
  activity grouping, convenience projections) into guarantees.

## Open decisions for the operator

None. The goal-writing Brainstorming may improve expression, but it must not
reopen the settled task boundaries, review machinery, commit ownership,
verification placement/cadence, or public names in this report.
