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
| Seal halves review the same unchanged artifact and edit nothing | workspace snapshots (file contents, directories, symlink targets, unreadable-file markers) before/after each half; violations invalidate the half and send the unit back through pre-seal verification |
| A rejected finding requires an opposite-family consultation | `contracts.validate_finding()` (P0-P3; therefore also P0/P1) |
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
and an optional advanced config JSON merged over defaults.

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

## The flow

For the milestone: one `skeleton` unit, then per slice a `slice_doc` and a
`slice_impl` unit. Every unit runs:

    draft/implement (full-permission worker call)
      -> verification suite
      -> codex review-and-fix rounds until a clean round
      -> claude review-and-fix rounds until a clean round
      -> verification suite
      -> double seal: both families report-only on a hash-verified
         unchanged workspace; findings -> one seal-fix call -> verify
         -> full new attempt; both clean -> sealed. An INVALIDATED
         attempt (a half modified the workspace) also goes back through
         pre-seal verification before the next attempt: the tampering
         delta is never double-sealed unverified.

Review rounds have full edit permissions and fix in-pass (exhaustive-pass
instruction is in the prompt). Consultations with the opposite family are
run by the worker itself; the driver records outcomes from the JSON.
A fix call on the skeleton unit that changes the slice plan reports the
updated plan in its JSON (`slices`); the driver keeps the structural unit
plan in sync until the skeleton seals. Slice ids are validated as unique
integers — a duplicate id would silently collapse the unit plan.

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
  `*.egg-info`), so a read-only seal half that runs the verification suite
  is not falsely invalidated by cache writes. Add tool-specific cache
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
- No git commits at gates yet; the state file is the ledger.

These are inputs for canon v10, which will be written against this driver.
