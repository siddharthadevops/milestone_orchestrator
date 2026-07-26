# Goal: Machinery Proportionate to Risk

## Outcome

Milestone Orchestrator adds a practical proportionality check to the existing
prompts used for design, re-documentation, Brainstorming, implementation,
fixing, and independent review. Whenever one of those prompts considers adding
or materially changing machinery, it asks the worker to choose the simplest
sufficient response to the real authorised need.

The check examines both the cost of building machinery and the plausible harm
of omitting it, so workers can remove unjustified mechanisms without weakening
real requirements or hiding valid defects. It is reasoning guidance inside
the prompts, not a new workflow object, protocol, or persisted account.

## The prompt check

Using the evidence already available in its call, the worker considers:

1. Who or what is affected without the change, what harm occurs, how exposed
   it is, and what authority establishes the need.
2. Which existing code, contracts, dependencies, and approved platform
   capabilities were inspected, and what can be reused or extended.
3. What the cheapest sufficient option is—including documentation,
   configuration, or no change—and why anything cheaper is insufficient.
4. What machinery remains to add, what authorised outcome it serves, and who
   will consume or observe it.
5. What it costs to build, migrate, operate, maintain, and review, considered
   alongside the cost and reversibility of omission.

If no machinery is justified, the worker says so briefly in the ordinary
response requested by that prompt.

An independently authoritative requirement fixes the outcome to satisfy;
proportionality chooses its simplest sufficient realization. A guarantee
created only by the working artifact, or made stricter than its governing
authority requires, is removed or weakened instead of authorising machinery.
If an authoritative outcome cannot be enforced, the result is a design gap
rather than a promise.

## How the check is applied

Each existing prompt applies the check locally, at the level relevant to its
own task:

- Skeleton and slice prompts use the current Question Battery and `Reuse
  Posture` to consider only machinery relevant to the document being written.
- Re-documentation prompts apply the same check to the reopened documentation
  set without multiplying paperwork per document.
- Implementation and fixing prompts apply it only to machinery introduced or
  changed by the work they are performing.
- Review, delta-review, and seal prompts independently challenge needless
  machinery and harmful omissions using the candidate and context they already
  receive.
- Brainstorming discussion, closure, and voting prompts apply the same check
  using the session context already available to them.

The check is evidence for judgment, not new design authority. No prompt must
receive a newly transported account from another call. If relevant context is
not already available, the worker uses the evidence it has, states any material
uncertainty in its ordinary response, and does not create machinery to carry
that context.

## Implementation boundary

Implementation is limited to prompt text and prompt composition using context
already available at each call, plus focused tests of that prompt behavior.
It must not add or modify output schemas, worker contracts, persisted state,
workflow transitions, review routing, fix acceptance, retry or recovery
behavior, profile semantics, compatibility behavior, ledgers, markers, or
delivery guarantees. It creates no exact-once, cross-call, cross-run, or
cross-version obligation.

This goal makes no promise that legacy or profile-less runs retain previous
prompt wording. The same simple guidance may be used wherever an existing
prompt surface benefits from it.

## Completion

The milestone is complete when the relevant existing prompts ask the
proportionality questions at an appropriate altitude, reviewers and
Brainstorming participants can apply the same judgment from their already
available context, prompt-focused tests pass, and no non-prompt workflow
machinery has been introduced.
