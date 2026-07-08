# Orchestrator

A deterministic driver for the canon delivery flow. The control loop that
used to be an LLM following prose rules — sequencing phases, launching
reviews, keeping bookkeeping consistent — is now hardcoded, tested Python.
LLM CLI workers keep all content judgment: they draft, review, fix, and run
opposite-family consultations themselves; the driver only decides *which*
call is legal next, records immutable history, and enforces gates
mechanically.

Motivation, from the field: mid-2026 milestone logs showed ~40% of failed
double-seal attempts caused purely by orchestrator bookkeeping drift
(stale work-log rows, misattributed self-review lines, evidence fields
forgotten). Every one of those rules is enforced here structurally.

## What is enforced in code (was prose)

| Rule (canon) | Enforcement point |
|---|---|
| History is never rewritten | `state.save()` refuses non-append-only diffs (`HistoryRewriteError`) |
| Phase gates (draft -> verify -> rounds -> verify -> seal) | `state.transition_unit()` raises `IllegalTransition` |
| Family order; later families never reopen earlier normal rounds | `state.advance_family_if_clean()` |
| Seal opens only after every family has a recorded clean round | `state.can_open_seal()` checked before `U_SEALING` |
| Whoever detects never fixes: ALL reviews are report-only | `contracts.REPORT_KINDS` forbid dispositions and file changes; workspace snapshots detect tampering; tampered reviews are discarded and the worktree restored to HEAD |
| A rejected finding requires an opposite-family consultation | `contracts.validate_fix_finding()` (P0-P3; therefore also P0/P1) |
| Settled findings stay settled | milestone-global adjudication registry injected into every prompt; `contests` and `rejected_adjudicated` references validated against it; misreadable-target rejections carry a `prevention` edit |
| The fixer triages exactly what was queued | `contracts.validate_fix_coverage()` (same ids, nothing invented) |
| Round/seal/verify-fix caps | driver executors fail the run with the explanation in the event log |
| Blocked -> stop with explanation, no silent retries | `status: "blocked"` or a `blocked` disposition ends the run; the reason is in `state.failure` and the events |
| No prose parsing of reviewer output | workers must return contract JSON (`contracts.py`); one repair retry, then the run fails |

## Layout

    orchestrator/
      contracts.py   JSON protocol (single source of truth)
      state.py       append-only state machine
      runners.py     subprocess + mock runners, JSON extraction, snapshots
      prompts.py     prompt builders (KIND/FAMILY/WORKSPACE headers)
      driver.py      decide() + executors + CLI
      webapp.py      read-only dashboard (stdlib http.server)
      static/        dashboard page
      examples/calculator/   fake-LLM end-to-end scenario + real-LLM config
      tests/         unit, mock-lifecycle, fake-CLI e2e, opt-in real-LLM

Python 3.9+ standard library only. No dependencies.

## Usage

    # create a run
    python3 -m orchestrator.driver init \
      --goal "Build X" --workspace /path/to/work --config my-config.json

    # inspect / advance
    python3 -m orchestrator.driver status --workspace /path/to/work [--json]
    python3 -m orchestrator.driver next   --workspace /path/to/work
    python3 -m orchestrator.driver step   --workspace /path/to/work
    python3 -m orchestrator.driver run    --workspace /path/to/work

    # live dashboard (read-only)
    python3 -m orchestrator.driver serve  --workspace /path/to/work --port 8765

State lives at `<workspace>/.orchestrator/state.json`; raw worker outputs at
`<workspace>/.orchestrator/raw/`. A failed run keeps its full explanation in
`state.failure` and the event log; `status` prints it. Config is frozen into
the state at `init`.

## Local service panel (multi-run)

The repo doubles as a local programming service: projects pin nothing — you
point the panel at any workspace directory and launch milestones from the
browser.

    ./panel.sh                # from the repo root -> http://127.0.0.1:8700
    ./panel.sh --port 9000 --open

Left pane: launched milestones (process dot, milestone status). Right pane:
the selected run — pipeline, rounds, seals, failure banner, event log,
driver log — with Start / Stop / Forget. "New milestone" takes a workspace
path plus a goal text **or a work-description doc path** (its content
becomes the goal, snapshotted at launch), an optional verification command,
and an optional advanced config JSON merged over defaults. Verification
is zero-config by default: the implement worker reports the repo's
official full-suite command (`suite_command` in its contract), the
driver arms the implementation-unit gates with it (explicit config
`verification` normally wins and runs on every unit; a `fix_findings`
`suite_command` that fixes a stale explicit gate replaces it for later
gates), each gate execution
lands in the ledger, and `verification_timeout` defaults to unlimited —
suites may legitimately run for hours. Panel launches
enable `git.enabled` by default — the full gate/amend/delta-review
discipline described above; pass `{"git": {"enabled": false}}` in the
advanced config for a deliberate pure-state run. Both path fields
have a Browse… picker (`GET /api/fs`, read-only listings; a typed path that
does not exist yet opens at its nearest existing ancestor) and a dropdown of
previously used paths (`GET /api/recents`, best-effort form memory in
`~/.impl_roadmap/recents.json` — a failed recents read or write never fails
the endpoint or the launch). Known limitation: `/api/fs` performs plain
synchronous filesystem calls with no timeout, so browsing into a dead
network mount (hung NFS/SMB under `/Volumes`) blocks that request — and any
retries — until the mount recovers; the service itself stays responsive
(one daemon handler thread per request), but such a listing cannot be
cancelled. Avoid pointing the picker at dead mounts.

Service home is `~/.impl_roadmap/` (override with `--home`): `registry.json`
(pointers to per-workspace states + PIDs; atomic writes under an advisory
lock) and `logs/<run-id>.log` (driver output). Runs execute as detached
background processes (`python3 -m orchestrator.driver run`); the panel is a
read-only poller plus launch/stop controls. Deleting a run only forgets the
registry entry — workspace files are never touched. Attaching
(`"attach": true`) adopts an existing workspace state exactly as it is on
disk; supplying a goal/goal_doc/config alongside it is rejected rather than
silently ignored.

Process semantics: the service keeps the handles of drivers it spawned and
reaps exited ones on every API call (an exited run can never linger as a
zombie shown "running"), clearing the recorded pid. Stop SIGTERMs the
driver's own process group and the driver forwards the stop to any
in-flight worker CLI's process group (workers run in their own sessions),
so no full-permission worker is orphaned mid-edit. A pid recorded by a
previous service process (after a restart) is trusted only while it is a
live session leader — which a real driver always is and an OS-recycled pid
almost never is — so stale pids neither wedge start/delete nor let stop
signal an innocent process group.

Trust model: binds 127.0.0.1, no auth. It spawns full-permission LLM CLIs,
exactly like running the driver yourself; never expose the port.

### Built-in reuse-audit safeguard

Projects can enable one built-in safeguard pair with:

    POST /api/projects/<slug>/policies/reuse-audit
    {"source": "...", "inventory": "...", "registry": "...", "version": 1}

The service writes two ordinary policies: `reuse-audit` for skeleton and
slice-note drafting, and `reuse-audit-review` for review/delta/seal reports.
They require one per-package audit row, with citations, checked against the
immediate children of `inventory`. Required `source`, `inventory`, and
`registry` values have no built-in defaults; blank or unknown parameters
refuse with `invalid_template_params`. Omit `version` to use `1`.

Illustration only, not a baked-in ecosystem:

    {
      "source": "life_product_components",
      "inventory": "vendor/life_product_components/packages",
      "registry": "vendor/life_product_components/REGISTRY.md",
      "version": 1
    }

V1 supports one audited source per project through this template because the
field names are fixed. Additional sources can be hand-authored as ordinary
policies with distinct ids and fields. Bump `version` on any substantive
parameter change so later runs record a new `project_safeguard_seen` event.

If a work area also records `work_area_meta.reuse_sources`, keep its
`root`, `inventory`, `registry`, and `consumption` descriptors consistent
with the template parameters. The template does not read that descriptor; it
is project-wide standing law supplied explicitly by the operator.

## The flow

For the milestone: one `skeleton` unit, then per slice a `slice_doc` and a
`slice_impl` unit. Every unit runs:

    draft/implement (edit-permission worker call) -> wip commit
      -> verification suite (fail -> the findings go to the FIX LOOP)
      -> codex review rounds (REPORT-ONLY) until a clean round
      -> claude review rounds (REPORT-ONLY) until a clean round
      -> verification suite
      -> double seal: both families report-only on the unit's amended
         commit; findings -> FIX LOOP -> verify -> full new attempt;
         both clean -> the wip commit is finalized as the GATE COMMIT.

Under a reform strategy profile (any governing profile that is not the
`legacy` compat artifact), doc-unit drafts additionally pass the question
battery gate: the skeleton and each slice note must answer a fixed set of
engineering questions (victim, machinery, consumers, cheaper alternative,
cost; slice notes inherit those and answer the slice-scoped remainder) as
structure with evidence citations — written into the document and
mirrored in the contract JSON, where presence is machine-checked
(`contracts.validate_battery`; a violation costs the worker's single
repair retry). Reviews check presence AND substance (a hollow entry or
evidence that does not support its answer is a finding) but never
re-litigate the wording of an answered, evidenced entry. Reform reviewer
findings also hard-require the `plain`/`example` lay mirror. Legacy and
profile-less runs see none of this — their prompts and worker validation
stay byte-identical to the pre-reform driver (the one global change is
that `battery` is now a reserved output key on doc-draft kinds, so a
project contract extension may no longer claim it).

### Review/fix separation (whoever detects never fixes)

Every review — codex round, claude round, seal half, delta review — is
REPORT-ONLY: it returns findings and edits nothing (enforced by workspace
snapshots; a tampering reviewer's output is discarded and, because reviews
run on a clean worktree, the workspace is mechanically restored to HEAD —
with git disabled there is no restorable HEAD, so a tampering reviewer
fails the run with the explanation instead of touching the worktree).
The driver uses clean reviews to advance state; dirty reviews queue their
findings for the FIX LOOP:

    findings -> FIXER (edit permissions: verifies each finding against the
      real code/doc; concedes-and-fixes, or dissents-and-justifies)
      -> DELTA REVIEW (report-only, target = the pending `git diff HEAD`
         of the fix — review the 5 changed lines, not the 1000-line unit)
      -> findings? -> back to the FIXER (same episode, capped by
         max_fix_loops)
      -> green -> AMEND into the unit's wip commit -> continue exactly
         where the dirty review left off (next round of the same family,
         re-verify, or a fresh seal attempt)

Per-act family policy (config "acts"): each act — fixer, delta_review,
consultation — is a fixed family name, "self", or "opposite" (relative to
the act's origin). This release pins fixer and delta_review to codex for
speed; review rounds and seal halves keep their family identity by
definition.

### Adjudicated rejections (no infinite finding loops)

A fixer rejection requires the opposite-family consultation, and when the
target was correct-but-misreadable, a `prevention` edit documented in the
target itself. Every rejection lands in the milestone-global registry
(derived from the append-only rounds; ids like `skeleton-claude-r1/F1`)
and is injected into EVERY subsequent review and fix prompt. Re-raising a
settled finding requires `contests` with the registry id and genuinely new
evidence — both validated structurally (unknown ids fail the run). A
duplicate without new evidence dies by pointer: `rejected_adjudicated`
citing the registry entry, zero new consultations. A contested finding is
never killable by pointer — the contest re-opened that adjudication, so the
fixer must fix or reject it with a fresh consultation (enforced
structurally). When the fixer CONCEDES a contested finding (`fixed`), the
contested adjudication is overturned: it leaves the registry, no longer
satisfies `adjudication_ref`, and the finding may be re-raised freely. The
jurisprudence is committed at every gate in the milestone's `adjudications.md` ledger.

### Git gates and the amend discipline

With `git.enabled`, the workspace is (or becomes) its own git repository —
strictly its OWN: a workspace nested inside another repo gets an
independent nested repo, and every staging/commit operation hard-fails
rather than touch an enclosing project. Each unit opens with a wip commit
of its draft; green fix episodes AMEND it (one clean commit per unit, no
patch stacking); the double seal reviews that amended commit and a passing
seal finalizes it under the canonical gate message (`Seal milestone
skeleton`, `Seal slice NN note`, `Seal slice NN implementation and close`,
`Close milestone`). At each gate the driver regenerates the markdown
ledgers from state.json — the milestone record (`README.md`; `MILESTONE.md`
in the legacy `docs_dir: "docs"` layout), `review-log.md`,
`adjudications.md`, `closures/`, all under the run's `docs_dir`
(default `implementation/milestones/<slug>/`), plus the machine-maintained
milestone index in the parent directory — and folds them into the gate.
The JSON is the source of truth; ledgers are compiled views, so
ledger-vs-state drift is structurally impossible.

Access model: workers get full READ access (sibling repositories,
dependency checkouts — whatever tracing requires; the CLI bypass flags
stay). Edits are only legitimate inside the workspace and only for
edit-kind calls; the boundary is enforced by detection, not sandboxing.

## Demo (no LLMs, ~seconds)

    orchestrator/examples/calculator/run_demo.sh

Runs the whole flow against a scripted fake LLM: deliberate div bug (forces
the verification-fix path), a mid-flow review finding, and a seal finding
(forces a seal-fix + second attempt). Ends with the milestone closed.

## Tests

    python3 -m unittest discover -s orchestrator/tests -t .

Tiers:
1. Unit: state transitions, append-only enforcement, JSON extraction,
   contract validation, subprocess runner against tiny fake commands.
2. Mock lifecycle: full milestone via `MockRunner`, happy path and every
   failure path (blocked worker, round caps, seal-half tampering, protocol
   violations).
3. Fake-CLI e2e: real subprocesses, the calculator scenario end to end.
4. Real LLMs (opt-in, costs quota):

       ORCH_REAL_LLM=1 python3 -m unittest \
         orchestrator.tests.test_real_llm -v

   Uses `examples/calculator/config.real.json` (codex + claude CLIs must be
   installed and authenticated).

## Operational semantics

- **Worker calls are at-least-once.** State is saved atomically only after
  a step completes; a crash between a worker CLI call and that save leaves
  the pre-call state on disk, so resuming re-executes the same call over
  the (possibly half-mutated) workspace. Bookkeeping never duplicates —
  records exist only once saved — but LLM cost and workspace edits from the
  lost execution are not rolled back.
- **One driver invocation at a time.** Each step takes an advisory
  `flock` on `<state>.lock` and refuses (`ConcurrentRunError`) if the
  in-memory state is stale relative to disk — BEFORE running any worker
  call. Two concurrent `run`/`step` invocations on the same state fail
  fast instead of double-executing side effects. (`serve` is read-only and
  needs no lock.)
- **Snapshot exclusions.** Workspace snapshots skip runtime dirs and
  common Python tool caches (`.git`, `.orchestrator`, `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.hypothesis`, `.tox`,
  `*.egg-info`), so a report-only worker whose focused checks write tool
  caches is not falsely invalidated (with git enabled the tamper universe
  additionally honors `.gitignore`). Reviewers and seal halves are told
  NOT to run the full suite — the driver runs it mechanically at the
  verification gates. Add tool-specific cache
  directory names (or fnmatch patterns) via the `snapshot_exclude_dirs`
  config list. Cache FILES written at the workspace root (e.g. coverage's
  `.coverage`) are not excludable; point such tools elsewhere (e.g.
  `COVERAGE_FILE`).
- **`max_verify_fix_attempts` is per stage.** The cap bounds consecutive
  fix attempts for the currently failing verification stage (pre-review or
  pre-seal) and resets when that stage passes.

## Deliberate v0 divergences from canon v0.9

- Seal halves run sequentially by default (`seal_concurrent: false`):
  deterministic and per-half attributable; flip the flag for concurrency.
- The pre-relaunch self-review disappears as a bookkeeping device: every
  round already is a fresh stateless agent, and bookkeeping is code now.
- Consultation transcripts are saved by workers under
  `.orchestrator/scratch/` on the honor system; only the JSON resolution is
  recorded structurally.
- Gate commits, the amend discipline, and delta reviews require `git.enabled`
  (off by default for pure-state CLI runs; the demo config and service-panel
  launches enable it); pushing is not automated — the operator pushes.

These are inputs for canon v10, which will be written against this driver.
