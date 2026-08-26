# Slice 11 — Accepted-range reconciliation

## Register 1 — INTENT (lay language)

### What this slice builds

Slice 10 stops at a committed accepted revision `B` whenever a plan change
computes a wipe boundary. This slice gives that frozen record its sole repair
path.

The driver first consumes the open reconciliation as it stands. Before any
provider dispatch it requires the recorded branch, clean repository, `HEAD ==
B`, and the valid canonical block anchored at B. It resolves
`merge_repair@workspace` through the current prompt router, inherits the
source call's material, and supplies the persisted source range, opening
account, and required outcome. Prompt preparation may fail before dispatch;
that is an ordinary terminal failure and marks no handoff.

Immediately before the provider starts, the driver durably records the one
`merge_repair` handoff. That marker is the dispatch authority. A marked open
reconciliation is never dispatched again, including after restart. The call
has exactly one physical attempt: no contract correction, infrastructure
retry, error-classifier call, fallback repair, or second merge-repair engine.

The LLM owns every repository mutation and its final same-branch commit. The
driver does not reset, checkout, apply, cherry-pick, merge, resolve conflicts,
fold commits, restore the work tree, write refs, or regenerate ledgers. A
blocked result, interruption, malformed reply, provider failure, or failed
postcondition records terminal failure and leaves Git exactly as the LLM left
it.

After a valid `status: ok` result, the driver performs only finite read-only
checks:

- the original branch is still checked out and final HEAD is a new commit;
- index and work tree are clean;
- the recorded skeleton is a regular file with one valid canonical block;
- the run-owned interval after milestone start is linear;
- the final account is recomputed from the persisted **original old plan and
  original run boundaries** to the final block, never from the opening
  accepted plan;
- with a final wipe, its boundary is an ancestor of final HEAD and every
  commit in the original `boundary..accepted_revision` interval is absent
  from final HEAD ancestry;
- without a final wipe, B is an ancestor of final HEAD and the account contains
  no invalidations.

The final plan may therefore remove or move the opening boundary. Its account
replaces the opening account and does not dispatch another repair.

Success is one in-memory state transition followed by one save. It installs
the final projection and anchor at final HEAD without calling a Git-writing
anchor helper. It preserves slice-note units and immutable rounds, seals, and
debt. Invalidated implementations whose ids survive the final plan return to a
fresh pending implementation; their stale closure, gate, and parked-candidate
resume marker stop counting. The parked marker also retires when the
invalidated slice is deleted, while its immutable historical records remain.
Deleted slices remain immutable historical records and are no longer planned.
If a later accepted plan reintroduces one of those ids, the existing close
barrier makes every historical implementation phase ineligible and the same
unit identity becomes due for a fresh implementation. A requeue issued by that
same close, or a later closure, prevents resetting an active current rebuild.
An append-only reconciliation-close event records `accepted_revision`, final
HEAD, and the complete final account. It is also the invalidation barrier for
old slice closures and full-suite checkpoint anchors; later reimplemented
closures and checkpoints count normally, including when a later plan edit
computes another account.

The source reply was frozen before consumption. The close retires only its
exact attached task/session carrier and never adopts the discarded reply. If
the final plan retains its owning unit, that ordinary action runs fresh; if the
owner was deleted, it remains historical and is not scheduled. Neither case
starts another structural repair. Finally the active reconciliation key is
removed, allowing a later independent plan edit to open its own one-shot
reconciliation.

### What this slice does not build

- No deterministic Git surgery, preliminary apply, semantic/path/hunk proof,
  commit-message parser, or worker-intent classifier.
- No retry, rollback, cache, backup, migration, compatibility, crash recovery,
  or reconstruction lane.
- No duplicate unit identity or generation system.
- No reconsideration of debt, adjudications, staffing, suite cadence, or
  activation beyond the explicit invalidation barrier. Slice 13 owns cadence
  scheduling and activation.
- No protection from malformed configuration, external repository damage,
  malicious workers, manual Git mistakes, or compound catastrophes beyond the
  declared terminal boundary.

## Register 2 — PINNED FACTS (hard register)

| Fact | Value |
|---|---|
| Trigger | One open `milestone.accepted_range_reconciliation` produced by Slice 10 |
| Dispatch HEAD | Recorded `accepted_revision` B |
| Route | `merge_repair@workspace`, executor `agent_call` |
| Material | Exact source material persisted by Slice 10 |
| Attempts | One physical provider call; no correction, classifier, or retry |
| Handoff authority | Durable marker written immediately before provider dispatch |
| Git author | The merge-repair LLM alone |
| Driver Git writes | None from reconciliation dispatch through close or failure |
| Final-account inputs | Persisted `original_old_plan` + `original_run_boundaries` + final Git block |
| Final-plan freedom | May differ from B; one final account, no second repair |
| Requeue | Retained invalidated `slice_impl` units only; notes stay intact |
| History | Old units/events remain append-only; close event is the invalidation barrier |
| Failure | Terminal operator-visible failure in the LLM-left repository state |
| Success persistence | One atomic state save, then ordinary scheduling resumes |

## Register 3 — VERIFICATION CONTRACT

### Focused tests

1. The routed adapter mounts every merge-repair payload, current amendments,
   project context/safeguards (including a policy scoped directly to
   `merge_repair`), inherited material, and the exact served reply contract.
2. The handoff is visible before the fake runner executes; an already-marked
   reconciliation dispatches zero calls.
3. Invalid output, a transport failure, and `blocked` each make exactly one
   physical call, invoke no classifier/correction/retry, preserve raw/accounting
   evidence, and leave the repository untouched by the driver.
4. Startup with an interrupted merge-repair marker records interruption but
   performs no cleanup restore; startup with any open reconciliation does not
   materialize units from its provisional accepted projection.
5. Final validation rejects branch change, dirty state, unchanged/no final
   commit, invalid block, non-linear run-owned history, missing boundary
   ancestry, and any surviving commit from the original invalidated interval.
6. Final-account recomputation uses the original persisted boundaries and may
   replace the opening boundary with an earlier, later, or no-wipe account.
7. Atomic close requeues retained implementations, preserves note/history,
   leaves deleted units historical, retires the exact source carrier, installs
   the final projection/anchor, appends a barrier carrying final HEAD and the
   complete final account, removes the active reconciliation, and always
   materializes the first unit due in the final plan. Separately, the source
   owner itself reruns only when that owner survives. Reintroducing a
   previously deleted id later requeues its historical implementation rather
   than accepting the invalidated seal.
8. Cadence and subsequent-account readers ignore invalidated pre-barrier
   closures/checkpoints, accept later events for the reimplemented slice, and
   do not resurrect an old checkpoint when another reconciliation opens.
9. `Driver.run()` continues ordinary scheduling after a successful close; it
   returns frozen only while reconciliation remains open.

### Slice gate

Run the focused reconciliation, router/contract, runner, state, driver, and
chronology tests named by this slice. The repository-wide suite remains owned
by the milestone's scheduled checkpoint boundary.

## Register 4 — PROPORTIONALITY CHECK

| Axis | Decision |
|---|---|
| victim | Without this cut, every valid structural plan edit freezes forever at B. |
| machinery | One routed call, finite Git reads, one pure account recomputation, and one state transition. |
| consumers_touched | Reconciliation action, generic call retry switches, canonical-plan account, state requeue, and cadence readers. |
| cheaper_alternative | Driver Git surgery is explicitly forbidden; another repair or recovery lane is larger and unauthorized. |
| cost | Reuses the current route, validator, task, unit, event, and Git seams; adds no parallel store. |
| threat_model | Normal one-shot repair only. Everything outside the declared postconditions fails closed to the operator. |
| verification | Focused structural tests prove the real traversal without Cartesian catastrophe cases. |
