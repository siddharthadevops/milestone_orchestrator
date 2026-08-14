# Goal: Milestone Tasks — Pluggable Slice Execution

Status: **operator-directed draft, non-canonical implementation input**. This
document states a desired product outcome and its boundaries as input for a
Brainstorming review. It does not allocate phases, slices, participants, or
workflow stages, and it does not authorize implementation by itself. The
reviewed milestone skeleton is the implementation authority and may refine or
reorganize this proposal.

## Outcome

Separate what a milestone guarantees from who produces its content. The
milestone keeps the law: unit sequencing, verification gates, review and fix
cycles, seals, and cost accounting. The step that actually produces a unit's
content becomes a named, pluggable **task**:

1. **Worker task** — the current implementer: one contracted CLI worker call.
   It remains the default and reproduces today's behavior unchanged.
2. **Brainstorming task** — Brainstorming transforms into a task type with
   brainstorming scope: a bounded multi-seat discussion whose lead applies
   the agreed work directly. Its usage examples are work categories such as
   drafting documents, elaborating strategies, or programming small chunks
   of code.
3. **Future task types** — added later without changing milestone law.

The concept is `Milestone → Task`: milestones remain the long-horizon
structure; tasks are the interchangeable executors of their content steps.

The first wiring connects tasks where content is produced today — drafting,
implementing, and fixing — and builds the plain TaskExecutor that simply
calls the LLM, exactly as those steps run now: the default type.

## Motivating case

A milestone whose product is not code — a contract drafted for a lawyer, a
policy set, structured prose. The skeleton, slices, review discipline, seals,
and bookkeeping all still earn their keep, but a single implementer call is
the wrong producer for some or all slices: deliberation among seats, not one
worker's draft, is what the content step needs. Today the implementer call is
the only path; the operator cannot order a milestone whose slices are
executed by discussion. The widening is not one-way: a code slice may also
warrant a deliberative task.

## What already exists

Brainstorming is an independent process with its own lifecycle, sessions,
state, and result contract; milestones already consume it through an adapter,
and the driver already knows how to wait on an attached discussion. This goal
generalizes that seam: from "a discussion resolves a question so the
implementer can proceed" to "a discussion may itself be the producer of the
unit's content." The independence boundary stays: Brainstorming never depends
on milestone internals, and milestones integrate through the adapter.

## A first-class entity

A task is not a milestone internal. It can be ordered from a milestone —
the driver launching the content step of a unit — or directly by the
operator or a calling product, with the same request contract, the same
self-description, and the same result and accounting records. Brainstorming
already lives this way: standalone sessions with their own service records,
consumed by milestones through the adapter. That shape becomes the rule for
every task.

## What defines a task type

Milestone law consumes every task type through one contract and never
interprets type internals. Each task type is backed by a **TaskExecutor**.
The vocabulary is settled: `task` names the ordered unit of work,
`TaskExecutor` the engine that runs it, and the record layer uses exactly
these two words. A task type is self-describing; the record layer carries,
for every type:

- **Executor description**: the TaskExecutor's name and a short prose
  presentation of what it is and what it is good at. The name alone already
  declares much of the intent — "Brainstorming" — and the description
  completes it.
- **Operating mode**: a definition of how the type executes — one contracted
  worker call, a led multi-seat discussion, a future mode.
- **Usage examples**: the work categories the type suits, each under ten
  words — "drafting documents", "programming small chunks of code",
  "elaborating strategies".
- **Available agent configurations**: the seats, agents, models, and efforts
  the type can be staffed with, composing with model profiles instead of
  duplicating them.
- **Output**: a typed result — success or failure with a reason, plus
  duration, token, and cost accounting, including partial figures when a
  task fails mid-flight; a failed task still spent money.

A task does not return an artifact and never enumerates what it produced:
implementing a slice may touch five documents or fifty. It operates in the
resolved work area, its effects land there, and milestone law keeps judging
that work area with its own gates, reviews, and seals — seals bind
decisions, not enumerations.

## The task request

Every task type receives the same request contract; only the type's
internals differ in how they use it:

- **Request**: what this task must accomplish, as free text.
- **Context**: the background needed to understand the request.
- **Reference documents**: an ordered list of documents the task may consult
  or work over, so selecting one concrete document to work on is a
  first-class, comfortable choice.
- **Output directory** (optional): a concrete destination for the task's
  effects. A work area holding a complex legal case has many directories;
  choosing the one related to the matter at hand makes sense. When absent,
  the task operates wherever the work area and request call for.

The request carries no artifact target and no domain taxonomy, matching the
output rule: destinations and references are choices, never enumerated
promises of what will be produced. The built Brainstorming contract's
`target_path` becomes an executor internal: the Brainstorming task resolves
it from the reference documents and the optional output directory; the
generic request grows no target field.

## Type-aware verification

A gate can only judge artifacts it understands: a legal document neither
builds nor runs tests, and a prose review is not a code review. Which gates
and review machinery apply is already the run's governing strategy choice;
task types must compose with that choice instead of hardcoding one. This goal
does not decide whether task type becomes a third named axis beside model
profiles and strategy configurations or a decision inside one of them — that
is for the discussion and the skeleton to settle.

The review process keeps belonging to the milestone: when review happens and
what convergence requires stay milestone law. The review itself is also a
task — its default TaskExecutor is the current review run — and it may
become interchangeable in the future without the milestone ceding that
ownership. The fix cycle inside it is likewise a task, wired in the first
connection to the plain LLM call it runs today.

## Where the type is decided

The task type of a slice is decided when work is planned, not discovered at
runtime. The planner may propose a type per slice — reading each type's
definition and usage examples to judge who best executes this work — but the
proposal is visible in the
skeleton, and the operator sees it and may override it before the run
executes it. There is no silent runtime routing: an LLM proposes, the
operator disposes.

## Boundaries

- Milestone law does not fork per task type: sequencing, seals, and ledger
  semantics stay identical for every type.
- The default (worker) task reproduces current behavior; existing runs and
  profile-less runs are unaffected.
- Brainstorming remains an independent process; this goal adds a consumer,
  not a coupling.
- Tasks carry no domain taxonomy (legal, code, prose): domain lives in the
  content and its gates, not in the task machinery.

## Completion

The goal is achieved when the operator can order a milestone in which each
slice names its task type, at least one slice executes end-to-end as a
Brainstorming task through the existing adapter boundary, the default worker
task remains byte-identical for runs that never choose otherwise, the run
summary attributes result and cost per task exactly as it does today, and
the panel's unit activity row shows one chip per executed task where it
shows review rounds and seal attempts today.
