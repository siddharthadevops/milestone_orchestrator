# Slice 02 — Current profile resolution and override authority

## Goal

Deliver the thin current-state resolver required by operator amendment A1 and
the accepted current-state design amendment. Slice 1's editable validated
catalogue remains the source. Before a model dispatch, resolve the applicable
act from the run's current selection, the selected profile's current saved
definition, and the current override layer. Retain no earlier model-profile
state or model-profile history.

This note replaces the withdrawn binding/attribution Slice 2 design. Its old
snapshots, content identities, binding/change events, override generations,
acknowledgements, per-call profile attribution, provenance projections,
pre-feature opt-out, and related tests are obsolete and must be removed.

## Scope

In scope:

- one current `{name, rigor}` selection per run, read from the run's atomic
  current-selection sidecar; no file means `default@medium`;
- a current load and validation of the selected saved profile at act resolution;
- `current override > current profile entry > existing structural/config
  default > family default`, with whole-act replacement;
- existing fixed/derived authority for review, delta, counterpart, and
  consultation seats;
- service and direct-CLI execution startup seeding a missing `default`,
  validating an existing one, and supplying that active catalogue home to the
  driver for old and new runs alike;
- project-default, launch-input, and CLI creation act layers projected into
  `acts.json` only, with existing merge order, partial values, explicit per-act
  empties, whole-map replacement, and legacy/unknown-key tolerance preserved;
- the existing live acts route accepting the full nine-act surface through the
  Slice 1 authority validator, refusing invalid input atomically.
- independently supervised milestone Brainstorming turns resolving the current
  lead and structurally opposite counterpart immediately before each dispatch,
  with the creating driver supplying launch-only current state and catalogue
  inputs; explicit service restart reuses the generic run/session attachment
  when present, while unattached milestone restarts refuse before launch and
  no lifecycle record retains a model-profile locator;

Out of scope:

- the Slice 3 selection read/replace routes and panel controls;
- any model-profile snapshot, hash, binding, generation, event, origin,
  attribution, provenance, history, acknowledgement, replay, migration,
  recovery, lock, CAS, retry, rollback, or reconciliation;
- changes to strategy profiles/configuration, artifact seals, generic worker
  accounting/recovery, executor vocabulary, or Slices 4–6.

## Pinned facts

| concern | contract | implementation posture |
|---|---|---|
| Current selection | Read the sidecar immediately before act resolution. Missing means `default@medium`; malformed shape, unknown name, or unknown rigor fails before dispatch without fallback. | One atomic current value, no ledger event or prior value. |
| Current definition | Load and validate the named profile on every resolution. A saved edit visible to that load affects the next call, including in an active unit. | Reuse `model_profiles.load`; never cache or retain resolved content. |
| In-flight call | Settings already supplied to a dispatched provider call stay unchanged. | Ordinary call-local arguments only; no profile-specific record. |
| Precedence | A present `acts.json` entry is the whole policy. If absent, use the current profile entry. If both omit the act, use existing config/structural defaults. | Extend `_act_profile`, do not add a second resolver. |
| Explicit empty | A creation-time `null`, `""`, or `{}` surface entry remains present and suppresses the profile for that act, exposing only structural/family defaults. The live route keeps its existing clear meaning and removes empty submitted entries. | Presence controls precedence, not provenance. |
| Creation merge | Project defaults are below launch input. A later object after a lower non-object acts replacement replaces that non-object and carries only its explicit keys; a final non-object replacement suppresses every surface act. | Project the ordered raw layers with the same one-level merge semantics before restricting baseline config. |
| Single home | Creation-supplied surface winners exist only in `acts.json`; baseline config retains shipped surface entries. Unknown/legacy creation keys remain tolerated in merged config and are not activated. | No origin label, event, or inferred migration. |
| Authority | Full-policy acts, fixed/derived model-effort acts, and consultation family-only retain Slice 1's closed matrix. | Shared validator for profile documents and hot route; structural resolvers remain final authority. |
| Catalogue readiness | Service startup and direct CLI init/run/step seed absence and validate existing `default`, then pass that catalogue home to runtime resolution. Read-only status does not seed or use catalogue readiness as a gate. | Startup work only; resolver never repairs catalogue data. A status-only resolution error withholds the optional current-model projection while generic state, diagnostics, projection, and guard recovery continue. |
| Stale data | Superseded unit bindings, content hashes, selection snapshots, generations, and attribution fields have no authority. Pre-feature config acts are not inferred or migrated into `acts.json`; after adoption they remain baseline beneath the current profile. | Resolver does not read obsolete model-profile fields and performs no migration or cleanup pass. |
| Brainstorming | Each milestone-owned turn reads current implementer/counterpart staffing before dispatch. Its prompt names the complete shared transcript, so it starts a fresh provider session rather than retaining a provider binding that could freeze earlier settings. Monitoring reports fresh current participant staffing and completed-call identity from generic activity; it omits unproven active-call identity rather than presenting the ignored creation roster. | Reuse the shared current resolver and generic activity records; standalone non-profile Brainstorming remains unchanged. |

## Creation-layer algorithm

Project the explicit raw `acts` layers in ascending precedence:

1. A missing layer changes nothing.
2. A dict updates the current dict; if the prior whole value was non-dict, it
   replaces it.
3. A non-dict replaces the whole current value.
4. From the final dict, copy only configurable surface keys to `acts.json`,
   retaining explicit-empty values and validating every non-empty value through
   the Slice 1 authority validator before any run state is created. If the final
   value is non-dict, write an empty per-act policy for every configurable act.
   If there is no surface result, create no override file.
5. In merged baseline config, restore only shipped surface entries while
   retaining tolerated non-surface keys.

This specifically prevents a lower whole-map clear from leaving stale empty
overrides after a later higher-precedence object.

## Verification contract

Focused command:

`python3 -m unittest orchestrator.tests.test_model_profile_runtime orchestrator.tests.test_brainstorming_execution.BrainstormingExecutionTest.test_current_staffing_is_reresolved_for_each_fresh_dispatch orchestrator.tests.test_brainstorming_milestone_adapter.BrainstormingMilestoneAdapterTest.test_projectless_adapter_uses_active_home_for_launch_only_profile_input orchestrator.tests.test_brainstorming_milestone_adapter.BrainstormingMilestoneAdapterTest.test_current_profile_launch_input_is_not_persisted orchestrator.tests.test_brainstorming_coordination.BrainstormingCoordinationTest.test_withdrawn_attribution_fields_are_ignored_on_read_and_resume orchestrator.tests.test_driver_implementation_size.DriverImplementationSizeTest.test_rejected_valid_delivery_keeps_its_usage orchestrator.tests.test_p3_debt.TestP3Debt.test_reclassifier_repair_keeps_full_duration_and_identity orchestrator.tests.test_p3_debt.TestP3Debt.test_reclassifier_predispatch_failure_keeps_parent_review_usage orchestrator.tests.test_p3_debt.TestP3Debt.test_reclassifier_policy_change_before_dispatch_is_not_incident orchestrator.tests.test_p3_debt.TestP3Debt.test_current_profile_can_explicitly_choose_same_family_reclassifier orchestrator.tests.test_runners.TestCallWorker.test_profileless_call_preserves_supplied_prompt_bytes orchestrator.tests.test_run_init.TestDefaultsPrecedence orchestrator.tests.test_service_api.ActsApiTest orchestrator.tests.test_service_projects.TestConfigPrecedence orchestrator.tests.test_service_fixes.TestStartRunAtomic orchestrator.tests.test_service_fixes.TestSummaryCache orchestrator.tests.test_model_profiles`

| observable claim | named check | pass condition |
|---|---|---|
| Default applies to every run | `test_old_and_new_unselected_runs_use_current_default` | States made before and after this slice both read current `default@medium`; editing the default changes their next resolution. |
| Current writes govern next resolution | `test_profile_selection_and_override_are_last_write_wins`; `ModelProfileStoreTest.test_concurrent_saves_are_atomic_and_last_replacement_wins`; `ModelProfileStoreTest.test_staged_save_does_not_enter_catalogue`; `ModelProfileStoreTest.test_valid_long_profile_name_remains_writable`; `ActsApiTest.test_concurrent_saves_are_atomic_and_last_replacement_wins` | Profile edit, selection replacement, and override replacement each alter the next resolved act without a unit boundary; already-returned call settings remain unchanged values. Concurrent profile and override saves stage independently, profile staging is never a catalogue candidate and does not narrow the validated name space, each successful replacement carries its own submitted content, and the last replacement wins. |
| Invalid current state is loud | `test_invalid_current_selection_or_profile_fails_without_fallback`; `test_dangling_current_state_links_fail_without_fallback`; `test_dangling_default_link_is_unavailable_not_missing` | Malformed/unknown selection and missing/corrupt profile raise before a provider call; no default or prior content is substituted. A dangling current-state link is unavailable rather than absent, and startup preserves rather than seeds over a dangling default link. |
| Precedence and authority | `test_current_precedence_and_structural_authority`; `test_consultation_resolution_keeps_caller_structural_origin`; `ActsApiTest.test_acts_validation`; `ActsApiTest.test_patch_preserves_untouched_explicit_empty_and_can_clear_it`; `ActsApiTest.test_patch_rejects_malformed_current_state_without_mutation`; `ActsApiTest.test_panel_blank_rows_advertise_layer_semantics` | Override > profile > existing rules/defaults; whole-act partial/empty behavior holds; the panel mutates only edited rows so an untouched creation-time explicit empty remains authoritative and its explicit “Use profile” action clears it; a partial write refuses malformed current state without changing its bytes; blank live rows advertise current-profile inheritance, while blank launch rows truthfully add no panel override and warn that project defaults or Advanced config can still supply the current override; reviews, delta, counterpart, and consultation cannot be reassigned outside their allowed fields or lose the caller's structural origin. |
| Creation channels are equal | `test_creation_acts_are_single_homed_without_staffing_drift`; `test_creation_authority_validation_refuses_before_state_creation`; `ActsApiTest.test_projectless_creation_acts_are_single_homed`; `ActsApiTest.test_creation_acts_use_live_authority_validator`; `TestConfigPrecedence.test_bound_creation_acts_are_single_homed_after_merge`; `TestConfigPrecedence.test_bound_creation_acts_use_live_authority_validator` | CLI, project-less service, and project-bound service preserve winners, partial/empty behavior, and unknown-key tolerance while surface entries occur only in `acts.json`; invalid non-empty winners are refused before state creation through the shared authority matrix. |
| Lower clear cannot survive higher object | `test_higher_object_replaces_lower_whole_map_clear` | Project `acts:null` followed by launch `{fixer: ...}` writes only `fixer`; an omitted act resolves from the current profile. |
| Stale machinery has no authority | `test_stale_binding_and_attribution_data_are_ignored`; `test_withdrawn_attribution_fields_are_ignored_on_read_and_resume` | Injected old binding/hash/generation/attribution fields do not affect resolution or append new profile records; old Brainstorming activity attribution is discarded while the generic session stays readable and resumable. |
| Fresh runtime ownership | `test_purged_legacy_run_does_not_supply_next_run_current_settings` | Purging and recreating the same legacy runtime path removes the deleted run's selection and live act overrides, so the new run resolves current `default@medium`. |
| Entrypoint readiness | `test_execution_entrypoints_seed_validate_and_supply_catalogue_home`; `test_catalogue_failure_does_not_suppress_generic_recovery`; `TestStartRunAtomic.test_concurrent_starts_spawn_exactly_one_driver` | CLI and service paths seed a missing default, reject an invalid existing default, and supply the active home to the resolver. Catalogue refusal occurs only after an earlier physical call's generic crash accounting and cleanup run unchanged. |
| Brainstorming is current | `test_brainstorming_turns_read_current_profile_and_overrides`; `test_brainstorming_restart_uses_ephemeral_generic_run_attachment`; `test_brainstorming_monitoring_uses_current_or_actual_staffing`; `test_noop_brainstorming_start_does_not_validate_attachment`; `test_start_refuses_unattached_milestone_without_profile_locator`; `test_current_staffing_is_reresolved_for_each_fresh_dispatch`; `test_projectless_adapter_uses_active_home_for_launch_only_profile_input`; `test_current_profile_launch_input_is_not_persisted` | Profile and counterpart-override edits affect the next turn. Creation and a registered-run restart supply current resolution only to the launched child, including for project-less runs under a non-default service home; the lifecycle record contains no model-profile locator. Monitoring participant info is current, completed closing labels come from actual generic activity, and active-call staffing is omitted when actual identity is unavailable. Unattached milestone restarts refuse without mutating the session, while terminal/already-running starts remain idempotent without attachment lookup. |
| Every physical dispatch is current | `test_secondary_dispatches_reresolve_current_staffing`; `test_infrastructure_retry_reresolves_current_staffing`; `test_cutoff_stabilizer_reresolves_current_staffing`; `test_error_classifier_paths_use_current_resolver` | Contract repair, infrastructure retry, cutoff stabilization, post-discussion continuation, consultation, and both classifier dispatch paths resolve again immediately before invocation; a family change starts a fresh provider session and the dispatched prompt names that current family. |
| Non-profile callers are unchanged | `test_profileless_call_preserves_supplied_prompt_bytes` | Without a current dispatch resolver, the generic runner passes the supplied prompt byte-for-byte. |
| Counterpart state is coherent | `test_counterpart_dispatch_reads_one_profile_generation` | One counterpart dispatch resolves lead derivation and counterpart model/effort from one ephemeral current profile read, so it cannot combine two saved generations. |
| Generic records stay complete | `test_predispatch_failure_preserves_completed_malformed_attempt`; `test_nonrepairable_verifier_failure_keeps_dispatch_identities`; `test_double_malformed_family_change_records_each_dispatch_identity`; `test_double_malformed_same_family_change_keeps_each_identity`; `test_rejected_valid_delivery_keeps_its_usage`; `test_reclassifier_repair_keeps_full_duration_and_identity`; `test_reclassifier_predispatch_failure_keeps_parent_review_usage` | Removing profile provenance does not remove ordinary raw output, duration, usage, cost, or label/family/model/effort identity from unaccepted, malformed, repaired-strike, interrupted, or cutoff records. A double-malformed call retains one truthful generic incident per physical attempt whenever family, model, or effort changes; only attempts with the same full identity share the established combined incident. |
| Reclassification uses current policy | `test_current_profile_can_explicitly_choose_same_family_reclassifier`; `test_reclassifier_policy_change_before_dispatch_is_not_incident` | The shared resolver identifies a current profile or live override as an explicit full-family policy; structural same-family fallback retains the finding without dispatch or a false worker incident. |
| Generic status is truthful | `test_summary_choice_equals_next_call_without_intervening_change`; `test_status_does_not_require_catalogue_readiness`; `TestSummaryCache.test_guard_projection_survives_unavailable_model_catalogue` | During review rounds with valid current state, service/panel and CLI status report the model returned by the same current resolver and profile, selection, and override writes invalidate the summary cache. Missing, invalid, or unreadable catalogue state never hides the generic status or prevents guard projection/recovery; strict dispatch still fails before provider invocation. |

The repository's scheduled full-suite gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`; this worker runs only
the focused command.

## Reuse posture

Reuse Slice 1's strict loader/validator and missing-only seed, the existing
`_act_profile` resolution seam, `acts.json` and its atomic service write, the
existing creation merge order, and the structural review/delta/counterpart/
consultation resolvers. The creation projection reuses that validator for every
non-empty winner before claiming state while retaining the already-pinned empty
semantics. The panel's thin per-act mutation reuses the resolver's strict
current-layer read, the same validator, and atomic writer: malformed current
state refuses without mutation, omitted rows remain untouched, while a
supplied empty retains the live route's clear meaning. Live blank-row labels
name current-profile inheritance; launch blanks name only the absence of a
panel-layer override because project defaults or Advanced config can still
provide the creation winner. Structural defaults are shown only after a row
becomes an override. This is necessary because the whole-map
replacement form cannot carry a meaningful explicit empty without clearing it.
The only new durable model-profile value is the current selection sidecar owned
by Slice 3's later write surface; Slice 2 reads it.
Atomic profile and override saves reuse same-directory replacement with one
unique temporary file per write. Profile staging uses a short basename outside
the `.json` catalogue namespace, so overlapping readers do not validate it and
staging does not narrow the accepted profile-name space. This is sufficient for
overlapping writers without a lock, retry, or retained generation. Lexical path presence
distinguishes a dangling current-state link from genuine absence, so the
resolver fails and the missing-only seed does not replace operator data.
The existing purge lifecycle removes both current-setting sidecars before a
legacy runtime path can be reused; no separate ownership or cleanup mechanism
is added.

The cheapest sufficient implementation performs current reads and returns the
ordinary family/model/effort tuple already consumed by callers. The existing
physical-invocation seam asks for that tuple immediately before initial,
repair, retry, stabilization, continuation, and classifier calls; the fixer's
separately launched consultation uses a thin late-resolution command over the
same seam and receives the caller act plus its structural origin. Related
lead/counterpart derivation shares one ephemeral source read. The same resolver
supplies the existing generic current-model summary
and its cache key tracks the current selection and selected source. If that
read-only projection encounters invalid current model-profile state, it omits
the enhancement and leaves generic state/status/guard recovery intact; the
physical dispatch seam remains strict. Existing
busy markers and the existing worker-incident type keep ordinary per-dispatch
identity and accounting truthful when a repair changes family, model, or
effort; a current
structural policy that removes the independent rater simply retains the
finding without inventing a provider failure. Snapshots, hashes, binding
events, generations, profile-attribution
extensions, profile-provenance summary content, and Brainstorming provenance
have no authorized consumer and are removed. Old Brainstorming attribution
keys are accepted only as discarded compatibility input. No migration, new
ledger, or parallel resolver is added.
The catalogue adds no Git policy. The normal registry home is outside the run
workspace. If an operator explicitly places a custom home inside it, ordinary
repository staging, commit, and recovery semantics apply; the resolver adds no
exclusion, preservation, startup refusal, migration, or cleanup exception.

Milestone Brainstorming reuses that same resolver from its independently
supervised process. Because each prompt already points to the complete durable
chat, the cheapest sufficient option is a fresh provider session per turn. The
creating driver passes the run state and active catalogue directly to the
child launch and places a project-less lifecycle in that same active service
home, including a non-default one; neither value enters the lifecycle record.
On explicit service restart, the existing generic run state attachment in that
home supplies those launch-only values when present. The same attachment gives
the read-only participant view a fresh current projection; invalid or
unavailable current state withholds staffing instead of restoring the creation
roster. Active milestone calls likewise omit unproven staffing until the
existing generic activity record provides actual identity, and completed
closing labels use that record. Without the attachment, a milestone restart
cannot resolve current settings and refuses before launch rather than
dispatching its creation-time roster. Standalone sessions remain
profile-independent. Terminal and already-running starts keep their idempotent
projection without attachment lookup. No roster is inferred or migrated and no
profile-specific binding, generation, history, or recovery state is added.

## Enforceability gate

| invariant | mechanism | focused evidence |
|---|---|---|
| Current selection/definition | atomic sidecar read that distinguishes unavailable links from absence, plus `model_profiles.load` inside `_act_profile` | edit files between consecutive resolutions; inject dangling selection, override, and default links |
| No fallback | selection/profile validation error propagates before runner invocation | provider spy remains unused |
| Last-write-wins | no cache, retained binding, or unit snapshot; unique non-catalogue same-directory staging followed by atomic replacement | same Driver instance observes consecutive writes; overlap profile save with catalogue read, overlap two profile saves and two override saves with an ordered replacement; save a validated name whose final filename approaches the filesystem component limit |
| Override precedence | key-preserving `acts.json` read before profile entry | profile/override matrix including explicit empty |
| Structural authority | strict whole-layer validation through the shared Slice 1 validator plus existing fixed/derived resolvers | unknown or disallowed live entry fails before an unrelated act dispatch; route and creation refusal plus end-result assertions |
| Creation parity | one raw-layer projection helper used by all three creation channels; it validates non-empty winners before state creation | CLI, project-less, and bound fixtures |
| No obsolete authority | no resolution authority or new writes for binding/hash/generation/attribution fields; old activity keys are discard-only compatibility input | injected stale fields and event census |
| Brainstorming next-turn visibility | shared current resolver plus fresh per-turn provider dispatch; launch-only inputs from the creating driver or generic registered-run attachment, never the lifecycle record; read-only views reuse current resolution and generic completed-call activity without persisting identity | edit profile/override between turns; inspect the durable runtime for no locator; restart a registered session, refuse an unattached milestone without mutation, keep terminal/running starts idempotent, and observe current participant staffing, omitted unproven active staffing, and actual completed closing labels |
| Generic continuity | discard-only legacy activity compatibility plus existing busy marker, worker incident, summary cache, and purge ownership | resume old sessions; inspect each physical failed attempt; compare status with immediate next-call resolution; purge and recreate a legacy runtime path without inheriting its prior current selection or live act overrides |

Any implementation that caches profile content, preserves an earlier selection,
adds model-profile history, silently falls back, duplicates resolution, or lets
a lower whole-map clear survive a later object does not deliver this slice.
