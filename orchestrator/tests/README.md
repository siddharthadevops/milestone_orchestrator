# Test suites

## Commands

Repository-specific normal milestone checkpoint command:

    python3 -m unittest orchestrator.tests.suite_checkpoint

Manual release, architectural-change, or deep verification suite:

    python3 -m unittest orchestrator.tests.suite_extended

Mechanical partition proof:

    python3 -m unittest orchestrator.tests.test_suite_inventory

The suites are disjoint. Their union is unrestricted `test_*.py` discovery
after deliberate duplicate removal, so a newly discovered test enters the
extended complement until it is deliberately promoted.

## Measured baseline and classification

One serial module-level profile on 2026-08-26 discovered 2,410 tests and ran
green with two existing opt-in skips in 2,237.2 seconds (37m17.2s). The test
split was made from elapsed cost and exercised guarantee, not filenames.

After removing 264 inherited duplicate executions and adding the default-
command and inventory proofs, retained discovery contains 2,148 tests. The
checkpoint contains 1,332 and passed in 229.7 seconds (3m49.7s) with the same
two opt-in skips. The extended complement contains 816 tests. It was loaded
and sampled after the split but not run end to end, because the one requested
full-catalogue profile had already established its modules' baseline results
and costs.

| Classification | Measured examples | Guarantee and placement |
| --- | --- | --- |
| Fast contracts/state | `state` 5.8s/135; `verifiers` 0.1s/76; `prompt_contracts` 0.02s/16; `prompt_router` 0.3s/13 | State transitions, validation, registered routed replies, prompt assembly, and golden coverage stay in checkpoint. |
| Bounded execution seams | `suite_checkpoint_call` 16.7s/8; `canonical_plan` 14.5s/13; `judgment_call_cutover` 25.5s/35; selected `runners` 2.7s/146 | Checkpoint pins the official command, canonical read-only boundary, fresh routed judgments, output validation, subprocess, and snapshots. |
| Representative lifecycle | `e2e_fakecli` 42.1s/20 | Checkpoint retains a real subprocess/Git calculator lifecycle, including verification repair and review restart. |
| Exhaustive lifecycle/failure matrices | `verification_chronology` 193.5s/10; `driver_mock` 147.1s/35; `p3_debt` 143.5s/28; `fix_loop` 109.6s/10 | Extended retains repeated failure, cadence, debt, and compatibility permutations. Their underlying state, error, reply, checkpoint, and real-lifecycle contracts remain pinned by the fast checkpoint modules above. |
| Multi-profile and driver cutover matrices | `staffing_driver_cutover` 163.1s/52; `profile_equivalence` 91.6s/11; `project_context` 80.2s/36 | Extended retains cross-profile, hot-edit, repeated review-seat, and full-context permutations; checkpoint keeps schema, resolver, session, initialization, and direct routed-call contracts. |
| Service/Git/process depth | `service_api` 211.3s/374 before de-duplication; `service_e2e` 85.1s/2; `service_projects` 75.2s/106; `gitops` 38.9s/63; full `runners` 87.4s/213 | Checkpoint keeps the base HTTP contract, service failure/FS boundaries, a real fake-CLI E2E, and fast runner contracts. Extended keeps endpoint matrices, detached-service lifecycle, Git permutations, watchdogs, and live-control races. |
| Legacy prompt substrings | `prompts` 0.1s/88 | Extended retains these because legacy builders still have production consumers, but they are not checkpoint authority for routed prompts. Dynamic router, bound-contract, prompt-set, and golden coverage replaces that checkpoint guarantee. |

The service API profile exposed 33 base tests inherited identically by eight
subclasses. Discovery now executes those base contracts once, deliberately
removing 264 duplicate executions without removing a distinct assertion.

One Brainstorming participant liveness case is also extended because it uses
real multi-process CPU-floor timing. Checkpoint retains the other execution
adapter cases and fast subprocess contracts; extended retains the frozen,
active, blind-observer, and operator-stop supervision matrix unchanged.

Whole modules assigned to extended are `test_adversarial_fixes`,
`test_brainstorming_api`, `test_brainstorming_slice_production`,
`test_brainstorming_visualization`, `test_driver_fixes`,
`test_driver_implementation_size`, `test_driver_mock`, `test_fix_loop`,
`test_gitops`, `test_malformed_observability`, `test_p3_debt`,
`test_profile_equivalence`, `test_project_context`, `test_prompts`,
`test_reconciliation_call`, `test_reuse_audit`, `test_seal_predicate`,
`test_service_e2e`, `test_service_projects`,
`test_session_repository_turns`, `test_staffing_conformance`,
`test_staffing_driver_cutover`, `test_task_conformance`,
`test_verification_chronology`, and `test_worker_tasks`. `test_runners` and
`test_service_api` are split at class boundaries, and the one real-time
Brainstorming liveness case is split at test-case granularity. The manifest's
computed complement, rather than this prose, is membership authority.

Mocks on the checkpoint path derive routed question IDs from the bound prompt.
Filesystem tilde expansion is exercised against a temporary fake home rather
than the operator's real home or configuration.
