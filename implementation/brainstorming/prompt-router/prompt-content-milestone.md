# Milestone Job Content — Zero-Based Analysis

Status: **non-canonical analysis** — the design rationale behind
[`goal.md`](goal.md) and the [`adapted-kinds/`](adapted-kinds/) seed corpus;
raw evidence in [`current-prompts.md`](current-prompts.md).

Method: this document is NOT a conversion of the current prompts. It derives, job
by job, what each prompt section must contain **for a milestone to execute
perfectly** — and what must NOT be there. The current corpus is used only at the
end, as evidence of how shared blocks accumulate text that no single job earns.

## 1. The job grid

A "kind" is not a job. The same kind over a different unit type is different
work: reviewing a skeleton is design review against the GOAL; reviewing a slice
note is contract review against the SKELETON; reviewing an implementation is
code review against the NOTE plus the CURRENT skeleton. Skeleton work and slice
work are different jobs even when the kind name matches.

The milestone grid — 12 jobs:

| # | Job | Kind | Unit | Judges against |
|---|-----|------|------|----------------|
| 1 | Skeleton draft | draft_skeleton | skeleton | goal |
| 2 | Skeleton review | review_round | skeleton | goal |
| 3 | Skeleton fix | fix_findings | skeleton | goal + findings |
| 4 | Slice-note draft | draft_slice_note | slice_doc | skeleton |
| 5 | Slice-note review | review_round | slice_doc | skeleton |
| 6 | Slice-note fix | fix_findings | slice_doc | skeleton + findings |
| 7 | Implementation | implement | slice_impl | note + current skeleton |
| 8 | Implementation review | review_round | slice_impl | note + current skeleton |
| 9 | Implementation fix | fix_findings | slice_impl | note + findings |
| 10 | Delta review | delta_review | skeleton / slice_doc / slice_impl | same standards, scoped to the current work tree against an explicit base revision |
| 11 | Drift rating | reclassify | any doc | the finding as raised |
| 12 | Full-suite checkpoint | suite_checkpoint | workspace | the repository's official complete suite |

Canonical job ids (the complete set the router serves):
`draft_skeleton@skeleton`, `review_round@skeleton`, `fix_findings@skeleton`,
`delta_review@skeleton` (skeleton fix deltas exist — the grid's row 10
extends to it), `draft_slice_note@slice_doc`, `review_round@slice_doc`,
`fix_findings@slice_doc`, `delta_review@slice_doc`, `implement@slice_impl`,
`review_round@slice_impl`, `fix_findings@slice_impl`,
`delta_review@slice_impl`, `reclassify@doc`, `suite_checkpoint@workspace`,
`merge_repair@workspace`;
`rethink@doc`, `rethink@impl` (session charges — job "fix this" by
artifact type, opened by the orchestrator from a need_rethink finding);
sessions: `discussion_turn`, `questioner_turn` (seat-coordinate routed).

## 2. What each job's prompt must contain

Per job: **Purpose** (one deliverable), **Inputs** (what must be named),
**Own law** (rules that change THIS worker's behavior), **Output**, and
**Not here** (text that dilutes this job even though the process needs it
elsewhere). Vocabulary: in prompt text the goal is the **MANDATE**; the
skeleton frames downstream kinds as **BASELINE** (adapted-kinds decision 20).

### Job 1 — Skeleton draft
- Purpose: turn the goal into the milestone's planning contract.
- Inputs: goal (the mandate, read in full), workspace + read roots, the
  executor catalogue with the producer-choice duty, target path, amendments
  when relaunching.
- Own law: skeleton scope (thin; planning contract, never slice notes; narrow
  slices with the size aim), two-register form, doc altitude, the shared
  REUSE GATE ("requirements fix outcomes, not mechanisms"), guarantee-posture
  declaration duty, the design due diligence (victim / machinery / consumers /
  cheaper_alternative / cost / threat_model / enforceability — these are
  design questions, answered at design level; job 4 re-answers the battery
  at slice scope for what each slice concretely introduces).
- Output: artifact, slice plan with both producer choices, and `questions`
  (the due diligence lives in the DOCUMENT only; the output carries
  QUESTIONS, whose `due_diligence_count` item confirms it was answered —
  presence check, no validator).
- Not here: need_rethink (the whole design is in its hands — a contradictory
  GOAL is `blocked`, an open design question is its own to settle), review
  rubric, severity, fix dispositions, deferred debt,
  adjudications (none exist yet — the skeleton FIXER sees them, not the first
  drafter), delta rules, suite duties.

### Job 2 — Skeleton review
- Purpose: verify the plan is a faithful, buildable contract of the goal.
- Inputs: goal, skeleton, amendments, adjudicated rejections (rework cycles).
- Own law: judgment core (finding validity, severity battery, plain+example
  expression bar), report-only stance, exhaustive pass, doc-altitude review
  duty (both directions), design-level machinery challenge, coverage duty:
  every goal requirement lands in some slice; every slice is reviewable alone.
- Output: findings (review schema) or clean.
- Not here: scope-authority doctrine (this IS the skeleton — there is no
  higher reviewed design to defer to; the baseline is the goal), fix law,
  edit permissions, deferred debt. (The review body — including the
  verification boundary — is ONE shared sequence for all reviews; only
  scope lines differ: decision 33.)

### Job 3 — Skeleton fix
- Purpose: triage exactly the queued skeleton findings.
- Inputs: skeleton, goal, queued findings, adjudications.
- Own law: fix core (adversarial validation, decision table, verdict account,
  and the prohibition on worker-owned model calls), the skeleton as primary target (fences are
  down: touching siblings is legitimate when the fix requires it;
  reviews judge the result), the slice-table
  duty (any table change returns the FULL plan in `slices`), doc-altitude fix
  duty ("fix at altitude").
- Output: fix results, files_changed, slices when the table changed.
- need_rethink is available here too (operator, 2026-08-23): a MANDATE
  hole that is designable within it may go to a rethink session — owning
  the document means it may edit it, not that it is denied the
  adversarial machinery; only "the MANDATE itself is broken or must
  change" stays blocked to the operator. A rethink leaves the skeleton
  FIXED, not proposed.
- Not here: complete-suite discovery or execution (owned by job 12),
  implementation_cut, code-review law, delta rules.

### Job 4 — Slice-note draft
- Purpose: one slice's contract — observable scope, tests that pin it,
  acceptance, non-goals, postures.
- Inputs: skeleton (operative goal restatement), goal (trace intent only),
  amendments, slice id/title, target path.
- Own law: doc altitude, two-register, the slice due diligence — the FULL
  battery at slice scope (victim / machinery / consumers_touched /
  cheaper_alternative / cost / threat_model / pinned_facts / verification /
  enforceability), answered for what THIS slice concretely introduces (the
  skeleton answered design level; decision 25 merges) — the shared REUSE
  GATE, need_rethink (a design contradiction it may not resolve alone:
  finding + artifact, no proposed direction), producer planning only when
  re-planning is requested.
- Output: artifact, `questions` (incl. `due_diligence_count` — the due
  diligence is document-only, presence confirmed in output), slices when re-planning.
- Not here: severity, review rubric, fix law, suite duties, delta rules.

### Job 5 — Slice-note review
- Purpose: is this note in-scope, observable, and testable against the
  skeleton?
- Inputs: skeleton, note, amendments, adjudications, deferred debt (this
  unit's), goal for unsettled intent.
- Own law: judgment core, report-only, exhaustive pass, doc-altitude review
  duty, citation verification (every pinned file:line must really say what
  the note claims — this reviewer's distinctive duty).
- Not here: scope-authority doctrine in its impl-review form (the note IS
  the thing being judged for scope), fix law.

### Job 6 — Slice-note fix
- As job 3 (fix core + doc-altitude fix duty) with: this note as primary
  target (the EDITABLE header line; fences are down), need_rethink for cross-document contradictions
  (finding + artifact, no proposed direction), deferred debt list. No slice-table duty unless a finding moved the table
  (then the same `slices` rule). No complete-suite duty.

### Job 7 — Implementation
- Purpose: working code + tests for one slice, cut into reviewable units.
- Inputs: note, current skeleton, amendments, workspace.
- Own law: IMPLEMENTATION RULES — the driver meters reviewable lines live
  (coherent close asked at soft, hard stop at hard; per-run variables
  defaulting to 500/750), implementation_cut semantics, and focused checks
  only (the complete suite belongs to job 12) — the
  shared REUSE GATE, and need_rethink for design contradictions.
- Output: files_changed, implementation_cut when cutting,
  slices when re-planning.
- Not here: two-register (document form), doc altitude (document discipline),
  any due diligence (the current corpus already agrees), review/fix law, severity,
  adjudications, deferred debt.

### Job 8 — Implementation review
- Purpose: does the code satisfy the note's pinned contracts under the
  CURRENT skeleton?
- Inputs: note, current skeleton, amendments, adjudications, deferred debt.
- Own law: judgment core, report-only, exhaustive pass, verification boundary
  (focused checks only; never the full suite), **scope authority** (GOAL >
  current SKELETON > this note; code following a design amendment over its
  stale note is NOT a violation — this doctrine exists FOR this job and job
  9), code-level machinery challenge, test-pinning check (each pinned
  contract has its named test).
- Not here: doc altitude, two-register, citation-verification duty in its
  note form, fix law.

### Job 9 — Implementation fix
- Fix core + code specifics: focused checks, scope
  authority (as job 8), direct evidence-backed rejection, need_rethink. No doc-altitude tail; a
  `prevention` edit lands where the misreading lives (comment or doc).

### Job 10 — Delta review (three unit routes; document law / implementation law)
- Purpose: the CURRENT WORK TREE against the required
  `delta_base_revision`, and its direct effects, nothing else. The comparison
  includes changes after that base whether they are committed, staged,
  unstaged, or newly created; HEAD is not the baseline. A normal fix supplies
  its unit base, and a Brainstorming seal supplies the pre-session commit.
- Own law: NONE of its own — a review is a review (decision 33): the
  identical shared body (verification boundary, evidence, judgment core,
  hunter reuse gate, target-type units), differing from a full round only
  in the TASK/STANDARD scope lines. The DELTA CHECK block and the
  fix-claims coverage duty are retired.
- Flavor difference is exactly the target-type law: doc deltas mount the
  doc-altitude review unit; impl deltas mount scope authority.
- Not here: re-judging the whole artifact (the STANDARD line says so), fix
  law. Eligible findings enter the same driver-owned rating gate as findings
  from a full review before any fixer is queued.

### Job 11 — Drift rating (reclassify)
- Purpose: one calibrated two-axis measurement of one finding.
- Inputs: the finding (summary, plain, example), the artifact, who builds on
  it, read roots.
- Own law: the rater briefing (axes, builder's return path, self-revelation,
  no inflation/deflation) and nothing more.
- Not here: EVERYTHING else. No amendments (it is neither author, fixer, nor
  reviewer), no reuse gate, no severity battery (it does not choose P-levels),
  no adjudications, no consultation, no two-register. The current capture is
  56–68% text this job cannot act on — the strongest evidence in the corpus
  that sharing defaults to oversupply.

### Job 12 — Full-suite checkpoint
- Purpose: at the existing scheduled boundary, have one fresh agent identify
  and execute the repository's official complete suite on the current work
  tree. The cadence remains every four completed logical slices and milestone
  close; only the final implementation part can trigger, parts count as their
  one logical slice, and documentation never triggers it. When the fourth-slice
  and final boundaries coincide, one `milestone_final` call wins; a plan wipe
  invalidates checkpoints after its boundary together with the unwound work.
  Only an unchanged `passed`/`no_suite` attempt whose owning slice subsequently
  closes becomes the next cadence anchor; re-implemented slices count anew.
- Charge: `suite_checkpoint@workspace` × `agent_call` × `code`, staffed on the
  existing `implement` seat 1.
- Inputs: workspace, checkpoint reason, and any ordered operator-configured
  commands. When no commands are supplied, the agent discovers the official
  suite from repository-owned evidence; it must distinguish that from a repo
  that genuinely has no suite. With configured commands, `no_suite` is invalid
  and the returned command plan must equal them exactly and in order: operator
  configuration defines the complete gate for that run. Without it, repository
  evidence establishes completeness.
- Own law: report-only and work-tree read-only; run the ordered commands at
  most once each, non-interactively, from the workspace root, stopping at the
  first failure. Report the full plan, the authority proving it complete, the
  attempted exit results, and concise output evidence. A failure carries one
  complete actionable `failure_account`, preserved verbatim in the synthetic
  P1 finding. It cannot be deferred or reclassified; after its ordinary
  fix/delta/review cycle this same job reruns on the
  corrected work tree; no fixer or implementer executes the complete suite.
  A fixer's rejection cannot satisfy the gate: only a fresh unchanged
  `passed`/`no_suite` attempt permits seal.
  Staffing reuses the existing `implement` seat 1 — the prompt, not a new role,
  makes this call report-only. The driver snapshots governed bytes, index, and
  HEAD for every status; any mutation invalidates the reply and is restored
  before failure routing. Commands/evidence live only on the attempt event.
  The contextual validator enforces configured-plan equality, forbids
  configured `no_suite`, and checks that results are the full passing plan or
  the exact failing prefix. Configured calls identify `operator_config`;
  discovery/no-suite calls supply non-empty `{path,basis}` evidence whose
  workspace-relative paths must exist. A later checkpoint resolves afresh.
- Output: `passed`, `failed`, `no_suite`, or `blocked`, with the fields required
  by that state. This remains a bare technical kind with no craft law, while
  still answering the three universal explanatory QUESTIONS mounted by the
  shared header.
- Not here: implementation craft law, reviews, fixes, `suite_command` discovery
  state, or command correction/adoption.

Legacy discovered/corrected commands and suite-repair flags remain display-only.
On resume, interrupted or accepted fixer work completes recovery plus its delta
and full reviews; only a clean pre-seal boundary converts to one fresh checkpoint.
Explicit operator-configured commands remain authoritative.

## 3. The genuinely universal core — two items, nothing more

1. **Envelope**: exactly one JSON object, no prose, echo the kind, with the
   kind's QUESTIONS entries in EVERY reply where that kind defines or mounts
   a battery. There is no ACCESS block and no
   secrets line: read grants and edit orientation live in the header's
   WORKSPACE plus the ecosystem map's per-root lines.
2. **Process authority, one bullet**: ignore agent instruction files and
   the entire .orchestrator/ directory — they do not govern the run and
   are not yours to edit. (Blocked semantics live in the common contract
   fields: `blocked_reason` explains what stops you; nothing more is said.)

Everything else in section 2 is job text.

## 4. Why the shared-block approach manufactures oversupply

The suspicion is correct, and the mechanism is visible in the corpus: a block
written once for the UNION of its audiences necessarily carries every
audience's clause to every audience.

- The amendments frame says BOTH "for authors and fixers these bind like the
  TASK itself" AND "for report-only reviewers, a violation … is a finding" —
  to everyone, including a rater who is neither. Per job, each file needs only
  its own sentence.
- The judgment rubric ends "A reviewer reports only exceeds_baseline=true; a
  fixer independently uses true for fixed/blocked and false for either
  rejection" — a dual-audience sentence baked into a shared block; the
  reviewer needs half, the fixer the other half.
- Process authority ships a fix-only clause to all 12 jobs (§3.3).
- The author output contract enumerated all kinds (~80% dead text for the
  receiver) — union-by-inertia at the contract level.
- `adapted-kinds/shared.json` faithfully inherits this: correct as a record
  of today, wrong as the design. A shared unit is where a per-job clause
  hides and gets "duplicated by error" into jobs that never earned it.

## 5. Consequence for the router

- **The routing key is the job**: kind + unit type (skeleton / slice_doc /
  slice_impl), with material and executor as further axes (see §6). Twelve
  milestone cells, not seven kinds with conditional blocks; merge repair and
  the session turns remain technical/executor routes beside that grid.
- **Storage deduplicates, the wire does not**: kind files reference shared
  units by id and the router answers FULLY ASSEMBLED prompts — consumers
  never stitch generic blocks themselves; they substitute variables and
  honor the charge's optional units. (Final model; supersedes the earlier
  "every cell self-contained on disk" cut of this analysis.)
- **Sharing needs a high bar**: identical full text AND identical audience
  meaning — otherwise per-audience variants (the altitude and reuse-gate
  families are the precedent), kept aligned by authoring-time lint.
- **Consistency between cells is an authoring-time concern**: passages meant
  to be identical across jobs (e.g. the judgment core in jobs 2/5/8/10) are
  kept aligned by a lint/diff check over the stored documents, not by a
  runtime ref that forces one text on divergent audiences. When two jobs'
  needs diverge, the texts diverge freely — that is the point of the grid.
- `adapted-kinds/` is the SEED CORPUS — the target text `goal.md` binds.
  It began as a faithful record of the old system and was pruned into the
  target through the decisions recorded in its README.

## 6. The composition model — job × executor × material (decided 2026-08-23)

**Brainstorming is not a job; it is an EXECUTOR.** The task-executor
catalogue already says so: `agent_call` and `brainstorming` are two ways of
staffing the same steps. Any call's prompt is composed mechanically from
three orthogonal axes plus the run's live services — nobody hand-picks
blocks per prompt:

1. **JOB** (the operation: draft_document, implement, review, fix, rate…)
   supplies the craft law, the output contract, and the QUESTIONS battery.
   The milestone jobs of §1 are these generic jobs plus milestone payloads.
2. **EXECUTOR** (one agent call, or a multi-seat session) supplies only the
   execution mechanics — for sessions: chat, the WORK AREA git
   law, TURN, ROLE, envelopes — decomposed per seat: the job's AUTHOR law
   rides with the sole editing seat (the Initial Position), its
   JUDGE law with the read-only Contrary seat, and its UNDERSTANDING LENSES (reuse
   gate in hunter voice, altitude, the charge's craft rules) with the
   read-only questioner (Dante) — who carries no authoring law. Contrary and
   Dante leave files, the index, and HEAD unchanged.
3. **MATERIAL** (the substance: code, business plan, legal contract…) is a
   flat axis — no sub-classification: what looks like a sub-material is the
   job kind, the other coordinate. Resolution reuses staffing's precedence,
   not its admission/catalogue semantics: start with the job's complete base
   cell, then apply the exact override for the non-empty material id when
   present. An absent override is identity, not
   an error or a fallback event. The milestone ships the resolver and a
   synthetic `code`-override test but no real override or material catalogue;
   `code`, `business_plan`, and any other id therefore receive the same base
   today. Adding a future override changes stored data only.
   New charges require a non-empty id; a persisted pre-router charge with no
   material reads as `code` at dispatch and therefore receives the base today.
4. **Run services** (line metering, amendments,
   adjudications…) are drop-if-absent variables: a charge outside a
   milestone simply lacks them and the units fall away — the corpus
   already degrades this way. A job's OWN payloads (a fix's queued
   findings, a rating's finding) are required: a charge without them is
   invalid, never rendered thinner.

The charge triple (job, executor, material) comes frozen from the milestone
order, or is chosen in the panel for standalone charges ("brainstorm code"
= implement × brainstorming × code; "draft a business plan" =
draft_document × brainstorming × business_plan). Both material ids resolve to
the complete base today; their prompts diverge only when their stored override
exists. The same law governs the
content wherever it is produced: a session that implements carries
IMPLEMENTATION RULES; one that redrafts a skeleton carries the drafter's
form and gates. The charge job's QUESTIONS battery — where the job defines one — mounts
on EVERY lead turn beside the session battery; a `ready` declares nothing
beyond readiness — the outcome, plan table included, is read from the
committed repo, never from reply fields. The production-effect call is
retired: with the work already committed in the repo, there is nothing
left for an agent to apply.

**Versioning is a platform capability (operator decision, 2026-08-23).**
The milestone and every task and session use the SAME project git repository
as their editable work tree — no session copies, no snapshots. Chat and
run-state storage are not work areas. That is
what carries multi-document change: each completed editing turn is a
commit; "accepted revision" is the repo's commit hash (new and
modified documents become the same case — diff hunks); seats verify chat
claims against the diff; any turn may carry `ready: true`, anchored to the
current commit — a new commit voids earlier readies, and when every seat's
ready anchors to the same commit the session closes (a ready declares
nothing else — the work is already committed where it lives, the driver
derives the outcome from git); at close there is NOTHING to apply. Every
delta review compares the current work tree with an explicit base revision;
the session seal uses the pre-session commit, so committed turns remain
visible without preserving dirty files. When any plan change computes a wipe
boundary — deleted built slices or a forbidden historical insertion/reorder —
the driver first anchors one accepted-change range: for Brainstorming,
`source_base_revision` is `pre_session_commit` and `accepted_revision` is the
ready commit. Before a direct contract that may return `slices`, the driver
checkpoints the current work tree; that isolated pre-call HEAD and the driver's
commit of an accepted plan-changing result become the two revisions. Git then rewinds to the earliest candidate
boundary and merge_repair ALWAYS re-lands exactly
`source_base_revision..accepted_revision` on the new base. Its charge uses
`agent_call` and inherits the accepted source charge's material. The final
delta seal compares the resulting work tree with `source_base_revision`; for a
session that is `pre_session_commit`. The chat carries the WHY,
git carries the LETTER. One minimal VCS seam (snapshot/commit, diff, log,
restore) with two backends: the system git where it exists, and an
embedded pure-Python git (Dulwich — standard on-disk format, so both
backends produce the same repos) for agent_99 deployments with no git
(law firms, medical offices, schools). **The router milestone is built
assuming git exists for ALL tasks; Dulwich is introduced afterwards.**
Binary documents (docx/pdf) keep versioning and rollback even where
textual diffs say little.
