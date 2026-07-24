# Slice 08 — Milestone `need_rethink` adapter

## Register 1 — Intent

### What this slice builds

This slice lets a milestone worker pause on one focused design doubt and ask the
independent Brainstorming process to produce a small amendment or proposal.
The discussion keeps its own record and result; it is not disguised as another
milestone review.

If the discussion succeeds, an implementer or fixer continues the exact
conversation that asked for help. A reviewer instead takes a fresh look at the
result. If it fails, the milestone returns to its existing design-gap or
operator route. Asking for help never counts as completed work or approval.

### Ownership and boundary

This slice owns the bridge: it records which milestone call is waiting, starts
the independent discussion with the caller's existing working context, and
returns its result to the right milestone path.

Brainstorming remains the sole owner of its discussion, accepted target
versions, transcript, and result. The milestone remains the sole owner of unit
progress, findings, review, sealing, and escalation. A successful discussion
does not approve its own proposal.

If the proposal requires a sealed slice note to change, the milestone reuses
its narrow, independently reviewed correction path. The discussion itself
cannot edit sealed milestone documents or generated records. Its target is a
separate artifact.

### Guarantee posture

- **Strict:** a valid request is help-seeking, not work completion. Once the
  milestone records the discussion, it stays on the same work item and accepts
  only that discussion's retained result. A proposal cannot approve itself.
- **Optimistic:** existing durable state and locking decide which of two
  competing milestone actions wins; a stale action cannot apply the return
  twice.
- **Eventual:** the milestone may notice completion on its next check. Until
  then, the same work item remains visibly paused.
- **Best-effort:** discussion creation, provider delivery, and liveness are not
  exactly-once across an unacknowledged crash. Uncertain work is never promoted
  to a result.

### Dependencies and consumers

This slice depends on the discussion contracts, durable participant
conversations, lead-owned target history, transcript, closure, and standalone
lifecycle delivered by Slices 1–6. It also reuses the milestone's existing
one-shot design-correction lane. It needs no new visualization from Slice 7.

Its consumers are implementation, fixing, full review, change review, and final
seal review. The current project and work-area binding remains authoritative.

No Agent99, Life, LPC, Tutor, external repository, standalone API caller, or
milestone browser surface is changed.

### Acceptance

- A valid request pauses the current work without recording a completion,
  review judgment, fix, or seal.
- The discussion receives the current working context, the focused question,
  the source finding unchanged, a separate output target, and a finite round
  limit.
- A recorded active discussion survives process restart without changing the
  milestone's place. An unacknowledged creation advances nothing.
- Success returns the retained accepted proposal from the recorded discussion.
  Builders continue their original conversation; reviewers start afresh.
- A proposal that changes the builder's own sealed note uses the existing
  provisional correction, rollback, and independent change-review path. A
  rejected correction leaves neither the note change nor dependent work behind.
- Discussion failure uses the predeclared normal escalation unchanged.
  Lifecycle or provider faults remain operational faults.
- The motivating fixer flow produces a small amendment, resumes the same fixer,
  receives independent change review, and continues without reopening all
  milestone documentation.

The production adapter should remain compact. Total changes are expected to
exceed about 500 lines because the executable matrix must cover five originating
worker kinds, concurrent final reviews, restart attachment, both escalation
classes, and exact conversation continuation. Generated and mechanical changes
remain excluded.

### Non-goals

- No change to the independent discussion's public request, state, transcript,
  closure, result, API, or visualization.
- No new milestone phase or substitute for ordinary verification, review,
  sealing, correction, or escalation.
- No use by documentation drafters, classifiers, verification commands, or
  external products.
- No new page, route, launch form, notification, event feed, or push transport.
- No repository requirement or version-control meaning for the discussion
  target.
- No new identity, permission, sandbox, work-area, custody, idempotency,
  provider, or threat model.
- No participant edit outside the requested target; no discussion edit to a
  sealed or generated milestone artifact.

### Risks

- Mistaking a help request for finished work could skip required review.
- Guessing which conversation or target version to resume could return the
  wrong proposal.
- Treating a coherent proposal as self-approving could silently rewrite sealed
  design.
- Concurrent final reviewers may ask different questions; the attempt must be
  discarded and restarted deterministically after one discussion.
- A service outage can look like disagreement; operational faults and a genuine
  unsuccessful discussion must remain distinct.

## Register 2 — Pinned facts and executable evidence

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Milestone worker signal | The exact control status is `need_rethink`. It is accepted only for `implement`, `fix_findings`, `review_round`, `delta_review`, and `seal_half`. Every `need_rethink` object has exactly `question` (non-empty string), `finding` (one current report-finding object), `target_path` (normalized workspace-relative non-empty path), and `max_rounds` (positive integer); `implement` and `fix_findings` additionally require exactly `failure_gap` (one current gap object), while report kinds forbid it. For `fix_findings`, `finding` must equal one currently queued finding as a JSON value and every other queued finding remains pending. The top level may carry common optional `notes`, but no ordinary result, gap array, retry field, artifact/files/suite claim, finding list, disposition, battery, correction verdict, or slice plan. The finding and builder fallback gap are preserved as JSON values. | `implementation/milestones/brainstorming/skeleton.md:77-80,107`; `implementation/milestones/brainstorming/goal.md:281-298`; `orchestrator/contracts.py:47-171,300-371,538-646,745-800`; `orchestrator/driver.py:2706-2905`; `orchestrator/brainstorming_lifecycle.py:497-591` | touch the common worker output contract, eligible prompt builders, and focused tests; do-not-enable drafters/reclassifiers, let report-only workers route a gap, drop sibling fix findings, or treat the signal as completed work |
| Generic request and adapter run policy | `workspace_path` is the milestone's resolved workspace; `question`, `target_path`, and `max_rounds` equal the signal; `context.source_payload` equals `finding` as a JSON value; `context.brief` is non-empty. `context.references` is the stable unique list, in order, of current skeleton artifact, applicable governing artifact, and current unit artifact, omitting absent values and the implementation placeholder `(workspace)`; no reference may be the target. Before launch the adapter supplies participants exactly `[{"id":"lead","role":"lead"},{"id":"interlocutor","role":"interlocutor"}]` and selects `unanimity`; existing resolver behavior chooses eligible assignments, prefers cross-family resolution, and records same-family fallback. The current project/work-area execution context is inherited unchanged. | `implementation/milestones/brainstorming/skeleton.md:25-28,42-43,73-80,99-103,107`; `implementation/milestones/brainstorming/goal.md:47-48,65-115,148-160,281-287`; `orchestrator/brainstorming.py:522-596,786-826`; `orchestrator/brainstorming_lifecycle.py:270-390,411-494`; `orchestrator/driver.py:570-584,642-650,2471-2483` | touch adapter translation into the existing create contract; do-not-interpret the finding, add a domain taxonomy, or re-resolve a different work area |
| Durable suspension and attachment | A valid signal records the origin unit, worker kind, family, model/effort, explicit origin provider-session reference when return requires it, and the exact signal. After standalone creation returns, it records that session id before any milestone transition. Until the recorded session is terminal, the originating milestone status and every review/fix/seal counter remain unchanged and no later milestone worker runs. Recovery follows a recorded session id; a stale or concurrent consumer cannot apply a second terminal return. An unacknowledged create has no exactly-once guarantee and cannot be treated as a recorded result. | `implementation/milestones/brainstorming/skeleton.md:23-34,42-43,65-67,80,107`; `implementation/milestones/brainstorming/goal.md:283-298`; `orchestrator/state.py:208-315,393-440,471-508,614-646`; `orchestrator/driver.py:487-509`; `orchestrator/brainstorming_lifecycle.py:802-936` | touch additive milestone adapter state and its deterministic step; do-not-store discussion state in milestone rounds, advance while waiting, or claim exactly-once create/provider delivery |
| Successful return routes | A terminal `success` is accepted only from the recorded Brainstorming session. The handoff has exactly `session_id`, the exact core `result`, and `accepted_target_revision`; the adapter reads the retained revision and requires it to exist. `implement` and `fix_findings` continue the exact recorded origin provider session—never a recent-session fallback—and their next accepted envelope is the ordinary result for that kind. Any report kind starts a fresh provider session; the requesting output is no review evidence. A seal waits for all sibling halves, selects the first valid request in configured family order, invalidates the attempt, re-verifies the candidate, and begins a fresh seal attempt. | `implementation/milestones/brainstorming/skeleton.md:23-34,77-80,103-108`; `implementation/milestones/brainstorming/goal.md:289-298,362-365`; `orchestrator/brainstorming.py:1075-1102,1983-2042,2417-2442`; `orchestrator/runners.py:751-901`; `orchestrator/driver.py:1703-1835,2706-3011,3072-3388,3676-3835,3859-4265` | touch session-aware milestone calls and existing return gates; do-not-resume reviewers, count the request, accept a live unversioned target, or bypass verification/review/seal |
| Amendment adoption | The accepted Brainstorming target is a proposal and cannot itself override a sealed goal, skeleton, or slice note. When a fixer must change its own sealed slice note to adopt it, the existing one-shot `design_correction` object retains `artifact`, `authority_artifact`, `contradiction`, and `resolution` and adds exactly `brainstorming_authority: {session_id, accepted_target_revision}`. The pair must equal the recorded handoff; authority bytes come from that retained Brainstorming revision, never the live target or VCS. Existing single-note scope, provisional rollback, independent delta verdict (`ratify`, `retry`, `remodel`, or `needs_operator`), and note-gate update remain authoritative. No parallel correction path is added. | `implementation/milestones/brainstorming/skeleton.md:36-47,49-67,80,107`; `implementation/milestones/brainstorming/goal.md:30-48,289-298,362-365`; `orchestrator/driver.py:1257-1501,2706-3011,3072-3351`; `orchestrator/prompts.py:1266-1321,1657-1701`; `orchestrator/contracts.py:374-421,651-719` | touch the correction authority variant and handoff context; do-not-make Brainstorming success self-ratifying, edit another sealed artifact, or create a second correction lane |
| Failure and operational split | Only a validated terminal Brainstorming result with `outcome: failure` invokes a domain route. For `implement` or `fix_findings`, the unchanged `failure_gap` enters its existing `fits_remodel` or `needs_operator` route. For a report kind, the unchanged `finding` becomes that report's sole finding and enters the normal fixer checkpoint; the reviewer does not classify or route a gap. No origin session resumes and no fresh review starts. Invalid request/access, target-in-use, unavailable lifecycle state, stop-incomplete, uncertain creation, and provider/continuation faults remain operational and consume neither fallback. | `implementation/milestones/brainstorming/skeleton.md:23-34,77-80,105-108`; `implementation/milestones/brainstorming/goal.md:270-298`; `orchestrator/contracts.py:94-171,300-371,360-371,651-673`; `orchestrator/brainstorming.py:1075-1102,1205-1291`; `orchestrator/brainstorming_lifecycle.py:39-73,802-936,1026-1035`; `orchestrator/driver.py:1941-2205,2662-2704,3269-3388,3676-3835,4109-4265` | touch deterministic result consumption and existing routes; do-not invent adapter result codes, let a report-only worker reopen design, synthesize a gap/finding after failure, classify infrastructure as disagreement, or erase terminal evidence |
| Target and compatibility boundary | The target resolves inside the current primary workspace from the signal's normalized relative path and is the caller-selected amendment/proposal artifact, versioned only by Brainstorming. It must not equal/overlap any context reference, sealed milestone artifact, generated milestone ledger, Brainstorming state/transcript path, or another active session's target. Brainstorming participant content mutation is confined to `target_path`; no Git/VCS fact selects, validates, restores, or merges a target revision. Existing standalone routes, milestone API/panel, ordinary worker outputs, project contracts, and external roots retain their behavior when no signal is returned. | `implementation/milestones/brainstorming/skeleton.md:36-47,65-67,80,98,101-108`; Operator Amendment A1, **Target versioning clarification**; `orchestrator/brainstorming.py:234-283,2009-2042,2180-2214`; `orchestrator/brainstorming_coordination.py:160-168`; `orchestrator/brainstorming_lifecycle.py:497-591,802-908`; `orchestrator/service.py:2773-2938` | touch only the Milestone adapter, non-VCS target eligibility checks, and declared correction authority variant; do-not-touch core semantics, HTTP/UI surfaces, generated artifacts, external roots, or—during Brainstorming—any path outside the target |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_brainstorming_milestone_adapter`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The control result is exact and exclusive | `test_need_rethink_signal_is_closed_eligible_and_non_completing` | All five eligible kinds accept only their exact object; ineligible kinds, missing/extra builder fallback gaps, any report fallback gap, malformed findings, and mixed completion/gap/retry claims are rejected without state or target change. | strict |
| Translation preserves caller facts and policy | `test_adapter_builds_exact_request_roster_and_execution_context` | Across skeleton, slice-note, and implementation units, the request copies question/target/round bound, preserves the finding as `source_payload`, produces the exact ordered/de-duplicated reference list, supplies the exact two participant ids/roles under unanimity, resolves with cross-family preference/same-family fallback, and retains the current primary/additional-root context. | strict |
| Adapter target admission isolates protected artifacts | `test_adapter_rejects_protected_and_aliased_targets_before_creation` | Targets equal to, overlapping, or resolving as aliases of any context reference, sealed milestone artifact, generated milestone ledger, Brainstorming state/transcript authority, or another active target are rejected before any session, target, or milestone mutation; a distinct proposal target remains admissible. | strict |
| A recorded wait is restart-safe | `test_rethink_pause_recovery_uses_recorded_session_without_advancing` | Recovery after association, a second driver, and repeated terminal inspection cannot consume twice, advance the unit, or count a worker/review/seal result while active. An uncertain create advances nothing and is surfaced operationally; the test makes no exactly-once creation claim. | strict recorded state; optimistic contention; best-effort create; eventual terminal observation |
| Builders return to the exact conversation | `test_implementer_and_fixer_continue_exact_origin_session` | A fake provider proves the handoff uses the recorded session reference with accepted target revision/result context; no recency fallback or fresh builder session is used; the resumed ordinary envelope alone advances, and the fixer still enters delta review. | strict routing; best-effort provider delivery |
| Reviewers always take a fresh look | `test_review_delta_and_concurrent_seal_restart_fresh` | Full and delta review requests create no review record and rerun in new provider sessions. Concurrent seal halves quiesce, configured order selects one request, siblings count as no evidence, and verification precedes a fresh attempt. | strict routing; optimistic concurrent winner |
| Domain failure and operational faults stay distinct | `test_failure_reuses_builder_gap_or_reviewer_finding_without_false_result` | Durable Brainstorming failure feeds each builder gap unchanged to its route or records the report kind's source finding as its sole finding for the normal fixer checkpoint. Every lifecycle/access/provider fault stays operational and consumes neither. | strict |
| The motivating amendment reuses correction ratification | `test_fixer_amendment_reuses_brainstorming_revision_and_design_correction` | A focused contradiction produces only its target amendment, resumes the same fixer, binds any own-note change to the accepted Brainstorming revision, and exercises clean ratification, retry rollback, remodel, and operator verdicts through the existing delta lane without a documentation reset or parallel correction path. | strict |

The repository gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:321-329`).

### Question Battery

The skeleton's Question Battery is **INHERITED**, not re-answered here. These
are the slice-scoped remainder; enforceability is intentionally answered again
for every guarantee this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **verified current consumers:** the shared worker-output validator and five prompt/result paths (`implement`, `fix_findings`, `review_round`, `delta_review`, `seal_half`); the driver's atomic unit/fix/review/seal state; explicit provider-session continuation; and existing Brainstorming create/inspect/result/target-revision surfaces. **not touched:** draft/reclassify workers, standalone routes/view, milestone panel, or external roots. | `orchestrator/contracts.py:47-85,538-742`; `orchestrator/prompts.py:1163-1406,1565-1830`; `orchestrator/driver.py:1703-1835,2662-3011,3072-3388,3676-4265`; `orchestrator/runners.py:751-901`; `orchestrator/brainstorming_lifecycle.py:270-494,748-1005` |
| pinned_facts | **closed facts:** eligible signal and kind-specific fallback schema; exact request/context and two-person unanimity policy; recorded-session suspension; same-session builder versus fresh-review returns; proposal-only amendment plus existing correction ratification; builder-gap versus reviewer-finding failure routing; accepted Brainstorming target version and no-VCS/no-sealed-target boundary. | `implementation/milestones/brainstorming/slices/slice-08.md:118-126`; `implementation/milestones/brainstorming/skeleton.md:23-47,77-80,94-108`; Operator Amendment A1, **Target versioning clarification** |
| verification | **focused:** eight named checks pin schema/eligibility, translation/context, protected-target admission, recorded-session recovery, exact builder continuation, all reviewer routes including concurrent seal, builder-gap/reviewer-finding failure routing, and correction-lane amendment ratification. **full:** repository unittest discovery remains the milestone gate. | `implementation/milestones/brainstorming/slices/slice-08.md:128-147`; `implementation/milestones/brainstorming/skeleton.md:124-137`; `orchestrator/README.md:321-329` |
| reuse_posture | **checked:** common result/finding/gap validation and prompts; driver lock, state and five origin paths; explicit provider sessions; standalone Brainstorming create/inspect and immutable target revisions; gap/operator routing; the one-shot design-correction integrity/rollback/delta gate; and concurrent seal handling. **adopted:** all of those contracts at their existing guarantee levels. **new-with-why:** one alternative control result, one recorded origin/session association, and one Brainstorming-revision authority variant are needed because ordinary results cannot suspend on an independent session and the existing correction gate accepts only an older file authority. | `orchestrator/contracts.py:94-171,300-421,538-782`; `orchestrator/state.py:208-315,393-440`; `orchestrator/runners.py:751-901`; `orchestrator/brainstorming.py:1075-1102,1983-2042`; `orchestrator/brainstorming_lifecycle.py:270-494,748-936`; `orchestrator/driver.py:1257-1501,1703-2205,2662-3388,3676-4265`; `implementation/milestones/brainstorming/skeleton.md:49-67,80,107` |
| enforceability | **signal/fallback:** existing closed output, report-finding, gap, and reserved-key validators. **target admission:** existing Brainstorming authority/active-target refusal plus adapter-owned context and milestone-artifact checks. **pause:** atomic append-only milestone state plus one-step driver lock; unacknowledged creation is explicitly best-effort. **same session:** explicit-reference start/continue with no recency fallback. **request/result:** exact generic validators and immutable accepted target revisions. **adoption:** existing one-shot correction scope, authority integrity, rollback, delta verdict, and note-gate update. **routing:** current gap/operator, review/delta/seal gates, and concurrent-half join. | `implementation/milestones/brainstorming/slices/slice-08.md:196-208`; `orchestrator/contracts.py:94-171,300-421,538-782`; `orchestrator/state.py:208-315,393-440`; `orchestrator/driver.py:487-509,1257-1501,1941-2205,3072-3388,4109-4265`; `orchestrator/runners.py:751-901`; `orchestrator/brainstorming.py:522-596,1075-1102,1983-2042` |

### Reuse Posture

- **Checked:** the common worker status/kind validator and output-key registry;
  all five eligible prompt and result consumers; atomic milestone state and
  exclusive step lock; exact provider-session creation/continuation; the
  standalone Brainstorming creation, inspection, request, result, transcript,
  and retained target-version contracts; current gap/operator routing; and the
  one-shot design-correction integrity, rollback, independent delta verdict,
  note-gate update, and concurrent-seal paths.
- **Adopted:** the existing exact JSON repair gate, current project/work-area
  resolution, two-role Brainstorming roster resolution, unanimity closure,
  standalone session lifecycle, immutable target revisions, explicit provider
  session references, exact report-finding and gap contracts, goal-fit routing,
  and the complete design-correction/delta lane.
- **New-with-why:** one alternative `need_rethink` control result and one
  durable association between its origin and a Brainstorming session, plus an
  authority variant that binds an own-note correction to an immutable accepted
  Brainstorming revision. The sealed design requires the adapter and
  caller-specific returns, while current results cannot wait on an independent
  session and the correction gate accepts only an older workspace artifact.
- **Compatibility:** without `need_rethink`, every existing worker envelope,
  transition, route, API, panel projection, and project extension behaves as
  before. The adapter consumes the stable Brainstorming contract and extends,
  rather than duplicates, the existing correction lane.

Authorities:
`implementation/milestones/brainstorming/skeleton.md:23-47,49-67,77-80,94-108`;
`implementation/milestones/brainstorming/goal.md:281-298`;
`orchestrator/contracts.py:94-171,300-421,538-782`;
`orchestrator/runners.py:751-901`;
`orchestrator/brainstorming_lifecycle.py:270-494,748-936`;
`orchestrator/driver.py:1257-1501,1703-2205,2662-3388,3676-4265`.

### Enforceability Gate

| invariant asserted here | mechanism that can enforce it | implementation gate |
|---|---|---|
| Exact eligible non-completion signal | The common status/kind validator, report-finding and gap validators, report-only boundary, and single reserved-key registry already reject malformed and colliding worker results (`orchestrator/contracts.py:47-171,300-371,538-782`) | Contract matrices require the exact kind-specific object only for the five eligible kinds, require builder fallback gaps, forbid reviewer fallback gaps, and reject every mixed work claim before adapter state changes. |
| One recorded wait and one terminal consumer | Atomic append-only milestone saves and the nonblocking one-step driver lock serialize recorded adapter state (`orchestrator/state.py:208-315`; `orchestrator/driver.py:487-509`); standalone create is durable but does not offer a caller idempotency key (`orchestrator/brainstorming_lifecycle.py:802-936`) | Recovery and concurrent-driver tests prove one winning return for a recorded session and unchanged origin counters while active. Uncertain creation is tested as operational, not exactly-once. |
| Exact builder conversation versus fresh reviewer | Provider sessions are created and continued by explicit reference, and continuation has no recency fallback (`orchestrator/runners.py:751-901`); current report paths already start independent calls (`orchestrator/driver.py:2662-2676,3269-3291,3735-3746,3970-4052`) | Fake providers expose every started/resumed reference; implement/fix must match the origin, while every report return must use a different reference. |
| Exact opaque request and inherited context | The generic request/context validator preserves JSON `source_payload`, the standalone creation contract fixes participants/policy before launch, and project binding resolves the existing work area (`orchestrator/brainstorming.py:522-596,786-826`; `orchestrator/brainstorming_lifecycle.py:270-494`) | Translation tests compare the whole request and resolved context, including reference order, primary/additional roots, assignments, policy, and fallback. |
| Protected targets are refused before mutation | Existing Brainstorming authority and active-target admission combine with adapter knowledge of context references and protected milestone artifacts (`orchestrator/brainstorming.py:234-283,2180-2214`; `orchestrator/brainstorming_lifecycle.py:497-591,802-908`) | Adapter admission tests exercise direct and aliased overlaps with context, sealed/generated milestone artifacts, Brainstorming authority, and active targets, and observe no session, target, or milestone mutation. |
| Handoff names only an accepted Brainstorming version | Terminal result validation binds target/transcript refs; immutable target revision reads reject missing or mismatched identifiers; success requires the accepted target to exist (`orchestrator/brainstorming.py:1075-1102,1983-2042,2417-2442`) | Tests mutate the live path after retained revision capture and require the handoff/check to use the recorded accepted revision or fail operationally—never infer from Git or accept the drift. |
| An amendment cannot self-ratify | The existing correction contract limits the edit to a fixer's own note, snapshots its authority and baseline, rolls back rejection, requires an independent delta verdict, and updates the note gate only on ratification (`orchestrator/contracts.py:374-421,651-719`; `orchestrator/driver.py:1257-1501,2706-3011,3072-3351`) | The amendment matrix substitutes only the recorded Brainstorming revision as authority and proves clean ratification, retry rollback, remodel/operator routing, single-note scope, and no parallel correction state. |
| Failure routing cannot swallow infrastructure or reviewer authority | Existing builder gap values feed the gap/operator router; report findings feed the ordinary fixer checkpoint; lifecycle/API faults have distinct typed codes (`orchestrator/contracts.py:94-171,300-371,651-673`; `orchestrator/driver.py:1941-2205,2662-2704,3269-3388,3676-3835,4109-4265`; `orchestrator/brainstorming_lifecycle.py:39-73`) | A result matrix passes builder gaps and reviewer findings through unchanged, proves the fixer remains the reviewer-confirmation checkpoint, and keeps every typed lifecycle/provider fault on its mutually exclusive operational route. |
| Existing review dosage remains authoritative | Fix completion already enters delta review; review rounds only advance on clean findings; seal halves join before judgment and seal only on accepted evidence (`orchestrator/driver.py:2973-3011,3072-3388,3676-3835,4109-4265`) | The motivating flow and review-kind matrix prove the signal counts as no evidence, fixer changes receive delta review, reviewer returns are fresh, and a changed seal candidate is verified again. |

No available mechanism promises exactly-once provider delivery, perfect provider
liveness, or immediately current UI observation. Those remain best-effort or
eventual and are not acceptance claims.

### Planning Material Disposition

- **Adopt:** the sealed skeleton as the operative boundary and the generated
  goal snapshot only for the caller-specific return and motivating amendment
  intent that Slice 8 must realize.
- **Revise:** the non-canonical live goal's arrow sketch into the exact closed
  signal, durable suspension, accepted-version handoff, and existing-route
  returns pinned here.
- **Reject:** non-canonical machine/Persona projection proposals as authority
  for this slice, including event cursors, replacement error envelopes, bearer
  tokens, push transport, digests, and Agent99 projection.

Authority:
`implementation/milestones/brainstorming/skeleton.md:3-5,36-47,77-80,94-122`;
`implementation/milestones/brainstorming/goal.md:28-48,281-298`;
`implementation/brainstorming/README.md:3-8,12-17`;
`implementation/brainstorming/machine-api-and-persona-projection.md:31-55,57-113`.
