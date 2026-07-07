# Slice 09 — Built-in Reuse-Audit Safeguard

Status: draft — pending review.

Milestone: canon-project-concept-isolated. This is the **payoff slice**: the
generic machinery of Slices 1–8 gets its first concrete load — the
reuse-audit safeguard, shipped as a **built-in template any project can
enable and parameterize** (goal deliverable (6), `:289`–`:290`). Enabling it
gives a project two standing policy objects over the sealed pipeline: the
**planning-side `reuse_audit` contract field** (an enumerated adopt/gap/reject
audit with `file:line` evidence, mechanically checked against a REAL
directory listing of the audited source) and the **review-side contract
field** carrying one concur/dissent entry per audited package with the
reviewer's own `file:line` citation (skeleton row 10, `skeleton.md:177`). It
pins fixture invariant **I11** — the priced gap "current prompts require
Reuse Posture, not a per-package adopt/gap/reject audit with mechanical
slots" — and closes the milestone's last Tests-That-Pin entry ("the built-in
reuse-audit planning and review contract fields", `skeleton.md:202`–`:203`).
This is the M26/M27 lesson made executable: the under-enumeration that
rebuilt ~2,300 sealed lines becomes a contract violation the driver rejects
before any reviewer reads a word.

Numbering reconciliation (per sealed slice-07 `:20`–`:32` and slice-08
`:20`–`:25`): the run ledger titles THIS unit "Built-in reuse-audit
safeguard" — the sealed skeleton's table row 10 (`skeleton.md:177`); what
earlier sealed notes call "Slice 10" or "the reuse-audit slice" lands here.
It is the ledger's final slice.

The compatibility target is the frozen goal contract
(`implementation/brainstorming/project-concept.md`, frozen at `45f6968`),
read read-only: the **policy-object example** (`:219`–`:236`) — the
`lpc-reuse-audit` document whose scope, field, entry, and checks this
template adopts VERBATIM (bootstrap rule (a): "the drafter COPIES them,
never re-derives", `:298`–`:299`) — and the gate machinery: the mandatory
planning audit and its content rules (`:314`–`:321`), the review duties
(`:322`–`:328`), the no-bare-boolean and driver-verifies-existence rules
(`:329`–`:343`), and the declarative-JSON policy bundle (`:344`–`:355`).
Policy semantics are SEALED and consumed as-is: validation and storage
(slice-03), the closed vocabulary, compile, merge, and repair-retry
enforcement (slice-04), rendering, `project_safeguard_seen`, and fail-closed
standing law (slice-06), the service gates (slice-07), and the authoring
routes and editor (slice-08). The template's concrete content, the
parameterization shape, and the enablement mechanics are this slice's
design, consistent with those pins and pinned by tests.

**Amendment A3 is this slice's governing scope pin**: implement EXACTLY to
the sealed skeleton contract and no further — the two fields are a FIRST
CONCRETE SAFEGUARD, deliberately minimal; no extensible schema variants, no
generalization hooks, no future-proofing of the field shapes (a planned
successor process will generalize the FORM). The lasting value to get RIGHT
is the **per-project parameterization** (the audited inventory a project
attaches — which sealed repos/packages must be checked, with their root and
registry paths) and the **enablement mechanics**; the template's default
inventory is EMPTY with one documented example. Every design decision below
is resolved toward that pin.

Like every slice since 4, the change is **additive and inert until used**:
nothing auto-enables the template (a fresh project's policy list stays
`[]`), no sealed module's semantics move, project-less runs and
template-less projects are byte-identical to today, and this milestone's own
bootstrap run — project-less by the goal's Bootstrap note — is untouched.

## Scope (observable contracts)

Five contracts. Each statement is falsifiable by a named test or, where the
panel is involved, by the slice-08 observation levels (served-page markers +
the API contracts every control calls). The pinned content is the two
instantiated policy objects, the parameter domain, the phrase-level prompt
content, the enable route's behavior, and the end-to-end enforcement the
template produces through the sealed pipeline. Concrete module and handler
names are the implementation's choice; the route path, body shape, refusal
tokens, policy ids, field names, and stored shapes below are public API for
the panel, operators, and the successor process.

### A. The template pair (two sealed-valid policy objects)

Instantiating the template for parameters `(source, inventory, registry,
version)` yields EXACTLY two policy objects. The **planning policy** is the
frozen goal example (`:222`–`:235`) with exactly two substitutions — the id
(rationale below) and the parameterized root:

```json
{"id": "reuse-audit", "version": <version>, "enabled": true,
 "scope": {"kinds": ["draft_skeleton", "draft_slice_note"],
           "unit_kinds": ["skeleton", "slice_doc"]},
 "prompt": "<the planning procedure, contract C>",
 "contract": {
   "field": "reuse_audit", "required": true,
   "entry": {"source": {"type": "string"},
             "package": {"type": "string"},
             "decision": {"enum": ["adopt", "gap", "reject"]},
             "evidence": {"type": "citation"}},
   "checks": [{"kind": "citation_exists", "field": "evidence"},
              {"kind": "dir_listing_matches",
               "root": "<inventory>", "match_field": "package"}]}}
```

The **review policy** is the minimal contract form of skeleton row 10's
review sentence and goal `:322`–`:328` — same entry discipline, decisions
swapped to the reviewer's vocabulary, same two mechanical checks over the
SAME inventory:

```json
{"id": "reuse-audit-review", "version": <version>, "enabled": true,
 "scope": {"kinds": ["review_round", "delta_review", "seal_half"],
           "unit_kinds": ["skeleton", "slice_doc"]},
 "prompt": "<the review duties, contract C>",
 "contract": {
   "field": "reuse_audit_review", "required": true,
   "entry": {"source": {"type": "string"},
             "package": {"type": "string"},
             "decision": {"enum": ["concur", "dissent"]},
             "evidence": {"type": "citation"}},
   "checks": [{"kind": "citation_exists", "field": "evidence"},
              {"kind": "dir_listing_matches",
               "root": "<inventory>", "match_field": "package"}]}}
```

Pinned properties, each a named test:

- **Sealed-valid and compile-clean as a pair.** Both objects pass
  `projects.validate_policy_value` (`projects.py:133`) unchanged, and the
  PAIR compiles through `verifiers.compile_extensions` (`verifiers.py:211`)
  with no config error — fields collide with no base-kind reserved output
  key (`contracts.reserved_output_keys`, `contracts.py:321`) and not with
  each other. The template adds NOTHING to the closed vocabulary: three
  existing type-spec forms, two existing check kinds, existing scope
  vocabularies only.
- **Fixed ids, deliberately not source-derived.** The pinned ids are
  `reuse-audit` and `reuse-audit-review` — the goal example's `lpc-` prefix
  is part of its ILLUSTRATION (the concept is "fully generic … nothing
  about any particular ecosystem is built in", goal `:35`–`:37`), not the
  schema. Source-derived ids would let a re-parameterization mint a SECOND
  pair whose duplicate `reuse_audit` field makes every in-scope worker call
  a sealed config error (`_require_distinct_fields`, `verifiers.py:199`) —
  a standing law that fails every planning run. Fixed ids make re-enable an
  overwrite of the same two documents, structurally.
- **Review scope covers the full report vocabulary.** `scope.kinds` for the
  review policy is exactly `contracts.REPORT_KINDS` (`contracts.py:59`):
  goal `:325`–`:327` binds "the review contract" unqualified, and a fixer
  may edit the note's audit table — the delta review is the reviewer that
  judges exactly that edit. Both scopes take `unit_kinds`
  `["skeleton", "slice_doc"]`: the audit is planning-altitude law (goal
  `:314`); `slice_impl` units and the `implement`/`fix_findings` kinds
  carry no reuse-audit obligation. An operator who wants a narrower binding
  edits the stored policy through the sealed editor — it is ordinary law
  (contract D).
- **The checks are the frozen example's, not extended.** Exactly
  `citation_exists(evidence)` + `dir_listing_matches(<inventory>, package)`
  on BOTH policies. No `non_empty` (an empty audit against a non-empty
  inventory already fails set equality; an empty inventory directory makes
  an empty audit vacuously true — the correct outcome), no `enum` check on
  `source`, no `path_exists` on the registry: additions would re-derive the
  frozen contract (bootstrap rule (a)) and add machinery with no victim
  (A1/A3).

### B. Parameterization: the inventory a project attaches (A3's core)

The template has **no default parameter values — the default inventory is
EMPTY** (A3): no source name, no path, no registry ships in code; the one
worked example lives in the README (contract D) and is explicitly marked an
illustration. The parameter domain, pinned by tests:

- `source` — non-blank string: the audited source's name as audit rows must
  cite it (rendered into both prompts; the entry field `source` is where
  workers repeat it, free-form per the frozen example).
- `inventory` — non-blank string: the directory whose IMMEDIATE CHILDREN
  are the audited packages. It becomes `dir_listing_matches.root` verbatim
  on both policies — this is A3's "root path" for the audited repo/package
  set, and it deliberately carries the goal's meta-role name (`inventory`,
  the "inventory to enumerate" of `work_area_meta`'s
  `{root, inventory, registry, consumption}`, `workareas.py:337`) rather
  than `root`, so an operator cannot confuse it with the source's repo root
  (enumerating a repo root would audit its top-level directories, not its
  packages). Relative and absolute paths both ride the sealed slice-04
  semantics unchanged: relative resolves inside exactly one granted
  work-area root at check time, absolute must lie inside a granted root —
  this slice adds no path logic.
- `registry` — non-blank string: the source's registry document path
  (A3's "registry path"). It renders into both prompts as the
  read-this-first procedure step (goal `:316`–`:317`); per the frozen
  example it carries NO mechanical check.
- `version` — optional positive integer, default `1`: stamped verbatim on
  BOTH policies (they change together as one safeguard). No auto-bump ever
  (sealed slice-03 non-goal); re-parameterizing without a version bump
  changes standing law without a `project_safeguard_seen` re-record —
  exactly the sealed editor's documented rule, restated at the enable
  surfaces (contract D).

Any missing, blank, or wrong-typed parameter — and any unknown body key —
refuses instantiation: the module raises, the route (contract D) answers
400 `invalid_template_params`, and nothing is written. Fail-closed beats a
hollow safeguard: a template that instantiated with defaults or blanks
would be the bare-boolean anti-pattern (goal `:335`–`:338`) wearing a
contract field's clothes.

**One audited source per project in V1, by design.** The skeleton pins the
planning field NAME (`reuse_audit`), each check quantifies over ALL entries
of its field (sealed slice-04 B), and two in-scope extensions may not share
a field (`verifiers.py:199`) — so one project carries exactly one
template pair, and one pair mechanically audits exactly one inventory
directory. A project whose ecosystem has further audited sources authors
additional ordinary policies (distinct ids AND distinct fields) through the
sealed editor — the README documents this path — or waits for the successor
process A3 names as the generalizer of the FORM. The template itself never
fans out.

**No enable-time filesystem validation, deliberately.** Enabling is config
authoring, not reconcile: the grant universe does not exist until a run
binds a work area, so the inventory path is validated where the sealed
machinery already validates it — at check time (`dir_listing_matches`
resolution; a missing directory is slice-04's operational error, routed by
slice-06 E to a recorded run failure, never a worker repair). An enable
with a not-yet-existing relative inventory path succeeds and the fault
surfaces at run time with the sealed reason. This mirrors declare →
pending: descriptors are authored first, reality is checked at the boundary
that owns it.

### C. The prompt texts (the operator-authority half)

The template renders both `prompt` strings from the parameters. Wording is
the implementation's choice; the CONTENT below is pinned at phrase level on
whitespace-normalized text (the `test_prompts.py` convention), because it
is the standing law operators ship — the machine-enforced half already
renders from the compiled extension via sealed slice-06 B.

The **planning prompt** must: name the `source`, the `inventory` path, and
the `registry` path verbatim; state the procedure of goal `:314`–`:318` —
enumerate the inventory, read the registry rows, record one
adopt/gap/reject decision per package with `file:line` evidence read from
the source itself; require the audit as a TABLE in the drafted artifact
(the output field carries the same rows — the mechanical slot; the table is
what reviewers read), with a missing or uncited audit a **P1 content gap**;
and state that recorded gaps go to the source's consumer-needs channel,
**never to local reimplementation** (goal `:318`–`:320`).

The **review prompt** must: name the same three parameters; state that
reviewers verify audit claims by reading the source READ-ONLY (goal
`:322`–`:323`); require one concur/dissent entry per audited package with
the reviewer's **own** `file:line` citation — never the author's echoed;
state that **every dissent must back a finding** (goal `:327`–`:328`); and
state that implementing locally what a reuse source already provides,
without a recorded reject decision, is a **P1 duplication finding** (goal
`:323`–`:324`).

Both prompts are stored policy content: sealed slice-06 renders them
verbatim (clipped only at `AMENDMENT_TEXT_CLIP`) under the safeguard's
id+version, followed by the machine-rendered obligation — field name, entry
type-specs with both enum vocabularies, and both checks with the
parameterized root (`prompts.py:429`–`:462`). Nothing in this slice touches
that renderer.

### D. Enablement mechanics (route, panel, and ordinary law thereafter)

- **The route.** `POST /api/projects/<slug>/policies/reuse-audit` with body
  `{"source": …, "inventory": …, "registry": …, "version"?: …}` → 200
  `{"ok": true, "policies": [<planning>, <review>]}` — the two STORED
  validated domain objects, planning first, no envelope control revision
  (slice-08's response discipline). The trailing segment is a FIXED literal
  naming the affordance — never a policy id — so amendment A2's
  path-normalization hazard is untriggered; the policy ids ride inside the
  written documents exactly as the sealed upsert defines identity.
- **Gates, in slice-07/08 order.** The project-bound gates run first
  (400 `invalid_project` / 404 `unknown_project` / 500 `missing_store`);
  then parameter validation (400 `invalid_template_params`, nothing
  written); then the slice-08 envelope gate for **BOTH pinned ids before
  anything is written** — an invalid stored ENVELOPE at either id refuses
  500 `malformed_store` with NOTHING written, so one corrupt entry cannot
  yield a half-enabled safeguard (planning enforced, review contrast
  missing). Store-level failures refuse with the sealed 5xx tokens. The
  remedy vocabulary is slice-08's unchanged: malformed VALUES are healed by
  this route's own overwrite; invalid envelopes take the store-level remedy.
- **Writes are the sealed upsert, twice.** Both policies go through
  `PolicyStore.put` (`projects.py:183`) — no parallel writer, no service
  reshaping. Consequences pinned by tests: enable over EXISTING policies at
  the pinned ids (template-written or hand-authored) overwrites them
  wholesale; re-enable with identical parameters is idempotent (both read
  back domain-identical); `version` rides verbatim with no auto-bump; after
  deleting ONE of the pair through the sealed delete route, re-enable
  restores both — the torn-pair heal path is re-enable itself, so a hard
  failure between the two puts (the response already reported it) leaves a
  state one successful retry repairs.
- **The panel affordance.** The safeguards card (slice-08 D) gains one
  "enable reuse-audit template" control opening a dialog with the four
  parameters and posting the route; refusal tokens surface VERBATIM in the
  editor's error line; the surface re-reads after success so both policies
  appear immediately. The dialog's hint restates the version rule of B. The
  panel never composes the policy objects — instantiation is service-side
  only, because a client-side copy of the template would be a parallel
  content source (the duplication class this milestone exists to kill).
  Pinned at the slice-08 observation levels: served-page markers carry the
  control's hooks and the route string; the JS is reviewed as content.
- **Ordinary law thereafter.** The instantiated policies are ordinary
  sealed policy objects with NO special-case path anywhere: the slice-08
  editor lists, edits, toggles (`enabled` flip preserving version), and
  deletes them; the project delete guard counts them; slice-06 renders and
  ledgers them — pinned by driving the sealed toggle and delete over one of
  the pair and by the end-to-end contract E.
- **The README section (A3's documented example).** `orchestrator/README.md`
  gains a section documenting: what the safeguard enforces, the route and
  parameter domain, ONE fully worked parameterization — the goal's LPC
  illustration, explicitly marked as an illustration of the generic
  machinery — the one-source-per-project V1 rule with the manual-authoring
  path for further sources, the version-bump rule, and the correspondence
  with `work_area_meta.reuse_sources` (the descriptor family an operator
  SHOULD author consistently; the template never reads it — Non-Goals).

### E. The safeguard live end-to-end (I11 through the sealed pipeline)

With the template enabled on a project-bound run, the sealed pipeline must
carry it whole — this contract is the milestone's Tests-That-Pin entry and
is exercised through the driver's real call path (`MockRunner`,
`test_project_context.py` conventions), against a real tempdir work area
whose granted roots contain a real inventory directory of several packages:

- **Planning altitude.** A `draft_slice_note` (and `draft_skeleton`) prompt
  carries the safeguard at operator authority — id+version, the contract-C
  phrases with the parameterized paths, the field name `reuse_audit`, the
  entry specs with the adopt/gap/reject vocabulary, both checks with the
  parameterized root. A first `status: "ok"` output whose audit **omits one
  real package** — the M26/M27 under-enumeration verbatim — fails
  `dir_listing_matches` and triggers exactly ONE repair retry; a second
  failure fails the call as the standard protocol violation. A conforming
  output — every package decided exactly, decisions in vocabulary, evidence
  citations whose path halves exist inside the granted roots — proceeds. An
  invented package (over-enumeration), a decision outside the enum, an
  ill-shaped or root-escaping citation, and a missing `reuse_audit` field
  each fail the same way. A valid `blocked` output is exempt (sealed
  ok-only merge).
- **Review altitude.** A `review_round` call on the doc unit must carry
  `reuse_audit_review` — set equality over the SAME inventory (one entry
  per audited package), concur/dissent enum, the reviewer's citation
  existing inside the roots — while the base findings contract rides
  unchanged beside it. `delta_review` and `seal_half` calls on doc units
  are bound identically; `implement`/`fix_findings` calls and `slice_impl`
  units validate byte-identically to the base contract (out of scope).
- **The ledger.** `project_safeguard_seen` records each policy once per
  (id, version) with the prompt's first 300 characters, re-recording on a
  version bump — sealed slice-06 semantics observed here with the template's
  real content, two policies distinctly.
- **The honest mechanical boundary** (public, so no later consumer
  overclaims): set equality pins COVERAGE — every real package decided, no
  phantom package — not row uniqueness (duplicate rows for one package
  still satisfy it; they are reviewer-visible content). **Dissent-backs-a-
  finding is prompt-carried reviewer duty, NOT mechanically verified**: the
  closed V1 vocabulary has no cross-field or cross-output check, and a new
  verifier kind is an orchestrator milestone deliberately not taken here
  (A3). Pinned by a test: a review output whose `dissent` entry has no
  corresponding finding still passes mechanical validation. Likewise the
  artifact's audit TABLE is reviewer-verified content (goal `:343`:
  "Reviewers verify semantics; the driver verifies existence").

## Non-Goals

- **No generalization of the FORM** (A3 verbatim): no template registry, no
  generic `/templates/<name>` surface, no second built-in template, no
  schema variants, no parameterizable scopes/entries/checks beyond the four
  parameters of B. The successor process generalizes; speculative
  generality built now would be rework.
- **No multi-source fan-out and no source-derived ids or field names.** One
  template pair per project (B's rationale); further sources are
  hand-authored ordinary policies or successor scope.
- **No new verifier kind or type-spec** — in particular, no
  dissent-implies-finding cross-check and no audit-table-vs-output-field
  comparison (sealed V1 is closed; the review duty is prompt law judged by
  reviewers and the seal process).
- **No reading of `work_area_meta` by the template.** The meta family stays
  the prompt-side descriptor surface sealed slice-06 renders; parameters
  are explicitly operator-supplied. Deriving law from unvalidated
  descriptors would couple two operator surfaces (per-work-area, mutable,
  optional) to project-wide law with no pinned consumer; the README
  documents authoring both consistently instead.
- **No auto-enable, no auto version bump, no enable-time filesystem
  validation** (B/D rationales).
- **No CLI enable surface** (the service API is the machine surface; the
  CLI keeps path-based init — slice-07's standing non-goal).
- **No changes to sealed module semantics**: `projects.py`, `verifiers.py`,
  `prompts.py`, `driver.py`, `runners.py`, `workareas.py`, `kvstore.py`,
  `state.py`, `contracts.py`, `registry.py`, `gitops.py` are consumed
  as-is; `service.py` gains only the enable route; `panel.html` only the
  enable control.
- **No skeleton price-tag / verified-assumptions machinery** — that is
  `skeleton-code-first-discipline.md`, the sibling milestone that CONSUMES
  this safeguard (skeleton Non-Goals).
- **No digest, no `primary_root` alias, no SCHEMAS doc** (machine-api
  milestone; skeleton Non-Goals).
- **No migrations, compat shims, or tolerant readers** (greenfield, I12).

## Expected Files

- `orchestrator/reuse_audit.py` (new) — the template: parameter validation
  (B) and the pair builder (A/C), pure functions over the sealed
  vocabularies; no storage, no I/O.
- `orchestrator/service.py` (edit) — the enable branch in the existing
  `projects_api` dispatcher (`service.py:692`; a fixed-literal `n == 3`
  route beside the `policies` branches) plus the module docstring's route
  table; the handler composes the sealed gates and `PolicyStore.put` (D).
- `orchestrator/static/panel.html` (edit) — the enable control and dialog
  in the safeguards card (D), reusing the existing dialog/error-line/
  re-read patterns.
- `orchestrator/README.md` (edit) — the documented example section (D).
- `orchestrator/tests/test_reuse_audit.py` (new) — the pinning tests:
  template shape/compile/parameters/prompt phrases (A/B/C) and the
  end-to-end enforcement matrix (E) over the driver + `MockRunner` with
  tempdir stores and real inventory directories (`test_project_context.py`
  conventions).
- `orchestrator/tests/test_service_projects.py` (edit) — the enable-route
  matrix and served-page markers beside the existing policy-route tests
  (keeping them in `test_reuse_audit.py` instead is the implementation's
  choice; the split above is the default).

## Dependencies

- **Slice 3** (`orchestrator/projects.py`, sealed) — `validate_policy_value`
  (`:133`), `PolicyStore.put/read/list_policies/delete` (`:183`, `:187`,
  `:204`, `:237`), `policy_matches`/`in_scope` (`:165`, `:244`), the
  refusal vocabulary (`:29`–`:32`), and the no-auto-versioning doctrine.
- **Slice 4** (`orchestrator/verifiers.py`, sealed) — `compile_policy`/
  `compile_extensions` (`:159`, `:211`), the closed check vocabulary and
  parameter sets (`:85`–`:91`), `_require_distinct_fields` (`:199`; B's
  one-pair rationale), the config/operational error split, and
  `contracts.reserved_output_keys` (`contracts.py:321`) with
  `KIND_OUTPUT_KEYS` (`:306`) as the collision ground truth;
  `runners.call_worker` (`runners.py:380`) as the enforcement seam.
- **Slice 6** (sealed) — `_project_context_block` (`prompts.py:379`,
  obligation rendering `:429`–`:462`, clip `:366`–`:376`), the
  selection/compile/seen pipeline and fail-closed routing its note pins
  (slice-06 B/C/D/E) — contract E observes them under real content.
- **Slice 7** (sealed) — the project gates (`_require_declared`
  `service.py:212`, `_require_store_file` `:226`), the dispatcher
  (`:692`–`:759`), ProjectEntry/`GET /api/projects` as the read model, and
  the launch binding contract E's tests drive runs through.
- **Slice 8** (sealed) — `put_policy` and its envelope gate (`service.py:609`,
  `:633`–`:644`), `delete_policy` (`:650`), the `policies` route branches
  (`:721`–`:732`), amendment A2's id-transport doctrine, and the safeguard
  editor + version hint (`panel.html:1278`–`:1435`) this slice's control
  sits beside — including its recorded deferral of concrete content here
  (`panel.html:1387`).
- **Slice 2** (sealed, context) — the meta value shape whose `inventory`
  role names B's parameter (`workareas.py:337`); **Slice 5** (sealed,
  context) — project-bound `init_run` for E's tests.
- The existing vocabularies as single sources: `contracts.KINDS`/
  `REPORT_KINDS` (`contracts.py:48`, `:59`) and the `state.py` unit
  constants (`:36`–`:38`).
- The sealed skeleton (row 10 `skeleton.md:177`; Sequencing `:184`–`:191`;
  Tests That Pin `:202`–`:203`; Shared Invariants `:149`–`:158`) and the
  pricing-pilot fixture (**I11** `priced_ok`; its `ecosystem_equivalent`
  gap evidence `orchestrator/prompts.py:253` — today's prose Reuse Posture
  duty, anchored at the fixture's provenance commit).
- The frozen goal re-read read-only as the contract source: `:35`–`:37`,
  `:219`–`:252`, `:259`–`:262`, `:289`–`:290`, `:298`–`:299`,
  `:310`–`:355`, `:359`, `:369`–`:371`.
- **Operator amendments A3** (the binding scope pin quoted in the
  preamble) and **A1** (Proportionality below); amendment A2 (context: why
  the route's trailing segment must stay a fixed literal).
- No later slice exists; the successor process A3 names lives in
  `skeleton-code-first-discipline.md` (non-canonical, sequenced after this
  milestone).

## Reuse Posture

- **Checked (this repo):** the sealed policy pipeline end to end — storage
  and validation (slice 3), compile/merge/enforcement (slice 4), rendering/
  ledger/fail-closed (slice 6), service gates (slice 7), authoring routes
  and editor (slice 8) — and confirmed the template can ride it with ZERO
  new validation, storage, rendering, or enforcement machinery; confirmed
  no template or enable surface exists anywhere (no production reference to
  `reuse-audit`; the panel comment at `panel.html:1387` explicitly defers
  concrete safeguard content to this slice); the existing prose Reuse
  Posture prompt duty (`prompts.py:253`) as I11's priced gap — a duty, not
  a per-package slot; the README's structure for the documented example.
- **Checked (contract sources, read-only):** the frozen goal's policy
  example and gate machinery (`:219`–`:236`, `:310`–`:355`), deliverable
  (6), the generic-concept doctrine (`:35`–`:37`); fixture I11; amendments
  A1/A2/A3.
- **Reused / extended:** instantiated policies are stored, compiled,
  rendered, enforced, ledgered, edited, toggled, deleted, and
  delete-guarded ENTIRELY by sealed machinery; the enable route composes
  the sealed gates + `PolicyStore.put` (no parallel writer or validator);
  the panel control reuses the editor card, dialog, error-line, and re-read
  patterns; the prompt-side ecosystem roles remain slice-06's meta
  rendering — the template prompt carries the PROCEDURE and parameters,
  never a duplicate ecosystem map.
- **Adopted verbatim (the frozen contract):** the planning policy object
  (`:222`–`:235`, id and root substituted); the closed verifier and
  type-spec vocabularies (nothing added); the scope vocabularies.
- **Non-canonical planning (Adopt / Revise / Reject):** ADOPTS the frozen
  goal example and gate machinery §§2–5 as pinned law; REVISES nothing;
  REJECTS (defers to the named successor per A3) any generalization of the
  template FORM — registries, variants, multi-source fan-out.
- **New machinery, and why (the I11 gap, not parallels):** the template
  module (the concrete standing content that exists nowhere), one route
  branch, one panel control, the README section, and the pinning tests.
  Nothing duplicates an existing facility.
- **Compatibility:** the pair is ordinary sealed policy data — future
  fusion sees two more `policy:<id>` documents with the shared
  id/version/enabled/scope vertebrae; no new KV family, key, namespace, or
  vocabulary token beyond the one route refusal `invalid_template_params`.

## Proportionality (amendment A1)

The two contract fields, their entry/check shapes, the built-in-template
deliverable, and the mechanical-verification posture are pinned by I11, the
frozen goal, and skeleton row 10 — not re-derived. New mechanism beyond
those pins, one line each:

- **The template module + enable route.** VICTIM: the operator — without a
  built-in, every project hand-authors two coupled standing-law JSON
  documents, and a hand-typo'd inventory path or field name is exactly the
  incomplete-inventory failure class this safeguard exists to kill
  (deliverable (6) pins "BUILT-IN" for this reason). COST: one small pure
  module plus one dispatcher branch over sealed puts.
- **Both-envelopes gate before the first write (D).** VICTIM: the operator
  with one corrupt envelope, who would otherwise get a HALF-enabled
  safeguard from a single enable call — planning enforced with the review
  contrast silently missing. COST: two sealed envelope reads.
- **Fixed pair ids (A).** VICTIM: every project-bound planning run —
  source-derived ids would let a re-parameterization mint a second
  same-field pair, turning standing law into a sealed config error that
  fails each in-scope call. COST: zero mechanism (a naming rule), recorded
  here.
- **The panel enable control (D).** VICTIM: the operator — the goal pins
  the record as panel-editable, and curl-only enablement of the flagship
  safeguard reintroduces hand-authoring at the exact surface built to
  remove it. COST: one dialog and one call site over the existing patterns.
- **The README example section (D).** Mandated by A3 ("one documented
  example"). COST: documentation lines.
- **The end-to-end enforcement tests (E).** The skeleton's own
  Tests-That-Pin entry for this slice. COST: test lines.

Nothing is SPECULATIVE and nothing requires operator approval. Deliberately
NOT built, with reasons: a template registry / generic template surface and
multi-source fan-out (A3 forbids; successor scope); meta-derived
parameterization (couples law to unvalidated per-work-area descriptors; no
pinned consumer); a dissent→finding verifier or table-vs-field cross-check
(outside the closed V1 vocabulary; reviewer duty by the goal's own split);
an `enum` check on `source` or `path_exists` on `registry` (extends the
frozen example's checks without a victim); enable-time path validation
(the grant universe does not exist yet; the sealed check-time errors own
it); a preview endpoint (the enable response already returns the stored
objects; upsert idempotence makes dry-runs valueless).

## Acceptance Criteria

1. **The pair, sealed-valid and compile-clean (I11).** Instantiation with
   valid parameters yields exactly the two objects of A — ids
   `reuse-audit`/`reuse-audit-review`, the pinned scopes, fields, entries,
   enum vocabularies, and the two checks with `root` equal to the
   `inventory` parameter on both; both pass `validate_policy_value`
   unchanged and the pair compiles through `compile_extensions` with no
   config error.
2. **Nothing baked in (A3).** The template ships no default parameter
   values: instantiation with any of `source`/`inventory`/`registry`
   missing or blank, a non-positive or non-integer `version`, or an unknown
   body key refuses; with sentinel parameters, every path and source string
   in the instantiated objects (prompts included) equals a supplied
   sentinel; omitted `version` stamps `1` on both.
3. **Prompt phrases (C).** Whitespace-normalized, the planning prompt
   carries the three parameters verbatim, the enumerate/read-registry/
   decide procedure, the adopt/gap/reject vocabulary, the in-artifact audit
   TABLE requirement, "P1 content gap", and the consumer-needs /
   never-local-reimplementation rule; the review prompt carries the
   read-only duty, per-package concur/dissent, the reviewer's-own-citation
   rule, "every dissent must back a finding", and "P1 duplication finding".
4. **Enable route happy path (D).** Against a declared project,
   `POST /api/projects/<slug>/policies/reuse-audit` returns 200 with
   `policies` = [planning, review] as stored validated domain objects (no
   envelope control revision); both appear in the project entry's `policy`
   list and render/enforce thereafter as ordinary policies.
5. **Enable route refusals (D).** Invalid slug 400 `invalid_project`;
   undeclared slug 404 `unknown_project`; declared-but-missing store 500
   `missing_store`; invalid parameters 400 `invalid_template_params` with
   nothing written; an invalid stored ENVELOPE at EITHER pinned id refuses
   500 `malformed_store` with NOTHING written (no half-enabled pair); all
   tokens verbatim.
6. **Idempotence, verbatim version, wholesale overwrite (D).** Re-enable
   with identical parameters reads back domain-identical (no auto-bump);
   re-enable with changed parameters and a bumped `version` overwrites both
   wholesale; enable over a hand-authored policy at a pinned id overwrites
   it (sealed upsert identity); deleting one of the pair through the sealed
   delete route then re-enabling restores both.
7. **Ordinary law thereafter (D).** The sealed slice-08 toggle flips
   `enabled` on one of the pair preserving `version`, and the sealed delete
   removes it; the pair blocks the guarded project delete exactly like any
   live policy.
8. **Planning enforcement end-to-end (E — the M26/M27 pin).** Through the
   driver's real path against a real inventory directory: the
   `draft_slice_note` prompt carries the safeguard (id+version, C's
   phrases, field, entry specs with both enum vocabularies, both checks
   with the parameterized root); an ok output omitting one real package
   triggers exactly ONE repair retry and a second failure fails the call; a
   conforming audit proceeds; an invented package, an out-of-vocabulary
   decision, an ill-shaped or root-escaping citation, and a missing field
   each fail; a valid `blocked` output is exempt.
9. **Review enforcement end-to-end (E).** A `review_round` call on the doc
   unit must carry `reuse_audit_review` satisfying set equality over the
   same inventory with existing reviewer citations and the concur/dissent
   vocabulary, beside the unchanged base findings contract; `delta_review`
   and `seal_half` on doc units are bound identically; `implement`/
   `fix_findings` calls and `slice_impl` units validate byte-identically to
   the base contract; a `dissent` entry without a corresponding finding
   passes MECHANICAL validation (the duty is prompt law — the honest
   boundary of E).
10. **Ledger (E).** `project_safeguard_seen` records each of the two
    policies once per (id, version) with the prompt's first 300 characters;
    a version-bumped re-enable re-records both on the next in-scope call.
11. **Run-time path faults are the sealed errors (B).** Enabling with a
    relative inventory path that does not yet exist succeeds; a bound run
    whose granted roots lack the directory fails at check time with the
    sealed operational error recorded in state (no worker repair burned); a
    root escaping every granted root is the sealed config error.
12. **Inertness.** A fresh project's policy list stays `[]` (nothing
    auto-enables); with the template never enabled, project-bound and
    project-less behavior is byte-identical to today; the served panel page
    carries the enable control's hooks and the route string (slice-08
    marker posture); the entire pre-existing suite passes unmodified.
13. **README example (A3) + suite green.** The README section exists with
    the elements of D (route, parameters, ONE illustrative parameterization
    marked as such, the one-source V1 rule and manual path, the
    version-bump rule, the meta correspondence);
    `python3 -m unittest discover -s orchestrator/tests -t .` passes.

## Tests / Verification

In `orchestrator/tests/test_reuse_audit.py` (standard library only; stores
in `tempfile.TemporaryDirectory` seeded through the service API and sealed
stores; project-bound runs through slice-05's `init_run` driven over
`MockRunner`, with real inventory directories under the granted roots —
the `test_project_context.py` conventions):

- **Template** — the pair's pinned shape, sealed validation, and pair
  compile (AC1); the parameter matrix and sentinel-only content (AC2); the
  normalized phrase sets for both prompts (AC3).
- **Enforcement** — the planning matrix: prompt content through the sealed
  renderer, under-/over-enumeration, decision/citation/missing-field
  failures, the single repair retry, blocked exemption (AC8); the review
  matrix including the three bound kinds, out-of-scope byte-identity, and
  the dissent-without-finding mechanical pass (AC9); the seen-event pair
  and bump re-record (AC10); the operational/config path faults (AC11).

In `orchestrator/tests/test_service_projects.py` (the threaded
`make_server(home, 0)` isolated-tempdir harness):

- **Route** — the happy path and response shape (AC4); the refusal matrix
  including the both-envelopes no-write pin (AC5); idempotence/overwrite/
  heal-after-partial-delete (AC6); ordinary-law toggle/delete/guard over
  the pair (AC7); served-page markers and the pre-existing suite unmodified
  (AC12).

README content is verified by reading (AC13); full slice verification:
`python3 -m unittest discover -s orchestrator/tests -t .` (AC13).

## Risks

- **Hollow enablement** — optional parameters, baked-in defaults, or a
  tolerated blank inventory would ship a slot that is statistically free to
  fill, the bare-boolean failure wearing a contract field's clothes. The
  AC2/AC5 fail-closed matrix is load-bearing.
- **Template drift from the sealed vocabulary** — content that validates
  today but fails compile (an unknown check parameter, a colliding field)
  would turn standing law into per-call config errors. The AC1 pair-compile
  test is load-bearing.
- **A client-side template copy in the panel** would create a second
  content source that drifts from the module — the duplication class this
  milestone exists to kill; instantiation stays service-side (D), and a
  reviewer finding template JSON composed in `panel.html` is a P1
  duplication finding.
- **Source-derived ids or fields** would let a re-parameterization mint a
  colliding second pair that fails every in-scope call (sealed
  distinct-fields rule). AC6's overwrite pins the fixed-id design.
- **Overclaiming the mechanics** — presenting set equality as row
  uniqueness, or dissent→finding as machine-checked, would mislead the
  successor process and reviewers about what is actually enforced. E's
  honest-boundary statements and AC9's mechanical-pass case are
  load-bearing.
- **Coupling parameters to `work_area_meta`** would derive project-wide law
  from optional, per-work-area, unvalidated descriptors; kept advisory-only
  (Non-Goals), with the README teaching consistent authoring — the residual
  risk (descriptors and law drifting apart) surfaces as odd prompts or
  failing checks, both operator-visible.
- **A trailing id-like route segment** would reopen amendment A2's
  normalization hazard; the segment is a fixed literal and no id ever rides
  the path (D).
- **Scope creep toward the successor** — variants, registries, extra
  checks, multi-source support — is the exact rework A3 forbids; Non-Goals
  and the A1 "deliberately NOT built" list guard it.

## Line budget

Production code is small: one pure template module, one dispatcher branch
composing sealed gates and puts, one panel dialog, one README section. As in
every prior slice, the pinning tests — the template/parameter/phrase
matrices, the route matrix with the no-write pins, and the end-to-end
planning/review enforcement that is the milestone's final Tests-That-Pin
entry — carry the bulk, so total changed lines may modestly exceed the ~500
target. That test surface is the deliverable's point (**I11**): this slice
is where the milestone proves, against a real directory listing, that the
M26/M27 failure class now dies at the contract layer.
