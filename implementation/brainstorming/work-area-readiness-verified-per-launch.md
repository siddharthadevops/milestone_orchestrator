# Work-area readiness: verified per launch, never a stored permission

Status: non-canonical brainstorming — operator-driven need (2026-08-07).

## Need

A brainstorming cannot be launched into a work area the operator has just
declared. The panel offers "New brainstorming" from the project menu, the
operator picks an existing directory, and the create refuses with
`work_area_not_ready`.

Nothing is missing from what the operator supplied. The chain is:

- declaring a work area writes the record at `pending` and touches no
  filesystem — the Body's declare role (`service.py:589`,
  `workareas.py:451`–`:462`);
- a project-bound create resolves through the sealed seam
  (`brainstorming_lifecycle.py:457` → `driver.py:8384` →
  `WorkAreaStore.resolve`), which refuses unless `status == "ready"`
  (`workareas.py:397`);
- the only `confirm()` (`pending` → `ready`) in production code sits inside
  the milestone launch (`service.py:1759`), after its three checks
  (`service.py:1745`–`:1753`).

So the first milestone is a de facto precondition of the first brainstorming.
That ordering was never designed; it is a side effect of where the reconcile
was pinned. The frozen goal contract assigns the executor's reconcile role to
"the launcher's validation" (`project-concept.md:126`–`:129`, adopted at
`canon-project-concept-isolated/slices/slice-07.md:9`–`:12`, §C at `:211`–`:245`),
because locally there is no separate executor process and the launch path was
the only site that already ran on the host with an effective config resolved.

Three defects follow.

**1. A descriptor claim is being read as a permission.** In agent_99's domain
`status` records what an executor found on its own filesystem — hence
`executor_id` on the record and the version bump when a different executor
confirms. `resolve()` turns that record into a gate. A stored flag then stands
in for a filesystem truth that can go stale between the confirm and the use.

**2. The flag buys nothing where it is written.** The milestone launch
re-runs all three checks on every launch before confirming, so `status` is
written but never consulted on that path. Its only live effect is to block
other consumers — today, brainstorming.

**3. Two unrelated requirements share one gate.** "The roots exist on this
machine" is kind-independent. "The primary is a git repository ROOT"
(`service.py:1747`) is a milestone requirement — the gate ledger must land in
a repo the operator created on purpose. Because the git check guards the same
confirm, brainstorming inherits a git requirement it never uses: the
brainstorming modules contain zero `gitops` references.

The refusal also loses the cause. `work_area_not_ready` does not say whether
the primary directory is missing, is not a repo root, or an additional root
vanished — the three specific tokens already exist
(`driver.MISSING_PRIMARY_PATH`, `service.PRIMARY_NOT_REPO_ROOT`,
`service.MISSING_ADDITIONAL_ROOT`) and are discarded at exactly the moment the
operator needs them.

## Obligation (what this milestone delivers)

### 1. Every launch verifies what it needs, when it needs it

No launch consults a stored status to decide whether it may proceed.
A milestone launch verifies that the roots exist AND that the primary is a git
repository root when git is enabled in its effective config. A brainstorming
create verifies that the roots exist. Each verification runs at the moment of
use, against the STORED descriptor's roots — never roots taken from the
request — exactly as the milestone launch validates today.

The check is three `isdir` calls and one repo-root probe. Its cost is not a
reason to cache it.

### 2. `status` becomes a result, never a gate

No product path consults the stored status to decide whether it may proceed.
Every caller that reached the work area through the ready-gated `resolve()`
now reads the live record and verifies what it actually needs: the launch
seam, the panel's work-area file picker, and git sync. The sealed store keeps
`resolve()` unchanged — it is part of Slice 2's mirror of agent_99's read
surface, sealed as such — it simply stops being how this product admits work.

Each launch writes what it observed: `ready` when the roots exist,
`unavailable` when they do not — the vocabulary already reserves both
(`workareas.py:40`–`:43`), and this gives `unavailable` its first writer.
The absence is recorded against the roots that were actually checked, so a
descriptor repointed between the check and the write refuses instead of
condemning roots this host never looked at.

Writing that record is provenance, and provenance that fails is lost
provenance, not a veto: a record that cannot be written never turns a
passing verification into a refusal, and never displaces the cause of a
failing one. A launch stands or falls on the filesystem.

agent_99's stored domain is untouched: the field, its three values, the
`executor_id`, the `pending` → `ready` version bump, and the version-silent
re-confirm all keep their current semantics. What is removed is the field's
authority over callers, not the field.

### 3. `status` describes only kind-independent truth

Root existence decides the status. The git-repo-root requirement belongs to
the milestone launch alone: it refuses with `primary_not_repo_root` and does
NOT write status.

This is load-bearing, not tidiness. If the git check could set the status, a
brainstorming succeeding in a non-repo directory would mark the area not
ready and the next milestone would mark it ready again — one field taking
dictation from whichever launch spoke last.

### 4. Refusals name the cause

Each verification refuses with its own specific token, surfaced verbatim to
the panel as sealed refusals are today. `work_area_not_ready` retires as a
launch-time refusal: no caller can be blocked by a stored state, so no caller
can be told a stored state is why.

### 5. The declare role stays path-blind

Declaring a work area continues to validate nothing against the filesystem and
continues to write `pending`. The Body may issue it from a machine that has
never seen those paths; collapsing declare and reconcile would destroy the
role separation the fusion target depends on. The panel must not present
`status` as a precondition for launching, nor require an activation step
before the first brainstorming.

### 6. Tests pin the reversal

At minimum: a brainstorming create succeeding into a freshly declared
(`pending`) work area; the same create succeeding when the primary is not a
git repository; a milestone launch into that same area refusing with
`primary_not_repo_root` while the record's status is left unchanged; a missing
primary path producing `missing_primary_path` and an `unavailable` status; a
missing additional root producing `missing_additional_root`; and the agent_99
version semantics (first confirm bumps, re-confirm with the stable identity is
silent) unchanged.

## Non-goals

- Removing `status`, `executor_id`, the three-value vocabulary, or the version
  semantics. agent_99's stored work-area domain is adopted verbatim and stays
  that way.
- Changing what a milestone requires. The repo-root rule is unchanged in
  content and unchanged in strictness; only its authority is relocated out of
  the shared gate.
- Adding an "activate work area" endpoint or any operator step between
  declaring an area and using it.
- Giving the declare route filesystem access.
- Defining a new permission, sandbox, or work-area system.

## Constraint

Canon changes run the canon's own full milestone cycle — uniform depth, no
fast paths.
