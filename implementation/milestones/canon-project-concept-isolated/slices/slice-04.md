# Slice 04 — Verifier Vocabulary + Contract-Extension Merge

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This slice makes safeguards BITE: it
delivers the closed V1 verifier vocabulary and the merge of an in-scope policy's
required contract field into a worker's base kind contract, enforced in the
**existing** repair-retry path (`orchestrator/runners.py` `call_worker`, one
retry then `WorkerProtocolError`). It supplies the two vocabularies Slice 3
deliberately deferred — the entry type-spec tokens inside `contract.entry` and
the check kinds inside `contract.checks` — plus the compile step that turns a
Slice-3-structural policy into an enforceable extension, and the merged validator
that binds a worker's output to the base kind contract PLUS the extension. It
pins fixture invariant **I9** and defines the contract half that Slice 6
activates together with the PROJECT CONTEXT prompt; Slice 5 only supplies the
resolved `(project, work_area)` and roots that Slice 6 consumes. Slice 10's
built-in reuse-audit policy is the first real load. It ships NO concrete
safeguard content, NO project resolution, NO prompt rendering, and NO
panel/service surface.

**This is the first slice to touch existing production code.** Slices 1–3 were
standalone facilities; enforcement is not. I9 pins the CLOSED vocabulary and the
EXISTING repair-retry path (`runners.py:389` frequency; `contracts.py:272`
ecosystem gap — "repair-retry validation but no project extension registry or
verifier vocabulary"). Honoring "use the existing repair-retry path" means the
merge runs at the SAME point as `contracts.validate_worker_output` and raises the
SAME `contracts.ContractError`, so a failed check is indistinguishable from a
malformed base contract to the retry logic. The change is **inert until wired**:
`call_worker` gains an optional in-scope-extensions argument that defaults to
absent, and with none supplied its behavior is byte-identical to today. Slice 6
populates that argument in the same worker calls where it renders the safeguard
obligation; Slice 5 only makes the resolved project/work-area context available.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md` §"Closed verifier vocabulary
V1", §"Policy object", §"Prompt and gate machinery" rules 4–5), read read-only.
The vocabulary NAMES and the policy-object shape are adopted verbatim; the
enforcement SEMANTICS below (the type-spec value rules, the per-entry check
quantification, the config-vs-worker error split, the field-collision rule) are
this slice's design, consistent with I9 and pinned by tests. Unlike Slice 2's
byte-readable agent_99 record, none of this is an agent_99-readable shape:
extensions are OUR enforcement layer over OUR policy family (`policy:<id>`),
which agent_99 never reads.

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test, not by reading the
diff. Concrete identifiers are illustrative and the implementation's choice; the
pinned content is the closed vocabularies, each verifier's pass/fail semantics
against a real filesystem, the config-vs-worker error split, and the merge's
enforcement in the existing repair-retry path — the seams Slices 6 and 10
depend on. Throughout, the extension's output value is a **list of entry
objects** (the enumeration the no-bare-boolean rule demands); a check's `field` /
`match_field` names a **sub-field declared in `contract.entry`**.

### A. The entry type-spec vocabulary (closed)

Slice 3 stored `contract.entry` as a non-empty object mapping declared field
names to type-spec objects but left the type-spec CONTENT unvalidated, assigning
its legality here (slice-03.md §C; `projects.py:98` `_validate_contract`). The
closed set of legal per-field type-specs — a new spec is an orchestrator
milestone, never project config:

- `{"type": "string"}` — the worker value for this field must be a `str`.
- `{"type": "citation"}` — the worker value must be a `str` shaped
  `<path>:<line>`: a non-empty path half and a `<line>` that is a positive
  integer, split on the LAST colon. This is a STRUCTURAL shape check with no
  filesystem access; existence is the `citation_exists` check's job (B).
- `{"enum": [<strings>]}` — a non-empty list of strings; the worker value must
  equal one of them.

All value matching is **type-exact**: a JSON boolean, integer, float, list,
object, or null never satisfies `{"type": "string"}`/`{"type": "citation"}`, and
never matches an `{"enum": …}` member even by Python truthiness (the exact
bool-vs-int hazard the sealed Slice-1 CAS finding names). A type-spec that is not
one of the three tokens above — an unknown `type`, a non-list/empty/non-string
`enum`, an object carrying both `type` and `enum`, or extra keys — is a **policy
config error** (C), never a worker error. Per-entry structural validation of a
worker output: the extension field's value is a list; each item is an object
whose key set **exactly equals** the declared entry field names (no missing, no
extra); each value satisfies its declared type-spec.

### B. The closed verifier check vocabulary (closed)

The whole V1 set (`project-concept.md` §"Closed verifier vocabulary V1"); a new
kind is an orchestrator milestone, never project config. Each check quantifies
over the entries of the extension field. Filesystem checks resolve paths through
Slice 1's `path_is_inside_roots` (`kvstore.py:596`) against the work-area roots
the caller supplies (D). Absolute paths are evaluated as written. Relative paths
must be **unambiguous** across the work area: exactly one granted root may contain
an **existing** target at that relative path. If the target exists at the same
relative path under more than one root, a worker-authored path/citation is a
worker `ContractError`, while an operator-authored `dir_listing_matches.root` is
a non-repairable config error.

- `non_empty(field)` — passes iff the extension list has **at least one entry**
  AND every entry's `field` value is a non-blank string. This is the
  "missing/short audit is rejected at the contract layer" guard; the other
  per-entry checks pass VACUOUSLY on an empty list, so a safeguard that must
  forbid an empty enumeration pairs them with `non_empty` (or
  `dir_listing_matches`, which fails set-equality against a non-empty directory).
- `enum(field, values)` — every entry's `field` value equals one of `values`
  (type-exact). `values` is a non-empty list of strings.
- `path_exists(field)` — every entry's `field` value is a path that resolves to
  an **existing** filesystem path **inside a work-area root**. A path that does
  not exist, or that escapes every root, fails.
- `citation_exists(field)` — every entry's `field` value is a `<path>:<line>`
  citation whose **path half exists inside a work-area root**. An ill-shaped
  citation, a nonexistent path, or an escaping path fails. The **line number is
  NOT verified** against the file's length (goal: "the path half of `file:line`
  exists") — a valid path with an out-of-range line passes.
- `dir_listing_matches(root, match_field)` — the **set** of `match_field` values
  across all entries **equals** the set of immediate child names of the directory
  named by `root`: every direct filesystem entry in that directory, including
  files, subdirectories, symlinks, and dotfiles, with no recursion and no
  synthetic `.` / `..` entries. Set EQUALITY, not subset: a missing enumerated
  child (under-enumeration — the exact M26/M27 incomplete-inventory failure) and
  an invented child (over-enumeration) both fail.

### C. Policy compile and the config-error class

The compile step turns a Slice-3-validated policy (`projects.validate_policy_value`,
whose `contract` envelope is `{field, required, entry, checks}` —
`projects.py:98`, `CONTRACT_KEYS` `:21`) into an enforceable extension, running
the vocabulary legality Slice 3 deferred (slice-03.md §C: "a structurally valid
envelope whose `checks[].kind` is a token Slice 3 does not recognize is ACCEPTED
… and rejected by Slice 4 at merge/load"). A policy that fails any rule below is
a **non-repairable config error** — a DISTINCT failure surfaced to the operator,
NEVER a worker repair prompt (I9 victim: "the operator … harmed if project
config can inject code/shell or pass unverifiable reuse claims"). Compile
rejects:

- an `entry` type-spec outside the closed set of A;
- a `checks[].kind` outside the five of B; a check missing or carrying extra
  parameters for its kind (`field`; `field`+`values`; `root`+`match_field`); an
  `enum` check whose `values` is not a non-empty list of strings; a `field` or
  `match_field` that does not name a declared `entry` sub-field; a
  `dir_listing_matches.root` that is not a non-empty string;
- an extension `field` that collides with a **base-kind reserved output key**
  for any kind in the policy's `scope.kinds`, or two in-scope extensions that
  share a `field` (an ambiguous merge). Slice 4 exposes the base-kind reserved
  output keys from `contracts` as the single source, kept beside
  `validate_worker_output` and pinned by tests; `verifiers.py` consumes that
  source and never re-lists the keys.

Root-containment of the operator-authored `dir_listing_matches.root` is enforced
when the work-area roots are available (D): a `root` that resolves OUTSIDE every
granted root is a non-repairable config error (the operator's mistake), distinct
from a worker citation that escapes (D). Config and operational errors are
outside `call_worker`'s repairable exception family, so they surface to the
operator without a worker retry. Projects compose declarative JSON over these
closed primitives only; there is no code, shell, regex, or callable a policy can
inject (I9's no-injection boundary).

### D. The merge and enforcement in the existing repair-retry path

Given the compiled extensions the caller selected as in-scope for a worker call
(via Slice 3's `policy_matches` / `PolicyStore.in_scope`, `projects.py:165`,
`:244`) and the work-area roots, the merged contract is the base kind contract
(`contracts.validate_worker_output`, `contracts.py:217`) PLUS, for each in-scope
extension, its `field` as a REQUIRED output key holding a list of entries
conforming to A, with every check of B passing. Observable enforcement:

- **Merge is additive and ok-only.** A validly **blocked** output is exempt
  (it produced no artifact to audit), mirroring the base contract's early return
  on `status: "blocked"`. An out-of-scope call is unaffected: the caller supplies
  no extension for it, and validation is byte-identical to today.
- **Same error, same one retry.** Any extension violation — the field absent, a
  non-list value, an entry whose key set or a value's type-spec is wrong, or any
  failed check — raises `contracts.ContractError` at the SAME point as the base
  validation, inside `call_worker`'s existing `try/except`. The driver's ONE
  repair retry then applies exactly as for a malformed base contract; a second
  failure raises `WorkerProtocolError` with both raw texts, unchanged.
- **The `call_worker` seam (Slice 6 consumes).** `call_worker` gains an OPTIONAL
  parameter carrying the in-scope compiled extensions and the roots; absent or
  empty ⇒ unchanged behavior. Slice 6 populates it only for worker calls whose
  prompt also carries the safeguard obligation; this slice supplies it directly
  in tests to prove enforcement in the real path.
- **Worker-authored path containment.** A worker citation or path that escapes
  every granted root is a WORKER contract violation (→ repair), so an audit can
  never "prove" reuse against a file the run was not granted (I7/I9). This splits
  by authorship from C's operator-root config error.

### E. Operational faults are not worker faults

A `dir_listing_matches` whose `root` is inside a granted root but is **absent or
not a directory** on disk cannot be satisfied by any worker output. It raises a
DISTINCT non-repairable operational error (surfaced like a config error), not a
`contracts.ContractError` or any exception class caught for worker-output repair
— so the driver never burns a repair retry, then a `WorkerProtocolError`, blaming
a worker for a missing reuse-source directory. The worker retry loop stays
meaningful: workers are only ever asked to repair things they authored (their
enumeration and citations).

## Non-Goals

- **No project resolution, no prompt rendering, no ledger.** Resolving the
  project/work-area roots at run init (Slice 5, `project_resolved`), selecting
  and passing the in-scope extensions while rendering the safeguard obligation
  into the worker prompt at operator-amendment authority (Slice 6, PROJECT
  CONTEXT + `project_safeguard_seen`), and the precedence of amendments over
  safeguards (Slice 6) are separate slices. This slice enforces whatever compiled
  extensions it is handed; it neither selects nor renders them.
- **No concrete safeguard content.** The built-in `lpc-reuse-audit` policy — its
  real `prompt`, `entry`, and `checks`, and the review-side concur/dissent
  field — is Slice 10. Slice 4 ships the GENERIC vocabulary + merge; the
  reuse-audit shape appears here only as an illustrative valid policy.
- **No new verifier kind or entry type beyond V1.** The five checks and three
  type-specs are the whole set; extending them is an orchestrator milestone, not
  project config (I9). No regex, content-diff, cross-file, or line-range verifier.
- **No content semantics.** Verifiers check existence, listing, enumeration, and
  shape — never whether a cited line SAYS what the audit claims. Semantic
  verification is the reviewer's duty (goal rule 4: "Reviewers verify semantics;
  the driver verifies existence"); the review-side dissent field is Slice 10.
- **No new storage, key family, or CAS.** Extensions are compiled from the sealed
  `policy:<id>` family (Slice 3); this slice writes no KV entry and adds no family
  to the frozen grammar (I7).
- **No parallel validator or second retry path.** Enforcement reuses
  `call_worker`'s single repair retry; building a separate validation loop with
  its own retry would fork I9's pinned "exactly one repair retry" semantics.
- **No migrations, compat shims, or tolerant readers** (greenfield, **I12**). A
  policy outside the closed vocabulary is a config error, never coerced;
  "compatibility" here means only that the vocabulary and merge honor I9's frozen
  contract.

## Expected Files

- `orchestrator/verifiers.py` (new) — the entry type-spec vocabulary and
  per-value validation (A), the five verifier checks (B), the policy→extension
  compiler and the non-repairable config/operational error class (C/E), and the
  merged-output validator that raises `contracts.ContractError` for
  worker-authored violations (D). Built on `orchestrator/kvstore.py`
  (`path_is_inside_roots`), `orchestrator/contracts.py` (`ContractError`, `KINDS`,
  and the base-kind reserved output keys as the single source), and
  `orchestrator/projects.py` (the validated policy / `contract` shape and the
  scope predicate). A finer module split is the implementation's choice.
- `orchestrator/runners.py` (edit) — `call_worker` gains the optional in-scope
  extensions + roots argument so the merged validation runs inside the existing
  repair-retry `try/except`; default absent ⇒ unchanged behavior.
- `orchestrator/contracts.py` (edit, minimal) — expose the per-kind reserved
  output-key sets beside `validate_worker_output` so the compiler derives
  collisions from the protocol's single source rather than re-listing it (a small
  helper or constants are both acceptable; no re-listing in `verifiers.py`).
- `orchestrator/tests/test_verifiers.py` (new) — the pinning tests (standard
  library `unittest`; each filesystem check a real `tempfile.TemporaryDirectory`,
  matching the repo convention), including a `call_worker`/`MockRunner`
  integration test for the repair-retry behavior.

## Dependencies

- **Slice 1** (`orchestrator/kvstore.py`, sealed) — `path_is_inside_roots`
  (`:596`), the containment predicate every filesystem check calls; no new
  path-safety predicate is introduced.
- **Slice 3** (`orchestrator/projects.py`, sealed) — the validated policy value
  and the structural `contract` envelope `{field, required, entry, checks}`
  (`:98`, `:21`) whose vocabulary legality was DEFERRED here, and the scope
  predicate `policy_matches` / `PolicyStore.in_scope` (`:165`, `:244`) the caller
  uses to choose the in-scope extensions.
- `orchestrator/contracts.py` — `ContractError` (`:70`, the shared worker-error
  vocabulary the merge reuses so the existing retry applies unchanged),
  `validate_worker_output` (`:217`) and `KINDS` (`:48`), and its per-kind output
  keys as the single source of base-kind reserved names.
- `orchestrator/runners.py` — `call_worker` and its one-repair-retry loop
  (`:380`–`:404`; the enforcement point I9 pins at `:389`), and `MockRunner`
  (`:310`) for the integration test.
- The sealed skeleton (Shared Invariants; Slices row 4; Tests That Pin) and the
  pricing-pilot fixture
  (`implementation/brainstorming/project-concept-pricing-pilot.json`, **I9**
  `priced_ok` — evidence `contracts.py:272`, `runners.py:389`) — the frozen
  source of the closed-vocabulary / repair-retry / no-injection contract.
- The frozen goal re-read read-only as the contract source: `project-concept.md`
  §"Closed verifier vocabulary V1", §"Policy object", §"Prompt and gate
  machinery" rules 4–5.
- Consumers arriving later (not required for this slice to land): Slice 5
  (resolve project/work-area roots), Slice 6 (render the obligation prompt block
  and populate the matching extensions for that same worker call; amendments win
  on conflict), Slice 10 (the built-in reuse-audit policy — the first real
  vocabulary load).

## Reuse Posture

- **Checked (this repo):** confirmed there is NO existing verifier vocabulary or
  contract-extension mechanism (grep for `path_exists`/`citation_exists`/
  `dir_listing_matches` is empty — the **I9** gap); the base schema validator
  `contracts.validate_worker_output` (`:217`) validates fixed kinds only, with the
  report-kind branch at `:272` (the fixture's I9 gap citation); the single-retry
  enforcement path `call_worker` (`runners.py:380`–`:404`, `WorkerProtocolError`
  on the second failure); Slice 1's `path_is_inside_roots` (`kvstore.py:596`);
  Slice 3's structural `contract` envelope and scope predicate (`projects.py:98`,
  `:165`, `:244`) that hand this slice exactly the deferred vocabulary + merge.
- **Checked (contract source, read-only):** the frozen `project-concept.md` gate
  machinery (closed verifier vocabulary; declarative-JSON, no-code-injection
  rule; the policy-object example) and fixture **I9**.
- **Reused / extended:** the merge runs INSIDE `call_worker`'s existing repair
  retry, not a parallel validator, and raises `contracts.ContractError`, so the
  one-retry-then-`WorkerProtocolError` semantics are unchanged; filesystem checks
  reuse Slice 1's `path_is_inside_roots` verbatim; the base-kind reserved keys are
  derived from `contracts`, not re-listed; the compiler consumes Slice 3's
  already-validated `contract` envelope and adds only the vocabulary legality and
  enforcement Slice 3 explicitly deferred.
- **Adopted verbatim (the contract target):** the closed V1 verifier names and
  the policy-object `contract` shape from the frozen goal.
- **New machinery, and why (the I9 gap, not a parallel):** the entry type-spec
  and check vocabularies with their value/pass-fail semantics; the compiler and
  its config-error class; the merged validator and its `call_worker` hook. None of
  this exists today (`contracts.py:272` validates fixed kinds only, with no
  extension registry or verifier vocabulary).
- **Compatibility:** projects compose declarative JSON over a CLOSED vocabulary —
  no code/shell/regex injection (I9 victim); a new verifier kind is an
  orchestrator milestone; worker citations and operator roots are confined to the
  granted work-area roots (I7). The extension layer is OURS over the `policy:<id>`
  family agent_99 never reads, so no agent_99 reader is affected.

## Proportionality (amendment A1)

The closed vocabulary, the declarative-JSON no-injection posture, the merge, and
the "existing repair-retry path" are each pinned by **I9** and are not
re-derived. New mechanism beyond that invariant, with victims:

- **The optional `call_worker` extensions hook (touches existing production
  code).** VICTIM: Slice 6, whose rendered obligation must be ENFORCED in the
  same worker call, not merely displayed; without a hook in the existing retry
  path, enforcement forks into a parallel validator with its own retry — the
  exact anti-pattern I9 forbids ("use the existing repair-retry path"). COST: one
  optional argument defaulting to absent (no behavior change for any current
  caller) plus the merged-validate call inside the existing `try/except`. This is
  anticipation of a named next-slice consumer, KEPT and recorded per A1; the
  change is inert until Slice 6 wires prompt and enforcement together.
- **The config/operational error class, distinct from worker `ContractError`.**
  VICTIM: the operator (I9's named victim) — a malformed policy (C) or a missing
  reuse-source directory (E) must fail loudly to the operator, not be mis-sent to
  a worker as a repair it cannot satisfy, burning a retry and then blaming the
  worker via `WorkerProtocolError`. COST: one non-repairable error class plus the
  branch routing config/operational faults outside the worker retry.
- **Root-containment on worker-authored paths and citations (D).** VICTIM: the
  operator / local machine (I7/I9) — a citation pointing outside the granted roots
  would let an audit "prove" reuse against a file the run was never granted. COST:
  reuses Slice 1's `path_is_inside_roots`; no new predicate.
- **Relative-path ambiguity checks for worker paths/citations and operator-authored
  `dir_listing_matches.root` (B/AC6-AC8).** VICTIM: the operator and reviewer — if
  the same relative target exists under multiple granted roots, an audit or
  inventory check could validate against whichever root resolution tries first,
  including the wrong reuse-source directory. COST: one deterministic
  multi-root-resolution check on top of the same containment predicate, plus the
  AC6-AC8 ambiguity tests; no new verifier kind.
- **The field-collision check (C/AC9), which Slice 3 deferred here as "a MERGE
  concern" (slice-03.md §C).** VICTIM: the base kind contract — an extension
  `field` named `findings` or `artifact` would silently shadow a base output key,
  and two in-scope policies sharing a `field` would make the merge ambiguous. COST:
  one comparison against reserved keys DERIVED from `contracts` (no re-listing), so
  it cannot drift from the real protocol.

Nothing is SPECULATIVE and nothing requires operator approval. The capability
deliberately NOT built — a content-reading verifier (does the cited line SAY what
the audit claims?) — is omitted because the goal assigns semantic verification to
human review; building it here would duplicate the reviewer's duty and exceed the
"driver verifies existence" boundary.

## Acceptance Criteria

1. **Entry type-spec legality (compile).** A `contract.entry` whose every
   type-spec is one of `{"type": "string"}`, `{"type": "citation"}`,
   `{"enum": [<non-empty strings>]}` compiles; an unknown `type`, a non-list /
   empty / non-string `enum`, an object carrying both `type` and `enum`, or extra
   keys is a config error (not a worker error). This is the Slice-3 deferred-seam
   validation.
2. **Entry type-spec worker validation (type-exact).** `{"type": "string"}`
   accepts a `str` and rejects a bool/int/float/list/object/null;
   `{"type": "citation"}` accepts `<path>:<positive-int>` (split on the last
   colon, non-empty path half) and rejects an ill-shaped string, a non-str, or a
   non-integer/zero/negative line; `{"enum": […]}` accepts a listed string and
   rejects a non-member and a truthy-but-non-string value. Each entry must be an
   object whose keys exactly equal the declared field names (a missing or extra
   key fails).
3. **Verifier kind legality (compile).** Each of `non_empty`, `enum`,
   `path_exists`, `citation_exists`, `dir_listing_matches` compiles with its
   correct parameters; an unknown kind, missing/extra parameters for a kind, a
   `field`/`match_field` not naming a declared entry sub-field, a non-string /
   empty `enum.values`, or a non-string / empty `root` is a config error.
4. **`non_empty` semantics.** An empty extension list fails; a list with an entry
   whose `field` is a blank string fails; a non-empty list whose every entry has a
   non-blank string `field` passes.
5. **`enum(field, values)` semantics.** Every entry's `field` in `values`
   (type-exact) passes; any entry with an out-of-set or wrong-typed value fails.
6. **`path_exists(field)`.** Every entry's `field` resolving to an existing path
   inside a work-area root passes; a nonexistent path fails; a path escaping every
   root is a worker `ContractError` (not a config error); a relative path that
   exists under more than one granted root fails as ambiguous.
7. **`citation_exists(field)`.** A `<path>:<line>` whose path half exists inside a
   root passes; an ill-shaped citation, a nonexistent path half, and an escaping
   path half each fail; the LINE number is not verified — an existing path with an
   out-of-range line passes; a relative path half that exists under more than one
   granted root fails as ambiguous.
8. **`dir_listing_matches(root, match_field)`.** Set equality between the
   `match_field` values and all direct filesystem entries in the directory
   (files, subdirectories, symlinks, and dotfiles; no recursion) passes; a missing
   child (under-enumeration) and an invented child (over-enumeration) each fail; an
   operator `root` escaping every granted root is a config error; a `root` that is
   absent or not a directory is an operational error DISTINCT from a worker
   `ContractError` and from `call_worker`'s repairable exception set (AC11 shows
   it is not retried as a worker fault); a relative `root` that exists under more
   than one granted root is a config error.
9. **Field collisions (compile/merge), single source.** An extension `field`
   equal to a base-kind reserved output key for any kind in `scope.kinds` is a
   config error; two in-scope extensions sharing a `field` is a config/merge
   error; the reserved-key set comes from `contracts` (a change to the exposed
   protocol keys changes what collides), not re-listed in `verifiers.py`.
10. **Merge presence, shape, and ok-only (worker).** An in-scope `status: "ok"`
    output missing the extension field, or whose value is not a list, or whose
    entry set/shape violates A, raises `contracts.ContractError`; a validly
    `blocked` output is exempt; an out-of-scope call (no extension supplied) is
    validated byte-identically to today.
11. **Enforcement in the existing repair-retry path.** Driving `call_worker` with
    a supplied extension and a first output that fails a check triggers exactly
    ONE repair retry (as a malformed base contract does); a second failure raises
    `WorkerProtocolError`; a repaired second attempt returns the validated output;
    with NO extensions supplied, `call_worker` is byte-identical to today. The
    operational error of AC8 (missing directory) does NOT enter this retry loop.
12. **Suite green.** `python3 -m unittest discover -s orchestrator/tests -t .`
    passes.

## Tests / Verification

In `orchestrator/tests/test_verifiers.py` (standard library only; each filesystem
check a real `tempfile.TemporaryDirectory` — the file-backed lesson from Slice 1's
seal history):

- **Type-spec vocabulary** — compile acceptance of the three tokens and the
  config-error matrix (unknown type, malformed enum, both-keys, extra keys) (AC1);
  the type-exact worker-value matrix for string / citation / enum and the exact
  entry key-set rule (AC2).
- **Check vocabulary legality** — compile acceptance of the five kinds and the
  config-error matrix for unknown kind, wrong/missing params, undeclared
  `field`/`match_field`, bad `enum.values`, and non-string / empty `root` (AC3).
- **Verifier semantics** — `non_empty` empty-list and blank-value rejection (AC4);
  `enum` type-exact matching (AC5); `path_exists` exist / not-exist / root-escape
  / ambiguous-relative-path against real files in multiple roots (AC6);
  `citation_exists` shape parse, path-half existence, escape, line-not-verified,
  and ambiguous-relative-path (AC7); `dir_listing_matches` set-equality against
  files, subdirectories, symlinks, and dotfiles with under- and over-enumeration,
  operator-root escape (config), ambiguous relative root (config), and
  missing-directory (operational, distinct from worker error) against real
  directories in multiple roots (AC8).
- **Merge** — field/base-key and duplicate-`field` collisions with the
  reserved-key set derived from `contracts` (AC9); presence/shape enforcement, the
  blocked-output exemption, and the out-of-scope no-op (AC10).
- **Repair-retry integration** — a `MockRunner` script driving `call_worker` with
  an extension: one repair retry on a first failed check, `WorkerProtocolError` on
  a second, a repaired second attempt succeeding, the missing-directory
  operational error not entering the retry loop (asserting the runner is called
  once), and byte-identical behavior with no extensions supplied (AC11).

Full slice verification: `python3 -m unittest discover -s orchestrator/tests -t .`
(AC12).

## Risks

- **Validating a bad policy as a WORKER repair** (instead of a config error) would
  send the operator's mistake to a worker that cannot fix it and then blame the
  worker (I9 operator victim). The config-vs-worker split tests (AC1/AC3/AC8/AC9)
  are load-bearing.
- **A parallel validator with its own retry** (instead of `call_worker`'s single
  repair retry) would fork I9's "exactly one repair retry" semantics. The
  `call_worker` integration test (AC11) is load-bearing.
- **Non-type-exact value matching** (a bool matching a string enum, `1` matching
  `true`) — the exact class of the sealed Slice-1 CAS finding — would let fake
  content pass a required slot. The type-exact tests (AC2/AC5) are load-bearing.
- **A subset (not set-equality) `dir_listing_matches`** would miss
  under-enumeration — the precise M26/M27 incomplete-inventory failure this
  milestone exists to prevent. The over/under-enumeration tests (AC8) are
  load-bearing.
- **Verifying the citation LINE** (not just the path half) would over-reach beyond
  I9 and reject a valid citation to a moved line. The line-not-verified test (AC7)
  is load-bearing.
- **Skipping root-containment on worker paths/citations** would let an audit cite
  outside the granted roots (I7 victim). The escape tests (AC6/AC7) are
  load-bearing.
- **Accepting ambiguous relative paths across multiple granted roots** would let
  an audit validate against whichever root an implementation happens to try
  first. The multi-root ambiguity tests (AC6-AC8) are load-bearing.
- **Opening the vocabulary to code/shell/regex** (an eval'd or regex-injected
  check) would breach I9's no-injection boundary. The closed-vocabulary
  config-error tests (AC1/AC3) are load-bearing; this slice adds no verifier that
  executes operator-supplied logic.
- **Re-listing the base-kind reserved keys in `verifiers.py`** (instead of
  deriving them from `contracts`) would drift from the real protocol and let a
  colliding extension field slip through. The single-source collision test (AC9)
  is load-bearing.
- **Building a tolerant reader / migration** for policies that cannot exist
  (greenfield, **I12**) is out of scope; the compiler reads only Slice 3's
  validated policy shape.

## Line budget

Production code is expected to stay modest: the type-spec and check vocabularies
are compact dispatch, the compiler is a walk over Slice 3's already-validated
envelope, the merged validator is a thin layer over `contracts.validate_worker_output`,
and the `call_worker` hook is a few lines. As in Slices 1–3, the pinning tests —
each verifier's pass/fail matrix, type-exactness, the config-vs-worker error
split, the field-collision single-source rule, and the repair-retry integration
that Slices 6/10 depend on — carry the bulk, so total changed lines may modestly
exceed the ~500 target. That test surface is the deliverable's point (**I9**), not
incidental.
