# Orchestrator

A deterministic driver for the canon delivery flow. The control loop that
used to be an LLM following prose rules — sequencing phases, launching
reviews, keeping bookkeeping consistent — is now hardcoded, tested Python.
LLM CLI workers keep all content judgment: they draft, review, fix, and run
opposite-family consultations themselves; the driver only decides *which*
call is legal next, records immutable history, and enforces gates
mechanically.

Motivation, from the field: mid-2026 milestone logs showed repeated gate
failures caused purely by orchestrator bookkeeping drift (stale work-log rows,
misattributed self-review lines, evidence fields forgotten). Every one of
those rules is enforced here structurally.

## What is enforced in code (was prose)

| Rule (canon) | Enforcement point |
|---|---|
| History is never rewritten | `state.save()` refuses non-append-only diffs (`HistoryRewriteError`) |
| Phase gates (docs: draft -> rounds -> final verify -> seal; implementation: baseline -> implement -> rounds -> final verify -> seal) | `state.transition_unit()` raises `IllegalTransition` |
| Family order; changed candidate bytes restart review at the first family | review-cycle freshness is reset whenever an accepted fix changes the candidate |
| Seal is a deterministic result, not another review | every family must be clean or debt-clean on the same current bytes, then the verification suite must pass |
| Whoever detects never fixes: ALL reviews are report-only | `contracts.REPORT_KINDS` forbid dispositions and file changes; workspace snapshots detect tampering; tampered reviews are discarded and the worktree restored to HEAD |
| A rejected finding requires an opposite-family consultation | `contracts.validate_fix_finding()` (P0-P3; therefore also P0/P1) |
| Settled findings stay settled | milestone-global adjudication registry injected into every prompt; `contests` and `rejected_adjudicated` references validated against it; misreadable-target rejections carry a `prevention` edit |
| The fixer triages exactly what was queued | `contracts.validate_fix_coverage()` (same ids, nothing invented) |
| Round/final-verify-fix caps | driver executors fail the run with the explanation in the event log |
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
    ./panel-remote.sh         # ngrok + Google OAuth exact-email allowlist

Remote access fails closed unless ngrok injects a known Google identity.
The configured administrator sees every project and assigns either configured
user from each project's **Admin users** menu; ordinary users see and operate
only assigned projects and their runs. Project creation/deletion, membership,
filesystem browsing, recents, and global profile writes remain admin-only.
Direct loopback access is the trusted administrator recovery path.

Left pane: one list per project of everything that project holds —
milestones (flag icon) and brainstorming sessions (lamp icon) together,
whatever is in progress first, then the rest newest-first. Both kinds open
in the right pane. For a milestone that is the run view — pipeline,
rounds, seal results, failure banner, event log, driver log — with Start / Stop /
Forget. For a session it is the polled session view: status and round
line, Stop session, an activity chip row (one chip per completed round
and ballot, a live spinner chip for the round under way, the accepted
target when one exists), the discussion transcript rendered as Markdown,
and the result below. Session metadata, participants and the accepted
target's content live behind its **Info…** button, along with a danger
zone: **Discard session…** removes a stopped session from the panel and
purges its stored discussion state (`DELETE
/api/brainstorming/sessions/<id>?purge=1`; without `purge` only the
service record is forgotten and the durable state stays as evidence — a
milestone replaying a retained revision keeps working). A running
session refuses deletion (`brainstorming_session_running`, 409 — the
same refusal covers a stop still reconciling, so a freed target can
never be rewritten by a stale stop) — stop it first; the target document
is never touched either way, and deleting frees its target for a new
discussion. A session whose stored state cannot even be read still
offers Discard from its failure screen — deletion needs only the
service record. There is no separate session
page — the panel is the only viewer.

Work starts from a project's **⋯ menu**, never from a standing button:
"New milestone" and "New brainstorming" are the first two items (every user
who can see the project gets them; Configure and Admin users stay
administrative). "New milestone" preselects that project and takes a goal
text **or a work-description doc path** (its content
becomes the goal, snapshotted at launch), an optional verification command,
and an optional advanced config JSON merged over defaults. Verification
is zero-config by default: the implement worker reports the repo's
official full-suite command (`suite_command` in its contract), the
driver uses it for that implementation's final boundary and later units
(explicit config `verification` wins and is available from the first
baseline; a `fix_findings` `suite_command` that fixes a stale explicit gate
replaces it for later boundaries). Documentation skips the pre-review suite
and runs the known suite once, after its reviews. Implementation establishes
a baseline before work starts, reusing a prior stable final green only when
the exact candidate bytes and exact command list still match; it then runs
the full suite once more after its reviews. There are no full-suite runs
between review/fix cycles. Before the first zero-config implementer reports a
command, the baseline and earlier documentation boundaries are necessarily
recorded as vacuous; that implementer's command arms its final boundary and
all later ones. Each execution or reuse
lands in the ledger, and `verification_timeout` defaults to unlimited —
suites may legitimately run for hours. Panel launches
enable `git.enabled` by default — the full gate/amend/delta-review
discipline described above; pass `{"git": {"enabled": false}}` in the
advanced config for a deliberate pure-state run.

Git-enabled implementation calls also keep reviews bounded. At 1,000
reviewable changed lines the active worker is asked to finish one coherent
functional cut; beyond 1,500 it is stopped and a fresh worker must reduce and
stabilize that cut. The meter is additions plus deletions from the fixed
pre-call Git tree, including non-ignored untracked files and excluding
Markdown, text, and runtime bookkeeping. A cut becomes part `a`, completes
its own commit and ordinary review cycle, and only then opens part `b`; later
parts repeat the same strictly sequential flow. Override the thresholds with
`implementation_size_control.soft_lines` and `.hard_lines`.

Both path fields
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

Persisted runs remain resumable: an old `pre_review_verify` state now opens
reviews without running the suite. An already-active old review cycle restarts
once because the declared final-suite command is now part of the evidence each
approval binds to.

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

Standalone Brainstorming uses a separate service record and state store under
`~/.impl_roadmap/brainstorming/`; it never creates a milestone run or registry
entry. `POST /api/brainstorming/sessions` accepts the exact generic request,
ordered `{id, role}` participants, and closure policy, with an optional
`project`/`work_area` pair. `GET /api/brainstorming/sessions/<id>` is the
polling/follow surface, and
`POST /api/brainstorming/sessions/<id>/stop` accepts no fields. All three
successes return `{"ok": true, "session": ...}`. Stop waits for local work to
be quiet, restores only the accepted target artifact, and publishes a coherent
failure; if that safety evidence is unavailable it returns
`brainstorming_stop_incomplete` without inventing a result.

`GET /api/brainstorming/sessions` lists every session the caller may see
(`{"ok": true, "sessions": [...]}`), newest creation first — the sidebar's
source. Authorization is decided from the immutable service record before
any durable state is read, so a session in a project you are not assigned
to is simply absent rather than refused; a project-less session is
administrative. Each row carries the service metadata plus a cheap state
projection (`status`, `question`, `rounds_used`/`max_rounds`, `revision`);
a session whose state store cannot be read still lists, with those fields
null and the fault in `state_error`, because one broken session must never
hide the others.

The panel's **New brainstorming** dialog assembles exactly that create body:
project and work area (the posted `workspace_path` is the bound area's own
primary root — the seam refuses any other value), question, brief, target
document (relative to the work directory), a managed reference-document
list (add/remove, Browse for the administrator), closure policy, and the
round ceiling. Beside the target's Browse, **New…** picks an existing
directory and proposes `bs-<stamp>/DECISION.md` inside it (editable): the
create body then carries the optional `create_target_parents: true`, and
the service makes the target's missing parent folders at creation — under
the registry lock, after containment and authority-overlap validation —
and removes exactly what it created if the create fails (a folder a
concurrent create adopted is never removed). Absent or false keeps the
historical refusal for a missing parent. Panel pickers open at the bound
work area's directory when one is chosen and fall back to
`~/Development/source` (walked up to the nearest existing ancestor on
other hosts). Participants are AI seats configured like milestone acts —
one lead plus one or more interlocutors, each with agent family, model and
effort, rows added and removed in place; seat ids are generated, never
typed. Every dial left at default is resolved by the service exactly as
before: family by rotation over what this host offers, model/effort from
the family's defaults — and when pins would herd every seat onto one
family while another is available, the last default seat takes the other
family instead, so a partially pinned roster is never refused for a shape
the service's own rotation produced. A pin travels in the create body (`model_family` /
`model` / `effort`, all optional per participant): a pinned family narrows
that seat's eligibility — so a roster pinned entirely to one family is a
deliberate choice, not an invalid same-family fallback — an unavailable
family refuses with `invalid_brainstorming_request`, and each seat's
resolved model/effort is recorded once in the service record's
`runtime.executors` (keyed by per-seat `executor_ref`), which the
lifecycle child replays without re-deriving; the session's **Info** view
shows the resolved family, model, and effort for every seat without exposing
runtime commands. Records created before seats
carried their own settings keep family-default behavior byte-identical.
Refusal tokens surface verbatim; the panel validates only form
completeness.

A milestone that opens a session remains alive, observes it until terminal,
and then routes the result without a manual restart. It chips the discussion
in the unit's chronology
(the `brainstormings` array of each unit in the run summary, derived from
the ledger's `brainstorming_wait_started` event and whichever event routed
its result back — `continued`, `restarted`, `failed`, `detached`, or still
`waiting`). The chip opens that session's page.

Panel time is completed LLM work derived from the append-only ledger, not
driver wall time: draft/implement calls, review/fix/delta rounds, reported
builder gaps, repaired first strikes, and reclassifications each count once.
Parallel review-profile calls both count because this measures work consumed.
The deterministic seal adds no LLM time. The global clock sums all units; each
Slice heading sums its doc + implementation units. Verification, backoff, and
interrupted calls without a completed duration stay out.

Trust model: binds 127.0.0.1, no auth. It spawns full-permission LLM CLIs,
exactly like running the driver yourself; never expose the port.

### Built-in reuse-audit safeguard

Projects can enable one built-in safeguard pair with:

    POST /api/projects/<slug>/policies/reuse-audit
    {"source": "...", "inventory": "...", "registry": "...", "version": 1}

The service writes two ordinary policies: `reuse-audit` for skeleton and
slice-note drafting, and `reuse-audit-review` for review/delta reports.
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

(What a milestone *is* — one bounded increment, not a whole project; sized
into ~500-line slices — is defined in [WORKSPACE.md](../WORKSPACE.md#what-is-a-milestone).
This section is the per-unit machinery.)

For the milestone: one `skeleton` unit, then per slice a `slice_doc` and a
`slice_impl` unit. Documentation runs:

    draft (edit-permission worker call) -> wip commit
      -> codex review rounds (REPORT-ONLY) until a clean round
      -> claude review rounds (REPORT-ONLY) until a clean round
      -> one final verification suite
      -> deterministic seal

Implementation runs:

    baseline boundary before implementation
      (run the known suite, or reuse an earlier stable final green when exact
       bytes and commands match; vacuous only while no command is known)
      -> implement (focused checks while working) -> wip commit
      -> codex review rounds (REPORT-ONLY) until a clean round
      -> claude review rounds (REPORT-ONLY) until a clean round
      -> one final verification suite
      -> deterministic seal: the ledger proves that every configured family
         is clean or debt-clean on these same bytes and final verification
         passed; no worker is called, and the wip commit becomes the GATE
         COMMIT.

If an accepted fix changes candidate bytes, all earlier whole-artifact
approvals become stale and review restarts at the first family. Implementers,
fixers, and reviewers use focused checks where relevant; the full suite is
not repeated between review cycles. If no bytes changed, same-byte approvals
remain current. If final verification itself changes candidate bytes, review
restarts on those resulting bytes and the final suite runs again only after
the new reviews are clean.

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

Every review — codex round, claude round, and delta review — is
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
      -> green -> AMEND into the unit's wip commit -> restart whole-artifact
         review at the first family; full verification waits for final closure

A failing final suite opens a dedicated full-suite fixer call, not a synthetic
review-finding dispute. The fixer receives the goal, reviewed design, project
context, amendments, proportionality rules, and configured suite commands; it
receives no parsed or truncated failure excerpt. It runs the complete suite,
repairs only justified failures, and returns `ok` only after the final workspace
bytes are green (`blocked` stops the run). That success is bound to the exact
bytes and commands. Changed bytes still take the normal delta and full-review
path, but unchanged review calls do not rerun the suite; any later edit or
command change invalidates the success automatically.

For a fix episode born from a review round, the pending diff is checkpointed
after the fifth fix instead of launching another delta review. No synthetic
clean round is recorded: the WIP commit is amended, the checkpoint is logged,
and the changed candidate returns directly to a full review beginning with
the first family. The limit is derived from the episode history, so
Stop/Start or Resume cannot reset it, and it keys off the episode's original
kind so a dirty-delta re-queue cannot disable it. Verification and gap-repair
episodes keep their real delta reviews. The threshold is configurable with
`delta_full_review_after_fixes` (zero disables it).

Per-act family policy (config "acts"): fixer and consultation are a fixed
family name, "self", or "opposite" (relative to the act's origin). The
`skeletoner` act drives all skeleton content work — its draft, re-drafts, and
fixes — with one operator-chosen model (default claude-fable-5/max); only
skeleton reviews stay on the review families. Delta review has no independent
policy: it always uses the latest fixer's family and the selected Review
profile for that family. Whole-artifact review rounds keep their family
identity by definition; sealing launches no family worker.

The liveness watchdog kills a worker whose whole process tree burns less than
`worker_stall_min_cpu_s` of CPU across a full `worker_stall_window_s` window (a
frozen CLI); it is typed as a recoverable timeout and auto-resumed. There is no
hard wall-clock timeout, so a legitimate long-running test suite is never
touched. Set the window to zero to disable it.

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
patch stacking). Whole-artifact reviews approve that amended commit; when all
families are effectively clean on the same bytes and final verification passes, the
deterministic seal finalizes it under the canonical gate message (`Seal milestone
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

Runs the whole flow against a scripted fake LLM: a deliberate div bug forces
the final-verification fix path, and later review findings change bytes twice. Each
change invalidates prior approvals and restarts review at the first family.
The milestone closes from clean same-byte reviews without a seal worker call.

## Tests

    python3 -m unittest discover -s orchestrator/tests -t .

Tiers:
1. Unit: state transitions, append-only enforcement, JSON extraction,
   contract validation, subprocess runner against tiny fake commands.
2. Mock lifecycle: full milestone via `MockRunner`, happy path and every
   failure path (blocked worker, round caps, review tampering, protocol
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
  additionally honors `.gitignore`). Reviewers are told NOT to run the full
  suite — it runs mechanically for an implementation baseline and at the final
  boundary after reviews; after a boundary failure, the dedicated fixer owns
  full-suite convergence. Add tool-specific cache
  directory names (or fnmatch patterns) via the `snapshot_exclude_dirs`
  config list. Cache FILES written at the workspace root (e.g. coverage's
  `.coverage`) are not excludable; point such tools elsewhere (e.g.
  `COVERAGE_FILE`).
- **`max_verify_fix_attempts` bounds unstable baselines.** The compatibility
  name remains in frozen configs, but the value now caps only repeated baseline
  executions that keep changing candidate bytes. Final-suite convergence is a
  single fixer responsibility. An ordinary failing baseline stops before
  implementation opens rather than being folded into a not-yet-existing WIP.

## Deliberate v0 divergences from canon v0.9

- The seal is a deterministic ledger result after same-byte reviews and the
  final verification boundary; it launches no reviewer and has no concurrency
  mode.
- The pre-relaunch self-review disappears as a bookkeeping device: every
  round already is a fresh stateless agent, and bookkeeping is code now.
- Consultation transcripts are saved by workers under
  `.orchestrator/scratch/` on the honor system; only the JSON resolution is
  recorded structurally.
- Gate commits, the amend discipline, and delta reviews require `git.enabled`
  (off by default for pure-state CLI runs; the demo config and service-panel
  launches enable it); pushing is not automated — the operator pushes.

These are inputs for canon v10, which will be written against this driver.
