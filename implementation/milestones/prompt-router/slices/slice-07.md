# Slice 07 — Session charge and seat composition

## Register 1 — INTENT (lay language)

### What this slice builds

This slice gives every milestone-owned Brainstorming turn one canonical routed
charge. A session may exist for a planned slice-note producer, a planned
implementation producer, or one `rethink` opened by the orchestrator from a
validated finding. Reviews, fixes, ratings, checkpoints, arbitrary panel
requests, and special design ceremonies are not session jobs.

The session keeps the work identity that must survive its child process: job,
material, prompt set, target type, and task coordinates. Each physical seat
attempt then resolves the selected prompt set afresh, mounts the law for that
seat, renders the current authority and session sources, binds the served reply
sections and questions, and sends exactly that rendered text. A correction is
another physical attempt and crosses the same fresh boundary.

Initial Position is the sole author seat. Contrary Position receives the judge
stance. Dante receives the questioner voice and returns `questioner_turn`, not a
discussion reply disguised as one. Producer leads also receive the originating
job's question battery; `rethink` mounts its complete finding once as opaque
JSON from the canonical charge and borrows no producer battery.

### Ownership and boundary

Owned here are milestone session eligibility, the persisted canonical charge,
the mapping from the fixed three-seat roster to router coordinates, fresh
per-attempt prompt preparation, exact prompt traces, and validation against the
sections, questions, and project extensions served in that same attempt.

This slice does not change where turns edit, how their repository effects are
accepted, or how a session closes. Slice 08 moves turns into the project
repository and owns commits and read-only restoration. Slice 09 owns revision-
anchored readiness, removal of proposal/vote closure, and closing without an
application call. Slices 10–11 own plan-change consequences and reconciliation.

### Guarantee posture

- **Strict admission.** Milestone sessions admit exactly
  `draft_slice_note@slice_doc`, `implement@slice_impl`, and `rethink`. The two
  producer jobs must come from an already admitted planned producer task whose
  selected executor is Brainstorming. Only the orchestrator may open `rethink`
  from a validated `need_rethink` finding and target.
- **Strict charge identity.** Producer material and coordinates come from the
  admitted task. `rethink` keeps one job id and receives its material from the
  origin plus a separately derived `document` or `implementation` target type.
  No caller supplies raw variants, craft switches, or `rethink@...` ids.
- **Strict per physical attempt.** Prompt-set resolution, mutable operator
  authority, seat composition, binding, rendering, and validation are fresh for
  the initial attempt and its one ordinary contract correction. Provider input
  byte-equals the recorded prompt trace; fallback remains sidecar evidence.
- **Strict seat composition.** Initial Position maps to
  `(initial_position, lead=true)`, Contrary Position to
  `(contrary_position, lead=false)`, and Dante to
  `(common_sense, lead=false)`. The first two use `discussion_turn`; Dante uses
  `questioner_turn`. Every mounted question has one non-empty answer of at most
  300 characters. Only producer leads borrow the originating job battery.
- **Best-effort across calls.** A completed prompt edit is eligible for the next
  physical attempt. A dispatched prompt is fixed; there is no version,
  notification, cache, monotonicity, or convergence promise between attempts.

### Non-goals

- No session copy, work-area migration, Git commit, rollback, canonical-plan
  observation, or read-only mutation handling; Slice 08 owns these.
- No readiness ledger, HEAD agreement, close rule, proposal/vote retirement,
  production-effect retirement, or delivery derivation; Slice 09 owns these.
- No plan diff, wipe, requeue, checkpoint account, merge repair, or seal work.
- No prompt parser, prose inspection, semantic classifier, retry system,
  compatibility lane, authority cache, last-known-good copy, or recovery path.
- No model, effort, staffing, material-catalogue, or standalone Brainstorming
  redesign.

### Acceptance

The focused gate proves the three admitted jobs and three seat coordinates,
producer-only borrowed questions, one unbranched `rethink`, fresh prompt and
amendment reads on correction, exact traces, routed reply validation, Dante's
distinct envelope, fallback sidecars, and refusal of every other milestone
session job. Existing standalone sessions retain their product-neutral prompt
path until global retirement; they are not alternative milestone authority.

## Register 2 — PINNED FACTS (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Eligible milestone jobs | Exactly `draft_slice_note@slice_doc`, `implement@slice_impl`, and orchestrator-opened `rethink` | `skeleton.md`, canonical Slice 07 intent and Session eligibility row; `goal.md`, sections 3–4 | touch milestone task/rethink admission; do not add review, fix, rating, suite, calibration, or caller-defined jobs |
| Seat coordinates | Initial Position is author/lead; Contrary is read-only/non-lead; Dante is questioner/non-lead | `skeleton.md`, Session eligibility and roles; adapted `prompt_router.py` seat table | touch routed turn preparation; do not create another role selector |
| Rethink identity | One `rethink` job carries the complete finding once as opaque JSON plus target, material, ordinary context, and a driver-derived artifact type; no request framing or route variant | `skeleton.md`, Routing identity; `goal.md`, Target output vocabulary | touch origin validation, session charge, and one shared finding mount; do not retain `rethink@doc`, `rethink@impl`, `request`, `result_mode`, `max_rounds`, or `failure_gap` |
| Per-attempt boundary | Resolve, render, bind, validate, and trace afresh for every provider attempt, including contract correction; current mutable amendments are a complete replacement set | `skeleton.md`, Served prompt boundary and Guarantee posture; amendments A4 and A8 | touch one session-call adapter and execution seam; do not cache prompts or infer authority from provider history |
| Question composition | Session questions ride every seat; the originating job battery is added only to a producer lead; rethink borrows none | `goal.md`, QUESTIONS and Brainstorming overhaul; adapted prompt-set composition contract | touch router-backed binding; do not stitch question prose or ids in callers |
| Later ownership | Repository turns are Slice 08; readiness and no-apply close are Slice 09; plan consequences are Slices 10–11; activation/global retirement is Slice 14 | `skeleton.md`, canonical slice plan | do not implement later slices merely to make this intermediate cut final |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_session_call_cutover orchestrator.tests.test_prompt_sets orchestrator.tests.test_prompt_router orchestrator.tests.test_prompt_contracts orchestrator.tests.test_brainstorming_execution orchestrator.tests.test_brainstorming_coordination orchestrator.tests.test_judgment_call_cutover`

| observable claim | named check | pass condition |
|---|---|---|
| Only planned producers and rethink enter | `test_milestone_session_admission_is_closed` | The two producer jobs require an admitted Brainstorming order; one orchestrator rethink passes; other jobs and guarantee calibration do not open sessions. |
| Every seat is routed correctly | `test_session_charge_matrix_mounts_exact_seat_law` | The fixed roster resolves the expected kind, role, lead, material, and artifact type with no raw selector. |
| Questions and envelopes match the served prompt | `test_session_questions_and_envelopes_are_bound` | Producer lead gets job plus turn questions; Contrary gets turn questions; rethink gets no producer battery; Dante returns `questioner_turn`; ready is unavailable to Dante. |
| Every physical attempt is fresh and exactly traced | `test_session_correction_reloads_prompt_and_authority` | Editing the selected prompt and amendments between attempts affects only the next attempt; both replies use their own bound validator and both provider inputs equal their traces. |
| Downstream mechanics remain downstream | existing Brainstorming regressions | Ordinary lifecycle state still consumes accepted markdown while repository acceptance and closure remain explicitly assigned to Slices 08–09. |

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | Operators and session workers otherwise receive legacy hand-built prompts or mismatched reply rules, wasting calls and making the selected prompt set ineffective. | `skeleton.md`, Slice 07 intent and strict router boundary |
| machinery | One prepared-session-call adapter and one execution hook are required so prompt and validator come from the same fresh route. The existing router, renderer, registry, runner, trace, and correction loop are reused. | `orchestrator/author_calls.py`; `orchestrator/judgment_calls.py`; `orchestrator/prompt_router.py` |
| consumers_touched | Milestone producer admission, rethink attachment, ordinary session turns, automatic Dante turns, participant execution, prompt traces, and routed contracts. | `orchestrator/driver.py`; `orchestrator/brainstorming_tasks.py`; `orchestrator/brainstorming_milestone.py`; `orchestrator/brainstorming_coordination.py`; `orchestrator/brainstorming_lifecycle.py` |
| cheaper_alternative | Reusing the existing hand-built turn prompts cannot honor editable prompt sets or bind the served questions. A small adapter over the existing router is the cheapest sufficient option. | `orchestrator/brainstorming_coordination.py`; `orchestrator/prompt_router.py` |
| cost | A bounded adapter and consumer tests; no store, service, migration, daemon, or compatibility path. Omission can spend every session call under the wrong law. | Slice 07 Non-goals and Verification Contract |
| threat_model | Prompt prose, operator amendments, configured project law, and the fixed roster are trusted authority. Replies are structurally untrusted and validated. Malicious workers and arbitrary repository damage are not Slice 07 robustness requirements. | amendments A1, A4, A7, A8; `skeleton.md`, Ownership and boundaries |
| pinned_facts | The three jobs, three coordinates, one rethink identity, per-attempt freshness, and exact question composition are strict. | Pinned-Facts Table above |
| verification | A focused matrix covers routing, binding, freshness, traces, and closed admission without a Cartesian or lexical test suite. | Verification Contract above |
| enforceability | Job/seat identity is enforced by the existing route table; registered output and questions by the bound contract; prompt identity by the existing trace seam; mutable authority by one fresh structural read per attempt. | `orchestrator/prompt_router.py`; `orchestrator/prompt_contracts.py`; `orchestrator/runners.py`; amendment A4 |
