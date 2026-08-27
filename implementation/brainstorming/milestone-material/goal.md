# Goal: Material Is the Milestone's Theme

Status: **operator-directed draft, non-canonical implementation input**. This
document states a desired product outcome and its boundaries as input for a
Brainstorming review. It does not allocate phases, slices, participants, or
workflow stages, and it does not authorize implementation by itself. The
reviewed milestone skeleton is the implementation authority and may refine or
reorganize this proposal.

## Outcome

`material` becomes a property of the milestone. The operator names it when
launching the milestone — `code`, `lawyer`, `default`, any name from the
owner's vocabulary — and changes it live whenever they want. Each dispatch
under the run simply uses whatever material is in force at that moment. The
skeleton planner no longer chooses a material per slice, and no job kind
carries its own material.

## What material means — correcting a confusion

Material names the **theme** of the work: the area whose knowledge,
vocabulary, and judgment the run must load. It works like a skill: the
milestone declares its theme, and the whole run — whatever mix of jobs it
contains — executes with that skill loaded. The per-material prompt layer is
the skill's content; the per-material staffing override is its casting.

Material never names the kind of task. Drafting documentation for a lawyer
and drafting documentation for an app are the same **job** in two different
**materials** — what changes is the theme, not the work.

The current implementation confused these two axes. Its per-job fallbacks
route document-drafting jobs under material `document` and implementation
jobs under material `code`, and pin one checkpoint job to `code`
unconditionally. Those values are job kinds disguised as materials; the
disguise is the defect this goal removes.

The routing machinery already keeps the axes apart and needs no structural
change: prompt layers are keyed by the pair (job, material), staffing
overrides by material on top of the document's role-based assignments. This
goal changes only where the material value comes from — the milestone — not
how routing consumes it.

## The change

- The milestone's material is named at launch, exactly as rigor is chosen
  today, and edited live at will; the next dispatch uses the value then in
  force. No freeze, no ceremony.
- Every prompt and staffing request under the run carries it. Nothing under
  a milestone derives a material from its task kind, its slice, or its
  order.
- The per-slice channel is retired: the contract key, the planner's
  solicitation, the skeleton table's material column, the freeze onto
  orders.
- The per-job material defaults are retired, the checkpoint's hard-wired
  `code` included.
- A run with no material in force runs under `default`.
- Standalone sessions already choose their material at session level; that
  stays as is.

## Boundaries

- The vocabulary stays open and owner-defined. An unknown name or one
  without prompt layers degrades to base, exactly as the routers' law
  already mandates — it never fails, blocks, or retries a call.
- Material selection is bookkeeping in the service of routing, not a
  guarantee: no ledgers, freezes, migrations, or delivery promises around
  it. A call dispatched before an edit ran on the previous material; that
  is fine, and the marker shows it.
- Old records carrying per-slice material values still read; the values
  stop routing anything.
- No design or review may reintroduce a per-slice, per-task, or
  per-job-kind material channel, shrink this goal's scope to match the
  current implementation, or harden material selection into a guarantee.

## Supersession

This goal supersedes the staffing-router goal's per-slice planner-material
channel and its storage amendment, and the prompt-router goal's per-charge
material rules — the checkpoint's `code` charge, merge-repair's material
inheritance, the legacy charge-without-material-reads-as-`code` default, and
the corpus's per-slice `material` schema line. Under this goal all of it is
one rule: a call runs the milestone's material, and a record without one
reads as `default`. Those texts remain as chronology.

## Completion

The milestone is complete when a milestone's material is named at launch and
changeable live; every prompt and staffing resolution under the run uses the
material in force, with `default` standing in; no per-slice or per-job
material remains in the contract, the prompts, or newly produced skeletons;
old records still read; and tests prove the milestone channel.
