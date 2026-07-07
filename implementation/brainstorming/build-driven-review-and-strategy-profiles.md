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

A document unit is reviewed until no finding **rates ABOVE the run's
gate threshold** (see §2 — the canonical rule: at-or-below defers as
debt, above fixes) — not until prose-clean. It then seals and the
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
what records as tracked debt (timeline chips, already live). THE ONE
CANONICAL RULE, everywhere this note says "gate" (fixed by review — two
sections phrased it in opposite directions): **rating <= threshold ->
tracked debt (or log); rating > threshold -> fix cycle.** A "light"
profile with threshold `medium` therefore fixes only high/xhigh. Workers
rate; config decides; every rating is auditable in the ledger. The existing
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
- The report is a concrete worker contract (second-review fix — pinned
  so no driver invents it): draft/implement outputs gain a third status
  value — `"status": "gap"` alongside `ok|blocked` — with a mandatory
  `"gaps"` array; each entry: `{target: goal|skeleton|slice_doc-NN,
  missing_or_conflict: <what>, where: <file:line on the upstream>,
  forced_decision: <the choice it forces>, proposal: null | <marked
  proposal, never self-service>, plain: <lay sentence>, example:
  <smallest concrete scenario>}`. A gap response carries NO artifact
  claim (nothing was finished); `ok` with a non-empty gaps array is a
  contract violation. The driver routes it as a repair queue on the upstream
  unit: fix at P1 quality, delta review, reseal, then the downstream
  unit resumes with fresh budgets (the resume amnesty markers, already
  live). HONEST SCOPE (corrected by review): today a SEALED unit is
  terminal — the M164 "reseals" were failed seal ATTEMPTS reopening a
  not-yet-sealed unit, not a reopen of a sealed one. The reform must
  BUILD the reopen: a `reopen_for_repair` transition (sealed ->
  repairing) with its ledger event, gate-commit discipline for the
  repaired artifact, and the reseal path. New machinery, priced as
  such.
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
| Implementation seal | full cross-family approval, always (see precise invariant below) | full cross-family approval, always |

THE SEAL INVARIANT, stated precisely (corrected by review — "double
seal never relaxed" contradicted live production, where
`single_seal_first_attempt` already applies to every unit kind): what
can never be relaxed is CROSS-FAMILY APPROVAL OF THE SEALED BYTES —
every family has approved the exact bytes that seal, through a
WHOLE-ARTIFACT look: an open-scope clean round or a seal half. Narrow
parallel-block actions do NOT count as whole-artifact approval
(second-review fix): the a1 single seal may drop a family's half ONLY
when that family's last whole-artifact look approved these exact
bytes; in a profile that omits final open-scope passes, the skipped
family has no such look and BOTH halves run — single-seal is a
consequence of the invariant, never an override of it. Approval
composes with the live P3-debt path (second-review fix): a family's
seal half that raised ONLY findings rated at-or-below the threshold by
the opposite family counts as approval WITH RECORDED DEBT — the
deferral events and debt entries are the approval's written remainder.
Any change after a family's approval requires that family to look
again (a2+ full double seal). Decision 2's single-family reseal
applies to DOC units only, never implementations.

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
extends it to gap reports and adjudication records — INCLUDING carrying
`plain`/`example` through the paths that today drop them
(second-review fix): the fixer's queued-finding echo and the
adjudicated-rejections registry preserve both fields verbatim, so the
lay context survives triage and adjudication. Rationale, in the
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
  requeue — a partial batch never fails the block. BUT (fixed by
  review) partial tolerance never waives the battery: the stage's
  evaluator CANNOT pass the unit until every MANDATORY dimension has
  completed — requeued mandatory dimensions block advancement; only
  optional lenses may end a stage unrun.
- **The component algebra (operator refinement, 2026-07-07).** Four
  orthogonal primitives compose the review phase; profiles are saved
  compositions:
  - **Action** — one atomic review call: `{scope (a battery question, a
    standing lens, open, or delta — the re-review of a pending fix
    diff, today's delta_review as a scope), family, model, effort}`.
    Produces raw candidate findings. Scopes cover doc AND impl units:
    an `until_clean` loop re-enters after a fix either with a cheap
    `delta` action or by re-running its full composition — a per-stage
    knob.
  - **Loop** — the dispatch shape over actions: `single`, `parallel`
    (concurrent fan-out, one tamper snapshot around the batch,
    partial-tolerant), `until_clean` (repeat while the evaluator passes
    findings), `alternate_families` — the CURRENT sequential process,
    preserved as just another loop, so compatibility costs nothing.
  - **Fuser** — optional continuation certain loops use when they
    parallelize: dedupe, contrast-vs-code, re-rate. Candidates in,
    vetted candidates out. The fuser has a MANDATORY declared identity
    in the profile — `{family, model, effort}` (second-review fix) —
    because its discard/re-rating authority depends on whether it is
    opposite-family to a finding's raiser. Valid only after a `parallel` loop; discards
    only with citing evidence; fully ledger-recorded. Re-rating bar
    (fixed by review): a fuser re-rating that would FLIP a finding
    across the gate threshold carries the same bar as a discard —
    citing evidence in `light`, evidence plus an opposite-family concur
    in `strict` — and a fuser rating counts as the opposite-family
    rating only when the fuser IS opposite to the finding's raising
    family.
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
    creation. A profile SEALS on first production use — immutable from
    then on; editing means CLONING to a new identity (name@version or
    content hash), which runs reference explicitly. Sealed profile +
    orchestrator_rev fully attribute a run's behavior (the existing
    provenance doctrine extended), and sealing is what makes per-profile
    metrics comparable and model-assignment tuning an honest experiment
    (one dial changed per clone). Once the project-concept milestone
    lands, a project's KV may carry its default profile.
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
  operator}` — repeated until done. The gap TARGET vocabulary is closed
  and covers the top of the chain (fixed by review): a slice
  implementer targets its slice doc or the skeleton; a slice-note
  drafter targets the skeleton (or `goal` when the skeleton faithfully
  mirrors a goal-level contradiction — second-review fix); the skeleton
  drafter — who has no upstream unit — targets `goal`, which routes to
  the OPERATOR as a blocked-with-report (chip + the report's forced
  decision), because the goal document is operator-authored and only
  its author repairs it. The legacy mode survives as pure
  config (an impl action pinned exit-0-always), so migration is a
  profile choice, not a code fork. FENCED (corrected by review — an
  exit-0-always action contradicts the constitutional gap semantics):
  `legacy` is a grandfathered COMPATIBILITY ARTIFACT, valid only for
  bit-equivalence testing and for reproducing pre-reform behavior; it
  is excluded from the constitution's claims, cannot be composed into
  new profiles (a reform profile may not embed an exit-0-always
  action), and the panel labels it as such. The back-edge is budgeted and judged
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

The meter's trigger parameters are PROFILE FIELDS, not folklore
(second-review fix): the net-zero window (N amends), the near-empty
epsilon (net lines), the churn-ratio bar, and the time-per-net-line
slope are named numeric fields of the profile schema; observe mode
ends by WRITING the chosen values into the cloned armed profile, so
two implementations cannot read different alarms from the same run.

Metrics are ANCHORED PER PROFILE — historical runs are NOT a calibration
source (they were produced under a process that no longer exists:
different prompts, binary reclassify, mid-run amendments changing
everything; a metric only compares within a constant configuration).
Every meter datum is recorded under the sealed profile identity that
produced it. Within a profile: real trends. Across profiles: defined A/B
experiments — clone the profile, change ONE dial (e.g. which model runs
the fan-out), run, compare anchored signals. A freshly sealed profile
starts its alarms in OBSERVE mode (signals and chips recorded, no
actions) until it has accumulated its own N runs; thresholds are then
set from its own data and the profile clones to an armed version.

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

## Planning-context decisions on project-concept.md (fixed by review)

This note consumes material from the project-concept milestone; the
required Adopt/Revise/Reject record:

- **Adopt (deferred dependency)**: the project KV as the future home of
  per-project DEFAULT profiles — consumed only AFTER project-concept
  lands; until then profiles live and resolve entirely in the service
  home. Nothing in this milestone blocks on project-concept.
- **Adopt as prototype, Revise into general form**: the reuse-audit
  structured contract field (enumerated adopt/gap/reject entries with
  file:line evidence, presence-checked) — revised from a single
  safeguard into the form of the WHOLE question battery (§4).
- **Reject (for this milestone)**: storing profiles or meter data in
  the project KV now, and any per-project profile resolution logic —
  premature until the KV exists and a second project needs it.

## Reuse posture (the battery, applied to this milestone itself)

Existing workflow engines were checked as the loop-interpreter base and
REJECTED — adopt their concepts, not their engines:

- **Checked**: Temporal (durable execution, retries, visibility — costs
  a server + SDK + its own event store); Airflow/Prefect/Dagster (DAG
  scheduling + UI — heavy packages, own databases, batch-pipeline
  semantics, not budgeted-and-judged loops); LangGraph/CrewAI/AutoGen
  (LLM graph composition — a dependency ecosystem with opaque state).
- **Rejected because**: (1) the hard parts of this model are NOT flow
  control — tamper snapshots/restore, seal semantics, contract
  validation with repair-retry, family rotation, gate-commit/amend
  discipline, typed failure classification with auto-resume, amnesties,
  the adjudication registry all exist and NO engine supplies them; the
  algebra needs a ~200-400 line deterministic interpreter over profile
  data, and importing an engine moves the easy 5% while fighting its
  framework for the remaining 95%. (2) Every engine brings its own
  state store, splitting or duplicating the append-only, inspectable
  state.json ledger that IS the product — and "nothing vendored or
  pinned" is sealed doctrine across all consumers. (3) The scale is one
  operator, one machine, a handful of concurrent CLI subprocesses:
  seal_concurrent already demonstrates the stdlib concurrency pattern,
  at-least-once worker calls + ledger idempotence are the documented
  execution semantics, and the panel is the visibility surface in the
  system's own vocabulary.
- **Adopted**: the VOCABULARY of those systems (parallel/until/join
  pipeline semantics) for the interpreter's design; and a portability
  safeguard — the profile JSON schema stays clean enough to retarget to
  a real engine if the ecosystem ever needs multi-machine durability,
  without rewriting profiles.

## Non-goals

- No relaxation of implementation double seals in any profile.
- No automatic classification of review depth — the profile is an
  explicit operator choice at run creation.
- No post-hoc compression of existing sealed docs.
- No process switch for in-flight runs: milestones started under the
  current doctrine finish under it; the reform applies to runs created
  after it lands.

## Decisions (all 16 settled 2026-07-07 — 14 taken under recorded
## operator doctrine and vetoable during live debugging; 5 and 8 decided
## directly by the operator)

1. Gate vocabulary — **P0/P1 always open a fix cycle unrated**; rating
   calls are spent only on P2/P3, where the threshold can actually
   change the outcome. Rating a P0 adds cost and no information.
2. Repair scope on a sealed upstream — **threshold-rated, DOC units
   only**: strict reseals full double, light reseals single-family for
   repairs rated below high. WHO RATES (second-review fix — builders
   never rate their own blockers): nobody rates the gap itself; the
   REPAIR's delta review — run by the family opposite the repair fixer,
   the existing delta pattern — rates the repair diff's drift risk, and
   THAT rating picks the reseal depth. Implementation reseals always
   satisfy the cross-family approval invariant (see the seal invariant
   in §5).
3. Battery per unit kind — **skeleton carries the full battery per
   need** (victim / machinery / consumers / cheaper-alternative /
   pricing); **slice docs inherit** and answer only what is
   slice-specific: consumers touched, pinned facts, verification, AND
   the slice-scoped Reuse Posture (checked/adopted/new-with-why —
   second-review fix: the two-register template must not drop the one
   mandatory reuse section every note carries today). No re-answering
   the skeleton's battery at slice level.
4. Hard-table format — **one canonical schema** for every unit kind:
   `fact | value | authority (file:line) | touch/do-not-touch`.
   Variants would breed format nitpicking, the disease being treated.
   Unused columns stay empty.
5. Profile set — **DECIDED (operator): profiles are not a fixed enum;
   they are operator-COMPOSED artifacts** built in a panel constructor
   (forms over the stage schema: pick loops, add actions, attach fuser,
   choose evaluator rules, save under a name — the acts-dialog pattern
   scaled up). Phase 1 ships TWO seed profiles hardcoded (`strict`,
   `light`); the constructor UI lands in a later phase over the same
   JSON store. Profiles are **swappable at RUNTIME** (essential for the
   testing phase) with strict semantics: swap ≠ edit — a profile is
   never mutated in place; the run REPOINTS to another profile, the
   change takes effect at the next stage/loop boundary (never mid
   fan-out; the amendments/acts overlay pattern), a
   `profile_changed: A@hash -> B@hash` ledger event + timeline chip
   records it, and the run is marked `profile_mixed` — its meter data
   excluded from anchored series by default (experiment data, not
   calibration).
6. Gap reports MAY carry the builder's proposed resolution — **allowed,
   explicitly marked `proposal, not decision`**; the upstream fixer must
   verify independently against sources before adopting (contract
   obligation, counters anchoring). Speed wins; the mark plus the
   fixer's verification duty carries the risk.
7. Panel surface — **a dedicated timeline chip class**, exactly the
   reclassify-chip pattern: `gap → skeleton` (amber) placed
   chronologically, clickable to the report story; the upstream repair
   appears on the upstream unit's own row.
8. Fuser discard bar — **DECIDED (operator): a per-stage fuser knob**
   (`discard: evidence | evidence+concur`), configurable like every
   other dial, hardcoded in the seeds to start: `strict` = evidence +
   opposite-family concur (a cheap extra call only where a wrong
   discard is most expensive), `light` = citing evidence alone. The
   ledger audits every discard either way.
9. Fan-out dimensions — **battery + three standing lenses**
   (grounding-citations-exist, contract self-consistency, altitude),
   defined IN the profile and sealed with it: the dimension list is
   part of what anchored metrics compare, so it must not drift
   independently.
10. Final open-scope pass after parallel blocks — **profile content**:
    strict includes one per family; light omits it and relies on the
    double seal as catch-all. Not a global rule.
11. Model choices — **pinned in the sealed profile** (they are exactly
    what A/B experiments tune; a hot override would corrupt the
    anchor). The acts hot-edit mechanism SURVIVES for operator
    sovereignty, but any act override on a profile run marks that run's
    meter data `deviated: true`, excluding it from the profile's
    anchored series. You keep the wheel; the data stays honest.
12. Repair blast radius — **cited-only directed re-verification**, with
    the repair fixer contractually obligated to list every collateral
    section it touched, each listed section triggering its own directed
    re-verification. Never a global downstream reopen.
13. Back-edge budget — **the convergence rubric is the judge, the cap
    is the backstop**: deterministic meter/alarm triggers the LLM
    trajectory evaluation (same gap bouncing = stall → operator); a
    fixed cap of 3 impl->doc->impl cycles per unit pair backstops it,
    amnesty-on-resume as everywhere.
14. Alarm action — **chip + trigger the LLM progress evaluation; never
    an autonomous pause**. A pause only happens as the evaluation's
    stall verdict (threshold-decided), so stopping is always a judged
    outcome, not a tripwire reflex. Observe mode for a fresh profile:
    **its first 3 runs**, then thresholds arm on its own data.
15. Profile identity — **both**: human `name@version` as the label,
    content hash as the truth (recorded in the run config snapshot;
    verified on load — a mutated profile fails loudly). Corrected by
    review (the seal bit cannot live inside the hashed content — sealing
    would change the identity): the hash covers the CANONICAL SEMANTIC
    CONTENT only (the stages composition and its dials, canonical JSON);
    name, version label, seal bit, and timestamps are METADATA outside
    the hash. Sealing flips metadata; the identity is stable. A run MAY
    reference an unsealed profile; that first production reference is
    what seals it.
16. Metric store — **service home, keyed by profile identity**
    (profiles are global objects and the home exists today);
    per-project views arrive later through the project KV once
    project-concept lands. No blocking dependency.
