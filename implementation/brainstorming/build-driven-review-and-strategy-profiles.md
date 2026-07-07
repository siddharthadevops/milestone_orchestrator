# Build-driven review and per-run strategy profiles

Status: non-canonical brainstorming — operator-driven need (2026-07-07).
Sequencing: FOLLOWS "project concept" (project-concept.md — consumes its
structured reuse-audit contract machinery as the battery-as-structure
prototype) and should PRECEDE "machine API and persona projection": it
changes the cost of every future run, so it compounds earliest.

## Need

Document-phase review has no fixpoint. Code review converges because code
has an external oracle (the suite passes or it does not); a 600-line prose
contract admits one more precision forever, and a reviewer asked to "review
and report findings" pays nothing for raising a nit and something for
returning clean. The result, measured live on the LPC chat-workflows bundle
(2026-07-06/07):

- The milestone skeleton took **15 full codex reviews, ~70 rounds, ~10
  hours** to its first clean full review. Of ~46 findings raised, **5-6
  protected construction** (one genuine P1: a participant conflict-code
  seam that was unbuildable as designed because the shared transport
  discards the field it needed). The rest refined the map, not the
  territory: enumeration completeness, wording precision, mechanism
  placement.
- Late rounds review the fixes, not the draft. Forensic trace of one
  finding (slice-02, 2026-07-07): a fix at 12:49, satisfying a P2 that
  asked to "specify the exact CSS custom property names", ADDED a fourth
  public CSS variable no recorded authority supported; the next seal
  half flagged it; the drift-risk rater rated it high; another fix
  removed it at 14:09. Eighty minutes and three worker calls to return
  to the starting point — self-inflicted churn, invisible without commit
  archaeology.
- The register itself is a cause, not a symptom. The operator's own
  account: the doc reads "exquisite, I would not know where to start
  cutting" — until he remembers it specifies a floating menu. The
  specification register induces precision worship in every reader,
  models and humans alike. (Mitigation already live as a soft field: the
  plain-language mirror, orchestrator commit `8a7b874`.)
- Asked binary risk questions, workers refuse risk categorically. The
  P3-deferral reclassifier, asked "is this safe to defer?", never
  deferred anything in contract work. The same worker, asked to RATE
  drift risk on a fixed scale with no decision attached, produced a
  calibrated `medium` on the identical finding and artifact (A/B
  replayed on the pre-fix commit, 2026-07-07). Measurement belongs to
  the LLM; decisions belong to deterministic thresholds — that machinery
  is live (`drift_risk` rating vs `p3_defer_max_risk`) and this reform
  generalizes it.
- Post-hoc compression is not the answer. An external summarizer cut the
  sealed slice-02 doc by 64% "keeping the meaning"; a 16-agent
  adversarial audit confirmed **5 distinct material contract losses, 0
  refuted** — one actively inverting an instruction (a mandated
  package-wide README/moduledoc correction read as a prohibition), plus
  every file:line citation (which kills reviewability). What died was
  exactly the dense-register mechanics and the audit trail; the intent
  survived fine. Compression must happen at authoring time, by form,
  not afterwards by summary.

The current doctrine ("no backtracking by design: catch everything in the
cheapest layer") buys its guarantee at a price that is only worth paying
when the cost of being wrong is high. A Life brain change deserves it. A
floating menu does not — and the process cannot tell them apart.

## Proposal

### 1. The review oracle moves to the next builder

A document unit is reviewed until no finding **rates at or above the run's
gate threshold** (see §2) — not until prose-clean. It then seals and the
next stage consumes it: the slice-doc drafter consumes the skeleton, the
implementer consumes the slice doc. The consumer works under a mandatory
gap-report contract (§3). Gaps it reports are repaired upstream at full
quality and the pipeline resumes. The reviewer that matters most for a
document is the agent that has to build from it: it has a natural cost
function (it only surfaces what blocks or contradicts construction) that
prose re-readers lack.

### 2. Threshold gates over drift-risk ratings

The live reclassify machinery generalizes from "lone P3s at seal time" to
the whole document gate: findings carry the reviewer's severity AND the
opposite-family drift-risk rating where the gate needs it; the run's
profile threshold decides deterministically what opens a fix cycle and
what records as tracked debt (timeline chips, already live). Workers rate;
config decides; every rating is auditable in the ledger. The existing
scale (`low | medium | high | xhigh`, `contracts.DRIFT_RISK_LEVELS`) is
the vocabulary.

### 3. Uniform gap semantics — stop, report, repair upstream, resume

In EVERY profile, identically:

- Draft and implement workers receive: **if you meet a hole or a conflict
  that would change what you build — a choice between readings, a missing
  fact, a contradiction with a sealed upstream — STOP and report it. Do
  not resolve it, do not build around it.** Continuing around a gap
  delegates to the builder the judgment of what the gap contaminates;
  that judgment is silent drift (the M164 backtracks were exactly
  problems discovered after building on top).
- The report is a structured contract field (per gap: what is missing or
  in conflict, where — file:line on the upstream doc — and what decision
  it forces). The driver routes it as a repair queue on the upstream
  unit: fix at P1 quality, delta review, reseal if the unit was sealed
  (the amendment+reseal path exists — M164 skeleton resealed a3/a4),
  then the downstream unit resumes with fresh budgets (the resume
  amnesty markers, already live).
- Builders never rate their own blockers: a low self-rating would be
  permission to continue, which is drift through the back door. Any
  build-changing gap halts, no gray scale.
- Bright line for what is NOT a gap: observations that do not change
  what the builder builds (typos, shifted line citations, stale cosmetic
  wording) go in a notes field of the normal output, without halting
  anything.

### 4. The question battery survives in every profile — as structure

The engineering battery is untouchable in ALL profiles: who is the victim
without this, what new machinery and why, who consumes it (verified, not
assumed), what cheaper alternative was rejected and why, what does it
cost. But it becomes a **structured gate**, not a prose genre: each
question is a contract entry with its answer and file:line evidence, and
review checks **presence and substance** (is it answered? does the
evidence exist and say that?). A finding against an ANSWERED question's
wording ("it did not name that product X uses Y" when consumption is
already evidenced) is an ordinary finding that rates against the threshold
like any other — re-litigating the prose of answered questions is exactly
the churn this reform removes. The project-concept milestone's reuse-audit
contract field (enumerated adopt/gap/reject entries with file:line
evidence, machine-checked for presence) is the prototype; this reform
extends that form to the full battery.

### 5. Per-run strategy profiles, chosen by the operator

A run is created WITH a profile. Nothing auto-classifies (the operator
explicitly rejected depth-by-classifier in the S7 discussion, 2026-07-03,
and that rejection stands — the choice is his, per run, by
cost-of-being-wrong):

| Axis | `strict` (e.g. Life brain, canon itself) | `light` (e.g. UI shell work) |
|---|---|---|
| Question battery | mandatory, evidenced | mandatory, evidenced |
| Doc gate | every finding opens a fix cycle | only rated >= high opens; rest -> tracked debt |
| Doc register | dense contract prose allowed | lay register + hard table (§6) |
| Gap semantics | stop-report-repair-resume | stop-report-repair-resume (identical) |
| Implementation double seal | full, never relaxed | full, never relaxed |

Profiles decompose into config dials (several already exist:
`p3_defer_max_risk`, `p3_reclassify_debt`); the panel's new-run form
offers the profile and shows the decomposition. Defaults ship ARMED per
the standing rule: the profile field is mandatory at creation, with no
silent default that no-ops the operator's intent.

### 6. Two-register documents

Doc-phase artifacts split into two registers with different review
treatment:

- **Intent register (lay language)**: what is being built, for whom, what
  it owns and does not, in words a non-engineer follows. "This slice
  builds the floating action menu; the menu accepts configurable icons;
  colors belong to the product." Reviewed for substance, not for prose
  perfection.
- **Pinned-facts table (hard register)**: the small set of facts where
  ANY deviation is a bug — exact names, events, routes, error codes,
  enforcement mechanisms, what must NOT be touched, each with its
  authority citation. Reviewed strictly; this is where file:line
  precision lives and where the compression audit showed all real losses
  concentrate.

The 64%-compression audit is the empirical sizing: intent survives
compression; ~5 material contracts and the citations do not. Write docs
born at the compressed size with the hard table intact, instead of
600-line uniform-register prose cut down afterwards.

### 7. The plain-language mirror becomes mandatory

Already live as a soft field (`plain` on every reviewer finding, commit
`8a7b874`: one sentence a non-engineer understands, written BEFORE
choosing severity; shown first in panel stories; fed to the drift-risk
rater). This milestone hard-requires it in the finding contract and
extends it to gap reports and adjudication records. Rationale, in the
operator's words: the NASA-engineer register strips common sense from
every reader; the plain sentence shows the real size of the problem
before the severity is chosen.

### 8. Parallel review blocks — the wall-clock leg

The other half of the cost is TIME: reviewers surface findings in a
dribble because an open-scope review satisfices ("found a couple of
things, return") — and each pass is a full sequential worker call. The
reform makes the doc-review phase a **composable pipeline of review
blocks**, declared per profile, interchangeable like bricks; the final
gate (seal) is invariant and outside the composition.

- **Parallel battery pass (the new block).** One narrow-scoped review
  per battery question / standing lens (consumers verified? machinery
  priced? grounding citations real? contract self-consistent?), fanned
  out CONCURRENTLY, both families, on fast tiers (codex at xhigh is
  fast; claude on a fast/cheap model). A scoped reviewer has a
  completion criterion — it drains its one dimension instead of
  sampling everything shallowly. Empirical basis (2026-07-07): two
  multi-agent parallel audits of live artifacts (6-lens skeleton audit;
  16-agent compression audit, 6.5 min wall-clock, 10/10 findings
  surviving adversarial verification) found in minutes what sequential
  open rounds took days to reach.
- **The fuser (max effort, single call).** Takes the raw candidate
  batch: contrasts each against the actual code/doc, merges duplicates,
  re-rates severity/drift-risk, and passes survivors to the normal
  consideration path. Three shackles, because it is a single point of
  judgment: it may DISCARD only with citing evidence (file:line that
  refutes the candidate — "seems minor" is the threshold's job, not
  the fuser's); every candidate/merge/discard/pass is recorded in the
  ledger and surfaced as a panel chip (auditable calibration of the
  cheap tier's noise rate); when unsure it passes the finding through —
  the fuser never owns risk (the binary-reclassify lesson).
- **Concurrency mechanics.** Reuses the seal_concurrent pattern: report-
  only workers, one tamper snapshot around the whole batch (any
  workspace change voids the batch). Partial-result tolerance is
  mandatory: a fan-out hitting a quota window returns what it returns;
  the fuser works with the arrived subset and the missing dimensions
  requeue — a partial batch never fails the block.
- **The component algebra (operator refinement, 2026-07-07).** Four
  orthogonal primitives compose the review phase; profiles are saved
  compositions:
  - **Action** — one atomic review call: `{scope (a battery question, a
    standing lens, or open), family, model, effort}`. Produces raw
    candidate findings.
  - **Loop** — the dispatch shape over actions: `single`, `parallel`
    (concurrent fan-out, one tamper snapshot around the batch,
    partial-tolerant), `until_clean` (repeat while the evaluator passes
    findings), `alternate_families` — the CURRENT sequential process,
    preserved as just another loop, so compatibility costs nothing.
  - **Fuser** — optional continuation certain loops use when they
    parallelize: dedupe, contrast-vs-code, re-rate. Candidates in,
    vetted candidates out. Valid only after a `parallel` loop; discards
    only with citing evidence; fully ledger-recorded.
  - **Evaluator** — the DETERMINISTIC per-stage gate: a config rule
    over findings — `all` (everything passes to consideration: the
    right rule when the pass was cheap/lay and fine judgment comes
    later), `>= Pn`, `drift_risk <= threshold`,
    `battery_complete` — deciding what opens a fix cycle, what records
    as debt, what merely logs. No LLM inside the evaluator: models live
    in actions and the fuser; the evaluator is pure decide() applying
    rules.
  - **Profile** — a NAMED, SAVED, reusable sequence of stages
    `loop(actions) -> [fuser] -> evaluator`, stored as JSON documents
    under the service home (`~/.impl_roadmap/profiles/`), selectable in
    the panel's new-run form, and SNAPSHOTTED into the run's config at
    creation — editing a profile later never mutates a live or closed
    run's semantics (the existing config-snapshot doctrine). Once the
    project-concept milestone lands, a project's KV may carry its
    default profile.
  Invariants live OUTSIDE the algebra and no profile can compose them
  away: the final double seal, the gap semantics (stop-report-repair-
  resume), battery presence, report-only + tamper snapshots on every
  review, and full ledger recording of every stage.

- **The algebra is recursive: implementation and the operating mode are
  loops too (operator refinement, 2026-07-07).** Implementation is a
  loop with the same architecture — only the ACTIONS differ (implement/
  fix instead of review). And the unit lifecycle itself is the outer
  loop: a deterministic controller reading typed exit codes from inner
  loops. The current process, expressed in the algebra, is
  `review_loop(until clean) -> impl_loop(exit 0 ALWAYS)` — today's
  implement action cannot fail softly; its only escapes are "done"
  (with any gap resolved silently inside: the built-in drift channel)
  or hard `blocked` (run dead awaiting the operator). The reform gives
  implementation actions an honest return: a CLOSED, TYPED exit
  vocabulary — `done | gap(report) | blocked` (no free integers; `gap`
  carries the structured report including its cited repair TARGET: this
  slice doc or the skeleton). The operating mode becomes:
  `review_loop(profile) -> impl_loop -> {done: seal; gap: repair the
  cited upstream through its own gate, then re-enter impl; blocked:
  operator}` — repeated until done. The legacy mode survives as pure
  config (an impl action pinned exit-0-always), so migration is a
  profile choice, not a code fork. The back-edge is budgeted and judged
  like every loop: cycle caps with resume amnesties, and the
  convergence rubric (gaps shrinking and changing = converging; the
  same gap bouncing = stalled -> operator). The mechanical suite gate
  slots in as the impl loop's non-LLM evaluator — the one place the
  exit-code metaphor is literal.

### 9. The deterministic progress meter — an alarm no rhetoric can fool

Besides the LLM progress evaluation (convergence rubric), a PURE metric
watches every loop, computed from data the ledger already records:
worker time per episode (`duration_s` on every round) over lines changed
in the PURE artifact — the unit's own document for doc units, the
declared code changes minus generated bookkeeping (review-log, milestone
record, adjudications) for impl units — diffed between the amend shas
the ledger already stores. Three derived signals:

- time-per-net-line rising across episodes;
- net-zero cycles: an episode whose cumulative artifact diff vs N amends
  back is empty or near-empty (the measured travel-var case: 80 worker
  minutes, three calls, net diff ~0 — a full add-then-remove round
  trip);
- churn ratio: (added+deleted)/|net| high = the same lines rewritten
  repeatedly.

It cannot be argued with: it reads diffs, not prose. Composition:
**deterministic tripwire -> LLM judgment -> threshold -> operator** —
the free metric decides WHEN the expensive opposite-family progress
evaluation runs (never per-round); that evaluation judges trajectory
quality (new-and-narrower findings vs the same gap bouncing); the
profile threshold decides continue/stall; the operator sees an alarm
chip carrying all three layers of evidence. Alarms are first-class
ledger events. In the algebra, this extends the evaluator's inputs from
findings to process metrics.

Because the amend shas are all in the ledger, the meter is computable
RETROACTIVELY: thresholds get calibrated by backtesting against recorded
runs (the 15-review LPC skeleton, the travel-var episode) so the shipped
defaults are values that would have fired there and stayed silent on
healthy runs — no speculation.

## Already-live pieces this composes with

- Drift-risk rating + threshold decision (`b9d0a75`), A/B-validated.
- P3 debt deferral default ON (`b0c05b1`), timeline chips (`03709b5`).
- Resume amnesties for review-round/seal caps (`a251afd`) — repairs and
  resumes get fresh budgets mechanically.
- The `blocked` worker path (halt semantics exist), amendments and their
  authority rendering, the adjudicated-rejections registry, the
  amendment+reseal precedent (M164 a3/a4).
- The plain mirror soft field (`8a7b874`).

New machinery this milestone must build: the gap-report contract field on
draft/implement kinds and its driver routing (upstream repair queue +
downstream resume), the battery-as-structure contract for doc units, the
profile config + panel selection, the two-register doc templates and
their review rubrics, generalized threshold gating of doc rounds, and the
hard requirement of `plain`.

## Non-goals

- No relaxation of implementation double seals in any profile.
- No automatic classification of review depth — the profile is an
  explicit operator choice at run creation.
- No post-hoc compression of existing sealed docs.
- No process switch for in-flight runs: milestones started under the
  current doctrine finish under it; the reform applies to runs created
  after it lands.

## Open decisions (the milestone must settle)

1. Gate vocabulary: rate every doc finding through the opposite family
   (cost: one rating call per finding) or only findings below a severity
   floor, with P0/P1 always opening a fix cycle unrated?
2. Repair scope: when a gap report reopens a SEALED upstream doc, does
   the repair reseal single-family (the delta-style cheap path) or full
   double seal? (Proposal: rated by the same threshold — light profile
   reseals single-family for gaps rated below high.)
3. Battery enumeration per unit kind: which questions are mandatory for
   a skeleton vs a slice doc (skeleton: victim/machinery/consumers/
   alternatives/pricing per need; slice doc: consumers + pinned facts +
   verification only?).
4. Hard-table format: one canonical table schema (name | value |
   authority citation | touch/do-not-touch) or per-unit-kind variants.
5. Profile set: exactly two (strict/light) or three (a `standard`
   between them)? Names and default dial values per profile.
6. Whether the gap-report path can also carry the builder's PROPOSED
   resolution (as input to the upstream fixer, never as self-service) —
   speeds repair, risks anchoring the fixer.
7. Panel surface: where gap reports and upstream repairs appear (a
   dedicated chip class in the timeline, mirroring reclassify chips?).
8. Fuser discard bar: is refuting evidence (file:line) enough, or does a
   discard additionally require an opposite-family concur (costlier,
   safer)? Proposal: evidence alone in light, evidence+concur in strict.
9. Fan-out dimension list per unit kind: battery questions only, or
   battery + standing lenses (grounding-citations-exist, contract
   self-consistency, altitude)? Who maintains the list — config or the
   profile definition?
10. Is a final open-scope pass (single per family, normal effort)
    mandatory after parallel blocks as a did-we-miss-anything catch, or
    profile-optional with the double seal as the only catch-all?
11. Fast-tier model choices per family (e.g. claude fan-out on a
    fast/cheap model, fuser on max) — fixed in the profile or
    per-run overridable through the acts mechanism?
12. Repair blast radius: when an impl gap repairs the SKELETON, which
    sealed slice docs re-verify — only what the gap report cites
    (directed re-verification), or everything downstream of the edited
    sections? (Proposal: cited-only, with the repair fixer obligated to
    list collateral sections it touched, each triggering its own
    directed re-verification.)
13. Back-edge budget: how many impl->doc->impl cycles before the
    operator is surfaced — a fixed cap with amnesty-on-resume (the
    existing pattern), or the convergence rubric (same gap bouncing =
    stall) as the primary judge with the cap as backstop?
14. Alarm action when the deterministic meter trips: chip + trigger the
    LLM progress evaluation only (proposal), or also pause the unit
    until the evaluation returns? And the backtested default thresholds
    per signal (time-per-net-line, net-zero window N, churn ratio).
