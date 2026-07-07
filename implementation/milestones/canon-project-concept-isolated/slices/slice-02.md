# Slice 02 — Agent99-Compatible Work-Area Store

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice puts agent_99's full
work-area domain onto Slice 1's storage foundation: the raw
`refs/work_area:<name>` family carrying the verbatim agent_99 stored record,
its per-operation `version`/`status` state machine (create → `pending`,
confirm → `ready`, label-only rename, positive-version tombstone delete)
over **whole-value** CAS, plus the enveloped `work_area_meta:<name>`
reuse-source family beside it. It pins fixture invariants **I3**, **I4**,
and **I5**, and defines the store seam that Slice 5 (run-init resolution),
Slices 7/9 (service + panel work-area CRUD), and Slice 8 (launch binding)
consume. It changes NO run state, service, prompt, panel, or ledger, and
runs no filesystem validation of roots — those callers are later slices; the
store here governs descriptors only.

The compatibility target is agent_99's `Agent99.Body.WorkAreaStore`
(`life_prod/agent_99/apps/agent_99/lib/agent_99/body/work_area_store.ex`)
and `Agent99.Body.Root` (`.../body/root.ex`), read read-only. Every domain
and version claim below was verified against those sources and their tests;
the slice mirrors `WorkAreaStore`'s behavior **operation by operation**,
never a blanket rule.

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test, not by
reading the diff. Concrete identifiers are illustrative and the
implementation's choice; the pinned content is the stored record shape, the
per-operation `version`/`status` semantics, and the CAS/tombstone behavior a
future agent_99 reader depends on.

### A. The agent_99-compatible work-area record domain

The store is **project-scoped at the point-KV boundary**: callers bind/open it
for exactly one project slug (the local orchestrator's agent_99 workspace
equivalent), and all read/write/list/meta operations address work-area `name`s
inside that bound project scope. The project slug is **not** encoded in family
keys. Inside one project backing, the raw value at `refs/work_area:<name>`
(Slice 1's `raw_work_area_key`, never namespaced) is the verbatim agent_99
stored record: a serialization-stable **atom-keyed** map (stored through Slice
1's point-KV term codec, not the JSON envelope) with exactly the keys
`{name, display_name, primary, additional, executor_id, version, status}`
(`work_area_store.ex` moduledoc "Stored value" and `interpret/1`, lines
43–55 and 581–622). The values this store writes use agent_99's field
predicates while retaining the greenfield full-key requirement:

- `name` — a non-blank, valid-UTF-8 string, ≤128 bytes, containing no `/`
  and no control characters (`validate_name/1`, lines 687–698). This
  tightens Slice 1's fragment check (blank / `/` / control only) with the
  UTF-8 and ≤128-byte bounds, which Slice 1 explicitly left to this slice.
- `display_name` — a trimmed, non-blank, valid-UTF-8 string, ≤128 bytes,
  no control characters; slashes **are** allowed (`normalize_display_name/1`,
  lines 710–722). Leading/trailing whitespace is accepted only when trimming
  leaves a valid non-blank label, and read/relabel results expose the trimmed
  value. WE always write `display_name` and our store treats omission as
  malformed; agent_99's older-record default is cited only to explain the
  upstream reader, not to define local tolerance.
- `primary` and each element of `additional` — a `{path, device}` map where
  `path` is an **absolute, canonical** path (starts with `/`; no empty, `.`,
  or `..` segment; no trailing slash except the bare `/`), per
  `Root.new/2` (`root.ex` lines 31–44, `canonical?/1` lines 73–81), and
  `device` is a non-blank string or an integer (`scalar_device?/1`, lines
  727–730). The `primary` and `additional` roots are pairwise **distinct**
  by `{path, device}` (`distinct/1`, lines 732–735).
- `executor_id` — a non-blank string; here the local orchestrator's
  identity. Provenance is non-authoritative by agent_99's design, so its
  exact value is not a correctness contract, only its non-blankness is.
- `version` — a non-negative integer; a **validated domain field**, never
  the CAS token (see C).
- `status` — exactly one of `"pending" | "ready" | "unavailable"`
  (`@valid_statuses`, line 63). This slice's state machine drives `pending`
  and `ready` (and the tombstone); `"unavailable"` is a valid readable value
  in the domain but has no local writer here (see Non-Goals).

A stored value missing any key in the full domain above, including
`display_name`, or violating any predicate above is **malformed**: the reader
rejects it with no write rather than tolerating it. The only operation that
may replace a malformed stored value is an explicit **declare**, which writes a
fresh pending v1 declaration as specified in B/AC3. `primary`/`additional`
semantics (primary = the git repo the driver executes in; additional =
read-only grants) are recorded here but consumed by Slices 5/8.

### B. The write state machine (create · confirm · relabel · delete)

The store mutates a work area only through these operations; each pins an
observable `version`/`status` post-condition mirrored from `WorkAreaStore`
operation by operation. "Content" below means the `primary`, the
`additional` set (order-independent), or the `executor_id`.

- **Create / declare** against an absent, malformed, or tombstoned key →
  a fresh record at `status: "pending"`, `version: 1`
  (`declare_fun/3`, lines 406–444).
- **Identical re-declare** (same content) → the record **unchanged**: no
  `version` bump and the current `status` preserved — no downgrade of a
  `ready` (or `unavailable`) record (`same_declaration?/3`, lines 446–451;
  no-downgrade test, `work_area_store_test.exs` ~105–113).
- **Content-change declare** → the new roots at `status: "pending"` with
  `version` bumped by one, while preserving the existing `display_name`
  (`record.display_name`, lines 409–421).
- **Confirm / reconcile** transitions an existing well-formed record to
  `status: "ready"` only when the reported `primary` and `additional`
  descriptors equal the stored descriptors (including `device`, with
  `additional` order-independent); a mismatch returns `descriptor_mismatch`
  with **no write** (`descriptors_match?/3`, lines 564–566; mismatch test
  ~299–328). On a match it bumps `version` **iff** the `status` or
  `executor_id` actually changes — so a `pending` → `ready` confirm bumps
  `1 → 2`, a same-status confirm with a new `executor_id` bumps and stores the
  new provenance, and a re-confirm that changes neither preserves `version`;
  all successful confirms preserve the existing `display_name`
  (`transition_map/3`, lines 507–522; pending→ready bump test ~270–283;
  executor-change test ~351–362). It is **transition-only**: an absent,
  tombstoned, or malformed key → an error with **no write**; it never creates
  and never heals (`do_transition/6`, lines 467–502). The precondition that
  admits `ready` — the launcher's "`primary.path` is a git repo root" check —
  is Slice 7's; this store performs the transition on an already-validated
  work area.
- **Relabel** (display-name rename) changes `display_name` only, preserving
  `version`, `status`, roots, and `executor_id`; it is **not** a key rename,
  so the stable `name` (the key) is unchanged and remains the identifier
  (`display_name_map/2`, lines 524–534; version-preserving test ~114–127).
  Transition-only on the same absent/tombstoned/malformed keys.
- **Delete** writes agent_99's own path-free tombstone — the raw atom-keyed
  map `{name, deleted: true, version: prev_version + 1}` with a **positive**
  `version` (`tombstone_map/1`, lines 536–538; delete test asserting
  `version: 3` after declare→confirm→delete, ~455–470). This is **never**
  the Slice-1 revision-envelope tombstone: agent_99's reader recognizes only
  a `{name, deleted: true, version > 0}` record (`interpret/1`, lines
  581–583). Transition-only: delete of an absent, already-tombstoned, or
  malformed key → an error with no write.

### C. Whole-value CAS (no lost update)

Every mutation in B is applied by **whole-value** CAS on the raw family via
Slice 1's `LocalKVClient.cas(key, expected, value)` (`kvstore.py:343`),
comparing the **entire current stored record**, exactly as agent_99's
transitions CAS the whole value (`context.client.cas(..., value,
new_value)`, `work_area_store.ex:489`). The domain `version` is a validated
field, **not** the CAS token. Observable consequences:

- A concurrent change to the record causes a re-read/retry, never a silent
  overwrite. If the fresh record still satisfies the requested operation, the
  mutation applies to that fresh value; if the fresh record no longer qualifies
  (for example descriptor mismatch, unknown/tombstoned, or malformed), the
  operation returns that bounded error and writes nothing. No-lost-update does
  not mean every racing request succeeds.
- A **version-preserving** mutation (the relabel) still serializes correctly
  against a concurrent confirm or content-declare — proof that the whole
  value, not `version`, is the token. A `version`-only CAS (as a naive
  reading of the goal prose might build) would silently drop a
  label/status/provenance update at the same `version`; this is the specific
  loss I4's victim names.

### D. Read, resolve, and list

The read surface mirrors agent_99's inspection/resolution/listing so Slices
5, 7, and 9 can consume work areas, and so the domain-acceptance test can
round-trip records.

- **Read a record** by `name` → the full record for any live status only when
  the stored `name` equals the requested/key-derived name; a matching
  tombstone or absent key → an "unknown" result; a name mismatch or any other
  value outside domain A → a "malformed" result (`fetch_record/3`, lines
  234–245; `interpret_named/2`, lines 573–579).
- **Ready-gated resolve** → the work area's roots **only** when
  `status == "ready"`; a `pending` or `unavailable` record → a
  "not-ready" result (`fetch_work_area/3`, lines 215–232). This is the
  admission seam Slice 5 wires into run init.
- **List records** for a work-area set → the live records in key order,
  **skipping tombstones**, by reading Slice 1's local `list_entries` under the
  `refs/work_area:` prefix with values included and interpreting each value
  through domain A (`list_records/2`, lines 247–262; `read_list_item/2`,
  lines 351–378). A listed key is not necessarily live — the tombstone skip
  is the store's, matching Slice 1's "listings include tombstones" primitive.
  The list surface fails closed without repair writes for malformed stored
  values, invalid suffixes under the prefix, and key/name mismatches
  (`work_area_store_test.exs` lines 588–624).

### E. The `work_area_meta:<name>` reuse-source family

Beside the raw family, a **distinct**, **enveloped** family carries the
reuse-source role metadata for a work area's roots — the data that rides
BESIDE agent_99's fields, never inside them, and that agent_99 never reads.

- Stored and read through Slice 1's `RevisionEnvelopeStore`
  (`kvstore.py:460`) at `work_area_meta_key(name)` (`kvstore.py:100`), with
  the full revision-envelope semantics Slice 1 pins (stored
  `{revision, value, deleted?}`; public `{exists?, revision, value}`;
  monotonic revision; string-keyed JSON-plain value).
- The value is exactly a JSON object with one top-level `reuse_sources` list.
  Each source entry is an object with exactly the string fields
  `{"root": "<root>", "inventory": "<inventory>", "registry": "<registry>", "consumption": "<consumption>"}`.
  Per source: `root` names the work-area root the source lives at;
  `inventory` is the inventory to enumerate; `registry` is the registry to
  read; `consumption` is the sanctioned consumption model (submodule + path
  dep, hex, HTTP client…). Their reuse-audit consumption is Slice 10's, and
  verifier path-containment of `root` against actual roots is Slice 4's
  (`path_is_inside_roots`).

## Non-Goals

- **No service, panel, run, prompt, or ledger wiring.** Work-area CRUD
  endpoints and the launcher's git-repo-root reconcile precondition (Slice
  7), the panel surfaces (Slice 9), run-init resolution and
  `project_resolved` (Slice 5), and launch binding (Slice 8) all consume
  this store but are not built here. No existing production module changes.
- **No `mark_unavailable` operation.** agent_99 has one, but no local role in
  this milestone writes `"unavailable"` (the note maps only declare and
  reconcile locally). The status stays a valid readable domain value;
  building a writer with no named consumer would be SPECULATIVE.
- **No project record, policy object, or verifier.** The project record that
  aggregates work areas (Slice 3), the versioned policy objects (Slice 3),
  and the closed verifier vocabulary that path-checks citations (Slice 4)
  are separate slices. This slice stores work areas and their reuse-source
  metadata inside an already-bound project scope only.
- **No deep meta validation or cross-binding.** Enforcing `reuse_sources[].root`
  against a work area's actual roots, or validating the audit semantics of
  `inventory`/`registry`/`consumption`, belongs to Slices 4/10; adding a
  validation path here has no slice-2 victim.
- **No fusion transport.** The namespace pump that later ships our families
  into agent_99's datastore is future; this slice only guarantees the raw
  record, tombstone, and key already match agent_99's current reader.
- **No migrations, compat shims, or tolerant readers** (greenfield, I12).
  The store is the only writer; a value outside the full domain A (including
  omitted `display_name`) is reported as malformed by read/list/transition
  surfaces, never coerced or version-migrated. Explicit declare-over-malformed
  remains the create contract in B/AC3, not a migration path. "Older records
  may omit `display_name`" describes agent_99's reader, not our data — we
  always write the full domain.
- **No extra list-client hardening beyond Slice 1's local listing contract.**
  Malformed backend pages and non-progressing cursors are agent_99 client
  hazards, not greenfield local-store behavior here; this slice pins domain
  failures observable through its own point store.

## Expected Files

- `orchestrator/workareas.py` (new) — the agent_99-compatible work-area
  store bound to one project scope: domain A validation, the
  create/confirm/relabel/delete state machine (B) over the raw
  `refs/work_area:<name>` family via whole-value CAS (C), the
  read/resolve/list surface (D), and the enveloped `work_area_meta:<name>`
  family (E). Built entirely on `orchestrator/kvstore.py` (`LocalKVClient`,
  `RevisionEnvelopeStore`, `Atom`, the key builders); a finer module split
  within the slice is the implementation's choice.
- `orchestrator/tests/test_workareas.py` (new) — the pinning tests
  (standard library; each store a `tempfile.TemporaryDirectory`, matching
  the repo convention).

No existing production file changes in this slice.

## Dependencies

- **Slice 1** (`orchestrator/kvstore.py`, sealed) — the point-KV
  `LocalKVClient` (whole-value `cas`, term codec for atom-keyed raw records,
  `list_entries`), the `RevisionEnvelopeStore` for the meta family, `Atom`,
  and the `raw_work_area_key` / `work_area_meta_key` builders. This slice
  adds no new storage subsystem.
- The sealed skeleton (Shared Invariants; Slices row 2; Tests That Pin) and
  the pricing-pilot fixture
  (`implementation/brainstorming/project-concept-pricing-pilot.json`, **I3**,
  **I4**, **I5** `priced_ok`) — the frozen source of the record/version/
  tombstone shapes.
- The reuse sources re-read read-only as the compatibility target:
  `agent_99/.../body/work_area_store.ex` (stored value, per-operation
  version, whole-value CAS, tombstone, listing) and `.../body/root.ex`
  (path canonicality + scalar device).
- No later slice is required for this one to land; the store is a standalone
  facility whose consumers (Slices 5, 7, 8, 9, 10) arrive later.

## Reuse Posture

- **Checked (this repo):** Slice 1's `kvstore.py` — confirmed
  `LocalKVClient.cas` is whole-value (`:343`, `_point_values_match` `:205`),
  the `Atom` term codec stores atom-keyed maps uncoerced (`:236`–`:311`),
  `raw_work_area_key` is namespace-free (`:128`) and `work_area_meta_key`
  enveloped (`:100`), and `RevisionEnvelopeStore` supplies the meta family
  (`:460`); confirmed there is NO existing work-area / project store
  (`state.py:125` knows a single workspace path — I3/I12 gap); the
  unit-kind and generated-record conventions (`state.py:36`, `WORKSPACE.md`).
- **Checked (reuse sources, read-only):** `WorkAreaStore` (`interpret/1`
  domain, per-operation `transition_map` version rule, `tombstone_map`,
  `declare_fun` no-downgrade, `list_records`/`read_list_item`) and its tests
  (pending→ready bump, rename preserves version, positive-version tombstone);
  `Root.new/2` + `canonical?/1`.
- **Reused / extended:** the raw family, its whole-value CAS, and its
  listing are Slice 1's primitives — this slice adds only the domain layer
  (validation + the version/status state machine + the tombstone shape) on
  top; the meta family reuses `RevisionEnvelopeStore` verbatim, adding only
  the `{reuse_sources: [...]}` value shape.
- **Adopted verbatim (the compatibility target):** agent_99's full stored
  work-area domain, its per-operation `version` behavior, and its
  `{name, deleted: true, version}` positive-version tombstone.
- **New fixture-priced machinery, and why (not a parallel):** the
  domain-typed work-area store module (none exists — I3 gap `state.py:125`);
  the `work_area_meta` value shape over the existing envelope (I7 grammar /
  skeleton row 2). No new store, CAS engine, or listing path is introduced.
- **Compatibility:** the raw record, tombstone, and key are byte-/shape-
  identical to agent_99's current reader, so fusion stays a namespace-pump
  transport swap; the meta family is ours alone and agent_99 never reads it.

## Proportionality (amendment A1)

The record domain, whole-value CAS, per-operation version behavior, and the
positive-version tombstone are each pinned by invariants **I3**/**I4**/**I5**
and are not re-derived. New mechanism beyond those invariants, with victims:

- **Read/resolve/list surface (D).** VICTIM: Slice 5's run-init resolution
  (which needs the ready-gated roots to launch a run) and Slices 7/9 (which
  list and display work areas); without it the store is write-only and its
  own domain-acceptance test cannot round-trip a record. COST: thin reader
  functions over Slice 1's `get`/`list_entries` plus the domain-A interpret
  and the tombstone skip — no new listing protocol, cursor guard, store,
  index, or background process. This is anticipation of named next-slice
  consumers, KEPT and recorded per A1, not slice-boundary churn.
- **`work_area_meta:<name>` family (E).** VICTIM: Slice 10's reuse-audit
  (which reads `inventory`/`registry`/`consumption` per source) and Slices
  7/9 (which edit the reuse-source metadata); the reuse-source role must ride
  BESIDE agent_99's fields, so it cannot live in the raw record. COST: one
  value shape plus put/get wrappers over the existing `RevisionEnvelopeStore`
  — no new family machinery.

Nothing is SPECULATIVE and nothing requires operator approval. The one
capability deliberately NOT built — `mark_unavailable` — is omitted precisely
because it has no local writer/victim in this milestone.

## Acceptance Criteria

1. **Domain acceptance (I3).** A created or confirmed work area is stored as
   an atom-keyed raw value with exactly the keys
   `{name, display_name, primary, additional, executor_id, version, status}`,
   `primary`/`additional` as `{path, device}` maps; a domain reader
   implementing agent_99's `interpret/1` accepts it, and this store reports a
   value missing any full-domain key (including `display_name`) or violating
   any field predicate as malformed with no read/list/transition write. AC3
   separately pins declare-over-malformed as a fresh pending v1 write.
2. **Field domains.** `name` rejects blank, non-UTF-8, >128 bytes, `/`, and
   control characters; `display_name` rejects blank, non-UTF-8, >128 bytes,
   control characters, and omission, accepts slashes and trims surrounding
   whitespace on create defaults, relabel input, and read interpretation;
   `executor_id` rejects blank/whitespace-only and non-string values; `path`
   rejects non-absolute and non-canonical
   (`.`/`..`/empty segment, trailing slash) values; `device` accepts a
   non-blank string or an integer and rejects blank/other; duplicate roots
   are rejected; `status` accepts only `pending`/`ready`/`unavailable`;
   `version` accepts only a non-negative integer.
3. **Create → pending v1.** Declaring against an absent (or malformed, or
   tombstoned) key yields `status: "pending"`, `version: 1`.
4. **Identical re-declare is a no-op.** Re-declaring the same content leaves
   `version` and `status` unchanged, including no downgrade of a `ready` (or
   `unavailable`) record; a content change re-declares at `pending` with
   `version` bumped by one while preserving the existing `display_name`,
   including a changed `executor_id`, which stores the new provenance.
5. **Confirm → ready bump (I3).** A `pending` → `ready` confirm whose
   reported descriptors equal the stored descriptors sets `status: "ready"`
   and `version: 2`; a confirm changing neither status nor `executor_id`
   preserves `version`; a same-status confirm with a changed `executor_id`
   bumps `version` and stores the new provenance; every successful confirm
   preserves the existing `display_name`; a descriptor mismatch returns
   `descriptor_mismatch` and writes nothing; confirm of an absent, tombstoned,
   or malformed key returns an error and writes nothing (never creates or
   heals).
6. **Relabel preserves version (I3).** A display-name rename changes
   `display_name` only — `version`, `status`, roots, `executor_id`, and the
   `name` key unchanged; relabel of an absent/tombstoned/malformed key
   returns an error and writes nothing.
7. **Positive-version tombstone (I5).** Delete of a live record writes the
   raw atom-keyed `{name, deleted: true, version: prev+1}` with a positive
   `version` (e.g. `3` after declare→confirm→delete), never the envelope
   tombstone; a subsequent read returns unknown; delete of an
   absent/already-tombstoned/malformed key returns an error and writes
   nothing.
8. **Whole-value CAS / no lost update (I4).** Concurrent mutations of one
   work area serialize on the whole current value with no silent overwrite;
   a version-preserving relabel and a concurrent confirm both take effect when
   the fresh record still qualifies; a stale whole-value expectation loses and
   re-reads; if that fresh record is now descriptor-mismatched, unknown/
   tombstoned, or malformed, the operation returns the matching bounded error
   and writes nothing. `version` is never the CAS token.
9. **Read / resolve / list (D).** Read returns the full record for any live
   status only when the stored `name` matches the requested/key-derived name
   and returns unknown for a matching tombstone; ready-gated resolve returns
   roots only when `status == "ready"` and not-ready otherwise; name
   mismatches are malformed; list returns live records in key order, skips
   tombstones, and fails closed without writes for malformed stored values,
   invalid key suffixes, and key/name mismatches.
10. **Meta family (E).** `work_area_meta:<name>` round-trips the enveloped
    value
    `{"reuse_sources": [{"root": "lpc", "inventory": "docs/inventory.md", "registry": "docs/registry.md", "consumption": "submodule + path dep"}]}`
    with Slice 1's revision-envelope semantics (first read `revision: 1`,
    monotonic on rewrite), string-keyed and JSON-plain; each source is an
    object with the four string fields `root`, `inventory`, `registry`, and
    `consumption`; it is a distinct key family from the raw record and does
    not perturb it.
11. **Project scope / raw-key discipline.** The raw record and its tombstone
    are stored at `refs/work_area:<name>` with NO namespace or project segment,
    while `work_area_meta:<name>` is namespaced and enveloped; the two never
    share storage. Two different bound project scopes can both declare the same
    work-area `name` and retain independent raw records, tombstones, meta
    records, listings, and ready-gated resolves.
12. **Suite green.** `python3 -m unittest discover -s orchestrator/tests
    -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_workareas.py` (standard library only; each store
a `tempfile.TemporaryDirectory`):

- **Domain + validation** — full-domain acceptance and atom-keyed stored
  shape (AC1); the field-predicate matrix for name / display_name /
  executor_id / path / device / distinctness / status / version, including
  omitted `display_name` as malformed, display-name trim on create/relabel/read,
  and the ≤128-byte UTF-8 name bound beyond Slice 1's fragment check (AC2).
- **State machine** — create→pending-v1 (AC3); identical re-declare no-op +
  no-downgrade + content-change bump, including changed-executor provenance
  and `display_name` preservation on content-change declare (AC4); confirm
  pending→ready v2, `display_name` preservation, descriptor-mismatch/no-write,
  no-op-confirm version preserve, changed-executor version/provenance update,
  and transition-only errors (AC5); relabel preserving version/status/roots/key,
  trimming the input label, and its transition-only errors (AC6); the
  positive-version tombstone value, post-delete unknown read, and
  transition-only delete errors (AC7).
- **Concurrency** — whole-value CAS with no lost update across a racing
  relabel and confirm, a stale-expectation re-read that still qualifies, and a
  stale-expectation re-read that no longer qualifies and returns the bounded
  no-write error (AC8).
- **Read/resolve/list** — read for each status, ready-gated resolve,
  point-read key/name mismatch, tombstone-skipping listing in key order, plus
  fail-closed listing cases for malformed stored values, invalid key suffixes,
  key/name mismatches, and no repair writes (AC9).
- **Meta family** — enveloped round-trip of the `reuse_sources` shape with
  revision monotonicity and family separation from the raw record (AC10),
  the raw-vs-meta namespace/storage split, and same-name work areas isolated
  across two bound project scopes without adding a project segment to the raw
  key (AC11).

Full slice verification: `python3 -m unittest discover -s
orchestrator/tests -t .` (AC12).

## Risks

- **Enveloping the raw work-area record** (storing it through
  `RevisionEnvelopeStore` instead of the atom-keyed point-KV) would make
  agent_99's reader unable to decode it at fusion (I4 victim). The
  atom-keyed domain-acceptance test (AC1) is load-bearing.
- **Using `version` as the CAS token** — copying a version-only CAS from the
  goal prose — would silently drop a label/status/provenance update at the
  same `version` (I4 victim). The version-preserving-relabel-under-race test
  (AC8) is load-bearing.
- **Writing the Slice-1 envelope tombstone for a work-area delete** would
  leave a record agent_99's reader does not recognize as deleted (it reads
  only `{name, deleted: true, version > 0}`). The positive-version tombstone
  test (AC7) is load-bearing.
- **A blanket version rule** (always-bump, or descriptor-only) would make a
  future agent_99 consumer read label-only edits as material changes or see
  stale versions (I3 victim — the exact rule the fixture rejects). The
  per-operation version tests (AC4–AC6) are load-bearing.
- **A confirm/relabel/delete that creates or heals** instead of being
  transition-only would silently manufacture or repair a work area on a
  resolve-before-declare or a malformed value. The transition-only error
  tests (AC5–AC7) are load-bearing.
- **Name validation weaker than agent_99's** (>128 bytes, control chars,
  non-UTF-8) would admit a record agent_99 rejects as malformed at fusion.
  The name-bound test (AC2) is load-bearing.
- **Building tolerant readers, migrations, or `mark_unavailable`** for data
  or roles that cannot exist here (greenfield, I12; no local unavailable
  writer) is explicitly out of scope; the store reads only what it wrote.

## Line budget

Production code is expected to stay modest: the domain validation mirrors
agent_99's `interpret` compactly, and the operations are thin over Slice 1's
whole-value CAS and envelope store. As in Slice 1, the pinning tests — the
per-operation version matrix, the whole-value-CAS no-lost-update proof, the
positive-version tombstone, and full domain acceptance that future fusion
depends on — carry the bulk, so total changed lines may modestly exceed the
~500 target. That test surface is the deliverable's point (I3, I4, I5), not
incidental.
