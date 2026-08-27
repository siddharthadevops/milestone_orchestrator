# Slice 14 — Legacy retirement and end-to-end conformance

## Outcome

Activate the canonical Prompt Router runtime after the operator has drained
all old drivers. New runs use one routed prompt/canonical-plan lifecycle;
pre-activation state is refused rather than migrated. Remove the superseded
runtime lanes that earlier slices deliberately left in place until every
consumer had crossed its replacement boundary, then prove the complete flow
through current Git-backed fixtures and end-to-end tests.

The drain is an operational deployment precondition. This slice adds no drain
coordinator, migration, compatibility mode, or state rewrite.

## Activation boundary

- Set the active state schema to the already-reserved Prompt Router activation
  version.
- Every new run is created directly at that schema with a named prompt set and
  one explicit mutable-amendments document, including the empty set.
- Loading, attaching, resuming, serving, or driving a pre-activation state is
  refused before registration, dispatch, or any other effect.
- The service attach path must not swallow a schema refusal in order to adopt
  the run. Deletion of an unreadable registry entry remains a separate service
  operation and is not a reason to admit incompatible state.
- No historical reply, producer default, discovered command, pending repair,
  or prompt payload is translated into the activated schema.

## One live authority path

Before every physical author, judgment, repair, checkpoint, or session-turn
attempt, read one complete structurally valid mutable operator-amendments file
through the shared strict reader. Combine it with applicable append-only
accepted Brainstorming design authority and serve one unconditional current-set
block. A missing, unreadable, malformed, or invalid mutable source fails before
dispatch. Remove the `operator_complete`/complete-incomplete compatibility
decision and all retained/provider-history amendment authority.

Each physical call or seat turn then uses its already-installed routed charge,
registered reply contract, fresh authority, prompt trace, and canonical-plan
boundary. Tests prove the matrix from real consumers; runtime does not add a
second dispatcher, generic wrapper, text parser, or semantic policing layer.

## Retirements

Delete the now-unreachable milestone runtime and contract surfaces for:

- hand-built milestone prompt builders/decorators, regex contract scrubbing,
  rounds substitution, substring prompt assertions, and parallel prompt-file
  consumption;
- `battery` reply transport and validation, reply-carried `slices`, producer
  defaults/planning discriminators, split rethink routes, plan-authority flags,
  and `design_update` as a plan writer;
- producer/material mutation controls and any remaining successful replay or
  adoption compatibility;
- implementer/fixer `suite_command` output, validation, adoption, stored
  discovered/corrected command state, driver shell-suite execution, fixer suite
  certification/reuse, and pending suite-repair flags;
- design-document write fences and matching-file/byte-identity rejection lanes
  superseded by the source-neutral canonical observer and the explicit
  editing/read-only/trusted-judgment postures;
- detached session work-area, production-effect, target-application, and close
  machinery superseded by repository-backed turns and a no-apply session seal;
- resume/default adapters whose only purpose is accepting pre-activation run
  shapes.

Retire ordinary fixer consultation: workers never dispatch other models, and
eligible findings from both full and delta reviews use the driver-owned
classifier. Keep staffing/rigor/model selection, project safeguards,
caller-authored standalone orders, Git gate commits, immutable history, and
the finite canonical-plan/reconciliation boundaries.

## Conformance evidence

The final gate must prove:

- all 15 direct jobs — three author and twelve judgment/repair/checkpoint
  routes — resolve the canonical charge and fresh authority on every physical
  attempt, including the single contract correction where declared;
- all 12 Brainstorming coordinates — three seats across each producer job and
  across both `rethink` artifact types — use the repository-backed turn
  boundary, with only the initial seat editing ordinarily and no close-time
  apply;
- all surviving valid plan changes enter the shared anchor/projection/range
  transition, while unchanged plans follow the job's ordinary lifecycle;
- suite fourth/final cadence, failure-to-dedicated-fixer, and exact-byte fixer
  certification reuse work without driver shell execution;
- schema-2 load/attach/resume is refused and schema-3 creation starts with a
  valid explicit amendments source;
- service, CLI, fake-provider, Brainstorming, panel projection, ledger, and
  Git-backed end-to-end fixtures exercise the activated contracts;
- shipped JSON corpus, generated seed, registered section inventory, and
  golden renders agree exactly; and
- repository-wide tests and the official complete suite pass on the final
  candidate.

## Explicit non-goals

No migration, compatibility lane, prompt cache, amendment retention, recovery
store, daemon, watcher, parser, semantic detector, inferred retry, automatic
repair, protection against arbitrary repository/state damage, malformed LLM
output beyond the declared correction/terminal boundary, provider/model
mistakes, or malicious workers. Missing required state fails closed to the
operator.
