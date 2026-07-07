# Slice 03 — Project Record + Policy Config Model

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice adds the workspace-shaped
**project record** and the versioned **policy object** — the configuration model
the safeguard machinery runs on. It delivers the policy value schema
(`{id, version, enabled, scope, prompt, contract}`), a project-bound policy
store over the existing enveloped `policy:<id>` family, scope matching against
the EXISTING worker-kind and unit-kind vocabularies (no new names), and the
assembled read model `{work_areas, policy, defaults}`. It pins fixture invariant
**I8** and defines the seams that Slice 4 (verifier vocabulary + contract merge),
Slice 6 (PROJECT CONTEXT block + `project_safeguard_seen`), Slice 5 (run-init
resolution), and Slices 7/9 (service + panel) consume. It wires into NO run,
service, prompt, panel, or ledger, ships NO concrete safeguard content, and adds
NO verifier execution or contract merge — those are later slices.

The compatibility target for I8 is agent_99's **versioned capability-policy
concept** (`life_prod/agent_99/docs/cli-body-connector.md:88` — "Capabilities are
versioned policy objects… the effective capability set is the **enabled,
in-scope** set"), read read-only. Unlike the work-area record (Slice 2), our
policy is NOT a byte-readable agent_99 record: it lives in OUR enveloped
`policy:<id>` family that agent_99 never reads, and its `prompt`/`contract`
payload is orchestrator-specific. The adopted compatibility is CONCEPTUAL —
the shared `id + version + enabled + scope` vertebrae, so a safeguard later
becomes a workspace capability policy with zero translation of those handles.
Overclaiming byte-compatibility here would be false (see Reuse Posture).

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test, not by reading
the diff. Concrete identifiers are illustrative and the implementation's choice;
the pinned content is the policy value shape, the scope-match result, the store's
observable read/list/delete behavior, and the assembled record shape that later
slices and the future fusion depend on. The `lpc-reuse-audit` policy from the
goal (`project-concept.md` §"Policy object") is used below and in tests only as
an ILLUSTRATIVE valid policy — its concrete content ships as a built-in template
in Slice 10, never here.

### A. The versioned policy object (the config record)

A policy is a JSON document — one per safeguard, stored at `policy:<id>` — with
EXACTLY the top-level keys `{id, version, enabled, scope, prompt, contract}`
(`project-concept.md` §"Policy object"; fixture **I8** payload). A stored value
whose key set differs, or that violates any field domain below, is **malformed**:
read/list report it as malformed with no repair write (fail-closed; greenfield,
see Non-Goals). Field domains:

- `id` — a non-blank string that is a valid key fragment (no `/`, no control
  characters), reusing Slice 1's `validate_fragment` (`kvstore.py:96`) as applied
  by `policy_key` (`kvstore.py:107`). The stored `id` field MUST equal the `id`
  derived from the `policy:<id>` key; a mismatch is malformed (parallel to
  Slice 2's name/key discipline).
- `version` — a **positive integer**: the safeguard's DOMAIN version, operator-
  authored and bumped when the safeguard changes (the ledger re-records
  `project_safeguard_seen` on a bump — Slice 6). It is stored verbatim and is
  **independent of** the envelope control revision (Slice 1's I6 rule: the
  control revision counts writes; the domain `version` changes only when the
  operator changes it). Slice 3 never auto-derives `version` from the revision.
- `enabled` — a boolean. Only `enabled` policies participate in scope matching
  (B); a disabled policy is stored and readable but never in scope.
- `scope` — the scope object of B.
- `prompt` — a non-blank string: the block the worker will see. Slice 3 stores
  it verbatim; its amendment-authority RENDERING into a prompt is Slice 6's.
- `contract` — the contract-extension declaration of C.

### B. Scope, matched against the EXISTING vocabularies

`scope` is exactly `{kinds, unit_kinds}`, each a **non-empty list** whose members
are drawn from the existing single-source vocabularies — no prose names, no new
constants (`project-concept.md` §"Normative contracts"; **I8** frequency
"whose worker kind and unit kind match policy scope"):

- `scope.kinds` — worker-call kinds from `contracts.KINDS` (`contracts.py:48`):
  `draft_skeleton`, `draft_slice_note`, `implement`, `review_round`,
  `delta_review`, `seal_half`, `fix_findings`.
- `scope.unit_kinds` — unit kinds from `state.py`'s constants (`state.py:36`):
  `skeleton`, `slice_doc`, `slice_impl`. This is the FULL set — deliberately not
  `prompts.DOC_UNIT_KINDS` (`prompts.py:199`), which is only the document subset.

A `scope` missing either key, carrying any extra key, with an unknown member,
an empty list, or a non-list `kinds`/`unit_kinds` is malformed. The
**scope-match contract** (the seam Slice 4's merge
and Slice 6's prompt block consume): a policy matches a worker call
`(worker_kind, unit_kind)` iff `enabled` is true AND `worker_kind ∈ scope.kinds`
AND `unit_kind ∈ scope.unit_kinds`. There is no implicit wildcard/all — a
safeguard must state where it binds (falsifiable scope). Slice 3 exposes both the
per-policy predicate and a store-level query returning the enabled, in-scope
policies for a `(worker_kind, unit_kind)` pair (D). Slice 3 does NOT enforce
cross-consistency between a kind and the units it can occur on (that is the
driver's kind↔unit mapping, not config); membership in each list is the whole
contract.

### C. The contract-extension envelope (structural; vocabulary is Slice 4's)

`contract` is the declaration of the single required output field the safeguard
adds to in-scope workers. Slice 3 pins its **structural envelope**: exactly
`{field, required, entry, checks}`. A `contract` object missing one of those
keys, or carrying any extra key, is malformed. The verifier and entry-type
VOCABULARIES and the MERGE/enforcement are Slice 4's single source
(`project-concept.md` gate machinery §5; fixture **I9**) — slice 3 deliberately
does not duplicate that vocabulary. The envelope:

- `contract.field` — a non-blank string: the output key the worker must fill
  (e.g. `reuse_audit`). Collision of this name with a base-kind contract field is
  a MERGE concern and belongs to Slice 4, not here.
- `contract.required` — a boolean that MUST be `true`. A non-required safeguard
  field is prose-equivalent — the exact failure **I8** exists to prevent
  ("safeguards ADD REQUIRED contract fields, not prose-only warnings"). `false`
  is malformed.
- `contract.entry` — a **non-empty object** mapping field names to object
  type-specs: the per-item schema the worker must enumerate. Non-emptiness is the
  structural form of the goal's "**no bare booleans**" rule — the slot must
  demand structured, falsifiable content (`{source, package, decision, evidence}`),
  never `check_lpc: true`. An empty or non-object `entry`, or an `entry` value
  that is not an object, is malformed. The type-spec CONTENT (`{"type": …}` /
  `{"enum": […]}` tokens and their legality) is Slice 4's.
- `contract.checks` — a **list** (possibly empty; a safeguard may rest on
  reviewer semantics alone) whose every item is an object carrying a string
  `kind`. The legal `kind` values (the closed verifier set `path_exists`,
  `citation_exists`, `dir_listing_matches`, `non_empty`, `enum`) and their
  per-kind parameters are Slice 4's — a structurally valid envelope with a
  `kind` string Slice 3 does not recognize is ACCEPTED by this store and rejected
  by Slice 4 at merge/load. That deferral is the pinned seam, not an oversight.

### D. The project-bound policy store

A store bound to exactly one project slug, exposing the policy family over the
existing revision envelope. It reuses Slice 2's project binding verbatim:
`workareas.validate_project_slug` (`workareas.py:101`), the `<base>/<slug>`
per-project backing directory (`workareas.py:372`), and Slice 1's
`RevisionEnvelopeStore` (`kvstore.py:460`) over `KeyBuilder.policy(id)`
(`kvstore.py:139`). Policies live in the SAME project KV backing as that
project's work areas — the `policy:<id>` key is namespaced but carries NO project
segment (the slug is the backing directory, exactly as Slice 2).

- **Put** validates the policy value (A/B/C) then writes it through the envelope;
  the first write reads back at envelope `revision: 1`, each later write bumps the
  revision monotonically, while the stored domain `version` changes only if the
  operator changed it (A).
- **Read** by id returns the validated policy for a live entry, `unknown` for a
  never-written or tombstoned key, and `malformed` for a stored value outside
  A/B/C or whose `id` field ≠ the key — never a repair write.
- **List** returns the live policies (envelope `exists?: true`) in key order,
  **skipping envelope tombstones**, and fails closed (no write) on any malformed
  stored value or key/id mismatch.
- **Delete** writes the standard envelope tombstone (Slice 1) — NOT agent_99's
  work-area tombstone; policies are OUR enveloped family. A subsequent read is
  `unknown` and the entry is excluded from `list`.
- **Authority is local-authoritative** (skeleton Shared Invariants): this store
  is the writer of record for `policy:<id>`; nothing auto-applies a server copy.

Revision-checked (CAS) updates are available from the envelope (Slice 1) if a
caller wants optimistic concurrency; the store's own surface is put/get/list/
delete, and richer concurrency control is the service's choice (Slice 7).

### E. The assembled project record

The workspace-shaped read model `{work_areas, policy, defaults}` for one bound
project (skeleton Slice 3 row; `project-concept.md` §"Concept"):

- `work_areas` — the live work-area records, from Slice 2's `list_records`
  (`workareas.py:406`) over the same project backing. Slice 3 adds no work-area
  logic; it composes the sealed store.
- `policy` — the live policy objects from D, in key order.
- `defaults` — an OPTIONAL object (acts/model preferences, docs_dir convention).
  It has **no KV family** — the key grammar is frozen and closed (Slice 1;
  fixture **I7**), so slice 3 introduces none. It is caller-supplied and, when
  present, must be a JSON-plain object; non-object values are rejected even when
  JSON-plain. When omitted it is absent from the record. Its inner keys are
  consumed by later slices (run-init defaults in Slice 5; authored and persisted
  by the service/panel in Slices 7/9) and are not constrained here — pinning them
  would add a contract with no slice-3
  consumer.

Assembly succeeds only when BOTH constituent lists succeed. If the work-area
list reports a malformed raw work-area entry, or the policy list reports a
malformed policy entry, the project read fails closed with that reason and
returns no partial `{work_areas, policy, defaults}` record; `defaults` is never
used as a fallback around malformed stored data.

The assembled record is the single "read the project" entry point Slice 5
(resolve `(project, work_area)` and read defaults), Slice 7 (`GET
/api/projects`), and Slice 9 (panel display) consume. Per-worker in-scope
policy selection stays on the scope-match/query seam consumed by Slice 4
(contract merge) and Slice 6 (PROJECT CONTEXT prompt block).

## Non-Goals

- **No verifier vocabulary, no contract merge, no enforcement.** The closed V1
  verifier set (`path_exists`, `citation_exists`, `dir_listing_matches`,
  `non_empty`, `enum`), the entry type-spec vocabulary, and the merge of in-scope
  contract fields into a worker's base kind contract in the repair-retry path are
  Slice 4 (I9). Slice 3 stores and structurally validates the `contract`
  declaration; it never runs a check or merges a field.
- **No concrete safeguard content.** The built-in `lpc-reuse-audit` policy (its
  real `prompt`, `entry`, and `checks`) is Slice 10's template. Slice 3 ships the
  GENERIC model only; the reuse-audit shape appears here purely as an
  illustrative valid policy.
- **No run, service, prompt, panel, or ledger wiring.** Run-init resolution and
  `project_resolved` (Slice 5), the PROJECT CONTEXT block and
  `project_safeguard_seen` (Slice 6), project/policy service endpoints (Slice 7),
  launch binding + `run:<id>/status` (Slice 8), and the panel + safeguard editor
  (Slice 9) all consume this model but are not built here. No existing production
  module changes.
- **No new KV family; no project-declaration or defaults persistence store.** The
  key grammar is frozen and closed (I7); slice 3 adds no `project:`/`defaults:`
  key and no service-level project registry. A project's identity is its backing
  slug (Slice 2); where a project is DECLARED with its defaults and enabled-policy
  selection is the service's surface (Slice 7). Slice 3's record is assembled, not
  a stored blob.
- **No automatic policy versioning.** `version` is operator intent, validated and
  stored verbatim; slice 3 never couples it to the envelope revision (I6).
- **Not the act-routing "policy".** `driver.py`'s per-act family policy
  (`driver.py:847`, which agent/model/effort runs an act) is an unrelated concept
  in a different module; slice 3's policy is the project SAFEGUARD object at
  `policy:<id>`. They never interact.
- **No migrations, compat shims, or tolerant readers** (greenfield, **I12**). The
  store is the only writer; a value outside A/B/C is reported malformed, never
  coerced or version-migrated. "Compatibility" means only: the id/version/enabled/
  scope handles align with agent_99's capability-policy concept for future fusion.

## Expected Files

- `orchestrator/projects.py` (new) — the policy value schema + validation (A/B/C),
  the scope-match predicate (B), the project-bound policy store over `policy:<id>`
  (D), and the project-record assembler (E). Built on `orchestrator/kvstore.py`
  (`RevisionEnvelopeStore`, `KeyBuilder.policy`) and `orchestrator/workareas.py`
  (`validate_project_slug`, `WorkAreaStore.list_records`, the `<base>/<slug>`
  binding); the scope vocabularies are imported from `orchestrator/contracts.py`
  (`KINDS`) and `orchestrator/state.py` (the unit-kind constants), not re-listed.
  A finer module split within the slice is the implementation's choice.
- `orchestrator/tests/test_projects.py` (new) — the pinning tests (standard
  library `unittest`; each store a `tempfile.TemporaryDirectory`, matching the
  repo convention).

No existing production file changes in this slice.

## Dependencies

- **Slice 1** (`orchestrator/kvstore.py`, sealed) — the revision envelope
  (`RevisionEnvelopeStore`), `KeyBuilder.policy` / `policy_key`, the JSON-plain
  value discipline, and the control-revision ⟂ domain-version rule (I6/I7).
- **Slice 2** (`orchestrator/workareas.py`, sealed) — the project binding
  (`validate_project_slug`, `<base>/<slug>` backing) and `WorkAreaStore.
  list_records`, composed by the project-record assembler.
- The existing vocabularies as single sources: `contracts.KINDS`
  (`contracts.py:48`) and the `state.py` unit-kind constants (`state.py:36`). The
  fixed-schema `contracts.validate_worker_output` (`contracts.py:217`) is the
  **I8** gap this milestone fills (contracts are fixed schemas today).
- The sealed skeleton (Shared Invariants; Slices row 3; Tests That Pin) and the
  pricing-pilot fixture (`implementation/brainstorming/
  project-concept-pricing-pilot.json`, **I8** `priced_ok`) — the frozen source of
  the policy-object shape and the versioned-policy rule.
- The reuse source re-read read-only as the (conceptual) compatibility target:
  `life_prod/agent_99/docs/cli-body-connector.md:88` — the versioned
  capability-policy concept (versioned; enabled, in-scope).
- No later slice is required for this one to land; the model is a standalone
  facility whose consumers (Slices 4, 5, 6, 7, 9) arrive later.

## Reuse Posture

- **Checked (this repo):** confirmed there is NO existing project/policy config
  model or store (`state.py:125` knows a single workspace path — the **I8**/I12
  gap; `contracts.py:217` validates fixed kinds only); the enveloped `policy:<id>`
  key already exists from Slice 1 (`kvstore.py:107`, `:139`) with no writer yet;
  the project binding + `list_records` already exist from Slice 2
  (`workareas.py:101`, `:372`, `:406`); the worker-kind vocabulary
  (`contracts.py:48`) and unit-kind constants (`state.py:36`); the pre-existing
  unrelated act-routing "policy" (`driver.py:847`), confirmed a distinct concept.
- **Checked (reuse source, read-only):** agent_99's versioned capability-policy
  concept (`cli-body-connector.md:88`) — "versioned policy object", "enabled,
  in-scope set".
- **Reused / extended:** the policy store is the sealed `RevisionEnvelopeStore`
  over the sealed `policy:<id>` key — no new storage subsystem, family, or CAS
  engine; the project binding and work-area listing are Slice 2's, composed
  verbatim by the assembler; the scope vocabularies are the existing
  `contracts.KINDS` + `state` unit constants, imported not re-declared (no new
  names); malformed-read/fail-closed and local-authoritative posture mirror
  Slices 1/2.
- **Adopted (conceptual compatibility target, NOT a byte-readable record):**
  agent_99's versioned-policy-object shape — the shared `id + version + enabled +
  scope` handles. Our `policy:<id>` family is OURS (agent_99 never reads it) and
  the `prompt`/`contract` payload is orchestrator-specific, so — unlike Slice 2 —
  there is deliberately no claim that an agent_99 reader decodes our policy.
- **New fixture-priced machinery, and why (not a parallel):** the concrete policy
  value schema + validation, the scope-match predicate, and the project-record
  assembler (the **I8** gap — orchestrator contracts are fixed schemas today). No
  new store, key family, or vocabulary is introduced.
- **Compatibility:** the `id/version/enabled/scope` handles align with agent_99's
  capability-policy concept, so a safeguard later becomes a workspace policy with
  zero translation of those handles; policies stay in OUR enveloped family, so no
  agent_99 reader is affected; the closed verifier boundary (Slice 4) is
  preserved because policies carry declarative JSON only — no code or shell.

## Proportionality (amendment A1)

The policy object, its versioning, scope matching, and contract-field declaration
are each pinned by **I8** and are not re-derived. New mechanism beyond that
invariant, with victims:

- **Project-record assembler (E).** VICTIM: Slice 5's run-init resolution (which
  reads the project to resolve a work area and defaults) and Slices 7/9 (which
  display the project); without it there is no single "read the project" surface
  and the policy store cannot be observed alongside work areas. Slice 4/6
  selection uses the separate scope-match/query seam, not the assembler.
  COST: a thin composition over Slice 2's `list_records` and the policy list plus
  an optional validated `defaults` pass-through — no new store, family, index, or
  background process. Anticipation of named next-slice consumers, KEPT and
  recorded per A1, not slice-boundary churn.
- **`defaults` in the assembled record.** VICTIM: Slice 5 (run-init acts/model/
  docs_dir defaults) and Slices 7/9 (authoring). It rides in the record shape the
  skeleton pins; it has no KV family (closed grammar) and no inner-key constraints
  (no slice-3 consumer for those). COST: one optional JSON-plain object validated
  and passed through — no persistence path, no new family. Not SPECULATIVE: the
  future consumer is named and the field is the skeleton's pinned record shape.

Nothing is SPECULATIVE and nothing requires operator approval. The capability
deliberately NOT built — enforcing the verifier/entry-type vocabulary at store
time — is omitted precisely because Slice 4 is its single source; duplicating it
here would create two vocabularies to keep in sync (see Risks).

## Acceptance Criteria

1. **Policy acceptance + closed key set + id↔key match (I8).** A valid policy
   with exactly `{id, version, enabled, scope, prompt, contract}` round-trips
   through the store; a stored value with a missing/extra top-level key, or whose
   `id` field ≠ the `policy:<id>` key fragment, is reported malformed by read/list
   with no repair write.
2. **Field domains.** `id` rejects blank, `/`, and control characters; `version`
   accepts only a positive integer and rejects `0`, negatives, booleans, and
   non-integers; `enabled` accepts only a boolean; `prompt` rejects blank; a value
   violating any domain is malformed.
3. **Scope vocabulary (I8).** `scope.kinds` accepts only members of
   `contracts.KINDS` and `scope.unit_kinds` only `skeleton`/`slice_doc`/
   `slice_impl`; an unknown member, an empty list, a non-list, or a `scope`
   missing either key or carrying any extra key is malformed. The vocabularies
   are read from `contracts.KINDS` and the `state` constants (a drift in those
   sources changes what validates).
4. **Scope-match contract (I8).** A policy matches `(worker_kind, unit_kind)` iff
   `enabled` and `worker_kind ∈ kinds` and `unit_kind ∈ unit_kinds`; a disabled
   policy, a non-member worker kind, and a non-member unit kind each fail to
   match; the store-level query returns exactly the enabled, in-scope policies for
   a pair.
5. **Contract envelope + no bare booleans (I8).** A `contract` with a non-blank
   `field`, `required: true`, a non-empty object `entry`, and a list `checks` of
   `{kind: str, …}` items is accepted; a `contract` object with a missing or
   extra key, blank/non-string `field`, `required: false`, an empty/non-object
   `entry`, an `entry` value that is not an object, non-list `checks`, or a
   `checks` item without a string `kind` is malformed. An absent top-level
   `contract` remains the closed top-level key-set failure covered by AC1. A
   structurally valid envelope whose `checks[].kind` is a token slice 3 does not
   recognize is ACCEPTED (the verifier vocabulary is Slice 4's; this pins the
   seam).
6. **Envelope round-trip + revision ⟂ domain version (I6).** First put reads back
   at envelope `revision: 1`, a rewrite at `revision: 2`; the stored domain
   `version` is unchanged across a rewrite that did not change it, and is stored
   verbatim when the operator changes it — the revision never derives it.
7. **List (live only) + delete tombstone.** `list` returns live policies in key
   order and skips envelope tombstones; `delete` writes the envelope tombstone
   (not the work-area tombstone), after which read is `unknown` and the policy is
   absent from `list`; a malformed stored value or key/id mismatch fails `list`
   closed with no write.
8. **Project record assembly (E).** The assembled record is
   `{work_areas, policy, defaults}`: `work_areas` equals Slice 2's live
   `list_records` for the bound project, `policy` equals the store's live policy
   list, `defaults` is the caller-supplied JSON-plain object when present and
   absent otherwise; a non-object or non-JSON-plain `defaults` is rejected. If
   either constituent list reports malformed stored data, assembly fails closed
   with no partial record.
9. **Project binding / isolation.** `policy:<id>` carries the namespace but NO
   project segment; two different bound project slugs hold independent policies,
   and the same policy `id` in two projects yields independent records, lists,
   tombstones, and assembled records.
10. **Greenfield fail-closed.** A stored policy outside A/B/C is reported
    malformed by read and list without any repair, migration, or tolerant-reader
    behavior; the store reads only what it wrote.
11. **No new family / grammar untouched.** The slice writes only `policy:<id>`
    (and reads Slice 2's work-area families); it defines no `project:`/`defaults:`
    key and imports Slice 1's `KeyBuilder.policy` rather than hand-assembling a
    key.
12. **Suite green.** `python3 -m unittest discover -s orchestrator/tests -t .`
    passes.

## Tests / Verification

In `orchestrator/tests/test_projects.py` (standard library only; each store a
`tempfile.TemporaryDirectory`):

- **Policy schema** — full acceptance and the closed top-level key set, id↔key
  match and mismatch-is-malformed (AC1); the field-domain matrix for id / version
  / enabled / prompt (AC2).
- **Scope** — vocabulary acceptance and rejection for `kinds` and `unit_kinds`
  including missing/extra-key, empty/non-list/unknown-member, and the `state` vs
  `DOC_UNIT_KINDS` distinction (AC3); the match matrix over enabled ×
  member-kind × member-unit and the store-level in-scope query (AC4).
- **Contract envelope** — accepted envelope, the no-bare-boolean rejections
  (missing/extra keys inside the `contract` object, blank/non-string `field`,
  `required: false`, empty/non-object `entry`, non-list `checks`, kindless
  `checks` item), and the deferred-vocabulary seam: an unrecognized
  `checks[].kind` is accepted here (AC5).
- **Storage** — envelope revision monotonicity and revision ⟂ domain-version
  independence (AC6); live-only listing in key order, delete → envelope tombstone
  → unknown read + list exclusion, and fail-closed list on malformed/mismatched
  values (AC7); greenfield malformed-read with no repair (AC10); `policy:<id>`
  written via `KeyBuilder.policy` with no project segment (AC11).
- **Project record** — assembly composing Slice 2's `list_records` and the policy
  list with an optional validated `defaults`, and the non-object/non-JSON-plain
  rejection plus fail-closed malformed-list propagation with no partial record
  (AC8);
  same-name isolation across two bound project slugs (AC9).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests
-t .` (AC12).

## Risks

- **Enforcing the verifier/entry-type vocabulary in slice 3** would duplicate
  Slice 4's single source, creating two vocabularies to keep in sync and
  contradicting "a new verifier kind is an orchestrator milestone." The
  deferred-seam test (AC5) is load-bearing.
- **Allowing `required: false` or an empty `entry` (a bare-boolean safeguard)**
  would reproduce the M26/M27 prose-warning failure **I8** exists to prevent — a
  slot statistically free to fill. The no-bare-boolean tests (AC5) are
  load-bearing.
- **Coupling the domain `version` to the envelope revision** would corrupt the
  `project_safeguard_seen` re-record semantics (Slice 6) and the fusion split
  (domain version ⟂ control revision, **I6**). The independence test (AC6) is
  load-bearing.
- **Inventing a `project:`/`defaults:` KV family or a project-declaration store**
  would break the frozen closed key grammar (**I7**) and the fusion namespace
  pump. Non-Goals + AC8/AC11 guard this; the assembler stays a read model.
- **A new (prose) scope vocabulary instead of `contracts.KINDS` / `state`
  constants** would drift from the driver's real kinds and units. The
  vocabulary-from-source test (AC3) is load-bearing.
- **Overclaiming byte-compatibility** with agent_99's capability policy (it is a
  conceptual target, not a reader of our enveloped family) would mislead the
  fusion work. The Reuse Posture states conceptual-only compatibility; no test
  asserts an agent_99 decode of a policy.
- **Building a tolerant reader / migration** for policies that cannot exist
  (greenfield, **I12**) is out of scope; the store reads only what it wrote
  (AC10).

## Line budget

Production code is expected to stay modest: the policy validator mirrors the
work-area validator's compact style, the store is thin over the sealed envelope,
and the assembler is a composition over Slice 2. As in Slices 1 and 2, the
pinning tests — the field-domain and scope matrices, the no-bare-boolean and
deferred-vocabulary seam, the revision ⟂ version independence, and cross-project
isolation that the future fusion and later slices depend on — carry the bulk, so
total changed lines may modestly exceed the ~500 target. That test surface is the
deliverable's point (**I8**), not incidental.
