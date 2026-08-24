# Slice 01 — Prompt-set store and seed fallback

## Register 1 — INTENT (lay language)

### What this slice builds

This slice gives the orchestrator one editable home for its prompt wording and a
built-in copy that is always available. An operator may keep named sets beside
the standard set. When a caller asks for one, it receives one complete set: the
chosen set when usable, otherwise the standard set, otherwise the built-in copy.
The caller is told when that fallback happened.

A broken or half-edited set is never patched together with another set. It loses
as a whole, so a worker cannot receive instructions whose sections came from
different owners. Reads are live: an edit completed before the next read begins
is read by that call. This is deliberately not versioned publication; edits racing
a read may still be observed as any valid combination from that same set.

Nothing sends these prompts to a worker yet. This slice makes the corpus
available, validates it, and selects a safe whole set. Later slices own charge
routing, assembly, reply validation, run selection, APIs, and consumer cutover.

### Ownership and boundary

Owned here are the service-home layout, the shipped standard set, the built-in
seed, whole-set readability, fresh selection, and the fallback indication. An
empty service home gains the standard set; an existing set remains the
operator's bytes and is neither repaired nor replaced during initialization.

Not owned here are prompt rendering, variable substitution, material overlays,
job or seat selection, output-contract enforcement, traces, run bindings,
operator controls, or any change to what current workers receive.

### Guarantee posture

- **Strict — complete rung.** Every successful read returns a complete validated
  set from one rung. Any required-file or corpus-validity defect rejects that
  entire rung, and the built-in rung makes selection total.
- **Strict — fallback disclosure and non-repair.** A fall is reported beside the
  selected set. Selection does not edit, heal, or complete any stored set.
- **Strict — missing-only installation.** A new home receives the shipped
  standard set; later initialization does not overwrite an existing one.
- **Best-effort — edit visibility.** Each read starts from current files, with no
  cache or snapshot. Completed edits are read; concurrent multi-file saves may
  yield any complete valid combination from one rung, and there is no consistency
  promise across reads.
- **Optimistic / eventual — none.** There is no compare-and-set, replication,
  notification, convergence, or delivery queue in this slice.

### Dependencies and consumers

This first slice has no earlier-slice dependency. It uses the reviewed seed
corpus and extends the service home's existing catalogue-initialization
boundaries. Those initialization boundaries and the new selector are the only
runtime surfaces touched. The next slice is the first consumer of the selected
set; current prompt builders, dispatches, validators, and traces stay in force.

### Non-goals

- No assembled prompt, route table, material layer, substitution, or reply
  validator.
- No service route, panel control, run-state field, compatibility read, or
  consumer cutover.
- No prompt trace change; selection itself stores no history.
- No version, snapshot, cache, migration, notification, edit event, retry,
  reconciliation, or background watcher.
- No semantic policing of trusted prompt prose and no regeneration from the
  legacy string builders.
- No edit in any granted read-only repository.

### Acceptance and size

Acceptance is the focused contract below: it proves the shipped corpus, the
missing-only installation, representative whole-set defects, all three fallback
outcomes, no cross-set mixing or repair, and a fresh second read after an edit.
The unchanged legacy prompt tests prove that no current worker consumer moved.

The implementation is expected to stay below about 500 non-mechanical changed
lines. Copying or mechanically converting the already-reviewed corpus and its
goldens does not count toward that aim; no reason to exceed it is known.

### Risks

The material risks are a shallow validator accepting a half-set, fallback code
mixing a usable file from the failed rung, initialization reverting an operator
edit, and two separately maintained seed copies drifting. The tests corrupt one
fact at a time, mark every rung with distinguishable values, preserve bytes
around fallback, and compare both shipped representations to one corpus.

### Reuse Posture

The affected parties are later router slices and, once they cut over, every
operator and worker; omission blocks that work, while a mixed set could produce
wrong instructions and rejected replies on every call. The harm is visible per
call and future edits are reversible, but spent calls are not. The current
workspace and all granted roots were checked; none contains a prompt-set router
to adopt. The cheapest sufficient option is one corpus validator and the
existing fresh-read/default-seed pattern, reusing the reviewed corpus and its
renderer checks. The only new machinery is the multi-file whole-set boundary
needed by the next slice. Its lifecycle cost is file reads and one validator;
versions, watchers, migrations, and another store would cost more than the
reversible omission risk warrants.

### Planning-context disposition

**Adopts** the reviewed skeleton and the seed corpus it makes binding. **Uses**
the historical prompt capture and rationale only as evidence. **Revises** no
accepted decision. **Rejects** brainstorming and `_drafts` material as
independent implementation authority.

## Register 2 — PINNED FACTS (hard register)

### Pinned-Facts Table

| fact | value | authority (file:line) | touch / do-not-touch |
|---|---|---|---|
| Stored corpus | Sets live at `prompt_sets/<set>/{shared,milestone,brainstorming}/…` under the service home. The canonical JSON inventory is `shared/shared.json`; milestone kinds `draft_skeleton`, `draft_slice_note`, `implement`, `review_round`, `delta_review`, `reclassify`, `fix_findings`, `suite_checkpoint`, `merge_repair`; and Brainstorming kinds `discussion_turn`, `questioner_turn`. Rendered `*.prompt.txt` files and `render_examples.py` remain authoring evidence, not runtime set members. | `implementation/milestones/prompt-router/skeleton.md:150,155`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:10-32` | touch the service-home set and shipped seed representation; do-not-create a second store or treat rendered examples as source units |
| Shipped floor and initialization | The reviewed adapted corpus and its recorded decisions are both the stored set named `default` and the in-code seed at ship. An empty home gets the complete stored `default` at each existing home-entry boundary; once `prompt_sets/default` exists, later initialization leaves all of its bytes alone, valid or invalid. Equality is semantic after parsing, not byte formatting. | `implementation/milestones/prompt-router/skeleton.md:13-16,130,150,155`; existing boundaries `orchestrator/driver.py:905-940,12873-12876`; `orchestrator/service.py:5481-5500` | touch the three existing initialization boundaries; do-not-overwrite, repair, migrate, or normalize an existing set |
| Whole-set readability | A rung is usable only when every canonical JSON member is present and readable and the corpus validates as one unit. Broken JSON, an unavailable or missing canonical member, an unresolved shared reference, a duplicate declared id, or an invalid variable declaration makes the whole rung unusable. Stored unknown contract-section ids remain data; semantic prose review and registered enforcement belong later. | `implementation/milestones/prompt-router/skeleton.md:150,153`; `implementation/milestones/prompt-router/goal.md:79-84`; corpus conventions `implementation/brainstorming/prompt-router/adapted-kinds/README.md:34-75` | touch one whole-set validator; do-not-skip a bad member, validate trusted prose semantics, or pull registered reply enforcement into this slice |
| Resolution and fallback | Resolve requested named set → stored `default` → in-code seed. Return exactly one complete validated rung. A fall returns a non-empty indication beside the selected set; an ordinary named-set success has none. No file from a rejected rung may survive in the answer, and resolution writes or repairs nothing. | `implementation/milestones/prompt-router/skeleton.md:62-70,89-100,130,150,161`; sidecar precedent `orchestrator/staffing.py:1587-1622,1717-1739` | touch the set selector and its sidecar result; do-not-mix rungs, put fallback prose inside prompt content, retry, or heal stored files |
| Freshness and consistency | Every selection rereads the requested set and any fallback rung it needs. A file edit completed before selection begins governs that file's read. A read racing multi-file saves may combine file states from that same rung, including a valid combination that never coexisted on disk; across calls there is zero consistency, monotonicity, or convergence guarantee. | `implementation/milestones/prompt-router/skeleton.md:89-100,150,161`; fresh-read precedent `orchestrator/staffing.py:1975-1994,2001-2029` | touch per-selection reads; do-not-add a cache, snapshot, version, lock ceremony, notification, retry, or reconciliation |
| Slice boundary | This slice does not assemble or dispatch prompts and does not alter current prompt text, reply validation, tracing, routes, panel state, run bindings, staffing, or model routing. Those outcomes are assigned to later slices. | `implementation/milestones/prompt-router/skeleton.md:131-143,152-160,162`; current builders `orchestrator/prompts.py:1-19`; current author dispatch `orchestrator/driver.py:7664-7712`; exact trace `orchestrator/runners.py:1663-1676,1754-1757` | touch store, seed, validation, initialization, and selection only; do-not-cut over a consumer or edit any granted read-only root |

### Verification Contract

Focused command:

`python3 -m unittest orchestrator.tests.test_prompt_sets orchestrator.tests.test_prompts orchestrator.tests.test_staffing_documents`

| observable claim | named check | pass condition | posture |
|---|---|---|---|
| The shipped floor is complete and singular | new `test_shipped_corpus_and_seed_are_equivalent` | The canonical JSON inventory is exact; an empty home gains a parsed `default` equal to the in-code seed and reviewed corpus; no rendered example or script enters the runtime set. | strict |
| Initialization is missing-only at every existing home boundary | new `test_default_install_is_missing_only_at_home_boundaries` | Driver start, run creation, and service start each install into an empty home; a valid edit and, separately, a malformed existing member remain byte-identical after another initialization. | strict |
| Every declared defect rejects a whole rung | new `test_whole_set_validation_rejects_declared_defects` | Broken JSON, missing/unavailable canonical member, unresolved ref, duplicate id, and invalid variable declaration each make the rung unusable; no partial set is returned. | strict |
| Fallback is total, disclosed, and never mixed or repaired | new `test_fallback_selects_one_complete_rung` | Distinct markers prove valid named selection, invalid named → stored `default`, and invalid named plus invalid `default` → seed; each fall has a sidecar indication, ordinary success has none, and all stored bytes are unchanged. | strict |
| Reads are fresh without stronger consistency | new `test_selection_reads_fresh_without_a_snapshot` | Two selections in one process, with a completed valid edit between them, return different set content; no persistent history appears. The test asserts no cross-set mix and does not demand a multi-file snapshot. | best-effort visibility / strict rung isolation |
| Existing consumers remain on their current path | existing `orchestrator.tests.test_prompts` and initialization regressions | Legacy builder outputs and existing staffing initialization checks pass without changing their asserted behavior; no dispatch or trace test is rewritten for this slice. | strict |

The repository's official full suite remains
`python3 -m unittest discover -s orchestrator/tests -t .`
(`orchestrator/README.md:544-546`). It belongs to the milestone's scheduled
checkpoint, not this slice's focused implementation gate
(`implementation/milestones/prompt-router/skeleton.md:141-143,159`).

### Question Battery

The skeleton's Question Battery is **INHERITED** and is not re-answered here.
These are the slice-scoped remainder. Enforceability is answered again for the
facts this note pins.

| question | answer | evidence |
|---|---|---|
| consumers_touched | **Verified touched:** the three existing service-home initialization boundaries—driver start, run creation, and service start—and the new selector consumed by Slice 2. **Verified untouched:** current milestone prompt builders/author dispatch and exact prompt recording; no API, panel, validator, or worker dispatch moves in this slice. | `orchestrator/driver.py:905-940,12873-12876,7664-7712`; `orchestrator/service.py:5481-5500`; `orchestrator/prompts.py:1-19`; `orchestrator/runners.py:1663-1676,1754-1757`; `implementation/milestones/prompt-router/skeleton.md:130-132` |
| pinned_facts | The one service-home layout and exact canonical JSON inventory; the adapted corpus as both stored `default` and in-code seed; missing-only non-repairing installation; whole-set validity; named → stored default → seed selection with a sidecar fallback indication and no rung mixing; per-read freshness with the declared best-effort consistency; and the no-consumer-cutover boundary. | `implementation/milestones/prompt-router/skeleton.md:89-100,130,150,155,161`; `implementation/brainstorming/prompt-router/adapted-kinds/README.md:10-75` |
| verification | The six checks above pin seed/corpus equivalence, all existing home boundaries, every declared unreadable-set class, each rung and fallback indication with byte-stable non-repair, a fresh second read, and unchanged legacy prompt consumers. The focused command names the exact modules; the official full suite remains the later checkpoint command. | `implementation/milestones/prompt-router/skeleton.md:130,141-143,150,155,159`; existing patterns `orchestrator/tests/test_model_profiles.py:374-405`; `orchestrator/tests/test_staffing_sessions.py:651-662,719-747`; `orchestrator/README.md:544-546` |
| reuse_posture | Affected parties are later slices and eventual prompt callers; omission blocks routing, while mixing can waste calls. Searches of this workspace and all granted roots found no existing prompt-set router. Reused are the binding corpus and renderer checks, the staffing selector's whole-rung fallback/sidecar shape, the model-profile missing-only seed, and the three existing home boundaries. Cheapest sufficient is one validator plus one fresh selector; the sole new cost is multi-file validation, reversible before cutover. | corpus `implementation/brainstorming/prompt-router/adapted-kinds/README.md:1-75`; renderer `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-266`; fallback `orchestrator/staffing.py:1587-1622,1717-1739`; seed `orchestrator/model_profiles.py:417-429`; boundaries `orchestrator/driver.py:905-940,12873-12876`; `orchestrator/service.py:5481-5500` |
| enforceability | Every asserted guarantee maps to an available mechanism in the Enforceability Gate: the existing missing-only seed guard; the corpus parser/ref/variable checks; staffing's single-rung fallback and sidecar result; fresh per-call reads and a read-only resolver; and named tests that corrupt inputs, mark rungs, and compare bytes. No snapshot, convergence, or semantic-prose guarantee is asserted. | `orchestrator/model_profiles.py:417-429`; `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-266`; `orchestrator/staffing.py:1587-1622,1717-1739,1975-1994,2001-2029`; `implementation/milestones/prompt-router/skeleton.md:89-100,150,161` |

### Enforceability Gate

| invariant asserted here | pinned mechanism that can enforce it | implementation gate |
|---|---|---|
| An empty home receives the seed and an existing set is not rewritten | The existing missing-only guard in `orchestrator/model_profiles.py:417-429`, invoked at the same three home boundaries already used at `orchestrator/driver.py:905-940,12873-12876` and `orchestrator/service.py:5481-5500`. | Exercise all three boundaries, then compare edited and malformed stored bytes before and after re-entry. |
| Only a complete valid corpus is eligible | The corpus renderer already parses kind/shared JSON, resolves shared refs, checks variable declarations during rendering, and checks question-id uniqueness at `implementation/brainstorming/prompt-router/adapted-kinds/render_examples.py:200-266`; the store extends that one corpus walk to all canonical members before eligibility. | Remove or corrupt one fact at a time and require rejection of the entire rung. |
| Fallback returns one rung, reports the fall beside it, and repairs nothing | The existing three-level selector and sidecar-result pattern at `orchestrator/staffing.py:1587-1622,1717-1739`, with the read-only resolution contract at `orchestrator/staffing.py:2001-2029`. | Give each rung distinct sentinels, force both falls, assert whole-result equality and byte-identical stored inputs. |
| A later read sees completed edits without a cache, but gains no snapshot promise | The existing per-resolution store read at `orchestrator/staffing.py:1975-1994`; the skeleton expressly permits same-rung combinations and zero cross-call consistency at `implementation/milestones/prompt-router/skeleton.md:89-100`. | Resolve, complete one valid edit, resolve again in the same process, and assert the second content while demanding no multi-file snapshot. |
