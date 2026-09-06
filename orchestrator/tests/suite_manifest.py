"""Explicit unittest-native checkpoint and extended suite membership."""

from pathlib import Path
import unittest


TESTS_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TESTS_DIR.parents[1]


# Fast contracts, state machines, and bounded integration seams. These whole
# modules were measured between effectively zero and 25.6 seconds each in the
# 2026-08-26 baseline, except for the representative 42.1-second fake-CLI E2E.
CHECKPOINT_MODULES = (
    "orchestrator.tests.test_access",
    "orchestrator.tests.test_author_call_cutover",
    "orchestrator.tests.test_brainstorming_closure",
    "orchestrator.tests.test_brainstorming_coordination",
    "orchestrator.tests.test_brainstorming_execution",
    "orchestrator.tests.test_brainstorming_state",
    "orchestrator.tests.test_brainstorming_tasks",
    "orchestrator.tests.test_brainstorming_transcript",
    "orchestrator.tests.test_canonical_plan",
    "orchestrator.tests.test_cost_accounting",
    "orchestrator.tests.test_e2e_fakecli",
    "orchestrator.tests.test_errclass",
    "orchestrator.tests.test_gap_contract",
    "orchestrator.tests.test_gitsync",
    "orchestrator.tests.test_interpreter",
    "orchestrator.tests.test_judgment_call_cutover",
    "orchestrator.tests.test_kvstore",
    "orchestrator.tests.test_ledgers",
    "orchestrator.tests.test_model_profile_runtime",
    "orchestrator.tests.test_model_profiles",
    "orchestrator.tests.test_plan_reconciliation",
    "orchestrator.tests.test_pricing",
    "orchestrator.tests.test_producer_selection",
    "orchestrator.tests.test_profiles",
    "orchestrator.tests.test_projects",
    "orchestrator.tests.test_prompt_contracts",
    "orchestrator.tests.test_prompt_router",
    "orchestrator.tests.test_prompt_set_binding",
    "orchestrator.tests.test_prompt_sets",
    "orchestrator.tests.test_registry",
    "orchestrator.tests.test_run_init",
    "orchestrator.tests.test_service_fixes",
    "orchestrator.tests.test_service_fs",
    "orchestrator.tests.test_session_call_cutover",
    "orchestrator.tests.test_session_repository_seal",
    "orchestrator.tests.test_staffing_api",
    "orchestrator.tests.test_staffing_brainstorming_cutover",
    "orchestrator.tests.test_staffing_documents",
    "orchestrator.tests.test_staffing_panel",
    "orchestrator.tests.test_staffing_sessions",
    "orchestrator.tests.test_staffing_standalone_cutover",
    "orchestrator.tests.test_state",
    "orchestrator.tests.test_suite_checkpoint_call",
    "orchestrator.tests.test_suite_inventory",
    "orchestrator.tests.test_task_activity",
    "orchestrator.tests.test_task_api",
    "orchestrator.tests.test_task_cancel_recovery",
    "orchestrator.tests.test_task_controls_api",
    "orchestrator.tests.test_task_controls_panel",
    "orchestrator.tests.test_task_execution",
    "orchestrator.tests.test_task_family_quiescence",
    "orchestrator.tests.test_task_panel",
    "orchestrator.tests.test_task_pause_quiescence",
    "orchestrator.tests.test_task_prespawn_recovery",
    "orchestrator.tests.test_task_recovery",
    "orchestrator.tests.test_task_result_quiescence",
    "orchestrator.tests.test_task_resume_accounting",
    "orchestrator.tests.test_tasks",
    "orchestrator.tests.test_verifiers",
    "orchestrator.tests.test_workareas",
)


# The broad runner module costs 87.4 seconds mainly because of watchdog and
# live-control matrices. Keep its fast parsing, validation, subprocess,
# snapshot, and environment contracts in the checkpoint (146 tests / 2.7s).
# The base service HTTP contract is likewise useful at the checkpoint, while
# its large profile/compatibility subclasses belong to the extended suite.
CHECKPOINT_SELECTORS = (
    "orchestrator.tests.test_runners.TestTokenUsage",
    "orchestrator.tests.test_runners.TestExtractJson",
    "orchestrator.tests.test_runners.TestValidateWorkerOutputHappy",
    "orchestrator.tests.test_runners.TestValidateWorkerOutputViolations",
    "orchestrator.tests.test_runners.TestValidateFixCoverage",
    "orchestrator.tests.test_runners.TestSubprocessRunner",
    "orchestrator.tests.test_runners.TestMockRunner",
    "orchestrator.tests.test_runners.TestApplyModelEffort",
    "orchestrator.tests.test_runners.TestSnapshotWorkspace",
    "orchestrator.tests.test_runners.TestSnapshotWithPaths",
    "orchestrator.tests.test_runners.TestSnapshotChangesFormatting",
    "orchestrator.tests.test_runners.TestWorkflowDisable",
    "orchestrator.tests.test_service_api.ServiceApiTest",
)


# Timing-dependent multi-process supervision is extended verification. The
# other Brainstorming execution cases and fast subprocess/adapter contracts
# remain in checkpoint; this case is retained by the computed complement.
CHECKPOINT_EXCLUSIONS = frozenset((
    "orchestrator.tests.test_brainstorming_execution."
    "BrainstormingExecutionTest."
    "test_participant_calls_reuse_liveness_and_stop_supervision",
))


def iter_tests(suite):
    for candidate in suite:
        if isinstance(candidate, unittest.TestSuite):
            yield from iter_tests(candidate)
        else:
            yield candidate


def retained_suite(loader):
    return loader.discover(
        str(TESTS_DIR), pattern="test_*.py", top_level_dir=str(REPOSITORY_ROOT)
    )


def checkpoint_suite(loader):
    selected = loader.loadTestsFromNames(
        CHECKPOINT_MODULES + CHECKPOINT_SELECTORS
    )
    return unittest.TestSuite(
        test for test in iter_tests(selected)
        if test.id() not in CHECKPOINT_EXCLUSIONS
    )


def extended_suite(loader):
    all_tests = retained_suite(loader)
    checkpoint_ids = {test.id() for test in iter_tests(checkpoint_suite(loader))}
    return unittest.TestSuite(
        test for test in iter_tests(all_tests) if test.id() not in checkpoint_ids
    )
