# Slice 01 — Task contracts and catalogue

## Register 1 — INTENT (lay language)

### What this slice builds

This slice gives operators, calling products, and later milestone integrations
one small language for handing off content work. A task request says where the
work belongs, what is wanted, what context and references matter, and optionally
where effects are requested. A task result says whether the work succeeded,
what it cost in time and model usage, and preserves the producer's own result
for the caller that understands it.

It also creates one catalogue as an ordered list of the two built-in
TaskExecutors. Its first entry is the default: Worker, followed by
Brainstorming. Worker describes one contracted worker call. Brainstorming
describes a bounded, led multi-seat discussion. The catalogue tells a caller
what each choice is good at and publishes the only configuration schema used to
check an order.

### Ownership and boundary

This slice owns the shared request, order, result, and self-description shapes;
the two built-in catalogue entries; and deterministic validation of those
shapes. It owns vocabulary, not execution.

It does not admit, store, run, resume, retry, staff, or display a task. It adds
no task identity, accounting ledger, activity event, HTTP route, panel control,
slice-producer selection, adapter, path-authority check, or destination
containment. Those consumers receive this contract in later slices.

The optional output directory remains a destination instruction. This slice can
check that the field is well formed, but it cannot prove authority, resolve the
path, confine an executor, or prove where effects landed.

### Guarantee posture

- **Strict:** catalogue inventory, public field names, allowed values, defaults,
  request and order validation, result validation, accounting shapes, and
  preservation of the executor-native result. The same valid input has the same
  accepted normalized value; malformed input is rejected.
- **Optimistic:** none. No concurrent or provisional state exists here.
- **Eventual:** none. There is no replication, polling, or convergence.
- **Best-effort:** none is added. This slice promises no execution, delivery,
  persistence, freshness, effect placement, or cleanup.

### Dependencies and consumers

This is the first slice and has no earlier-slice dependency. It depends on the
existing JSON value, Brainstorming closure-policy, token-usage, and cost
vocabularies, without taking ownership of their runtimes.

The immediate consumer is focused contract testing. No production path is cut
over in this slice: the current Worker and Brainstorming paths continue to use
their native contracts. Durable admission, adapters, API, and panel consumers
come later and must consume this one catalogue rather than restating it.

### Non-goals

- No durable task record, task id, state transition, call marker, chip, or
  accounting aggregation.
- No Worker or Brainstorming dispatch, staffing resolution, session creation,
  continuation, rethink handling, or recovery behavior.
- No producer planning, override, retry, Resume, or milestone scheduling change.
- No HTTP route, status mapping, panel surface, or public task listing.
- No work-area resolution, access decision, path canonicalization, filesystem
  confinement, effect inventory, placement gate, or rollback.
- No target path or domain taxonomy in the common request.
- No new model-profile, staffing, pricing, or Brainstorming lifecycle source.

### Acceptance

The slice is accepted when focused tests prove the exact ordered two-entry
catalogue and its first-entry default, its configuration defaults and choices,
the common request and order envelopes, success and failure result envelopes,
truthful partial-accounting shapes, and opaque native-result preservation.
Invalid types, missing or surplus fields, unknown executors, unsupported
configuration, and inconsistent accounting are rejected without invoking an
executor or writing state.

The expected implementation stays below the roughly 500 changed-code-line
target: one pure contract/catalogue surface and focused tests. Pulling storage,
routes, adapters, or UI into this slice would exceed its boundary rather than
justify exceeding the target.

### Risks

- Copied configuration defaults could drift between validation and presentation;
  one catalogue-backed schema and equality tests prevent that split.
- A common validator could flatten Worker or Brainstorming results; arbitrary
  nested native-result round trips pin opacity instead.
- Staffing descriptions could become an undeclared selector; configuration
  resolution reads only the declared configuration schema.
- Eager path or lifecycle checks could create authority this slice does not
  possess; tests stop at syntax and leave admission and execution to their
  owning slices.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Vocabulary and inventory | Public record vocabulary is exactly `task` and `TaskExecutor`. The catalogue value is an ordered list of exactly two entries: `worker`, then `brainstorming`; the first entry is the catalogue default. Each entry has exactly `id`, `name`, `description`, `operating_mode`, `usage_examples`, `available_agent_configurations`, and `configuration_schema`. Names/descriptions/modes are non-empty; usage examples are non-empty and each has fewer than ten words. `available_agent_configurations` is a JSON-plain description only. | `implementation/milestones/tasks-2/skeleton.md:293-297`; ordered catalogue projection precedent `orchestrator/profiles.py:66-71`; intent traced in `implementation/milestones/tasks-2/goal.md:83-105` | touch the one shared catalogue and its validator; do-not-add aliases, a wrapper/default field, a second catalogue, hidden selection, or model-profile definitions |
| Common request | The closed request object has required `work_area`, `request`, `context`, and `reference_documents`, plus optional `output_directory`. `work_area` is a non-empty JSON object carrying already-resolved execution context; `request` is a non-empty string; `context` is any JSON-plain value and remains opaque; `reference_documents` is an ordered list of non-empty strings; and `output_directory`, when present, is a non-empty string and means the requested destination. No `target_path`, artifact list, or domain kind is accepted. Slice 1 validates and detaches JSON values but makes no access, canonicalization, containment, placement, or contradiction-detection claim. | `implementation/milestones/tasks-2/skeleton.md:147-162,181-186,296,305`; `orchestrator/kvstore.py:177-203` | touch the common shape only; do-not-resolve authority, infer effects, canonicalize a destination, or expose Brainstorming's private target |
| Order and configuration | The closed order input has required `task_executor` and `request`, plus optional executor-specific `configuration`. Missing configuration is `{}` before catalogue defaults are resolved. Worker accepts only `{}` and resolves to `{}`. Brainstorming accepts only optional `max_rounds` and `closure_policy`; omitted members use catalogue defaults. `max_rounds` is an integer of at least 1, excluding booleans; `closure_policy` is exactly `unanimity` or `majority`. Unknown executor ids classify as `unknown_task_executor`; every other shape/configuration refusal classifies as `invalid_task_request`. This slice exposes no HTTP mapping and performs no admission. | `implementation/milestones/tasks-2/skeleton.md:295,297,301,304`; `orchestrator/brainstorming.py:32-35,1294-1297` | touch pure order/configuration validation; do-not-add staffing, task identity, availability checks, persistence, or route behavior |
| Configuration schema | Worker's `configuration_schema` is exactly `{}`. Brainstorming's is exactly `{"max_rounds":{"type":"integer","minimum":1,"default":10},"closure_policy":{"type":"choice","choices":["unanimity","majority"],"default":"unanimity"}}`. Order resolution consumes this same schema; defaults and finite choices are not copied into a second authority. | `implementation/milestones/tasks-2/skeleton.md:297,301,307`; existing closure vocabulary `orchestrator/brainstorming.py:32-35` | touch one schema-backed resolver; do-not-duplicate defaults/choices or read descriptive staffing as order input |
| Task result | The closed result has required `status`, `duration_s`, `token_usage`, `token_usage_partial`, `cost`, `cost_partial`, and `native_result`, with `reason` required only for failure. `status` is exactly `success` or `failure`; failure reason is non-empty and success carries none. `duration_s` is a non-negative finite number. `token_usage` is either null or the existing exact five-field non-negative integer shape with consistent totals. `cost` is either null or exact non-negative finite `api_usd`/`real_usd`, with real not exceeding API-equivalent. Each partial flag is boolean; a null value requires its flag to be true, while a known partial subtotal may also carry true. `native_result` is any JSON-plain value and is preserved without executor-specific interpretation. | `implementation/milestones/tasks-2/skeleton.md:299`; result precedent `orchestrator/brainstorming.py:1892-1919`; token/cost shapes `orchestrator/brainstorming.py:79-130`; normalization precedent `orchestrator/state.py:1874-1936` | touch generic result validation and detached preservation; do-not-flatten native output, invent a generic artifact field, or aggregate accounting here |
| Slice boundary | Slice 1 creates no durable record, event, route, dispatch, selection, adapter, task chip, or change to existing Worker/Brainstorming behavior. Durable orders begin in Slice 2; executor cutovers in Slices 3-4; producer selection in Slice 5; direct API in Slice 7; panel in Slice 8; chips in Slice 9. | `implementation/milestones/tasks-2/skeleton.md:269-287,304,306` | touch pure contracts, catalogue, and focused tests only; do-not-pull later slices forward or edit granted read-only roots |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_tasks`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| Catalogue inventory and descriptions are closed | `test_catalogue_has_exact_builtins_and_self_description` | The catalogue is a list whose entries are exactly `worker`, then `brainstorming`; the first-entry default is therefore `worker`. Both entries satisfy every pinned field and usage-example limit, and descriptive staffing is not configuration authority. | strict |
| Configuration has one authority | `test_configuration_schema_and_resolution` | Worker accepts/resolves only `{}`; Brainstorming accepts full or partial legal input, applies the pinned defaults, and rejects booleans, zero/negative rounds, unknown keys, and invalid policy values using the pinned classifications. | strict |
| Common inputs stay generic | `test_request_and_order_contracts` | Valid JSON context and ordered references round-trip; every missing/extra/wrongly typed member, unknown executor, `target_path`, or artifact/domain member is rejected; no state or executor is touched. | strict |
| Generic results are truthful and opaque | `test_result_contract_and_native_opacity` | Success/failure, reason, duration, normalized token/cost, null/partial coupling, and total consistency are checked; arbitrary nested Worker-like and Brainstorming-like native values round-trip unchanged. | strict |

The repository closure gate remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:522-532`). Later slices must add integration tests; this
slice claims no runtime delivery.

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Immediate consumer:** the focused pure-contract test surface. **Verified unchanged production consumers:** Worker calls still validate their native worker protocol, and Brainstorming still validates its own request/run configuration; neither is cut over here. **Declared downstream consumers:** durable admission, both adapters, API, and panel in their later slices. | `orchestrator/contracts.py:1-5,29-33`; `orchestrator/runners.py:2842-2858`; `orchestrator/brainstorming.py:1188-1307`; `implementation/milestones/tasks-2/skeleton.md:273-281` |
| pinned_facts | Exact vocabulary and ordered-list catalogue with first-entry default; exact self-description fields; closed common request and order members; Worker-empty and Brainstorming round/policy schemas; `unknown_task_executor` versus `invalid_task_request`; closed generic result and accounting shapes; native-result opacity; and the no-runtime/no-route boundary. | `implementation/milestones/tasks-2/skeleton.md:293-307`; `orchestrator/brainstorming.py:32-35,79-130` |
| verification | The focused four-check matrix pins catalogue, schema-driven configuration, request/order rejection, accounting consistency, and opaque native results. Repository unittest discovery remains the full regression gate; integration proofs remain with the slices that introduce each consumer. | `implementation/milestones/tasks-2/skeleton.md:284-287,307`; `orchestrator/README.md:522-532` |
| reuse_posture | **Checked/reused:** canonical detached JSON values, the existing closed-catalogue projection pattern, Worker contract validation/error family, Brainstorming closure choices, and current token/cost normalization. **Cheapest sufficient option:** one pure shared contract/catalogue surface plus focused tests. **Remaining machinery and consumer:** schema-backed validation for later admission/adapters; tests consume it now. **Lifecycle:** no migration or operations, small additive maintenance, reversible before integration; omission would force later consumers to duplicate authority. | `orchestrator/kvstore.py:177-203`; `orchestrator/profiles.py:66-71`; `orchestrator/contracts.py:104-157`; `orchestrator/brainstorming.py:32-35,79-130`; `orchestrator/state.py:1874-1936`; `implementation/milestones/tasks-2/skeleton.md:192-252` |
| enforceability | Closed shapes use deterministic required/optional/exact-key and type checks over detached JSON; configuration resolution reads the catalogue schema and existing closure vocabulary; accounting uses the existing normalized token/cost invariants; opacity is pinned by JSON round-trip tests. Description text cannot select staffing because the order validator consumes only `configuration_schema`. No admission, authority, placement, persistence, delivery, or freshness guarantee is asserted because this slice has no mechanism for one. | `orchestrator/brainstorming.py:79-130,385-428,1294-1297`; `orchestrator/kvstore.py:177-203`; `orchestrator/state.py:1874-1936`; `implementation/milestones/tasks-2/skeleton.md:147-168,297,307` |

### Reuse Posture

The affected parties are later task callers and integrations. Without a shared
contract they would duplicate defaults and validation, making incompatible
orders or misleading catalogue controls likely. That harm is exposed at every
later integration but is still cheap to reverse before tasks are admitted. The
reviewed skeleton independently requires one common contract and catalogue.

Checked and reused are the repository's canonical detached JSON value, ordered
closed-catalogue projection pattern, common contract error family, existing
Brainstorming closure choices, and normalized token/cost shapes. The cheapest
sufficient response is one ordered catalogue/validation surface whose first
entry carries the default, plus focused tests; no wrapper or separate default
field is needed. Documentation alone cannot give later consumers executable
validation; storage, routes, adapters, a schema framework, or a second
configuration source would be unnecessary machinery. The remaining validator
is consumed by tests now and by admission/adapters later. It adds no migration
or operational state, is small to maintain and reversible before integration,
while omission would force every consumer to invent the same authority.

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| Closed catalogue container and entry fields, including its default | Exact ordered-list equality and deterministic exact-key/type validation following the existing stored-contract pattern (`orchestrator/brainstorming.py:385-428`) over canonical JSON values (`orchestrator/kvstore.py:177-203`). | The focused catalogue check proves list shape, exact entry order, first-entry default, and closed entry fields; the rest of the matrix refuses every missing, surplus, wrong-type, non-JSON, and invalid-value case. |
| One configuration authority and exact defaults/choices | The order validator consumes each catalogue entry's `configuration_schema`; the accepted closure values already exist as `CLOSURE_POLICIES` (`orchestrator/brainstorming.py:32-35`). | Catalogue equality plus partial/default/invalid configuration cases prove there is no second accepted schema. |
| Truthful token and cost values | Reuse the exact normalized invariants already enforced for token usage and cost (`orchestrator/brainstorming.py:79-130`; `orchestrator/state.py:1874-1936`), with explicit null/partial coupling at the task boundary. | Invalid totals, negative/non-finite values, booleans, real-over-API cost, and null-without-partial are rejected. |
| Opaque native results | Canonical JSON detachment preserves arbitrary JSON structure without an executor-specific parser (`orchestrator/kvstore.py:177-203`). | Distinct nested Worker-like and Brainstorming-like values compare equal after validation. |
| Descriptive staffing never selects execution | The only order configuration consumer is the catalogue schema pinned above; `available_agent_configurations` is absent from the order envelope (`implementation/milestones/tasks-2/skeleton.md:295-298`). | Changing descriptive data cannot change accepted fields, defaults, or the resolved order configuration. |

There is deliberately no enforcement row for admission, work-area authority,
path canonicalization, effect placement, persistence, execution, or freshness:
this slice asserts none of those guarantees.

### Planning Material Disposition

- **Adopt:** the reviewed skeleton's Slice 1 boundary and its incorporated
  amendments.
- **Revise:** no baseline decision; this note only makes the bounded contract
  shapes and focused evidence executable.
- **Reject:** brainstorming and `_drafts` material as authority, plus any target,
  runtime selector, or machinery not carried into the reviewed skeleton.

Authority: `implementation/milestones/tasks-2/skeleton.md:3-5,254-267`.
