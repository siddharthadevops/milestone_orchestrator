# Slice 01 — Local KV Store + Key Grammar

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice delivers the
storage foundation every later slice builds on: a local, file-backed KV
that honors LPC's revision-envelope CAS contract for OUR families, the
reserved-namespace key grammar (including the agent_99-native raw
work-area key that is never namespaced), and the root-containment
predicate that keeps verifier/citation paths inside granted work-area
roots. The point primitive stores LPC-safe terms; the envelope adapter
then narrows OUR families to JSON-plain values. It pins fixture invariants
**I6** and **I7** and defines the seams
Slices 2 (raw work-area family), 3/8 (policy + run projections), and 4
(verifiers) consume. It writes NO family values and wires into no run,
service, prompt, or ledger — those are later slices.

## Scope (observable contracts)

Four foundations. Each statement is falsifiable by a named test, not by
reading the diff. Illustrative identifiers are marked; the pinned content
is the semantics and the on-the-wire key/record shapes a later slice or
agent_99 depends on.

### A. Point-KV Client primitive (the shared seam)

Mirrors LPC `Client`'s datastore primitives (put/get/cas/list_entries —
`life_prod/.../life_product_workspaces/lib/life_product_workspaces/client.ex:82`).
This is the single point store both the envelope adapter (B) and Slice 2's
raw work-area family build on; there is no parallel store.

- Keys are binary strings; values are stored and echoed verbatim. The point
  primitive accepts JSON-plain values and the atom-keyed LPC-safe term maps
  the raw `refs/work_area:<name>` family needs; the reserved **absent**
  marker is not a storable value.
- `get(key)` returns the stored value or a reserved **absent** marker,
  distinct from every storable value, for a never-written key.
- `cas(key, expected, value)` writes `value` iff the current stored value
  equals `expected` (the absent marker = create-only), else reports a
  **conflict** and does not write. Comparison is WHOLE-VALUE — this is the
  primitive Slice 2 uses for `refs/work_area:<name>`, where the domain
  `version` is a validated field, NOT the CAS token.
- Each successful point-store `put` or `cas` assigns a positive native
  entry `rev` (first write `1`, then `+1`); a failed CAS does not bump it.
  This `rev` is listing metadata only, not the envelope revision or a
  domain `version`.
- `list_entries(opts)` mirrors LPC's page shape: `{items, next_cursor}`,
  sorted by key after optional `prefix` and exclusive `cursor`, limited by
  `limit`; each item carries `{key, rev}` and also `value` when
  `include_values` is true (`client.ex:34-44`, `:96-98`). It returns live
  and tombstoned keys alike — a listed key is not necessarily live (LPC's
  native listing rule). Any live-only filtering is a
  documented wrapper on top, never the primitive's behavior.
- **Atomic write visibility.** A concurrent reader never observes a torn
  or partial value; a write becomes visible all-or-nothing.
- **Serialized writers.** Concurrent writers serialize; a CAS that raced
  another writer loses with a conflict, never a silent overwrite. Where
  the backing lives and how it locks is the implementation's choice.
- **File-backed persistence.** Reopening the store against the same backing
  directory preserves point entries, native `rev` metadata, envelope
  revisions, and envelope tombstones; an in-memory-only implementation does
  not satisfy this slice.

### B. Revision-envelope adapter (OUR families only)

Adopts LPC `Cas` verbatim as the compatibility target
(`life_prod/.../life_product_workspaces/lib/life_product_workspaces/cas.ex:9`,
`:31`). Applies to `work_area_meta:`, `policy:`, and `run:*` — the
families agent_99 never reads. It does NOT apply to `refs/work_area:`
(stored raw, Slice 2).

- Two distinct shapes. STORED envelope: `{revision: positive int, value,
  deleted?: bool}`. PUBLIC read record: `{exists?: bool, revision: nil |
  positive int, value}`.
- Never-written read → `{exists?: false, revision: null, value: null}`.
- First write → revision `1`; each later write → monotonic `+1`
  (`cas.ex:11`).
- Envelope CAS takes the **expected revision**: `null` = create-only
  (matches a never-written key only); a positive int must equal the
  current revision. A stale expectation performs no write and returns a
  distinguishable **revision-mismatch** carrying the current public read
  record (so the caller can re-read and retry).
- Delete writes a **tombstone** (`deleted?: true`, revision incremented),
  never a physical removal (`cas.ex:16`). A tombstoned read →
  `{exists?: false, revision: <kept, = prev+1>, value: null}`, and the key
  still appears in listings. A tombstone is NOT the never-written state:
  its revision is the CAS expectation for any subsequent write, so a
  create-only (`null`) CAS does not match a tombstone.
- The control **revision is independent** of any domain `version` inside
  the value (`cas.ex:13`): a value carrying its own `version` field never
  perturbs the envelope revision, and vice versa.
- Values are **JSON-plain, string-keyed, and serialization-stable**: only
  JSON scalars, lists, and maps with string keys are accepted; a stored
  value round-trips byte-identically. This restriction is adapter-level
  for OUR enveloped families only; it does not constrain the point
  primitive or the raw work-area family.

### C. Key grammar + reserved namespace

Pins the exact key strings later slices write and the single namespace
config point (I7).

- **One reserved-namespace constant**, default `milestone_orchestrator`,
  a single configurable key segment (non-empty UTF-8, no `/`, no control
  characters; final name TBD). It qualifies OUR families only as the byte
  prefix `<namespace>/`.
- **Our families** (qualified by the namespace, enveloped per B) have these
  default on-wire keys: `milestone_orchestrator/work_area_meta:<name>` ·
  `milestone_orchestrator/policy:<id>` ·
  `milestone_orchestrator/run:<run_id>/status` ·
  `milestone_orchestrator/run:<run_id>/digest`. With a non-default
  namespace, only the segment before `/` changes. The `digest` key is
  **RESERVED** here — this slice defines the builder and reserves the
  string; no writer or reader is built (the endpoint is the machine-api
  milestone's).
- **Raw family** (NEVER namespaced): `refs/work_area:<name>` — byte-
  identical to agent_99's fixed reader key `Datastore.ref_key("work_area:"
  <> name)` (`life_prod/.../life_product_workspaces/lib/life_product_workspaces/datastore.ex:63`).
  It carries no namespace segment so that at future fusion it pumps to
  that exact native key and agent_99's reader can see it.
- Key builders are the **single source** for these strings; no other
  module hand-assembles a family key.
- The builders reject blank `name`/`id`/`run_id` fragments and any fragment
  containing `/` or control characters; the exact validation of a work-area
  `name` against agent_99's domain (≤128 bytes, etc.) is Slice 2's, not
  this slice's.

### D. Root-containment predicate

The path-safety seam Slice 4's verifiers (`path_exists`,
`citation_exists`, `dir_listing_matches`) and the citation check consume;
skeleton-assigned to this slice (skeleton §Slices row 1, §Tests That Pin).
Pure, no I/O beyond resolving the path.

- A predicate over `(candidate_path, roots)` where each root is an
  absolute, canonical path. Returns true iff the candidate **resolves
  inside one of the roots**.
- A relative candidate resolves against a root; an absolute candidate is
  taken as given.
- Escapes return false: `..` traversal above a root, an absolute path
  outside every root, and a symlink whose real (canonicalized) target
  escapes every root. An empty root set → false.

## Non-Goals

- **No family value schemas.** The `work_area_meta` value
  (`{reuse_sources: [...]}`), the policy object, and the run-status
  projection shape are Slices 2/3/8. This slice treats family payloads as
  opaque values: JSON-plain through the envelope adapter for OUR families,
  and LPC-safe raw terms through the point-store primitive for the raw
  work-area family.
- **No raw work-area logic.** Domain validation, the pending→ready version
  bump, the display-name rename, and agent_99's `{name, deleted: true,
  version}` tombstone are Slice 2. This slice provides only the
  LPC-safe-term whole-value-CAS primitive that family will use.
- **No verifiers.** The closed V1 verifier vocabulary and the contract-
  extension merge are Slice 4. This slice provides only the containment
  predicate they call.
- **No wiring.** No run-init resolution, `GET /api/projects`, panel
  surface, PROJECT CONTEXT block, or ledger events (Slices 5–10). No
  existing production module changes.
- **No digest, no fusion transport.** The `digest` key is reserved only;
  the namespace pump / transport swap is future. This slice only
  guarantees the shapes already match (envelope = LPC's reader; raw key =
  agent_99's native key).
- **No migrations, compat shims, or tolerant readers** (greenfield, I12).
  The adapter reads only envelopes it wrote; there is no legacy/variant
  toleration and no corrupt-record recovery path for data that cannot
  exist. "Compatibility" here means exactly: our shapes match agent_99's /
  LPC's CURRENT readers.
- **Not the durable source of truth.** The store holds only descriptors
  and projections; run ledgers stay in `.orchestrator/state.json` and
  milestone/gate history in git. A wipe of the store loses nothing.

## Expected Files

- `orchestrator/kvstore.py` (new) — the point-KV Client primitive, the
  revision-envelope adapter, the key grammar (namespace constant + key
  builders), and the root-containment predicate. (A finer module split
  within the slice is the implementation's choice; this is the natural
  home. The four seams above must be importable; the key builders and
  containment predicate are pure/deterministic, while the point-KV and
  envelope seams are stateful storage APIs with deterministic observable
  behavior for a given backing state.)
- `orchestrator/tests/test_kvstore.py` (new) — the pinning tests
  (standard library, every backing store a `tempfile.TemporaryDirectory`,
  matching the repo convention).

No existing production file changes in this slice.

## Dependencies

- The sealed skeleton (Shared Invariants **I6**, **I7**) and the pricing-
  pilot fixture
  (`implementation/brainstorming/project-concept-pricing-pilot.json`, I6
  and I7 `priced_ok`) — the frozen source of the envelope/grammar shapes.
- LPC reuse sources re-read read-only as the compatibility target:
  `cas.ex` (revision envelope), `client.ex` (primitives + native listing),
  `datastore.ex` (`ref_key`).
- Repo idioms available to reuse: `orchestrator/registry.py` (atomic
  temp+rename plus advisory `fcntl.flock` serialization) and
  `orchestrator/state.py` (`save_new` exclusive create; `save` atomic
  replace).
- No later slice is required for this one to land; the store is a
  standalone facility.

## Reuse Posture

- **Checked (this repo):** `registry.py:8` (atomic temp+rename + advisory
  flock, `:88`); `state.py:239` (`save_new`) / `:264` (`save`) atomic
  writes; confirmed there is NO existing KV / datastore / envelope module
  (grep empty); the single-workspace-path run model (`state.py:125`), the
  I6/I12 gap this slice fills.
- **Checked (reuse sources, read-only):** LPC `Cas` (envelope shapes +
  revision/tombstone semantics), `Client` (put/get/cas/list_entries +
  native listing includes tombstones), `Datastore` (`ref_key` for the raw
  family).
- **Reused / extended:** the atomic temp+rename + advisory-flock idiom
  (`registry.py`) provides atomic write visibility and serialized writers
  — no new atomicity subsystem is invented; the single point-KV Client
  primitive is shared by both the envelope adapter (our families) and
  Slice 2's raw family, so there is no parallel store.
- **Adopted verbatim (the compatibility target):** LPC's revision-envelope
  stored/public shapes and semantics; the exact
  `refs/work_area:<name>` native key.
- **New fixture-priced machinery, and why (not a parallel):**
  a local file-backed project KV (none exists — I6 gap `state.py:125`);
  the reserved-namespace key grammar + builders (new — I7 gap); the
  root-containment predicate (new — I7 cost line "root containment
  checks").
- **Pulled-forward Slice-2 seam (A1-accounted below, not fixture-priced):**
  the point-store's small LPC-safe-term codec for the raw work-area seam
  (needed so Slice 2 can use the same point store for atom-keyed
  `refs/work_area:` values instead of adding a second raw store or coercing
  agent_99-readable records into JSON).
- **Compatibility:** the envelope shapes match LPC's current reader and
  the raw key is byte-identical to agent_99's fixed reader, so fusion
  stays a transport swap; the store exposes only data APIs plus the pure
  containment predicate (no code/shell surface), preserving the no-injection
  boundary a later verifier slice relies on.

## Proportionality (amendment A1)

The KV store, revision envelope, key grammar, and containment predicate
are each named in I6/I7's payload and cost lines; atomic visibility and
serialized writers reuse `registry.py`'s existing idiom rather than adding
a subsystem. This slice also pulls forward one Slice-2 seam:

- **LPC-safe-term point-value codec.** VICTIM: Slice 2's raw
  `refs/work_area:` family and future fusion with agent_99's atom-keyed
  WorkAreaStore reader; without this codec, the shared point store would
  either coerce raw records into string-keyed JSON or force a second raw
  storage path. COST: a small `Atom` wrapper plus encode/decode branches
  and one focused raw-work-area CAS/listing test; no new file, service,
  background process, config surface, or second store.

Nothing is SPECULATIVE and nothing requires operator approval. The only
other latitude taken — a reserved but unwritten `digest` key — adds one
string constant, not a mechanism, and the skeleton already mandates
reserving it.

## Acceptance Criteria

1. **Envelope round-trip.** A first write reads back `{exists?: true,
   revision: 1, value}` with the value byte-identical; a second write to
   the same key reads `revision: 2`. A JSON-plain, string-keyed value
   round-trips stably; non-JSON values and maps with non-string keys are
   rejected without writing.
2. **Never-written read** returns `{exists?: false, revision: null,
   value: null}`.
3. **Envelope CAS.** Create-only (`expected = null`) succeeds on a
   never-written key and fails on a present one; `expected =
   current_revision` succeeds and bumps the revision; a stale expectation
   performs no write and returns a distinguishable revision-mismatch
   carrying the current public read record.
4. **Tombstone delete.** Delete yields a read `{exists?: false, revision:
   prev+1, value: null}`; the key still appears in `list_entries`; a
   create-only (`null`) CAS does NOT match the tombstone, and a write
   against the tombstone's revision succeeds at `prev+2`.
5. **Revision ⟂ domain version.** A value that contains its own `version`
   field does not change the envelope revision across writes, and bumping
   the envelope revision does not touch the stored `version` field.
6. **Point-KV primitive (Slice-2 seam).** `put` followed by `get` returns
   the stored value; a never-written `get` returns the reserved absent
   marker, distinct from every storable value; `cas(key, expected_value,
   new_value)` writes iff the current stored value equals `expected_value`;
   successful `put`/`cas` bump a native listed `rev` while failed CAS does
   not; `list_entries` returns LPC-shaped sorted pages with `items`,
   `next_cursor`, `{key, rev}`, optional `value`, prefix/cursor/limit
   behavior, and tombstoned keys; a raced writer receives a conflict, never
   a silent overwrite; an atom-keyed raw work-area map can be stored,
   listed, and whole-value-CASed without being coerced to a string-keyed
   JSON object.
7. **Atomic visibility + serialized writers.** Under concurrent writers no
   reader observes a torn/partial value, and of two racing create-only
   writes exactly one wins.
8. **Listings include tombstones.** `list_entries` returns live and
   tombstoned keys alike; live-only filtering, if present, is a separate
   documented wrapper, not the primitive.
9. **File-backed persistence.** After reopening a store from the same
   backing directory, previously written point values, native listed `rev`
   values, envelope public reads, envelope revisions, and envelope
   tombstones are unchanged.
10. **Key grammar.** With the default namespace, the builders emit exactly
   `milestone_orchestrator/work_area_meta:<name>`,
   `milestone_orchestrator/policy:<id>`,
   `milestone_orchestrator/run:<run_id>/status`,
   `milestone_orchestrator/run:<run_id>/digest`, and
   `refs/work_area:<name>`; a non-default namespace replaces only the
   segment before `/`; invalid namespace/name/id/run_id fragments are
   rejected; `refs/work_area:<name>` is byte-identical to
   `Datastore.ref_key("work_area:" <> name)` and carries NO namespace
   segment.
11. **Root containment.** A path inside a root → true; `..`-escape,
    absolute-outside, and symlink-escape → false; a relative candidate
    resolves against a root; an empty root set → false.
12. **Suite green.** `python3 -m unittest discover -s orchestrator/tests
    -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_kvstore.py` (standard library only; each
backing store a `tempfile.TemporaryDirectory`):

- **Envelope semantics** — round-trip and monotonic revision (AC1),
  JSON-plain/string-keyed value rejection (AC1), never-written record
  (AC2), the full CAS matrix incl. stale-expectation revision-mismatch
  carrying the current record (AC3), tombstone read + listing + non-match
  of create-only + rewrite-against-tombstone (AC4),
  revision-vs-domain-version independence (AC5), and serialization
  stability (round-trip byte-identity).
- **Point-KV primitive** — put/get, the reserved absent marker, atom-keyed
  raw work-area term storage, whole-value CAS write/conflict, native `rev`
  bumps only on successful writes, LPC-shaped paged listings with
  prefix/cursor/limit and optional values (AC6), and
  listings-include-tombstones (AC8).
- **File-backed persistence** — reopen from the same temporary backing
  directory and verify point values, native `rev` metadata, envelope reads,
  envelope revisions, and tombstones survive unchanged (AC9).
- **Concurrency** — concurrent writers never yield a torn read and exactly
  one of two racing create-only writes wins (AC7).
- **Key grammar** — exact default namespaced bytes for our four families,
  namespace replacement limited to the first segment, invalid-fragment
  rejection, and byte-identity of `refs/work_area:<name>` with the cited
  agent_99 native key with no namespace (AC10).
- **Root containment** — inside/relative accepted; `..`-escape,
  absolute-outside, symlink-escape, and empty-root-set rejected (AC11).

Full slice verification: `python3 -m unittest discover -s
orchestrator/tests -t .` (AC12).

## Risks

- **Namespacing or enveloping the raw `refs/work_area:` family** would
  hide work areas from agent_99's fixed reader at fusion (I7 victim). The
  byte-identity test (AC10) is load-bearing.
- **Filtering tombstones inside the list primitive** would break Slice 2's
  tombstone visibility and any consumer that must see deletes. The
  listings-include-tombstones test (AC8) is load-bearing.
- **Returning only keys from the list primitive** would break agent_99's
  work-area listing consumer, which drains LPC-shaped pages and reads
  `{key, value, rev}` rows. The paged listing test (AC6) is load-bearing.
- **Coercing the point primitive to JSON-only storage** would make the raw
  `refs/work_area:` family lose agent_99's atom-keyed safe-term shape.
  The raw-term whole-value-CAS test (AC6) is load-bearing.
- **Unstable envelope serialization or accepting outside the JSON-plain,
  string-keyed value domain for OUR families** would silently break the
  future LPC-compatible byte pump. The envelope value-domain and
  serialization-stable round-trip tests (AC1) are load-bearing.
- **A containment predicate that resolves without canonicalizing symlinks**
  would let a verifier path escape a granted root (I7 victim). The
  symlink-escape test (AC11) is load-bearing.
- **Conflating the control revision with the domain `version`** would
  corrupt CAS and future fusion. The independence test (AC5) is
  load-bearing.
- **Over-building a tolerant / corrupt-record reader** for data that
  cannot exist (greenfield, I12) is explicitly out of scope; the adapter
  reads only what it wrote.

## Line budget

Production code is expected to stay modest (~300 lines: the point-KV
primitive, the envelope adapter, the key builders, and the containment
predicate). The pinning tests — the milestone's foundational
envelope/CAS/tombstone/atomicity/concurrency/grammar/containment semantics
that every later slice depends on — carry the bulk, so the total changed
lines may modestly exceed the ~500 target. This is the deliberate cost of
Slice 1 being the pinned storage foundation (I6, I7); the test surface is
the point, not incidental.
