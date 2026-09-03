# Report: possible improvements to the `literature` prompt set

Status: **non-canonical brainstorming — analysis of possibilities
(2026-09-03)**. This document does not authorize changes to the installed set.

## Verdict

The operator has now defined “perform better”: the questions should broaden
the context considered, reduce literalism, and contribute common sense. Their
consumer is the agent reasoning during the turn, and the affected person is
the one who receives an overly literal delivery. The fact that structured
answers are not reused later does not make that function ceremonial.

`literature` already requires the agent to read the text, distinguish defect
from taste, protect voice and ambiguity, limit scope, and provide textual
evidence. Each of its nine `human_scale` questions retains a route-specific
proportionality check: grain and size, smallest change, direct effect, real
cost, or rejection of an exhaustive audit. The absence of `default`'s exact
wording therefore does not by itself demonstrate a functional regression.

One bounded improvement is plausible: `review_round.human_scale` repeats
controls already imposed by the mounted rubric and spends its answer on how
the set was checked instead of **comparing the reviewer's findings with the
requester's intent and showing what that comparison changed**. Testing that
replacement requires no new ids, routes, or batteries, and this report does
not modify the installed set.

## What output questions do — and do not do

The architecture treats them as mandatory cognitive work: describing
something forces inspection, and answering forces a judgment. Mechanical
validation checks only ids and non-empty answers because it cannot judge
common sense; that verification limit does not reduce the questions to data
transport.

There are therefore two outcomes to observe: whether the answer shows a real
comparison and whether that broader consideration improves the final
manuscript, document, or Markdown. A longer answer, or one containing the
expected words, is not enough.

## Evidence reviewed

- All 12 canonical documents load, and their 15 direct routes and 18 session
  routes assemble without falling back to `default`.
- Planning answers four questions, implementation three, review two, and Dante
  three; a producer session may also inherit those of its task.
  `standalone@*` inherits no questions and its author answers only the two turn
  questions, as in `default`; its role already requires doing the work, and no
  failed delivery turns that thinness into a defect.
- The `literature` question introduction already requires textual or editorial
  evidence. The cited 222 historical answers come from `default` and code work:
  they do not measure this wording or a literary delivery.
- Across the 24 main questions, `default` uses a worked example in 20 and
  `literature` in none; all nine `default` `human_scale` questions name
  literalism, while none of the nine in `literature` do. That is a wording
  difference, not a performance measure. The useful comparison is semantic:
  several literary replacements already express the same restraint through
  “smallest change,” “grain and size,” or rejection of an “exhaustive audit.”
- `default` is the seed corpus and reviewed fallback, but a named set is a
  complete, independent corpus: no inheritance makes every sentence in
  `default` mandatory. It is a comparator and reusable source, not a lexical
  canon for `literature`. The agreement that created the set allowed generic
  proportionality examples that already worked at manuscript scale to be
  retained; reusing one respects that authority rather than expanding it.
- `review_round` and `delta_review` already require distinguishing defect from
  taste and demonstrating harm beyond the permitted baseline. `fix_findings`
  already contains an explicit falsification pass that can be reused if the
  problem appears.
- Dante's three questions protect different things: voice and form,
  decision-relevant questions grounded in five possible sources, and drift
  from the request. There is no signal justifying the removal, merger, or
  narrowing of any of them.
- No other literary prompt system appeared in the granted repositories that
  should be connected or extended.

## Best-supported question change

This report does not propose restoring three expressions across the set based
on counts. It preserves the literary vocabulary where it already triggers the
right comparison, especially in `discussion_turn`, `draft_skeleton`,
`draft_slice_note`, `implement`, `delta_review`, `fix_findings`, and
`reclassify`.

| Surface | Possible limitation | Replacement to test |
| --- | --- | --- |
| `review_round.human_scale` | Its body repeats obligations from `judgment_rubric`, mounted on the same route: standard, passage, material consequence, proportionate alternative, and scope. The distinctive contribution of this self-audit could be the perspective of the person who requested the review. | “Put your findings next to the mandate and the manuscript: would the person who asked for this review recognize the grain and priorities they meant, or did a literal application of one lens turn harmless variation into work? Answer with a brief description of the grain and priorities they asked for, and whether that comparison made you keep, reword, or withdraw a finding.” |

This is the only concrete replacement recommended. The `default` example
about cataloguing time skips can also be reused if the abstract formulation is
not enough; copying it into all nine routes before testing one would not add
nine distinct functions.

The fact that `review_round`, `delta_review`, and `fix_findings` share the
“explain how you checked” answer tail does not demonstrate that all three
questions do the same work. In the latter two, the body retains unique duties
about the delta or the full queue, and the prompt already puts them against the
mandate, context, and reader effect. Without answers showing self-certification
on those routes, the shared tail is something to watch, not grounds for three
changes.

## Other hypotheses and the criterion for locating a route

| Surface | Current coverage | Signal that would justify action | Smallest change to test |
| --- | --- | --- | --- |
| Author delivery (`standalone@*` or `implement`) | Both require doing the work; `implement` also compares the delivery with the brief and intended effect. | A request requires choosing, prioritizing, or deciding, but the actual delivery only compares options. | Test “Does the delivery perform the requested act, or only describe options? Point to where it resolves the request” only on the affected delivery; choose the mounting point after locating the case. |
| `review_round` | Every finding needs a standard, passage, material harm, and proportionate alternative. | A taste-based finding survives because the reviewer did not test a plausible reading of the passage. | Add counter-reading to this route's `human_scale`, reusing the falsification already used by the fixer. |
| `delta_review` | The same review coverage, but limited to the change and its direct effects. | The same failure appears specifically while reviewing a delta. | Apply the same clause there; do not change full review in advance. |
| `draft_skeleton`, `draft_slice_note`, `reclassify`, `fix_findings` | Their namesake questions govern planning, size, rating, or resolution of a queue. | No current signal. | No change: do not extend a recommendation to them merely because they share an id. |
| Dante | Three complementary checks on fit, decision-relevant questions, and focus. | No current signal. | Keep `turn_environment_fit`, `turn_human_scale`, and `request_focus`. |

The table locates only these two hypotheses; it does not inventory every route.
Including `standalone@*` in the first row avoids prejudging where a future
failure would occur, but does not turn its two-question battery into a
deficiency. Its turn questions are shared and cannot isolate it; resolving
that topology without a located failure would still be unnecessary machinery.
That constraint does not apply to improving the cross-cutting function of
`human_scale`, whose user and purpose the operator has identified.

Counter-reading should not be attached to `environment_fit`: that question
protects audience, stage, voice, ambiguity, and form against conventionalizing
pressure. The object to falsify is the finding, already governed by
`human_scale`.

## Other possibilities without a case yet

- **Creation from scratch.** `implement` already says “create or revise.” Only
  if a run stalls because no prior manuscript exists would it make sense to
  clarify on that route that the mandate and available sources are the
  authority.
- **Language fidelity.** Voice and diction are already protected, and Dante
  follows the language of the request. Only an unrequested translation or
  neutralization of variety, dialect, or code-switching would justify
  strengthening that rule.
- **Requested conclusion.** Before changing a question, there must be a
  delivery that fails to perform the requested act despite the current
  instructions. Without one, `task_outcome` would be a second statement of the
  contract rather than a solution.

This report does not recommend `textual_fidelity`, `editorial_priority`,
`downstream_decision`, `question_leverage`, or `missing_evidence` as new ids:
their outcomes are already covered or lack a demonstrated victim.

## Proportionate validation

During the first real literary review, compare the current question with
**only the `review_round` replacement**, keeping model, text, and context the
same. Preserve both the self-audit and the delivery. The person who requested
the work judges whether the agent reconstructed their intent more accurately,
removed work caused by a literal reading, and retained material findings.

No evaluator or lexical metric is needed. Retain the change only if it improves
the delivery without adding verbosity, taste-based findings, or work outside
the request.

## Out of scope

- Modifying the installed set or creating new routes or batteries.
- Storing self-audits as a new authority.
- Presenting the `default` corpus as literary validation.
- Turning the exact wording of `default` into a requirement for every set.
