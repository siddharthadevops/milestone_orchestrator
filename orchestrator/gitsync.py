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
"""


def build_prompt(workspace):
    return MANDATE.format(workspace=os.path.abspath(workspace))


def active_run_blocking(runs, workspace):
    """The first live run whose workspace is this one, or None.

    Compared by realpath: the registry stores what the launch supplied,
    which may reach the same directory by another name.
    """
    target = os.path.realpath(workspace)
    for entry in runs:
        if os.path.realpath(entry.get("workspace") or "") != target:
            continue
        if entry.get("alive"):
            return entry
    return None


def run_sync(commands, timeouts, family, workspace, model=None, effort=None,
             runner=None):
    """Hand the work area to `family` and return its prose report.

    Raises runners.RunnerError if the agent could not be run at all; a
    refusal or a partial alignment comes back as ordinary prose, because
    only the agent knows which of those happened.
    """
    runner = runner or runners.SubprocessRunner(commands, timeouts or {})
    result = runner.call(
        family,
        build_prompt(workspace),
        os.path.abspath(workspace),
        model=model,
        effort=effort,
    )
    return {
        "family": family,
        "model": model,
        "effort": effort,
        "report": (getattr(result, "text", "") or "").strip(),
        "duration_s": getattr(result, "duration_s", None),
        "token_usage": getattr(result, "token_usage", None),
    }
