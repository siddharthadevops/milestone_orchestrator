# Prompt Analysis — Milestone Path

Status: **non-canonical analysis, input for a future prompt-router goal**. It
describes how the milestone path builds its prompts today, read from the
implementation workspace while the staffing-router milestone is mid-flight
there. Companion: [`prompt-analysis-brainstorming.md`](prompt-analysis-brainstorming.md).

## Assembly model

- All builder prompt text lives in **one module** (`orchestrator/prompts.py`)
  as constant blocks concatenated by one builder per process step. No template
  files, no loader, no indirection. Only three texts live outside it: the
  cutoff-recovery block (driver), the contract-repair suffix (runner), and the
  failure-classifier prompt (error-classification module, shared with the
  Brainstorming path).
- The **output-contract block is generated**, not static: it is produced from
  the contracts module and post-processed at build time (retired vocabulary
  scrubbed, round caps rewritten). Two prompts deliberately carry no contract:
  the Brainstorming production brief and the review-handoff decorator.
- After building, the driver may still touch the text: **additive-only
  decorators** (worker episode authority refresh and the contract-repair retry
  suffix append; the killed-call notice and the review handoff prepend) and
  **one splice** — the implementation stabilizer removes the size-guidance
  block by exact string match and appends a cutoff-recovery block.
  String-match splices break silently if the shared constant changes; any
  mechanism that varies prompt text must own this hazard.
- **Frozen-request doctrine**: an admitted task's request is immutable and
  replayed verbatim across resumes and continuations; live inputs re-enter
  only through the decorators above. Amendments, project safeguards, material
  vocabulary and review seats are read live at each prompt boundary (an edit
  reaches the next prompt, never one already sent); goal, roots and admitted
  requests are frozen.

## The prompt set

One prompt per process step, each built at its own driver seam (the three
producer prompts — skeleton, slice note, implement — share one). Staffing is
resolved in the same function body at every seam **except two** (marked):

| Step (staffing role) | Prompt | Notes |
| --- | --- | --- |
| plan | draft skeleton | always carries producer planning + material catalogue |
| draft | draft slice note | catalogue rides it only inside amendment episodes |
| implement | implement | most code-bound text; stabilizer splice target |
| review | full review round / delta review | near-duplicate pair; scope framing, governing line and coverage sentence differ |
| classify | reclassify (drift-risk rater) | most domain-neutral judgment prompt; own inline contract |
| fix | fix findings / suite repair | most composite template (~25 conditional blocks); embeds a runnable consultation command whose seat resolves at worker runtime |
| — | Brainstorming production brief | family-neutral discussion brief; staffing resolves at admission and per seat, not at this seam |
| — | rethink continuation | replays the frozen request verbatim plus handoff; staffing inherited frozen from the origin call, the router is not consulted |

## What varies today (axes that change text)

Ranked by weight:

1. **Reform**: live-gates the two-register form, question battery, wave
   blocks and the two-axis reclassify (with its builders and backstop lines).
   The gap exit, reform reuse addenda and gap contract variants sit behind a
   retired legacy flag that is now constant-false — **dead text** a prompt
   router need not carry. The code repeatedly commits to legacy prompts
   staying **byte-identical** — many builder parameters exist only to default
   off.
2. **Unit kind**: doc units (skeleton, slice note) get altitude/posture/content
   blocks; implementation units get remodel-scope authority. Second-strongest
   axis.
3. **Episode state gates**: remodeled skeleton, sequential implementation
   scope, editable design paths, re-documentation wave set, verification
   repair, legacy design correction, phantom retry, killed call.
4. **Live content**: amendments, safeguards, registry, debt, material
   catalogue.

The milestone family appears in the header line and in the fix prompt's
consultation protocol. **A call's own model, effort, rigor and material change
none of its prompt text** — but other seats' staffing does reach two prompt
bodies: the reform reclassify names the draft and implement seats (family,
model, effort — resolved at the prompt boundary purely to produce text,
withheld rather than failing when unavailable), and the fix prompt names the
resolved consultation seat and renders its runnable command. With those
exceptions, staffing and prompt text are independent axes.

## Where subject matter is hardcoded

Domain assumptions are concentrated, not uniform:

- **Deeply code-bound**: implement, fix, suite repair — git line counts, full
  test-suite duties, tests-modified taxonomy, focused checks after each edit.
- **Code-review vocabulary over a neutral core**: review and delta — the
  severity battery (victim, damage, guarantee, baseline) is already
  domain-neutral.
- **Near-neutral**: reclassify and the decorators.
- **Doc-level**: skeleton and slice-note drafting, except file:line evidence
  demands and changed-line sizing.

A material-routed prompt set would have to swap roughly: implementation size
guidance, suite/verification duties, evidence and self-check blocks, the delta
coverage sentence, the two-register example, and battery phrasing. The laws —
sealing, separation of powers, severity doctrine, reuse gate, altitude — are
subject-independent and could stay shared.

## Material awareness today

Materials touch the milestone in exactly two ways: as a **staffing input** for
the two producer kinds only (never reviews, fixes, classify or the skeleton),
and as **planner vocabulary** rendered wherever a prompt may author or reshape
the slice plan — the skeleton draft always, note/implement/fix prompts and
rethink continuations when they hold design-edit authority — so a material can
be proposed per slice: visible in the skeleton table, operator-overridable
before ordering, frozen on the order at admission, resolved live per call, and
declared in the prompt itself as naming work, never staffing. No material
changes any prompt's text.

## Routing observations

- Two different cut points exist today: prompt **text is centralized** (one
  module) while dispatch and staffing are **distributed** (seven driver
  seams, each pairing its prompt build with its staffing resolution). The
  staffing router cut at the seams; a prompt router can cut at the module —
  one resolver, per-consumer cutovers.
- **Freezing is the first design decision.** Staffing re-resolves at every
  physical dispatch and its record is the marker; prompts freeze at admission
  and re-admit liveness only through decorators. A prompt router must state
  where its output freezes and what the record is.
- Routing keys already in hand: **material** (the existing proposal/override/
  freeze channel), **role/step**, **unit kind**, **round**, **reform**,
  **rigor** (unused for text today), and the plumbed-but-unread **brief**.
- The byte-identical-legacy invariant must be preserved or broken
  deliberately, never accidentally.
