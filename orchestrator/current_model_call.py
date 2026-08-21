"""Dispatch the fixer consultation from the run's current staffing."""

from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from orchestrator import interpreter, runners, staffing, state


def consultation_command(state_path, home):
    """The command line the fixer runs to consult, resolved right now.

    The `consult` seat of the run's own staffing session decides who
    answers, on which model, at which effort — read at the moment the fixer
    runs this, so a session or document edit reaches the consultation like
    every other call. Nothing is derived from the caller: no consulted
    family off the fixer's, no caller's effort carried across.

    This runs in the FIXER's subprocess and writes no run state — a child
    must not write the record its parent driver holds in memory. A surfaced
    condition here still reaches ordinary run recovery, by the channel the
    fixer's own prompt mandates: the fixer returns the closed
    `retry_reason: consultation_unavailable` envelope, and
    `Driver._check_worker_blocked` fails the run on it, carrying the fixer's
    notes into the reason. The driver also resolves `consult` in-process
    when it ORDERS the fix, so a condition already present then stops the
    run there with its own token.
    """
    run_state = state.load(state_path)
    config = interpreter.effective_config(run_state)
    answer = staffing.resolve(
        home,
        state.staffing_session(run_state),
        "consult",
        families=list(config.get("families_order") or []),
    ).answer
    template = (config.get("commands") or {}).get(answer["agent"]) or []
    if not template:
        raise RuntimeError(
            "no command configured for consultation family %s"
            % answer["agent"]
        )
    return runners.apply_model_effort(
        template, answer["model"], answer["effort"]
    )


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state", required=True)
    parser.add_argument("--home", required=True)
    # Retired by the cutover, still ACCEPTED and read by nothing. A fixer
    # admitted before it carries an immutable stored prompt whose command
    # line passes the caller derivation this slice retired; refusing the
    # flags would make that prompt's MANDATORY consultation unrunnable and
    # stall the run on the retry envelope it then has to return. The
    # `consult` seat decides, whatever these say.
    parser.add_argument("--caller-act")
    parser.add_argument("--caller-origin")
    args = parser.parse_args(argv)
    command = consultation_command(
        os.path.abspath(args.state), os.path.abspath(args.home)
    )
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
