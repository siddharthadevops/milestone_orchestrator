# Orchestrator

A deterministic driver for the canon delivery flow. The control loop that
used to be an LLM following prose rules — sequencing phases, launching
reviews, keeping bookkeeping consistent — is now hardcoded, tested Python.
LLM CLI workers keep all content judgment: they draft, review, fix, and rate
findings when dispatched. Workers never launch other LLMs; the driver alone
decides *which* model call is legal next, records immutable history, and
enforces gates mechanically.

Motivation, from the field: mid-2026 milestone logs showed repeated gate
failures caused purely by orchestrator bookkeeping drift (stale work-log rows,
misattributed self-review lines, evidence fields forgotten). Every one of
those rules is enforced here structurally.

## What is enforced in code (was prose)

| Rule (canon) | Enforcement point |
|---|---|
| History is never rewritten | `state.save()` refuses non-append-only diffs (`HistoryRewriteError`) |
| Phase gates (docs: draft -> rounds -> seal; implementation: implement -> rounds -> scheduled verify when due -> seal) | `state.transition_unit()` raises `IllegalTransition` |
| Family order; changed candidate bytes restart review at the first family | review-cycle freshness is reset whenever an accepted fix changes the candidate |
| Seal is a deterministic result, not another review | every family must be clean or debt-clean on the same current bytes; scheduled verification must also pass when due |
| Whoever detects never fixes: ALL reviews are report-only | `contracts.REPORT_KINDS` forbid dispositions and file changes; the report-only contract is carried by prompt and envelope, not re-verified by snapshot (see Review/fix separation) |
| A rejected finding requires a concrete fixer validity account, never another LLM call | `contracts.validate_fix_finding()` plus the routed fixer prompt |
| Eligible delta-review findings receive the same driver-owned classification as full-review findings | `_partition_defer_candidates()` partitions debt from fixer work before either review kind queues findings |
| Settled findings stay settled | milestone-global adjudication registry injected into every prompt; `contests` and `rejected_adjudicated` references validated against it; misreadable-target rejections carry a `prevention` edit |
| The fixer triages exactly what was queued | `contracts.validate_fix_coverage()` (same ids, nothing invented) |
| Round/verification-fix caps | driver executors fail the run with the explanation in the event log |
| Blocked -> stop with explanation, no silent retries | `status: "blocked"` or a `blocked` disposition ends the run; the reason is in `state.failure` and the events |
| No prose parsing of reviewer output | workers must return contract JSON (`contracts.py`); one repair retry, then the run fails, except cutoff stabilization starts a fresh stabilizer while preserving its work |

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
line, Stop/Start for pausing and resuming the same session, an activity chip
row (one chip per completed round
and ballot, a live spinner chip for the round under way, the accepted
target when one exists), the discussion transcript rendered as Markdown,
and the result below. Session metadata, participants and the accepted
target's content live behind its **Info…** button, along with a danger
zone: **Discard session…** removes a stopped session from the panel and
purges its stored discussion state (`DELETE
/api/brainstorming/sessions/<id>?purge=1`; without `purge` only the
service record is forgotten and the durable state stays as evidence — a
milestone replaying a retained revision keeps working). A session whose
process is running refuses deletion (`brainstorming_session_running`, 409 — the
same refusal covers a stop still reconciling, so a freed target can
never be rewritten by a stale stop) — stop it first. The target document and
any final sibling `chat-<session>.md` are delivered artifacts and are never
removed; deleting only frees the target for a new discussion. A session whose
stored state cannot even be read still
offers Discard from its failure screen — deletion needs only the
service record. There is no separate session
page — the panel is the only viewer.

The live human-readable `chat.md` stays in Brainstorming's private session
storage. On a terminal result, its complete final form is also delivered beside
the target as `chat-<session>.md`. Brainstorming activity is separate
operational evidence:
every physical provider call keeps its model, phase, duration and outcome,
including a malformed first response, its repair, and execution failures.
The session view shows those calls as clickable chips with raw output on
demand, a live clock for the call in progress, and accumulated LLM work.
Participant-call failures use the same classifier as milestones: it returns
only the typed failure, optional resume time and evidence. Brainstorming owns
the consequence. A recoverable diagnosis preserves the exact pending action,
waits five minutes, and retries it without consuming a turn or round; other
diagnoses close through the existing operational-failure path. Classifier LLM
calls are separate activity, never discussion or target authority, and their
time is included in accumulated LLM work.

A milestone worker requests `need_rethink` with one explained `problem`; it
does not choose a target or echo its call kind. The discussion works across the
project repository, and its durable request, result, prompts and panel carry Git
authority rather than a target artifact. On agreement, editing turns are
already commits and the terminal handoff names the exact
`source_base_revision..accepted_revision` range. An unchanged `A..A` success is
also authoritative. The driver observes that range through the ordinary
canonical-plan boundary and opens reconciliation only when the plan actually
changed. Nothing is applied or independently re-judged at close: the
originating kind runs fresh against the resulting repository. A missing
session/range, operational failure, or no agreement stops for the operator.

Work starts from a project's **⋯ menu**, never from a standing button:
"New milestone" and "New brainstorming" are the first two items (every user
who can see the project gets them; Configure and Admin users stay
administrative). "New milestone" preselects that project and takes a goal
text **or a work-description doc path** (its content
becomes the goal, snapshotted at launch), an optional verification command,
and an optional advanced config JSON merged over defaults. Verification
is zero-config by default. At every fourth completed logical implementation
slice and at milestone completion, the driver dispatches one routed
`suite_checkpoint` LLM call. Explicit config `verification` supplies the exact
ordered commands; otherwise the checkpoint agent inspects repository authority
for the complete suite and may report `no_suite`. The driver executes no shell
suite and implementers report no suite command. A failed checkpoint assigns
its complete command plan to a dedicated fixer. That fixer's `status: ok`
certifies the final workspace bytes; the driver reuses the certification on
those exact bytes instead of executing another checkpoint.
Documentation does not run the full suite, and split implementation parts
(`a`...`z`) still count as one logical slice. Focused checks remain the
implementer's and fixer's ordinary feedback while bytes change; there are no
full-suite runs between review/fix cycles. Each scheduled checkpoint lands in
the ledger. Panel launches
enable `git.enabled` by default — the full gate/amend/delta-review
discipline described above; pass `{"git": {"enabled": false}}` in the
advanced config for a deliberate pure-state run.

Git-enabled implementation calls also keep reviews bounded. Implementers aim
to close coherent sequential units below approximately 750 reviewable changed
lines and may proactively return a cut whenever original slice work remains.
At 1,000 lines the active worker receives a mandatory close instruction and
must acknowledge it explicitly. Crossing 1,500 starts a three-minute grace; a
real model acknowledgement extends it to ten minutes. Transport acceptance
alone is not an acknowledgement. During the grace the delta is not judged
again. On expiry, a fresh worker closes the work already in progress as a
coherent delivery. Stabilization has no further size cutoff and never rewrites
sound work merely to hit a number. A malformed stabilizer handoff starts
another fresh stabilization instead of failing the run. The meter is
additions plus deletions from the fixed
pre-call Git tree, including non-ignored untracked files and excluding
Markdown, text, and runtime bookkeeping. A cut becomes part `a`, completes
its own commit and ordinary review cycle, and only then opens part `b`; later
parts repeat the same strictly sequential flow. Override the thresholds and
graces with `implementation_size_control.soft_lines`, `.hard_lines`,
`.unconfirmed_grace_s`, and `.confirmed_grace_s`.

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

Update/restart protocol: inspect every active milestone or Brainstorming
worker immediately before stopping it. A call at or below two minutes may be
stopped; if it has already exceeded two minutes, let that exact call finish
and inspect again. Any replacement call has then only just begun and may be
stopped under the same two-minute rule. Restart on the new runtime. This
avoids throwing away substantial completed model work merely to load an
update.

Standalone Brainstorming uses a separate service record and state store under
`~/.impl_roadmap/brainstorming/`; it never creates a milestone run or registry
entry. `POST /api/brainstorming/sessions` accepts the exact generic request,
ordered participants with independent `role` and `delivery`, and closure policy, with an optional
`project`/`work_area` pair and an optional `staffing_session`. That session
must be one the caller may already read (`unknown_staffing_session` when it
does not exist, `forbidden` when it belongs elsewhere); omitting it staffs the
discussion from the `default` document at `medium`, which its activity
records. `GET /api/brainstorming/sessions/<id>` is the
polling/follow surface, and `POST /api/brainstorming/sessions/<id>/stop` and
`/start` accept no fields. These successes return
`{"ok": true, "session": ...}`. Stop halts the lifecycle without closing or
discarding the session; Start resumes that same session after an ordinary
stop. If the lifecycle does not stop within the existing shutdown window,
Stop returns `brainstorming_stop_incomplete`.

When a complete round reaches the limit without agreement, the session enters
non-terminal `waiting` and its process stops. Its task and any reviewed, deep,
or milestone owners remain open. The discussion view shows used, maximum, and
remaining rounds and offers **Add rounds** and **Continue**:

- `POST .../<id>/rounds` accepts exactly `{"maximum": <positive integer>}`.
  It raises the current maximum without starting work. Repeating the same
  absolute maximum is safe, and a smaller stale request cannot reduce it.
- `POST .../<id>/continue` accepts exactly
  `{"waiting_revision": <positive integer>}`, using the revision from the
  current waiting view. It resumes the same discussion with at least two
  complete rounds available, retaining a larger manually reserved allowance.
  A duplicate or stale revision returns `409 brainstorming_continuation_conflict`;
  a later exhaustion requires fresh action using that wait's revision.

Both controls use the existing authenticated session routes and return
`{"ok": true, "session": ...}`. Start cannot bypass `waiting`. The admitted
limit, accepted discussion history, and accounting are preserved. Waiting
for the operator has no timeout and consumes no reviewed execution-step budget.
Stopping an owning task explicitly abandons its discussion and leaves both
terminal. These controls never reopen historical terminal sessions or tasks;
further work on those requires a new order.

An external participant publishes one durable intervention and releases the
target lock while waiting. `GET .../<id>/intervention` returns that request;
`POST .../<id>/intervention` accepts exactly its token and one response.
Restarting preserves the wait; a stopped session resumes through its explicit
Start action. A stale, duplicate, or late response conflicts instead of entering
another turn. The `narrator`
provider uses this same channel today; `manual` leaves it waiting for an
external UI.

Separately from roster turns, any authorized caller may append one
out-of-turn **floor intervention** — `POST .../<id>/floor` with
`{"text", "author_name", "author_id"?}` — into the durable discussion
record at the current turn boundary. It renders in the transcript under
its author's name and participants read it as ordinary chat history on
their next call; it consumes no round, no target revision, and no
provider call, and does not interrupt an in-flight turn (the panel's
Intervene dialog offers an explicit stop/start restart for that).
`author_id` must be label_hex32-shaped (the agent_99 entity contract, e.g.
`entity_<32 hex>`), which structurally cannot collide with roster ids;
when absent the service derives one from the authenticated caller. A
terminal session refuses with `brainstorming_floor_intervention_conflict`.

`GET /api/brainstorming/sessions` lists every session the caller may see
(`{"ok": true, "sessions": [...]}`), newest creation first — the sidebar's
source. Authorization is decided from the immutable service record before
any durable state is read, so a session in a project you are not assigned
to is simply absent rather than refused; a project-less session is
administrative. Each row carries the service metadata plus a cheap state
projection (`status`, `request`, `rounds_used`/`max_rounds`,
`rounds_remaining`, `exhausted`, `revision`);
a row also carries accumulated `work_duration_s` and any active `in_flight`
call or `external_intervention`;
a session whose state store cannot be read still lists, with those fields
null and the fault in `state_error`, because one broken session must never
hide the others.

The panel's **New brainstorming** dialog assembles exactly that create body:
project and work area (the posted `workspace_path` is the bound area's own
primary root — the seam refuses any other value), request, brief, target
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
other hosts). The default roster is an Initial Position, a Contrary
Position, and Dante as an external narrator: roles and delivery, not
families — which family runs each of those seats is the discussion's
staffing session's answer (below). Dante asks anti-drift questions in the
language used by the request and discussion, then casts a binding judgment:
his vote counts, and under unanimity an unresolved material objection blocks
closure. New sessions persist
agreement protocol version 2, under which every roster seat votes; historical
sessions without that field retain their original two-position rule. The
dialog's roster rows carry the position and nothing about who runs it, and the
form's one staffing choice — document, rigor and an optional material — opens
the session that answers every seat. Dante's turn enters through the durable
external contract. Unanimity requires every voting seat to accept the exact
proposal. Majority requires a strict majority; ties and round-limit
disagreement end as an irreducible gap. The coordinator records that result
mechanically and never chooses a side.
Participant prompts use the Markdown chat as shared memory, point to the target
and reference documents, and carry only the applicable amendments instead of
duplicating the full transcript and caller payload on every turn.
Every automatic seat is staffed by the discussion's staffing session, not by
the create body: the seat's 1-based roster position resolves `brainstorm`
against that session — or against the `default` document at `medium` when the
create named none — immediately before every physical call, so a completed
session or document edit reaches the next turn, closure vote, classifier or
production effect. Two seats sharing one family is an ordinary answer; the
only split rule left is a `distinct_families` the document itself declares.
A pin still travels in the create body (`model_family` / `model` / `effort`,
all optional per participant) because the panel keeps sending one until its
own control retires, and it decides nothing — not even a pinned family this
host cannot run, which is no longer a request fault. A document that answers
with a family this host cannot run leaves nothing to bind and refuses with
`brainstorming_unavailable`. Each seat's answer at creation is recorded once
in the service record's `runtime.executors` (keyed by per-seat
`executor_ref`) as that seat's binding key and the child's initial binding,
and is never replayed: every dispatch overwrites it by resolving again. No
read-only surface shows it either — the session's **Info** view is that same
live read, what each seat would run on if it were dispatched now, without
exposing runtime commands. Refusal tokens surface verbatim; the panel
validates only form completeness.

A milestone that opens a session remains alive, observes it until terminal,
and then routes the result without a manual restart. It chips the discussion
in the unit's chronology
(the `brainstormings` array of each unit in the run summary, derived from
the ledger's `brainstorming_wait_started` event and whichever event routed
its result back — `continued`, `restarted`, `failed`, `detached`, or still
`waiting`). The chip opens that session's page and carries its consumed LLM
time; the same time is added once to the milestone total.

Panel time is completed processing work derived from the append-only ledger,
not driver wall time: draft/implement calls, review/fix/delta rounds, reported
builder gaps, repaired first strikes, reclassifications, and verification each
count once. Reused verification and a fixer's already-counted suite proof do
not count twice. Parallel review-profile calls both count because this measures
work consumed. The deterministic seal adds no work time. The global clock sums
all units; each Slice heading sums its doc + implementation units. Backoff and
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

### Standalone task Pause, Resume and Cancel

Standalone `agent_call`, `reviewed_task` and `deep_task` orders share durable
Pause/Resume controls. A manual pause or execution failure preserves the task
identity, completed phases, child identities, evidence and accounting, with
`result: null`. Failure is not an automatic retry. The panel shows the reason,
the paused pipeline position, and **Resume** once the prior execution can no
longer write. **Pause** first displays `pausing` while active work reaches a
safe boundary; it is not permission to start a concurrent replacement.

- `POST /api/tasks/<id>/pause` accepts `{}` or `{"reason": "..."}`.
- `GET /api/tasks/<id>` returns the canonical `task` and separate `lifecycle`
  metadata, including `status`, `revision`, `reason`, `source`, control
  availability and any recovery blocker. Sidebar rows include a compact
  `lifecycle` without full attempt history.
- `POST /api/tasks/<id>/resume` requires `{"revision": <paused revision>}`.
  An obsolete or repeated request returns 409; it cannot accept another run.
- `POST /api/tasks/<id>/stop` remains permanent cancellation (**Cancel task**
  in the panel), distinct from Pause. Existing terminal records are immutable.

Deep-task controls operate on the existing parent/child family: a paused child
keeps its parent open, and Resume reuses the recorded child rather than creating
a replacement. Paused state survives a panel restart. Resume refuses while the
previous worker still owns the execution lease or unrelated work owns the tree;
the panel displays that blocker and updates availability on later polls.
An attached discussion's Start/Continue cannot bypass its owner's Pause:
Resume the task first. Add rounds remains a non-starting capacity change.
Error pauses and restart adoption stop independently running owned discussions
before reporting `paused`; uncertain process/provider quiescence leaves the
family `pausing`, with live indicators and its workspace reservation intact.
Cancel also respects that boundary and preserves completed-call accounting,
even if the workspace has been removed or temporarily unmounted.

These task coordinators still run in the panel backend. This change does not
move them into independent process sessions. Brainstorming retains its existing
session controls and round-limit continuation semantics; milestone-owned tasks
remain controlled through their run.

## The flow

(What a milestone *is* — one bounded increment, not a whole project; sized
into ~500-line slices — is defined in [WORKSPACE.md](../WORKSPACE.md#what-is-a-milestone).
This section is the per-unit machinery.)

For the milestone: one `skeleton` unit, then per slice a `slice_doc` and a
`slice_impl` unit. Documentation runs:

    draft (edit-permission worker call) -> wip commit
      -> codex review rounds (REPORT-ONLY) until a clean round
      -> claude review rounds (REPORT-ONLY) until a clean round
      -> deterministic seal

Implementation runs:

    implement (focused checks while working) -> wip commit
      -> codex review rounds (REPORT-ONLY) until a clean round
      -> claude review rounds (REPORT-ONLY) until a clean round
      -> run the full suite after every fourth completed logical slice and at
         milestone completion; split implementation parts count once
      -> deterministic seal: the ledger proves that every configured family
         is clean or debt-clean on these same bytes and, when due, scheduled
         verification passed; no worker is called, and the wip commit becomes
         the GATE COMMIT.

If an accepted fix changes candidate bytes, all earlier whole-artifact
approvals become stale and review restarts at the first family. Implementers,
fixers, and reviewers use focused checks where relevant; the full suite is
not repeated between review cycles. If no bytes changed, same-byte approvals
remain current. If scheduled verification itself changes candidate bytes,
review restarts on those resulting bytes and the suite runs again only after
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
REPORT-ONLY: it returns findings and edits nothing. That is a CONTRACT,
carried by the prompts and by `contracts.REPORT_KINDS`, which forbid
dispositions and file-change claims in a report envelope. It is no longer
re-verified by snapshotting the workspace around the call. Operator
decision on the evidence: across 6,326 recorded report-only rounds the
check never once caught a reviewer editing code, while its false
positives — artifact churn written by the reviewer's own build or test
run, which the prompts explicitly invite — repeatedly discarded good
reviews and burned worker time. The driver uses clean reviews to advance
state; dirty reviews queue their findings for the FIX LOOP:

    findings -> FIXER (edit permissions: verifies each finding against the
      real code/doc; concedes-and-fixes, or dissents-and-justifies)
      -> DELTA REVIEW (report-only, target = the pending `git diff HEAD`
         of the fix — review the 5 changed lines, not the 1000-line unit)
      -> findings? -> back to the FIXER (same episode, capped by
         max_fix_loops)
      -> green -> AMEND into the unit's wip commit -> restart whole-artifact
         review at the first family; full verification waits for its scheduled
         checkpoint

Full and delta reviews use the same configurable classification floors.
`doc_reclassify_from` and `impl_reclassify_from` accept `disabled`, `P3`,
`P2`, `P1`, or `P0`; a floor includes that severity and every less-severe
one (`P2` means P2+P3). Defaults are P2 for documentation and P1 for
implementation. `p3_defer_max_risk` remains the independent rating threshold:
classification decides what is measured, while the threshold decides tracked
debt versus fixing. Deferred findings remain in the run's append-only debt
history and unresolved debt stays available for operator review after closure;
it does not block milestone completion.

A failing scheduled suite opens the fixer's dedicated full-suite mode through
the preserved synthetic P1. The fixer receives the goal, reviewed design, project
context, amendments, proportionality rules, and the checkpoint command plan; it
receives the checkpoint's exact preserved failure account, never a parsed or
truncated substitute. It runs the complete suite,
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

Per-act family policy (config "acts"): fixer is a fixed family name, "self",
or "opposite" (relative to the act's origin). The
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

A fixer rejects directly from its concrete validity account; it never invokes
another model. When the target was correct-but-misreadable, a `prevention`
edit documents the decision in the target itself. Every rejection lands in
the milestone-global registry
(derived from the append-only rounds; ids like `skeleton-claude-r1/F1`)
and is injected into EVERY subsequent review and fix prompt. Re-raising a
settled finding requires `contests` with the registry id and genuinely new
evidence — both validated structurally (unknown ids fail the run). A
duplicate without new evidence dies by pointer: `rejected_adjudicated`
citing the registry entry. A contested finding is
never killable by pointer — the contest re-opened that adjudication, so the
fixer must fix or reject it directly from current evidence (enforced
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
families are effectively clean on the same bytes and scheduled verification has
passed when due, the
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

When a checkpoint agent discovers this repository's official normal suite,
the proportional command is:

    python3 -m unittest orchestrator.tests.suite_checkpoint

For releases, large architectural changes, and deliberate deep verification,
run the exhaustive complement manually:

    python3 -m unittest orchestrator.tests.suite_extended

The two commands partition every retained test. Verify that inventory after
changing suite membership with:

    python3 -m unittest orchestrator.tests.test_suite_inventory

The checkpoint keeps fast unit and contract coverage, central routed-prompt,
state, validation, and driver boundaries, and the real fake-CLI lifecycle.
The extended suite retains slow failure matrices, Git/service/process cases,
multi-profile and compatibility permutations, and legacy prompt-substring
checks. See `orchestrator/tests/README.md` for the measured classification.

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
- **One driver mutation at a time.** Each action takes an advisory `flock`
  on `<state>.lock` and refuses (`ConcurrentRunError`) if the in-memory state
  is stale relative to disk — BEFORE running any worker call. A non-terminal
  Brainstorming wait poll is read-only and skips that mutation lock; terminal,
  stale, and failed polls retain the locked path. Two concurrent `run`/`step`
  invocations cannot double-execute side effects. (`serve` is read-only and
  needs no lock.)
- **Snapshot exclusions.** Workspace snapshots skip runtime dirs and
  common Python tool caches (`.git`, `.orchestrator`, `__pycache__`,
  `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.hypothesis`, `.tox`,
  `*.egg-info`), so a report-only worker whose focused checks write tool
  caches is not falsely invalidated. With git enabled the tamper universe
  additionally honors `.gitignore`, at every depth: a vendored submodule or
  embedded repo is still walked as a subtree, minus the regions ITS OWN git
  ignores, so a reviewer running the project's tests does not read as
  tampering because a vendored dependency rebuilt its `_build/`. The rule
  that makes that safe is that an ignored region is outside the universe, so
  CHANGING what a repo ignores is never free: every file deciding it is
  hashed wherever it lives — `info/exclude` and `config` from the repo's
  common git dir (a linked worktree reads both from there, not from its own),
  the `core.excludesFile` target, and the rule file of any region that cloaks
  itself. A nested repo whose git cannot answer keeps the fully unfiltered
  walk. The deliberate residual, unchanged from what the workspace repo has
  always done for its own ignored regions: content inside an already-ignored
  region is not covered, and such files can never reach a diff, a commit or a
  seal. Reviewers are told NOT to run the full
  suite — it runs mechanically after every fourth logical implementation slice
  and at milestone completion; after a checkpoint failure, the dedicated fixer owns
  full-suite convergence. Add tool-specific cache
  directory names (or fnmatch patterns) via the `snapshot_exclude_dirs`
  config list. Cache FILES written at the workspace root (e.g. coverage's
  `.coverage`) are not excludable; point such tools elsewhere (e.g.
  `COVERAGE_FILE`).
## Deliberate v0 divergences from canon v0.9

- The seal is a deterministic ledger result after same-byte reviews and any
  scheduled verification due at that boundary; it launches no reviewer and has
  no concurrency mode.
- The pre-relaunch self-review disappears as a bookkeeping device: every
  round already is a fresh stateless agent, and bookkeeping is code now.
- Gate commits, the amend discipline, and delta reviews require `git.enabled`
  (off by default for pure-state CLI runs; the demo config and service-panel
  launches enable it); pushing is not automated — the operator pushes.

These are inputs for canon v10, which will be written against this driver.
