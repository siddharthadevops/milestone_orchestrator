# Continuable Brainstorming — implementation completion

Date: 2026-09-06.

Status: the approved implementation scope is complete and independently
reviewed. The extended release gate remains non-green because of seven
pre-existing failures documented below.

## Authority and continuation

The approved contract is [Slice 01](slices/slice-01.md). This is the
operator-authorized direct completion of the work left in the implementation
checkout by deep task `895fca05-645e-411e-ac28-b4efc9170b09` and its failed
implementation child `08aae248-26ae-4cb2-bfb1-9890b7fe8d8b`.

Documentation commit `f7e8b81`, implementation part A `68aff40`, and part B
WIP `cd72f4b` are retained. The historical task stopped during review because
the provider exhausted its usage allowance. Its terminal result is not
rewritten, and this record does not claim a retroactive automated task seal.

## Completed work

The retained implementation provides nonterminal exhaustion waits, monotonic
round extension, revision-scoped same-session continuation, API and panel
controls, and preservation of accepted history and enclosing owners.

The completion review found one additional owner-lifecycle defect: every
Brainstorming poll consumed the reviewed task's 10,000-step guard. A long
operator wait could therefore fail its reviewed and deep owners. The guard
now counts execution actions and recovered gates; discussion polling and
pending Stop settlement do not consume it. Regressions prove both a wait
longer than 10,000 polls and the retained bound for nonprogressing execution.

The extended audit also found that the workspace ownership guard could
accidentally treat an absent exclusion as a matching session id. It now
excludes a session only when an explicit id was supplied. The existing
Git-sync ownership regression was retained unchanged and now passes, together
with seven Continue and Stop/Start ownership checks.

Two outdated test expectations were brought into line with the approved
contract. The transcript tests still cover immutable historical terminal
failures and additionally preserve an exhausted waiting ballot through round
extension and continuation. The panel contract recognizes waiting while
retaining the ordinary stopped-state branch. Public controls are documented
in the existing orchestrator README.

## Verification

The suite commands ran with `ORCH_REAL_LLM` unset, using isolated fixtures.
The focused and checkpoint gates were repeated after the final
workspace-guard correction and passed on the final implementation.

- The approved 11-module focused command passed:
  **262 tests, 279.306 seconds**.
- `python3 -m unittest orchestrator.tests.suite_checkpoint` passed:
  **1,417 tests, 245.177 seconds**, with two filesystem case-sensitivity skips.
- `python3 -m unittest orchestrator.tests.test_suite_inventory` passed:
  **1 test**.
- `git diff --check` passed.
- Two independent reviews covered state/coordinator/lifecycle and
  API/owners/panel/Stop behavior. The owner wait defect was reproduced and its
  correction verified. Twenty real session-store CAS races additionally
  preserved the larger round allowance and accepted transcript history.
- An actual browser exercised the panel against disposable test services,
  using the existing fake CLI participants and a simulated task host. Add
  rounds left the discussion stopped. Continue handled 2, 1, and 0 remaining
  rounds, returning the same session to waiting after rounds 3, 5, and 7.
  Its original limit remained 1 and its 14 accepted turns were not repeated.
  A second scenario continued from waiting to success after round 2, then
  removed the continuation controls. The temporary browsers and services
  were closed afterwards. Automated fixtures cover actual owner completion.

`python3 -m unittest orchestrator.tests.suite_extended` completed all
**952 tests in 2,235.988 seconds**, with seven failures and one error. Seven
of those eight incidences are the pre-existing cases below. The remaining
Git-sync ownership regression exposed the missing exclusion guard, which was
corrected during the audit and then passed in isolation on the final code
(1 test, 0.628 seconds), as well as in the eight focused ownership checks
(7.240 seconds). The final focused command and checkpoint also passed after
that correction. The full extended command was not repeated after the fix
and is not claimed green. Inventory proves the final partition of
**1,417 checkpoint + 952 extended = 2,369 tests**.

## Pre-existing extended-suite failures

The following failures also reproduce in the separate source checkout at
`ae80f35`, without this Brainstorming implementation. The named test cases
and the existing behavior responsible for their failures are unchanged by
this work:

- `test_milestone_deep_slice_composition.MilestoneDeepSliceCompositionTest.test_brainstorming_production_counts_in_child_and_parent`:
  its fixture selects the retired `brainstorming` milestone producer and
  fails canonical-plan validation before implementation runs.
- `test_milestone_skeleton_composition.MilestoneSkeletonCompositionTest.test_reconciliation_and_final_close_stay_milestone_owned`:
  expects one `commit_plain(..., "Close milestone")` call but observes none.
- `test_profile_equivalence.ProfileEquivalenceTest.test_event_sequence_equivalent`:
  compares generated verification-task UUIDs embedded in event messages as
  if they were deterministic, despite excluding nondeterministic fields.
- `test_service_api.ProfilesDecisionApiTest.test_invalid_stored_profile_failure_is_visible_on_launch_surface`:
  expects an old literal assignment in the profile-loading UI.
- `test_service_api.StrategyConfiguratorPanelTest.test_configurator_edit_preserves_non_string_description_until_changed`:
  its API preservation assertions pass, but an old literal renderer expression
  is no longer present in the configurator source.
- `test_service_e2e.TestServicePanelE2E.test_autostart_lifecycle_closes_then_stop_and_forget`
  and `test_service_e2e.TestServicePanelE2E.test_manual_start_reaches_same_closed_outcome`:
  both reach closure but expect a unit list without the already-existing
  `milestone_verification-1` unit.

These are not fixed as part of the approved continuation scope and must not
be represented as a passing release gate.

## Delivery boundary

This completion applies to the implementation checkout. No source-checkout
integration, remote publication, production-service restart, or mutation of
historical runtime records is part of this verification.
