# Skeleton code-first discipline: verified assumptions, priced invariants, doc double-contrast

Status: non-canonical brainstorming — operator-driven need (2026-07-05).

## Need

Planning is where nonsense enters cheapest and metastasizes worst. In Life
M164 the invariant "after delete success, Life must not publish pre-delete
content" entered the skeleton unpriced, survived 17 skeleton rounds and 31
slice-note rounds, and drove the implementation into platform surgery (lease
fences, payload rewrites, a shared-worker redesign) — while the relay payload
never carried message content at all. One question at planning time ("what is
actually IN that payload?") would have killed the whole requirement. Reviewers
verified the machinery's *correctness* for weeks; nobody was obligated to ask
whether the protected thing was worth anything.

A second gap surfaced in the same incident: the system's most load-bearing
consumption fact (relay worker = per-service continuous consumer publishing to
product-app backends) existed only in code (`@moduledoc false`), while the
transport doc mixes client-session semantics on the same page — an open
invitation to build the skeleton on a wrong mental model of who consumes what.

## Obligation (what this milestone delivers)

Make the following MANDATORY in the orchestrator's skeleton machinery
(prompts, review duties, gate surfaces). Not advice — content rules whose
absence is a finding.

### 1. Code-first drafting

The skeleton is drafted from code reconnaissance. Project documentation is a
secondary source, never the primary basis for an architectural claim.

### 2. "Architectural assumptions (verified)" section — mandatory

Every load-bearing assumption the skeleton relies on is listed and cited to
code (`file:line`). Anything the drafter could not verify in code is declared
`UNVERIFIED` explicitly — silent assumption is the failure mode being killed.
Delivered as structured contract entries too (same doctrine as section 3):
the driver existence-checks the citations mechanically; reviewers sample
their semantics.

### 3. Price tag on every invariant / guarantee / mechanism — mandatory

Delivered AS CONTRACT FIELDS, not prose (the project-concept doctrine: an
LLM fills a required slot far more reliably than it obeys an instruction).
The skeleton worker's JSON output carries one structured entry per
invariant/guarantee/mechanism — no bare booleans; every factual claim
carries a file:line citation — and the entries are echoed into the skeleton
doc as a table. Driver-side mechanical checks reject the contract without
spending a token: cited paths must exist; the entry list must be non-empty
when the note declares guarantees; a SPECULATIVE entry without recorded
operator approval blocks the seal. Reviewers verify the semantics of each
entry; the driver verifies existence.

Each entry must answer:

- **Who consumes/observes this, exactly?** Verified identity in code —
  a service, an app backend, a human surface. Never "the client" by prior.
- **What does the data/payload actually carry?** Read it; never assume.
- **Real frequency and timing window?** Hot path or low-frequency; bounded
  or unbounded.
- **Harm if violated — who is the victim, in product terms?**
- **Cost to honor?** Code size, platform touches, review burden, runtime.
- **Cheapest compliant alternative considered?**
- **Does an equivalent already exist in the project's reuse sources?**
  (consumes the project machinery of project-concept.md — enumerated
  inventory + adopt/gap/reject audit, not a shouted prohibition)

An invariant that cannot name its victim is marked `SPECULATIVE` and cannot
seal without explicit operator approval.

### 4. Double contrast against docs — mandatory

After code-first drafting, each assumption is contrasted against the project
documentation. Every doc-vs-code discrepancy is declared in a dedicated
skeleton section: code is the truth; discrepancies become doc-fix candidates,
never design inputs.

### 5. Reviewer duties at skeleton altitude — contrast by contract

Reviewers do not merely READ the drafter's answers; they answer the same
questions independently, and the contrast is itself a contract field. The
doc-review contract gains one contrast entry per draft invariant id: the
reviewer's OWN answer to each load-bearing question (consumer, payload
facts, frequency/window, victim) with the reviewer's OWN file:line
citations, plus a per-field verdict: concur or diverge. Every divergence
must back a finding (or an explicit, cited concurrence-with-nuance). A
diverging field with no finding, or a draft invariant with no contrast
entry, is rejected mechanically by the driver — coverage and citation
existence are checked without an LLM.

- Sample-verify the assumption citations against code.
- A missing price tag or missing assumptions/discrepancy section is a P1
  content gap.
- Disproportionality is a reviewable defect: a mechanism an order of
  magnitude larger than the harm it prevents draws a P2, and the finding must
  name the harm (findings that demand mechanisms without a victim are
  themselves invalid).

Scope (token economics): the full contrast is a FULL review-round
obligation only. Delta reviews contrast ONLY the entries the diff touches
(new or modified invariants/assumptions); untouched entries carry the last
full round's contrast forward. A delta must never re-pay the whole table —
the standing delta-cost rule applies here unchanged.

Known limit: anchoring cannot be mechanically prevented (the drafter's
table sits inside the artifact under review; "derive from code before
opening the table" is instruction, not enforcement). Mitigations: family
rotation makes the contraster a different model, and the slot demands the
reviewer's own citations — anchored or not, they are falsifiable.

### 6. Operator gate surface

At the skeleton seal, the milestone record (and panel) surface the "what you
are paying for" list: every invariant with its price tag and any SPECULATIVE
flags — a two-minute operator veto at the point of maximum leverage.
Because the price tags arrive as structured contract entries (section 3),
this card is GENERATED deterministically from the ledger — same doctrine as
the milestone records: no LLM prose, so it cannot disagree with what the
workers actually committed to.

## Non-goals

- No new review phases or units; this lands inside existing skeleton
  drafting/review prompts and gate rendering.
- No doc-crusade: discrepancy entries are candidates for later doc fixes,
  never blockers for the milestone that found them.
- Implementation/fix prompts unchanged except where they inherit the
  skeleton's sections.

## Constraint

Canon changes run the canon's own full milestone cycle — uniform depth, no
fast paths.
