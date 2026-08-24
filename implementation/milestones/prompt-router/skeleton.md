# Milestone skeleton — Prompt Router and session overhaul

Mandate: the frozen launch snapshot `implementation/milestones/prompt-router/goal.md`.
This is a thin planning contract. Slice notes will pin each bounded surface just
before implementation.

## Register 1 — Intent (lay language)

### Goal restatement

The operator and every orchestrated worker should receive one prompt assembled
for the work actually being done, instead of a large prompt assembled by many
call sites. A named, editable prompt set supplies the wording; one router selects
the work instructions, discussion-role instructions, questions, and reply
contract. A completed edit is visible to the next call without versions,
snapshots, migrations, or coordination ceremonies.

The same project repository becomes the place where a Brainstorming session does
its work. The author can fix all documents or code needed by the charge; the
other seats inspect without editing. Agreement means that the discussion seats
are ready on the same repository revision. There is no separate work area,
proposal/vote phase, or later application call.

Plan changes remain recoverable. If accepted work removes built slices or
rewrites their historical order, the orchestrator returns to the earliest safe
boundary, re-lands the accepted change, and requeues only the work whose commits
were unwound. Complete-suite verification becomes a read-only agent job at the
existing cadence, with fresh discovery and evidence on each attempt.

### Ownership and boundaries

Owned here: prompt-set storage and resolution, assembled prompt service,
registered reply validation, run prompt-set binding and operator selection,
cutover of milestone and Brainstorming prompt consumers, repository-backed
session agreement, plan rewind/reconciliation, the complete-suite checkpoint,
compatibility reads, prompt traces, and conformance tests.

Not owned here:

- prompt versions, snapshots, caches, edit notifications, consistency events,
  or prompt migration bookkeeping;
- a material catalogue or real material-specific prompt layer;
- a new staffing role, model/effort routing, rigor rule, or permission system;
- an embedded Git implementation; every task is assumed to have system Git;
- Brainstorming execution for reviews, fixes, ratings, or suite checkpoints;
- deployment into live runs: drivers are drained before activation.

The panel exposes the operator's charge choices, not router internals. Fixer
consultations remain the one worker-owned dialogue outside the served prompt
route. Prompt text is an authoring responsibility; code validates registered
reply obligations, not whether trusted prose means what its author intended.

### Planning-context disposition

**Adopts** the adapted prompt corpus and its recorded decisions as the target
prompt set, as the mandate directs. **Uses** the prompt analysis and captured
current prompts only as rationale and historical evidence. **Revises** and
**Rejects** none of the binding corpus decisions.

### Guarantee posture

- **Strict per router-served physical call:** before dispatch, resolution selects
  one complete readable rung (named set, stored `default`, or in-code seed),
  rejects a charge missing a required job payload, assembles the applicable
  variables, and records the exact prompt. Before any returned status is
  accepted, exactly the registered mounted or appended sections and every
  mounted question answer are validated; stored unregistered sections are
  deliberately unenforced. The fixer consultation is the sole unserved
  exception; its trace is the transcript at the driver-provided scratch path,
  not a router prompt trace.
- **Strict at the declared read-only boundaries:** a suite-checkpoint mutation
  of governed work-tree bytes, index, or HEAD invalidates its status and the
  driver restores that pre-call state. A read-only discussion seat must leave
  the same governed Git state unchanged; detected mutation is rejected or
  restored before another turn. Editing calls may make the edits their charge
  permits. Before a direct call that may return `slices`, the driver checkpoints
  that governed state; a changed plan without a matching file delta is invalid.
  A failed checkpoint's preserved P1 cannot be deferred or reclassified; its
  fixer may dispute the diagnosis, but no seal passes until a fresh unchanged
  attempt returns `passed` or `no_suite`.
- **Strict repository transitions:** explicit revisions anchor committed editing
  turns, readiness, delta review, rewind boundaries, accepted ranges, and
  reconciliation. A no-change editing turn creates no commit; its readiness
  anchors the unchanged HEAD and earlier readiness remains valid. Pre-call
  snapshots of governed work-tree bytes, index, and HEAD anchor checkpoint
  integrity. These mechanisms preserve and expose that governed Git state; the
  review seal remains the judgment of its content. A reconciliation that cannot
  complete blocks to the operator before review or further execution.
- **Best-effort edit visibility, strict whole-set fallback:** each dispatch reads
  afresh, without a point-in-time snapshot. Reads racing one or more prompt-file
  saves may observe any combination of files from the same rung. A complete
  readable combination may be assembled even if its contents never coexisted on
  disk; an unreadable combination makes that whole rung fall to the next
  complete one. A rung fallback is always returned to the router caller as a
  note beside the answer; ordinary material inheritance remains note-free. A
  dispatched prompt is fixed. Across physical calls—even within one task,
  session, or milestone run—there is zero prompt consistency guarantee: every
  call resolves afresh and may receive arbitrarily different content, with no
  snapshot, version, retry, reconciliation, notification, migration,
  monotonicity, or convergence duty.

### Reuse Posture

Operators and workers are exposed on every prompt dispatch; the realistic harm
is wrong or oversized instructions, rejected outputs, lost review time, and
incorrect recovery work. Git makes repository bytes reversible, but spent calls
and discarded runs are not. The mandate is the independent authority. Checked
and reused: the binding seed corpus, the staffing store/fresh-resolution pattern,
the existing task charge fields, worker-output validators, immutable prompt
traces, Git snapshot/restore/commit primitives, review seals, and suite cadence.
The cheapest sufficient option is one prompt router and extensions of those
seams; documentation or further string-builder patches cannot provide served
assembly, registered validation, repository-backed sessions, or read-only suite
jobs. The justified machinery is consumed by the driver, Brainstorming
coordinator, service/panel, and worker runner. Build and review cost is material
but bounded below; operation adds a fresh document read, while versions,
migrations, caches, daemons, and duplicate stores add no lifecycle cost.

### Planned slices

The table order is the delivery order. The mandate has already settled the
design, so both producer choices use one focused agent call; a multi-seat design
discussion would add no missing decision. The material column is empty because
this run supplied no material vocabulary. The shown role configurations belong
to this run's existing producer-order contract; they are not the target prompt
schema, whose Slice 5 cutover returns executor ids only.

| id | slice | draft_slice_note producer | implement producer | material | intent |
|---:|---|---|---|---|---|
| 1 | Prompt-set store and seed fallback | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Store the shipped corpus as `default`; validate a whole set and resolve named set, stored default, or in-code seed without mixing them, reading afresh for each call and reporting fallback beside the answer. |
| 2 | Charge resolver and assembled JSON | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Resolve a complete canonical job with executor/seat context and material layering into one assembled JSON prompt plus declared substitutions; required job payloads fail, absent run services drop, and a synthetic override proves data-only extension. |
| 3 | Registered contracts and QUESTIONS | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Bind registered section ids to their validators, serve stored unknown sections without enforcing them, refuse unregistered consumer additions, and validate the exact mounted question answers and per-job reply shape for every status. |
| 4 | Prompt-set binding and operator surface | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Let the operator choose a named prompt set at launch, persist that run binding, expose charge choices without router machinery, and read an absent legacy binding as `default` without rewriting history. |
| 5 | Milestone author-call cutover | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Serve skeleton, slice-note, and implementation calls through the router with their own law, variables, questions, and contracts; keep line metering while removing planner configuration and implementer suite reporting from the target protocol. |
| 6 | Milestone judgment-call cutover | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Serve full review, explicit-base delta review, fixing, and rating through their canonical jobs; keep consultations as the declared exception, scope adjudications to the unit, and adopt the reduced rethink report. |
| 7 | Session charge and seat composition | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Admit Brainstorming only for the two producer steps and orchestrator-opened rethink charges; compose author, contrary, and questioner turns from the same tagged job law and seat coordinates, with every applicable QUESTIONS set mounted. |
| 8 | Repository-backed session turns | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Run sessions in the project repository: checkpoint before opening, let only the author edit, commit each completed author turn in the driver, and reject or restore any change by a read-only seat. |
| 9 | Anchored readiness and session seal | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Close when all discussion seats are ready on one current commit, invalidate earlier readiness after a new commit, derive delivery from Git, review from the pre-session commit, and retire proposal, vote, and production-application calls. |
| 10 | Plan identity and wipe boundary | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Compare plans by slice id, compute one earliest historical boundary for deletions or forbidden positional change, unwind everything after it, invalidate affected closures/checkpoints, and requeue only unwound slices. |
| 11 | Accepted-range reconciliation | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Anchor accepted plan-changing work from sessions and direct calls, reject a changed plan without a matching delta, and always use the bare merge-repair job to re-land that exact range after a wipe before the normal review seal. |
| 12 | Read-only suite checkpoint | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Add the one direct suite-checkpoint job: honour configured commands exactly or discover the official suite with repository evidence, run each at most once, validate the attempted prefix, and invalidate and restore any workspace mutation. |
| 13 | Checkpoint cadence, failure, and resume | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Schedule one checkpoint every four completed logical slices and at final close, route a full failure account through a non-deferrable P1 repair cycle, rerun fresh, invalidate unwound anchors, and resume legacy state without feeding old discovered commands into routing. |
| 14 | Legacy retirement and end-to-end conformance | `agent_call` (`role=draft`) | `agent_call` (`role=implement`) |  | Remove hand-built prompt and retired session/suite/write-fence paths, replace substring assertions with golden assembled renders, prove every physical call is served and traced, preserve declared compatibility, and require drained drivers before activation. |

## Register 2 — Pinned facts (hard register)

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Routing identity | The routing key is `(job, executor, material)`; callers pass one canonical `kind@unit` job id whole, and session dispatch also supplies `(role, lead)`. The complete route inventory is the adopted kind×unit grid plus `rethink@doc`, `rethink@impl`, `merge_repair@workspace`, `discussion_turn`, and `questioner_turn`. | `goal.md:24-59`; `implementation/brainstorming/prompt-router/prompt-content-milestone.md:37-47` | touch one router and call adapters; do-not-pass raw variant options or hand-pick prompt units |
| Prompt-set storage and freshness | `prompt_sets/<set>/{shared,milestone,brainstorming}/…`; one JSON per kind and shared units by id. Resolve named set → stored `default` → in-code seed. A malformed file or missing canonical route makes the whole set unreadable; never mix sets. Read fresh at each physical call; keep only the exact call trace. | `goal.md:60-85`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:10-32` | touch the service-home store and resolver; do-not-add versions, snapshots, caches, migrations, notifications, or edit events |
| Material and variables | Every non-empty material id is admissible and layers exact override over a complete base; no match is silent inheritance. Ship no real override or catalogue, only the generic seam and synthetic `code` fixture. Required job payloads fail; absent run-service variables drop their units. | `goal.md:44-59,318-322` | touch resolution and fixtures; do-not-copy staffing admission semantics or invent unknown-material failure |
| Served prompt boundary | The router returns assembled JSON with variable declarations. Consumers substitute values and may append only registered contract sections; consumers never read prompt files. Headers/routing expose `KIND` and `WORKSPACE`, never an agent name; replies echo the plain kind. Fallback information is beside, never inside, prompt text. | `goal.md:17-22,85-91,350-355` | touch service API and all prompt consumers; do-not-leave a direct file or string-builder path |
| Contract registry | Each section id selects prose and, for the registered subset, its code validator. Validate exactly registered assembled ids. Stored unknown ids are served and ignored; consumer-appended unknown ids are refused. Stored prose never contains validation code. | `goal.md:93-109` | touch the section registry and worker-output validation; do-not-build a second resolution path or content-policing engine |
| Target output vocabulary | Runtime output uses `questions`, one non-empty answer per mounted id, each at most 300 characters, on every status where a battery mounts. The old runtime `battery` retires. Target `need_rethink` is only `finding` plus `target_path`; producer plans return executor ids, not configuration. This skeleton's Question Battery is launch-time planning evidence, not the target runtime field. | `goal.md:116-145`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:456-471` | touch target prompt contracts and validators; do-not-retain request/result_mode/max_rounds or implementer/fixer `suite_command` fields |
| Prompt corpus | The adapted corpus and its README decisions are the shipped `default`: per-job contracts, no ACCESS block, no secrets line, one PROCESS AUTHORITY bullet, and no all-kinds mega contract. | `goal.md:7-11,111-132,181-183`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:1-7` | touch seed conversion and golden renders; do-not-regenerate target prose from legacy builders |
| Session eligibility and roles | Brainstorming executes only planned `draft_slice_note`/`implement` producer steps and orchestrator-opened `rethink@doc`/`rethink@impl`; review, fix, rating, and suite triples are invalid and use direct `agent_call`. Initial Position is the sole editor; Contrary Position and the questioner are read-only. | `goal.md:323-332`; `goal.md:185-197` | touch session admission and dispatch; do-not-add session accounting or a prompt route for fixer consultations |
| Session repository and close | The project repository is the only work area. The driver commits before open and after an editing turn with a delta; an empty turn creates no commit. Any discussion seat may return `ready`, anchored to the current post-turn HEAD; only a new commit voids old readies; all discussion seats ready on one revision closes. The questioner never readies. Close applies nothing; delta review compares the current work tree with `pre_session_commit`. | `goal.md:198-226` | touch Brainstorming state, turns, and seal handoff; do-not-copy/snapshot a session work area, retain proposal/vote phases, or call `production_effect` |
| Plan rewind and repair | Slice id is identity. Deletion or forbidden insertion/reorder chooses the earliest old-plan boundary, rewinds to the prior surviving slice or milestone-start commit, invalidates later closures/checkpoint anchors, and requeues every unwound slice. Every wipe re-lands exactly `source_base_revision..accepted_revision` on `wipe_boundary` through `merge_repair`; the accepted range wins and the review seal judges the result. An incompletable reconciliation blocks to the operator. | `goal.md:228-282` | touch plan comparison, state reset, and Git reconciliation; do-not-renumber intact slices, verify paths separately, or use an auto-merge lottery |
| Suite checkpoint | Exactly `suite_checkpoint@workspace × agent_call × code`, staffed from existing `implement` seat 1. It runs after clean reviews every four completed logical slices and at milestone close; a coincident boundary is one `milestone_final` call. Configured commands are exact; otherwise existing `{path,basis}` evidence supports discovery or `no_suite`. Mutation of governed bytes, index, or HEAD invalidates and restores every status. A failed attempt preserves its full account as a non-deferable, non-reclassifiable P1, and no seal passes until a fresh unchanged attempt returns `passed` or `no_suite`. | `goal.md:149-180` | touch checkpoint contract, cadence, failure routing, and resume; do-not-run the complete suite in implement/fix/review or persist discovered command authority |
| Compatibility | Missing run prompt-set binding reads `default`; a persisted charge without material reads `code`; new charges require a non-empty material. Historical suite-command state is display-only. Resume completes an interrupted/accepted fixer stage before a fresh checkpoint; compatibility is read-time defaulting, never history rewrite. | `goal.md:336-346` | touch dispatch and resume reads; do-not-migrate state, rewrite events, or block resume solely for age |
| Guarantee posture | Every router-served call strictly resolves one whole rung, rejects missing required job payloads, records its exact prompt, and validates only registered mounted/appended sections and mounted question answers. The unserved fixer consultation is traced by its scratch transcript. Suite-checkpoint mutation of governed work-tree bytes, index, or HEAD rejects and restores; a read-only discussion seat keeps that governed Git state unchanged through rejection or restoration. A failed checkpoint cannot be bypassed by deferral or reclassification and gates every seal on a fresh unchanged `passed` or `no_suite`. Editing calls may edit within their charge, while direct plan-returning calls retain the checkpoint and matching-delta rules. Git revisions strictly anchor committed session and recovery transitions; an empty editing turn keeps HEAD and existing readiness. The review seal judges content, and incompletable reconciliation blocks to the operator. A dispatch racing one or more prompt-file saves may observe any combination of files from the same rung; a complete readable combination may be assembled even if its contents never coexisted on disk. An unreadable combination makes that whole rung fall, every rung fallback reaches the router caller as a note beside the answer, and ordinary material inheritance stays note-free. A dispatched prompt does not change; cross-call prompt behavior is exactly the single declaration in Register 1. | `goal.md:44-72,93-109,149-180,187-251,329-332,350-355`; `orchestrator/runners.py:2735-2775`; `orchestrator/gitops.py:742-824,944-981` | touch enforcing seams and focused tests; do-not-strengthen live prompt editing into bookkeeping or convergence machinery |
| Retirements and untouched systems | Retire prompt builders/scrubber, old battery plumbing, old rethink fields, milestone-wide adjudication injection, accepted-session amendments, closure/application paths, design-document write fences, byte-identity guarantees, substring prompt tests, and implementer/fixer suite reporting. Staffing, rigor, and the model router remain untouched; Dulwich is later. | `goal.md:294-335` | touch only replacement/cutover surfaces; do-not-preserve parallel legacy lanes or expand into staffing, model routing, or embedded Git |

## Question Battery

| question | answer | evidence |
|---|---|---|
| victim | Operators, milestone workers, and downstream repositories are affected. Today every author/reviewer/fixer call consumes hand-built strings and Brainstorming adds a separate application call; the realistic exposure is every physical call and every accepted session. Wrong instructions, rejected replies, discarded work, and excess model cost are observable. Git can reverse bytes, but spent calls and failed runs are irreversible. The frozen mandate independently requires replacement. | `goal.md:15-22,60-72,185-226`; `orchestrator/driver.py:7664-7712,9980-10033,12089-12108`; `orchestrator/brainstorming_execution.py:649-681` |
| machinery | New machinery is limited to the prompt-set store/router, registered section validators, a run binding/operator selector, repository-backed session agreement and rewind/reconciliation, and the suite-checkpoint job. Each directly serves an authorised outcome above. It must exist because current consumers call text builders, validate one union contract, retain single-target revisions/ballots, and execute suites outside a worker job. | `goal.md:13-109,185-310`; `orchestrator/prompts.py:49-121,1396-1431`; `orchestrator/brainstorming.py:1845-1869`; `orchestrator/driver.py:11379-11600` |
| consumers | Verified consumers are the milestone driver’s author, fix, delta, rating, and full-review dispatches; the Brainstorming lifecycle/coordinator and participant runner; the run service and panel that bind operator choices; and the runner that records the exact prompt before launching a worker. | `orchestrator/driver.py:7664-7712,9980-10033,11112-11129,11716-11742,12089-12108`; `orchestrator/brainstorming_lifecycle.py:2962-3000`; `orchestrator/brainstorming_execution.py:577-680`; `orchestrator/service.py:2301-2471`; `orchestrator/static/panel.html:649-657,5106-5115`; `orchestrator/runners.py:1754-1767` |
| cheaper_alternative | Cheapest sufficient is conversion of the binding corpus plus extension of existing document-resolution, contract, task-charge, prompt-trace, Git, and cadence seams. Doing nothing or further parameterising `prompts.py` is cheaper initially but cannot meet served-only JSON assembly, whole-set fallback, registered extensions, one-repository sessions, or agent-owned suite evidence; documentation alone enforces none of them. | `goal.md:15-22,60-109,185-251`; `orchestrator/staffing.py:648-681,1697-1739,1975-1994`; `orchestrator/tasks.py:693-725`; `orchestrator/runners.py:2735-2775` |
| cost | Build and review cost is fourteen bounded slices plus migration of broad tests and prompt goldens; there is no data migration, prompt history, daemon, or new operational service. Runtime adds a fresh set read per call and existing trace/Git operations; maintenance replaces duplicated builders and ceremonies with one route and one registry. Omission keeps per-call drift and recovery complexity. Fallback and Git make rollout reversible, while spent calls remain sunk. | `goal.md:60-72,294-346`; `orchestrator/prompts.py:1-13`; `orchestrator/gitops.py:1-21`; this skeleton, Planned slices |
| threat_model | Untrusted actors are model workers controlling reply JSON and, on editing calls, repository mutations; their fields and bytes are validated, traced, committed, or restored. A prompt set may be malformed and therefore falls as one unit. Trusted inputs are operator-authored prompt text, operator-configured suite commands, product code that registers sections, and compile-time configuration; the design deliberately does not police their semantics or invent defenses around them. | `goal.md:79-85,95-109,171-180,187-226`; `orchestrator/contracts.py:898-1059`; `orchestrator/gitops.py:742-824,944-981` |
| enforceability | No asserted guarantee lacks a mechanism. Fresh validated fallback reuses the staffing loader/resolver pattern; reply obligations extend the closed worker validator; exact traces use exclusive-create storage before dispatch; Git already exposes commits, HEAD/index/work-tree snapshots, hard restore, and seal boundaries; existing state enforces append-only transitions and cadence. The slices connect these mechanisms and pin their focused/golden tests; the design makes no semantic guarantee about trusted prose. | `orchestrator/staffing.py:648-681,1697-1739,1975-1994`; `orchestrator/contracts.py:898-1059`; `orchestrator/runners.py:1663-1676,1754-1767,2735-2775`; `orchestrator/gitops.py:730-824,944-981,1109-1117`; `orchestrator/state.py:1-25,49-77`; `orchestrator/driver.py:1304-1372` |
