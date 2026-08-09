"""Dispatch the fixer consultation from current model-profile state."""

from __future__ import annotations

import argparse
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from orchestrator import driver, interpreter, runners, state


def consultation_command(state_path, home, caller_act, caller_origin=None):
    run_state = state.load(state_path)
    config = interpreter.effective_config(run_state)
    strict, overlay, configuration = driver._read_current_profile_layers(
        state_path, home
    )
    caller_default = "codex"
    if caller_act == "skeletoner":
        caller_default = driver.DEFAULT_CONFIG["acts"]["skeletoner"][
            "agent"
        ]
    caller_family, _caller_model, caller_effort = (
        driver._resolve_act_from_layers(
            config,
            strict,
            overlay,
            configuration,
            caller_act,
            origin_family=caller_origin,
            default_family=caller_default,
        )
    )
    consultation_family, _model, _effort = driver._resolve_act_from_layers(
        config,
        strict,
        overlay,
        configuration,
        "consultation",
        origin_family=caller_family,
    )
    caller_defaults = (config.get("model_defaults") or {}).get(
        caller_family
    ) or {}
    if caller_act == "skeletoner" and not caller_effort:
        caller_effort = driver.DEFAULT_CONFIG["acts"]["skeletoner"].get(
            "effort"
        )
    consulted_defaults = (config.get("model_defaults") or {}).get(
        consultation_family
    ) or {}
    template = (config.get("commands") or {}).get(consultation_family) or []
    if not template:
        raise RuntimeError(
            "no command configured for consultation family %s"
            % consultation_family
        )
    return runners.apply_model_effort(
        template,
        consulted_defaults.get("model"),
        caller_effort or caller_defaults.get("effort"),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument(
        "--caller-act", choices=("fixer", "skeletoner"), required=True
    )
    parser.add_argument("--caller-origin")
    args = parser.parse_args(argv)
    command = consultation_command(
        os.path.abspath(args.state),
        os.path.abspath(args.home),
        args.caller_act,
        args.caller_origin,
    )
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
