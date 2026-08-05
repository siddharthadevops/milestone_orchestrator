"""Operator-ordered git alignment of a work area, performed by an agent.

The operation is deliberately NOT deterministic. Aligning a checkout with
its remote is mostly mechanical, but its interesting cases — divergence,
conflicting edits, a dirty worktree — need judgement, and coding every one
of them for an occasional manual action buys little. So the panel hands the
work area to the project's lead family with a stated mandate and reports
what it says it did.

What IS deterministic is the refusal: a work area whose milestone driver is
alive is never handed over. A driver owns its worktree — wip commits,
amends, gate commits, and a sealed-artifact guard that restores files — and
an agent merging underneath it would fight all three.

Nothing here can lose committed work: the mandate is to merge, never to
force or rewrite, so both sides stay reachable and a badly resolved merge
is undone by resetting to the commit before it.
"""

from __future__ import annotations

import os

from orchestrator import runners


MANDATE = """\
You are aligning one git working directory with its remote, on the
operator's explicit order, from a control panel.

Working directory: {workspace}

GOAL
Leave the local branch and its remote counterpart aligned, with BOTH
sides' work preserved. Merging is how you reconcile them.

RULES
- NEVER lose committed work. No force push, no history rewriting, no
  `reset --hard` onto a discarded state, no branch deletion.
- Uncommitted local changes are work too. Commit them on the current
  branch before merging, with an honest message saying they were
  committed by this sync.
- Resolve merge conflicts on the merits, keeping the intent of both
  sides. When a conflict is in a document you cannot judge safely, STOP
  and report it instead of guessing.
- STOP and report if a conflict falls in a SEALED milestone document
  (an artifact under a milestone's implementation directory that its
  review process has already sealed). Those must not drift silently.
- If the remote is unreachable, or authentication fails, STOP and say so.
- Do not touch anything outside the working directory, and do not start
  or stop any orchestrator run.

REPORT
Answer in plain prose, for a person reading it on a phone. Say what the
two sides looked like, what you did, and what — if anything — the
operator still has to decide. If you stopped without aligning, lead with
why. Be specific about files you resolved and how.

Then end your answer with a LAST LINE that is exactly one of:
  RESULT: aligned
  RESULT: stopped
`aligned` only if local and remote now hold the same work. Anything else
— you refused, you could not reach the remote, you left a conflict for
the operator — is `stopped`. Nothing may follow that line.
"""


def build_prompt(workspace):
    return MANDATE.format(workspace=os.path.abspath(workspace))


def paths_overlap(first, second):
    """Whether two paths name the same tree or one contains the other.

    Containment both ways, not equality: a merge in a directory disturbs
    everything beneath it, and a worker owning an ANCESTOR of the area is
    just as much an owner as one sitting exactly on it. Work areas may be
    declared at any depth, so nesting is reachable by configuration alone.

    Comparison is realpath-based, and case-folded only where the volume
    itself ignores case: realpath preserves the casing the caller supplied,
    so on a case-insensitive volume `/Users/x/Repo` and `/users/x/repo` are
    ONE directory a case-sensitive test would call two — while folding
    unconditionally would conflate genuinely distinct siblings on a
    case-sensitive one and block work that never overlapped.
    """
    if not first or not second:
        return False
    left = os.path.realpath(first)
    right = os.path.realpath(second)
    try:
        if os.path.samefile(left, right):
            return True
    except OSError:
        pass  # one of them does not exist yet; fall through to the paths
    if _ignores_case(left) or _ignores_case(right):
        left, right = left.lower(), right.lower()
    return left == right or _contains(right, left) or _contains(left, right)


def _contains(parent, child):
    """Whether `child` sits under `parent`, root included.

    Root needs its own arm: "/" already ends in the separator, so the
    ordinary parent + os.sep test builds "//" and matches nothing.
    """
    if parent == os.sep:
        return child.startswith(os.sep) and child != os.sep
    return child.startswith(parent.rstrip(os.sep) + os.sep)


def _ignores_case(path):
    """Whether the volume holding `path` treats case as insignificant.

    Probed by lookup, never by writing: walk up to something that exists
    and ask whether its own name resolves under a swapped case.
    """
    existing = os.path.realpath(path)
    while not os.path.lexists(existing):
        parent = os.path.dirname(existing)
        if parent == existing:
            return False
        existing = parent
    name = os.path.basename(existing)
    alias = name.swapcase()
    if alias == name:
        # Nothing to swap here (digits, separators); ask the parent.
        parent = os.path.dirname(existing)
        if parent == existing:
            return False
        name = os.path.basename(parent)
        alias = name.swapcase()
        if alias == name:
            return False
        existing, parent = parent, os.path.dirname(parent)
    else:
        parent = os.path.dirname(existing)
    try:
        return os.path.lexists(os.path.join(parent, alias))
    except OSError:
        return False


def read_outcome(report, exit_code):
    """"aligned", "stopped", or "unknown" for one agent report.

    A process exit code cannot answer this: an agent that obeys the
    mandate and stops — no remote, an unresolvable conflict — finishes
    normally and exits 0, so exit status alone reported every refusal as a
    success. The mandate therefore asks for a verdict line, and an answer
    that does not carry one is "unknown" rather than assumed good.
    """
    if exit_code not in (0, None):
        return "stopped"
    for raw in reversed((report or "").strip().splitlines()):
        if not raw.strip():
            continue  # trailing blank lines are not content
        line = raw.strip().strip("*_`> ").strip()
        if not line:
            # A line made only of markup (a closing fence, a rule): the
            # agent put something after its verdict, so the contract was
            # not followed and the answer is not trusted.
            return "unknown"
        if line.upper().startswith("RESULT:"):
            verdict = line.split(":", 1)[1].strip().lower()
            return verdict if verdict in ("aligned", "stopped") else "unknown"
        break
    return "unknown"


def active_run_blocking(runs, workspace):
    """The first live run whose workspace overlaps this one, or None."""
    for entry in runs:
        if not entry.get("alive"):
            continue
        if paths_overlap(entry.get("workspace"), workspace):
            return entry
    return None


def run_sync(commands, timeouts, family, workspace, model=None, effort=None,
             runner=None, stall_window_s=None, stall_min_cpu_s=None):
    """Hand the work area to `family` and return its prose report.

    Raises runners.RunnerError if the agent could not be run at all. The
    liveness watchdog is wired so a frozen CLI is killed instead of holding
    a request forever; without it this call had no upper bound at all.

    `exit_code` rides along because a textual answer is not evidence of
    success: the agent may have stopped and explained why, and the caller
    must be able to tell that from an alignment. Whether the worktree was
    left mid-merge only the report can say, so it is surfaced verbatim.
    """
    runner = runner or runners.SubprocessRunner(
        commands,
        timeouts or {},
        stall_window_s=stall_window_s,
        stall_min_cpu_s=stall_min_cpu_s,
    )
    result = runner.call(
        family,
        build_prompt(workspace),
        os.path.abspath(workspace),
        model=model,
        effort=effort,
    )
    code = getattr(result, "exit_code", None)
    report = (getattr(result, "text", "") or "").strip()
    return {
        "family": family,
        "model": model,
        "effort": effort,
        "report": report,
        "exit_code": code,
        "clean_exit": code == 0,
        "outcome": read_outcome(report, code),
        "duration_s": getattr(result, "duration_s", None),
        "token_usage": getattr(result, "token_usage", None),
    }
