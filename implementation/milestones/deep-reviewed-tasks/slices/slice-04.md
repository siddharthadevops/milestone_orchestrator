# Slice 04 — Reviewed seal, gate, result, and recovery

## Register 1 — INTENT (lay language)

### What this slice builds

This slice finishes the reusable reviewed-work boundary. Reviewed work may
report success only after the current production has passed its selected review
discipline, received the existing deterministic seal, and landed its own Git
gate commit. The returned result keeps the producer's outcome, compact citations
to the review evidence that earned the seal, and the gate commit identity.

Restarting does not create a replacement review or commit path. The same durable
work-in-progress, fix/amend, seal, and pending-gate facts remain authoritative.
Recovery completes the recorded boundary before success is returned or later
work can begin. Provider calls keep their existing delivery limits; this slice
does not claim that a crash can never repeat one.

The milestone driver remains the only runtime caller in this slice. Later slices
publish `reviewed_task` and compose deep work from this result. This slice does
not expose a new executor, order form, route, or panel control.

### Ownership and consumers

Reviewed work owns convergence through its gate and the success result derived
from that gate. The existing state ledger owns review history, the existing Git
discipline owns repository effects, and the generic task result envelope remains
the outer result vocabulary. Milestone sequencing, higher-level closure commits,
design repair, reconciliation, verification cadence, and deployment remain with
the milestone.

Pure-state milestone runs retain their historical internal sealing behavior, but
without a Git gate they cannot produce a reviewed-work success result. Public
admission policy for that condition belongs to the standalone-ordering slice.

### Guarantee posture

- **Strict:** success requires current-content review citations, one satisfied
  deterministic seal, and the reviewed work's non-empty gate commit; the native
  result has the single pinned shape below and preserves any implementation cut
  inside the producer result.
- **Strict:** recorded WIP and pending-gate intent is recovered before reviews,
  success, or successor work; accepted review, debt, seal, and gate evidence is
  not reconstructed from a display projection.
- **Strict:** result accounting is derived once from the reviewed work's retained
  physical-call evidence; a higher-level closure commit never replaces its gate.
- **Best-effort:** physical-call uniqueness, provider delivery, and convenience
  display freshness retain their current crash, provider, and polling limits.
- **Optimistic / eventual:** none. This slice adds no queue, replication,
  retry-delivery promise, eventual projection, or exactly-once claim.

### Dependencies

This slice depends on Slices 1–3's reusable lifecycle, frozen order policy,
direct routed-call evidence, and rethink continuity. It reuses the current
same-content seal predicate, append-only state, WIP/amend/gate Git operations,
unit accounting, and generic terminal-result envelope. It adds no third-party
dependency, service process, store, ledger, migration, or product-root adapter.

### Non-goals

- No `reviewed_task` or `deep_task` catalogue entry, task admission, public API
  change, panel field, or public error code.
- No new seal call, reviewer family, result status, task type, commit layer,
  rollback path, recovery daemon, retry ledger, or parallel evidence store.
- No change to producer selection, review breadth, debt, caps, Prompt Router,
  rethink, or implementation-size ownership. Direct agent calls and
  Brainstorming remain unchanged.
- No deep-task child admission, milestone scheduling, canonical-plan handling,
  design-repair wave, sibling verification cadence, final closure, merge repair,
  synchronization, or deployment change.
- No validation layer around trusted state emitted by this lifecycle, no
  compatibility backfill, and no edit in a granted read-only root.

### Acceptance criteria

The slice is accepted when Git-enabled reviewed work exposes no success before
the current seal and its gate, then returns the exact native result below with
the producer outcome, seal citations, verification citation, and persisted gate
identity. A fix/amend cycle must lead to citations for the final candidate, not
the earlier bytes. WIP and gate crash-window cases must recover the same logical
work without a second production, premature successor, or replacement result.
A pure-state run must retain its old internal behavior without fabricating a
gate-backed success. Existing lifecycle, route, accounting, direct-task, and
size-isolation goldens must remain satisfied.

### Risks

The principal risks are treating `sealed` as success before Git finishes,
returning stale review citations after accepted changes, deriving acceptance
from a convenience summary, losing an implementation cut while wrapping the
producer result, or returning a gate identity that recovery later replaces.
Other risks are admitting successor work during a gate crash window, counting
the same calls again in the result, changing Git-disabled compatibility, or
publishing Slice 5 surfaces early. Exact result, real-Git recovery, and retained
parity tests make those failures observable.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Current-content deterministic seal | A successful reviewed result cites exactly the final walked families' effective-clean whole-review round ids for the current review-evidence fingerprint. The existing deterministic seal appends one satisfied seal record and `seal_satisfied`; it dispatches no seal worker. Missing or stale evidence restarts ordinary review and produces no success. | milestone contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:28-55,77-88,111`; predicate `orchestrator/state.py:1195-1236`; deterministic closure `orchestrator/driver.py:12104-12156` | touch the reusable closure/result boundary and focused tests; do-not-add a seal call, accept an old cycle, derive acceptance from a projection, or change family/debt meaning |
| Gate before success | With Git gating enabled, `reviewed_task` success requires its own non-empty short `gate_commit` and matching `gate_commit` event after the satisfied seal. `pending_gate_unit` is durable before Git is touched. No success result or successor is emitted while that marker remains or the gate fails. A caller's later closure commit is separate. A Git-disabled legacy milestone may still seal internally but yields no reviewed-work success result. | mandate `implementation/milestones/deep-reviewed-tasks/goal.md:34-40,75-79`; strict posture `implementation/milestones/deep-reviewed-tasks/skeleton.md:77-88,128,137`; gate/recovery `orchestrator/driver.py:13232-13314`; Git gate `orchestrator/gitops.py:741-749` | touch lifecycle-owned gate completion, recovery, and result readiness; do-not-report success from production or seal alone, synthesize a SHA, replace the gate with milestone close, or force new law onto old pure-state runs |
| Successful native result | The existing generic terminal envelope remains unchanged. On `status: success`, its `native_result` is exactly `{"production_result": <durable producer-native JSON>, "review_evidence": {"seal_attempt": <positive integer>, "reviews": [<round id>, ...], "verification_event_seq": <integer or null>}, "gate_commit": <non-empty short SHA>}`. `reviews` and the verification citation come from the satisfied seal; `production_result` remains opaque and therefore retains `implementation_cut` at `native_result.production_result.implementation_cut` when present. Full rounds, debt, and events remain in the one authoritative lifecycle record rather than being copied into a second evidence store. | result requirement `implementation/milestones/deep-reviewed-tasks/skeleton.md:111,128`; mandate `implementation/milestones/deep-reviewed-tasks/goal.md:75-79`; producer/cut record `orchestrator/state.py:858-913`; seal record `orchestrator/state.py:1239-1278`; generic envelope `orchestrator/tasks.py:1018-1092` | touch one detached native-result projection and its contract tests; do-not-flatten or rename these fields, discard the producer result, expose a second result status, or make display summaries authoritative |
| WIP, amend, and gate recovery | Production persists one pending WIP parent/tree/message before opening reviews; recovery creates or adopts that exact WIP and records `wip_commit` once. Accepted green fixes retain the existing `amended` event and restart current-byte review. A failed or interrupted gate is recovered from the existing pending marker before result or successor work. The successful native result is derivable from durable production, seal, and gate records, so no `pending_result`, retry service, or result store is added. | WIP intent/recovery `orchestrator/driver.py:7402-7426,7740-7783`; amend outcome `orchestrator/driver.py:12054-12079`; Git primitives `orchestrator/gitops.py:638-694`; gate recovery `orchestrator/driver.py:13232-13314` | touch ownership and recovery entry through reviewed work; do-not-re-run production after recorded WIP, stack replacement commits, admit later work before the gate, or add deduplication machinery |
| Result, accounting, and terminality boundary | Reviewed physical calls remain evidence of one reviewed work item and are counted once in its existing unit totals. The result uses only `success` or `failure`; `need_rethink` remains non-terminal control. A successful result is a detached snapshot and, once Slice 5 records it, the existing null-to-terminal task mutation makes it immutable. Failure never carries the success-shaped native result or a fabricated gate. | routed-evidence contract `implementation/milestones/deep-reviewed-tasks/skeleton.md:48-55,87-88,132`; unit aggregation `orchestrator/state.py:2335-2458`; task statuses/envelope `orchestrator/tasks.py:53-64,1018-1092`; terminal mutation `orchestrator/tasks.py:822-837` | touch the reviewed-work result/accounting projection; do-not create per-call task results, count evidence twice, expose `need_rethink`, reopen a terminal record, or promise physical exactly-once delivery |
| Slice and compatibility boundary | Slice 4 publishes no TaskExecutor and changes no route, direct-task host, panel, milestone scheduling, verification cadence, or granted product root. The catalogue remains exactly `agent_call` and `brainstorming`; existing history is neither rewritten nor backfilled. The milestone driver is the only current runtime consumer of the reviewed boundary. | slice allocation and exclusions `implementation/milestones/deep-reviewed-tasks/skeleton.md:90-103,111-119,138`; current catalogue `orchestrator/tasks.py:66-125`; current consumer `orchestrator/driver.py:8284-8292`; direct host `orchestrator/task_api.py:580-590` | touch only reviewed closure/result/recovery and its milestone delegation; do-not implement standalone ordering, deep composition, sibling verification, presentation, or product adapters early |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_reviewed_result orchestrator.tests.test_reviewed_lifecycle orchestrator.tests.test_seal_predicate orchestrator.tests.test_driver_implementation_size orchestrator.tests.test_judgment_call_cutover orchestrator.tests.test_reviewed_call_routing orchestrator.tests.test_tasks`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Success requires current seal and landed gate | new `ReviewedResultContractTest.test_success_requires_current_seal_and_gate`; retained `SealPredicateDriverTest.test_changed_bytes_restart_both_reviewers_from_family_zero`; retained `DefaultReviewedLifecycleParityTest.test_default_boundary_matches_milestone_lifecycle_golden` | Before the final current-byte seal, during a failed gate, and with Git disabled, no success-shaped result exists. After the real gate, the result cites only the reviews that sealed the final candidate and names the persisted gate. | strict |
| Native result and accounting have one exact source | new `ReviewedResultContractTest.test_native_result_preserves_producer_citations_cut_and_gate`; new `ReviewedResultContractTest.test_result_totals_match_origin_evidence_once`; retained `ReviewedCallRoutingTest.test_internal_call_evidence_and_totals_survive_without_child_task_ids` | The exact schema above validates through the generic envelope, an eligible implementation cut remains nested in `production_result`, cited ids resolve to the satisfied seal, and envelope totals equal the originating evidence without task-child duplication. | strict |
| WIP and amend history survive recovery | new `ReviewedResultContractTest.test_recovery_keeps_wip_amend_and_final_review_history`; retained `DriverImplementationSizeTest.test_failed_wip_commit_is_retried_before_reviews_open`; retained `DriverImplementationSizeTest.test_resume_adopts_landed_pending_wip_without_second_commit`; retained `JudgmentDriverBoundaryTest.test_fixer_commit_survives_and_is_reviewed_from_pre_fix_revision` | Recovery makes or adopts one WIP, keeps accepted fixer/amend history, reruns whole review for changed bytes, and returns final citations without a second production. | strict effects / best-effort physical calls |
| Gate crash windows cannot leak success or successor work | new `ReviewedResultContractTest.test_gate_crash_recovers_before_result_and_successor`; retained `DriverImplementationSizeTest.test_failed_part_a_gate_is_retried_before_part_b_can_open` | A failure before or after the Git effect leaves durable recovery authority; restart completes one logical gate, then derives the result. No successor or success is visible first, and the result's SHA is the recovered persisted SHA. | strict |
| Later public surfaces and unrelated behavior remain absent | new `ReviewedResultContractTest.test_slice_four_does_not_publish_an_executor`; retained `TaskContractsTest.test_catalogue_has_exact_builtins_and_self_description`; retained Slice 2 producer/size and Slice 3 route/rethink goldens | The catalogue and direct host still expose only existing executors, direct tasks are unchanged, Brainstorming gains no size machinery, and the milestone remains the sole consumer. | strict compatibility |

Repository-level commands remain:

`python3 -m unittest orchestrator.tests.suite_checkpoint`

`python3 -m unittest orchestrator.tests.suite_extended`

They are the normal checkpoint and architectural complement and must not be
reported as run unless implementation actually executes them
(`orchestrator/README.md:565-586`).

### Due Diligence

| question | answer | evidence |
|---|---|---|
| victim | The operator and later standalone/deep callers need a reviewed result that cannot say success between seal and commit. Today the reusable boundary gates immediately after sealing but returns only a sealed unit/context, while pending-gate recovery still lives in driver startup. A gate failure can therefore leave a sealed unit with no commit; without this slice a later adapter could mistake that state for success or duplicate recovery. Repository changes are reversible, but a falsely accepted result, an admitted successor, and spent calls are not. | assigned need `implementation/milestones/deep-reviewed-tasks/skeleton.md:77-88,111`; current return/gate seam `orchestrator/driver.py:590-641`; current startup recovery `orchestrator/driver.py:1266-1300`; recorded gate-failure behavior `orchestrator/tests/test_driver_implementation_size.py:2036-2095` |
| machinery | The slice introduces one compact success projection and makes pending-gate completion/recovery part of the existing reviewed-work boundary. It reuses the durable producer result, round/seal/debt ledger, unit accounting, current Git intent markers, and generic result envelope. No new runtime module is required, and no API, dependency, process, schema version, store, or ledger is introduced. The projection exists because later adapters need one gate-aware native result; recovery ownership exists because a standalone caller cannot depend on milestone startup. | existing boundary `orchestrator/driver.py:477-641`; existing records `orchestrator/state.py:184-222,858-913,1060-1107,1239-1278`; result envelope `orchestrator/tasks.py:1018-1092` |
| consumers_touched | Verified direct runtime consumer touched is the milestone driver's delegation to reviewed work. State, Git, unit accounting, and the generic result contract are reused dependencies. The direct task host remains an unchanged comparison and still dispatches only the two existing executors. Searches across Life, Agent99, life_product_components, and Tutor found no code consumer of these ids or this result contract, so no product adapter is added and every granted root stays read-only. | milestone consumer `orchestrator/driver.py:8284-8292`; direct host `orchestrator/task_api.py:580-590`; public projection currently returns stored task records `orchestrator/service.py:4461-4482` |
| cheaper_alternative | Cheapest sufficient is to derive one result from the existing durable producer, satisfied seal, cited rounds, unit totals, and gate field, and to reuse the pending WIP/gate markers. Doing nothing leaves no machine result and keeps gate recovery milestone-owned. Reusing the display summary is cheaper but insufficient because it is explicitly bookkeeping rather than acceptance authority. Copying rounds into another store, adding a result marker, or wrapping a synthetic milestone would duplicate solved state. | authoritative records `orchestrator/state.py:858-913,1195-1278`; summary boundary `orchestrator/state.py:2599-2605`; existing pending gate `orchestrator/driver.py:13232-13314` |
| cost | Build cost is a small result/recovery seam plus real-Git crash-window, accounting, and compatibility tests. Migration and operating cost are zero: there is no daemon, dependency, extra call, or new durable store. Review cost is moderate because success spans state and Git. Omission cost is higher: Slice 5 would otherwise invent its own closure semantics or expose false success. The change remains reversible before public ordering, while a returned false result or spent provider work does not. | no-new-machinery boundary `implementation/milestones/deep-reviewed-tasks/skeleton.md:90-103`; current state/Git span `orchestrator/driver.py:12104-12156,13232-13314`; service standard enables Git gates by default `orchestrator/service.py:2421-2437` |
| threat_model | This slice adds no remote input. Untrusted inputs remain model/provider JSON and workspace edits; existing bound reply contracts, project edit detection, current-byte fingerprint, and Git root guards already contain them. The selected unit, persisted policy, round/seal records, pending markers, and result fields are trusted orchestrator emissions. Tests exercise real lifecycle outcomes and crash boundaries; they do not inject malformed self-emitted JSON or add defenses around trusted machinery. | untrusted reply boundary `orchestrator/runners.py:2922-2982`; edit authority `orchestrator/README.md:550-554`; current-byte predicate `orchestrator/state.py:1195-1236`; Git root guard `orchestrator/gitops.py:139-152` |
| pinned_facts | The six hard rows pin only deviations that change an observable or cross-slice contract: current-content deterministic seal, gate-before-success, exact successful native result, inherited recovery, result/accounting/terminality, and the pre-publication compatibility boundary. Internal class names, handler order, storage placement, and polling remain implementation choices. | slice assignment `implementation/milestones/deep-reviewed-tasks/skeleton.md:111`; settled success/result law `implementation/milestones/deep-reviewed-tasks/skeleton.md:77-88,128`; existing event/result names `orchestrator/driver.py:12133-12152,13265-13314`; `orchestrator/tasks.py:1018-1092` |
| verification | Five executable rows combine one new result/recovery contract module with retained current-byte seal, lifecycle parity, route/accounting, WIP adoption, amend-history, gate-blocking, catalogue, producer, rethink, and size-isolation goldens. The focused command pins this slice. Checkpoint and extended suites remain repository gates and cannot be claimed without execution. | retained seal proof `orchestrator/tests/test_seal_predicate.py:145-204`; lifecycle/gate proof `orchestrator/tests/test_reviewed_lifecycle.py:68-170`; WIP and gate recovery `orchestrator/tests/test_driver_implementation_size.py:582-689,2036-2095`; suite authority `orchestrator/README.md:565-586` |
| enforceability | Current review fingerprints plus `seal_predicate_reviews` can enforce same-content convergence; guarded transitions and append-only seal records can enforce deterministic closure; pending WIP identity and pending-gate intent plus Git's WIP/amend/finalize operations can enforce recoverable commit effects; unit evidence can enforce single-count totals; the generic result validator and null-to-terminal mutation can enforce the outer result and later task immutability. Two missing seams are this slice's implementation gates: reviewed work does not yet own pending-gate recovery, and it emits no gate-checked native result. Git-disabled execution cannot express a gate, so it cannot yield success. Physical-call uniqueness has no mechanism and remains best-effort. | seal mechanisms `orchestrator/state.py:806-855,1195-1278`; WIP/gate mechanisms `orchestrator/driver.py:7402-7426,7740-7783,13232-13314`; single-count mechanisms `orchestrator/state.py:2186-2458`; result/terminal mechanisms `orchestrator/tasks.py:822-837,1018-1092`; present gaps `orchestrator/driver.py:590-641,1266-1300`; delivery limit `orchestrator/state.py:1-17` |
