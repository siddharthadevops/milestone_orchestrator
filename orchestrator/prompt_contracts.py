"""Reply contracts selected by assembled prompt section ids.

This boundary is deliberately not wired to worker dispatch yet.  It binds the
already assembled prompt, admits only registered consumer additions, and later
validates the reply against the registered sections that were actually served.
Stored unknown sections remain visible to the worker but create no validator.
"""

import copy
import os
from collections import namedtuple

from . import contracts, prompt_sets


BoundContract = namedtuple(
    "BoundContract", ("prompt", "registered_section_ids", "question_ids")
)

_AUTHOR_STATUSES = {
    "draft_skeleton": ("ok", "blocked"),
    "draft_slice_note": ("ok", "blocked", "need_rethink"),
    "implement": ("ok", "blocked", "need_rethink"),
}
_REVIEW_KINDS = ("review_round", "delta_review")
_FIX_STATUSES = ("ok", "blocked", "need_rethink")
NEED_RETHINK_SECTION_ID = "need_rethink"
RETIRED_RETHINK_SECTION_IDS = frozenset((
    "need_rethink_author",
    "review_need_rethink",
    "fix_need_rethink",
))
_NEED_RETHINK_KINDS = frozenset((
    "draft_slice_note",
    "implement",
    "review_round",
    "delta_review",
    "fix_findings",
))


def _require(obj, key, types, ctx):
    return contracts._require(obj, key, types, ctx)


def _text(obj, key, ctx):
    value = _require(obj, key, str, ctx)
    if not value.strip():
        raise contracts.ContractError(
            "%s: key %r must be non-empty" % (ctx, key)
        )
    return value


def _kind(bound, expected=None):
    kind = bound.prompt["kind"]
    if expected is not None and kind not in expected:
        raise contracts.ContractError(
            "prompt kind %r cannot use this contract section" % kind
        )
    return kind


def _status(obj, bound, allowed, ctx, expected_kinds=None):
    kind = _kind(bound, expected_kinds)
    status = _require(obj, "status", str, ctx)
    if status not in allowed:
        raise contracts.ContractError(
            "%s: status %r not in %r" % (ctx, status, allowed)
        )
    if (
        status != "need_rethink"
        or NEED_RETHINK_SECTION_ID not in bound.registered_section_ids
    ) and _require(obj, "kind", str, ctx) != kind:
        raise contracts.ContractError("%s: kind does not match prompt" % ctx)
    return status


def _paths(values, ctx):
    if not isinstance(values, list):
        raise contracts.ContractError("%s must be a list" % ctx)
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise contracts.ContractError(
                "%s[%d] must be a non-empty string" % (ctx, index)
            )
    return values


def _relative_path(value, ctx):
    if not isinstance(value, str) or not value.strip():
        raise contracts.ContractError("%s must be a non-empty path" % ctx)
    if (
        os.path.isabs(value)
        or "\x00" in value
        or os.path.normpath(value) != value
        or value in (".", "..")
        or value.startswith(".." + os.sep)
    ):
        raise contracts.ContractError(
            "%s must be normalized and workspace-relative" % ctx
        )
    return value


def _relative_paths(values, ctx):
    if not isinstance(values, list):
        raise contracts.ContractError("%s must be a list" % ctx)
    for index, value in enumerate(values):
        _relative_path(value, "%s[%d]" % (ctx, index))
    return values


def _exact_keys(value, expected, ctx):
    if set(value) != set(expected):
        raise contracts.ContractError(
            "%s must contain exactly %s" % (ctx, sorted(expected))
        )


def _envelope(obj, bound, options, ctx):
    del bound, options
    if not isinstance(obj, dict):
        raise contracts.ContractError("%s: reply must be an object" % ctx)


def _common(obj, bound, options, ctx):
    del options
    kind = _kind(bound, tuple(_AUTHOR_STATUSES))
    status = _status(obj, bound, _AUTHOR_STATUSES[kind], ctx)
    if status == "blocked":
        _text(obj, "blocked_reason", ctx)
    if "notes" in obj and obj["notes"] is not None:
        _require(obj, "notes", str, ctx)


def _author_result(expected_kind, field):
    def validate(obj, bound, options, ctx):
        status = _status(
            obj, bound, _AUTHOR_STATUSES[expected_kind], ctx,
            (expected_kind,),
        )
        if status == "ok":
            value = _relative_path(
                _require(obj, field, str, ctx), "%s.%s" % (ctx, field)
            )
            expected = options.get("expected_artifact")
            if expected_kind == "draft_skeleton" and expected is not None:
                if value != expected:
                    raise contracts.ContractError(
                        "%s.%s must exactly equal the supplied skeleton path %r"
                        % (ctx, field, expected)
                    )

    return validate


def _implement_result(obj, bound, options, ctx):
    del options
    status = _status(
        obj, bound, _AUTHOR_STATUSES["implement"], ctx, ("implement",)
    )
    if status != "ok":
        return
    _relative_paths(
        _require(obj, "files_changed", list, ctx), "%s.files_changed" % ctx
    )
    cut = obj.get("implementation_cut")
    if cut is not None:
        contracts.validate_implementation_cut(
            cut, "%s.implementation_cut" % ctx
        )


def _report_finding(finding, ctx, require_plain=False):
    contracts.validate_report_finding(
        finding, ctx, require_plain=require_plain
    )
    _text(finding, "id", ctx)
    _text(finding, "summary", ctx)
    contests = finding.get("contests")
    if isinstance(contests, dict) and "new_evidence" in contests:
        _text(contests, "new_evidence", "%s.contests" % ctx)
    return finding


def _fix_finding(finding, ctx):
    contracts.validate_fix_finding(finding, ctx)
    _text(finding, "id", ctx)
    _text(finding, "summary", ctx)
    prevention = finding.get("prevention")
    if prevention is not None:
        _relative_path(
            prevention["documented_in"], "%s.prevention.documented_in" % ctx
        )
        _text(prevention, "note", "%s.prevention" % ctx)
    return finding


def _problem_rethink(obj, bound, options, ctx):
    del options
    _kind(bound, _NEED_RETHINK_KINDS)
    status = _require(obj, "status", str, ctx)
    if status != "need_rethink":
        return
    _text(obj, "problem", ctx)
    forbidden = {
        "kind", "finding", "target_path", "request", "result_mode",
        "max_rounds", "artifact", "files_changed", "findings",
        "implementation_cut", "failure_gap", "design_correction",
        "design_correction_verdict", "brainstorming_application",
    }
    claimed = sorted(forbidden & set(obj))
    if claimed:
        raise contracts.ContractError(
            "%s: need_rethink must not carry %s" % (ctx, claimed)
        )


def _review_result(obj, bound, options, ctx):
    del options
    status = _status(
        obj, bound, ("ok", "blocked", "need_rethink"), ctx, _REVIEW_KINDS
    )
    if status != "ok":
        return
    findings = _require(obj, "findings", list, ctx)
    for index, finding in enumerate(findings):
        _report_finding(
            finding, "%s.findings[%d]" % (ctx, index), require_plain=True
        )
    contracts._assert_unique_finding_ids(findings, ctx)
    if "notes" in obj:
        _require(obj, "notes", str, ctx)


def _review_blocked(obj, bound, options, ctx):
    del options
    status = _status(
        obj, bound, ("ok", "blocked", "need_rethink"), ctx, _REVIEW_KINDS
    )
    if status == "blocked":
        _text(obj, "blocked_reason", ctx)


def _design_correction_verdict(obj, bound, options, ctx):
    del options
    status = _status(
        obj, bound, ("ok", "blocked", "need_rethink"), ctx,
        ("delta_review",),
    )
    if status == "ok":
        contracts.validate_design_correction_verdict(
            _require(obj, "design_correction_verdict", dict, ctx),
            _require(obj, "findings", list, ctx),
            ctx,
        )


def _fix_result(obj, bound, options, ctx):
    status = _status(obj, bound, _FIX_STATUSES, ctx, ("fix_findings",))
    if status != "ok":
        return
    findings = _require(obj, "findings", list, ctx)
    for index, finding in enumerate(findings):
        _fix_finding(finding, "%s.findings[%d]" % (ctx, index))
    contracts._assert_unique_finding_ids(findings, ctx)
    files_changed = _relative_paths(
        _require(obj, "files_changed", list, ctx), "%s.files_changed" % ctx
    )
    for index, finding in enumerate(findings):
        prevention = finding.get("prevention")
        if (
            prevention is not None
            and prevention["documented_in"] not in files_changed
        ):
            raise contracts.ContractError(
                "%s.findings[%d].prevention.documented_in must name a path "
                "in files_changed" % (ctx, index)
            )
    if "notes" in obj:
        _require(obj, "notes", str, ctx)
    if options["queued_findings"] is not None:
        contracts.validate_fix_coverage(obj, options["queued_findings"])
        queued_severity = {
            finding["id"]: finding["severity"]
            for finding in options["queued_findings"]
        }
        for index, finding in enumerate(findings):
            if finding["severity"] != queued_severity[finding["id"]]:
                raise contracts.ContractError(
                    "%s.findings[%d]: severity must echo queued severity %r"
                    % (ctx, index, queued_severity[finding["id"]])
                )


def _fix_blocked(obj, bound, options, ctx):
    del options
    status = _status(obj, bound, _FIX_STATUSES, ctx, ("fix_findings",))
    if status == "blocked":
        _text(obj, "blocked_reason", ctx)


def _questions(obj, bound, options, ctx):
    del options
    expected = bound.question_ids
    if not expected and "questions" not in obj:
        return
    answers = _require(obj, "questions", list, ctx)
    seen = set()
    for index, answer in enumerate(answers):
        actx = "%s.questions[%d]" % (ctx, index)
        if not isinstance(answer, dict):
            raise contracts.ContractError("%s must be an object" % actx)
        _exact_keys(answer, ("id", "answer"), actx)
        question_id = _require(answer, "id", str, actx)
        if question_id not in expected:
            raise contracts.ContractError(
                "%s: unknown question id %r" % (actx, question_id)
            )
        if question_id in seen:
            raise contracts.ContractError(
                "%s: duplicate question id %r" % (actx, question_id)
            )
        seen.add(question_id)
        _text(answer, "answer", actx)
    missing = [question_id for question_id in expected if question_id not in seen]
    if missing:
        raise contracts.ContractError(
            "%s: missing question answers %s" % (ctx, missing)
        )


def _reclassify(obj, bound, options, ctx):
    del options
    _status(obj, bound, ("ok",), ctx, ("reclassify",))
    for field in ("drift_risk", "drift_damage"):
        if _require(obj, field, str, ctx) not in contracts.DRIFT_RISK_LEVELS:
            raise contracts.ContractError(
                "%s: %s must be one of %r"
                % (ctx, field, contracts.DRIFT_RISK_LEVELS)
            )
    _text(obj, "reason", ctx)


def _turn(expected_kind, allow_ready):
    def validate(obj, bound, options, ctx):
        del options
        _kind(bound, (expected_kind,))
        if _require(obj, "kind", str, ctx) != expected_kind:
            raise contracts.ContractError("%s: kind does not match prompt" % ctx)
        _text(obj, "markdown", ctx)
        if "ready" in obj:
            if not allow_ready:
                raise contracts.ContractError(
                    "%s: questioner_turn cannot become ready" % ctx
                )
            _require(obj, "ready", bool, ctx)

    return validate


def _questioner_readiness(obj, bound, options, ctx):
    """Require the binding common-sense judgment appended by the session."""
    del options
    _kind(bound, ("questioner_turn",))
    _require(obj, "ready", bool, ctx)


def _commands(value, ctx):
    return _paths(value, ctx)


def _results(value, commands, ctx):
    if not isinstance(value, list) or len(value) > len(commands):
        raise contracts.ContractError("%s must be a command prefix" % ctx)
    checked = []
    for index, result in enumerate(value):
        rctx = "%s[%d]" % (ctx, index)
        if not isinstance(result, dict):
            raise contracts.ContractError("%s must be an object" % rctx)
        _exact_keys(result, ("command", "exit_code", "evidence"), rctx)
        if _require(result, "command", str, rctx) != commands[index]:
            raise contracts.ContractError("%s: command is not plan prefix" % rctx)
        code = _require(result, "exit_code", int, rctx)
        if isinstance(code, bool):
            raise contracts.ContractError("%s: exit_code must be an integer" % rctx)
        _text(result, "evidence", rctx)
        checked.append(code)
    if any(checked[:-1]):
        raise contracts.ContractError(
            "%s must stop at the first non-zero exit" % ctx
        )
    return checked


def _authority(obj, configured, workspace, ctx):
    value = _require(obj, "authority", dict, ctx)
    _exact_keys(value, ("source", "evidence"), "%s.authority" % ctx)
    source = _require(value, "source", str, "%s.authority" % ctx)
    evidence = _require(value, "evidence", list, "%s.authority" % ctx)
    if configured is not None:
        if source != "operator_config" or evidence:
            raise contracts.ContractError(
                "%s: configured suite requires operator_config and no evidence"
                % ctx
            )
        return
    if source != "repository" or not evidence:
        raise contracts.ContractError(
            "%s: discovered suite requires repository evidence" % ctx
        )
    if workspace is None:
        raise contracts.ContractError(
            "%s: workspace is required to verify repository evidence" % ctx
        )
    root = os.path.abspath(os.fspath(workspace))
    for index, item in enumerate(evidence):
        ectx = "%s.authority.evidence[%d]" % (ctx, index)
        if not isinstance(item, dict):
            raise contracts.ContractError("%s must be an object" % ectx)
        _exact_keys(item, ("path", "basis"), ectx)
        path = _text(item, "path", ectx)
        _text(item, "basis", ectx)
        if (
            os.path.isabs(path)
            or os.path.normpath(path) != path
            or path in (".", "..")
            or path.startswith(".." + os.sep)
            or not os.path.exists(os.path.join(root, path))
        ):
            raise contracts.ContractError(
                "%s: path must be existing, normalized, and workspace-relative"
                % ectx
            )


def _suite_checkpoint(obj, bound, options, ctx):
    _kind(bound, ("suite_checkpoint",))
    status = _require(obj, "status", str, ctx)
    if status not in ("passed", "failed", "no_suite", "blocked"):
        raise contracts.ContractError("%s: invalid checkpoint status" % ctx)
    if _require(obj, "kind", str, ctx) != "suite_checkpoint":
        raise contracts.ContractError("%s: kind does not match prompt" % ctx)
    commands = _commands(_require(obj, "commands", list, ctx), "%s.commands" % ctx)
    configured = options["configured_suite_commands"]
    if configured is not None:
        configured = _commands(
            configured, "%s.configured_suite_commands" % ctx
        )
        if commands != configured:
            raise contracts.ContractError(
                "%s: commands do not equal operator configuration" % ctx
            )
        if status == "no_suite":
            raise contracts.ContractError(
                "%s: configured suite cannot report no_suite" % ctx
            )
    codes = _results(
        _require(obj, "results", list, ctx), commands, "%s.results" % ctx
    )
    if status == "blocked":
        _text(obj, "blocked_reason", ctx)
        if any(codes) or (commands and len(codes) == len(commands)):
            raise contracts.ContractError(
                "%s: blocked requires a successful proper prefix or no results"
                % ctx
            )
        return
    _authority(obj, configured, options["workspace"], ctx)
    if status == "no_suite":
        if commands or codes:
            raise contracts.ContractError(
                "%s: no_suite requires empty commands and results" % ctx
            )
    elif status == "passed":
        if not commands or len(codes) != len(commands) or any(codes):
            raise contracts.ContractError(
                "%s: passed requires one zero result per command" % ctx
            )
    else:
        if not commands or not codes or any(codes[:-1]) or codes[-1] == 0:
            raise contracts.ContractError(
                "%s: failed requires a zero prefix and final non-zero result"
                % ctx
            )
        failure = _require(obj, "failure_account", dict, ctx)
        _exact_keys(
            failure,
            ("command", "exit_code", "diagnostics", "affected_tests"),
            "%s.failure_account" % ctx,
        )
        failure_code = _require(failure, "exit_code", int, ctx)
        if isinstance(failure_code, bool):
            raise contracts.ContractError(
                "%s.failure_account.exit_code must be an integer" % ctx
            )
        if (
            _require(failure, "command", str, ctx) != commands[len(codes) - 1]
            or failure_code != codes[-1]
        ):
            raise contracts.ContractError(
                "%s: failure_account does not match final result" % ctx
            )
        _text(failure, "diagnostics", ctx)
        _paths(
            _require(failure, "affected_tests", list, ctx),
            "%s.failure_account.affected_tests" % ctx,
        )
    if status != "failed" and "failure_account" in obj:
        raise contracts.ContractError(
            "%s: failure_account is failed-only" % ctx
        )


def _merge_repair(obj, bound, options, ctx):
    del options
    status = _status(
        obj, bound, ("ok", "blocked"), ctx, ("merge_repair",)
    )
    _relative_paths(
        _require(obj, "files_changed", list, ctx), "%s.files_changed" % ctx
    )
    if status == "blocked":
        _text(obj, "blocked_reason", ctx)
    if "notes" in obj:
        _require(obj, "notes", str, ctx)


REGISTERED_SECTIONS = {
    "common_fields": _common,
    "draft_skeleton_result": _author_result("draft_skeleton", "artifact"),
    "draft_slice_note_result": _author_result("draft_slice_note", "artifact"),
    "envelope_compact": _envelope,
    "envelope_verbose": _envelope,
    "implement_result": _implement_result,
    NEED_RETHINK_SECTION_ID: _problem_rethink,
    "questions_output": _questions,
    "review_blocked": _review_blocked,
    "review_contract": _review_result,
    "design_correction_verdict": _design_correction_verdict,
    "discussion_turn_envelope": _turn("discussion_turn", True),
    "fix_blocked": _fix_blocked,
    "fix_results": _fix_result,
    "merge_repair_result": _merge_repair,
    "questioner_turn_envelope": _turn("questioner_turn", True),
    "questioner_readiness": _questioner_readiness,
    "reclassify_result": _reclassify,
    "suite_checkpoint_result": _suite_checkpoint,
}

_PROTOCOL_FIELDS = frozenset({
    "status", "kind", "blocked_reason", "notes", "problem", "artifact",
    "files_changed", "implementation_cut", "finding", "target_path",
    "findings", "retry_reason", "questions", "markdown", "ready",
    "tests_modified", "tests_changed",
    "drift_risk", "drift_damage", "reason", "commands", "authority",
    "results", "failure_account", "suite_command",
    "suite_command_finding_id", "slices", "battery", "gaps", "request",
    "result_mode", "max_rounds", "failure_gap", "design_update",
    "design_correction", "brainstorming_application",
    "design_correction_verdict",
    "plan_authoring_authorized", "producer_planning", "vote", "revision",
    "session_id", "accepted_target_revision", "ready_revision",
})
_FIELD_CONTRACT_SECTIONS = frozenset(REGISTERED_SECTIONS) - {
    "envelope_compact", "envelope_verbose", "questions_output",
}
_STRICT_FIELD_SECTIONS = frozenset({
    "reclassify_result", "suite_checkpoint_result", "merge_repair_result",
    "discussion_turn_envelope", "questioner_turn_envelope",
})


def _allowed_fields(bound, obj):
    status = obj.get("status")
    if (
        status == "need_rethink"
        and NEED_RETHINK_SECTION_ID in bound.registered_section_ids
    ):
        allowed = {"status", "problem"}
        if (
            bound.question_ids
            or "questions_output" in bound.registered_section_ids
        ):
            allowed.add("questions")
        return allowed
    allowed = set()
    for section_id in bound.registered_section_ids:
        if section_id == "common_fields":
            allowed.update(("status", "kind", "notes"))
            if status == "blocked":
                allowed.add("blocked_reason")
        elif section_id in ("draft_skeleton_result", "draft_slice_note_result"):
            allowed.update(("status", "kind"))
            if status == "ok":
                allowed.add("artifact")
        elif section_id == "implement_result":
            allowed.update(("status", "kind"))
            if status == "ok":
                allowed.update(("files_changed", "implementation_cut"))
        elif section_id == "review_contract":
            allowed.update(("status", "kind"))
            if status == "ok":
                allowed.update(("findings", "notes"))
        elif section_id == "review_blocked":
            allowed.update(("status", "kind"))
            if status == "blocked":
                allowed.add("blocked_reason")
        elif section_id == "design_correction_verdict":
            allowed.update(("status", "kind"))
            if status == "ok":
                allowed.add("design_correction_verdict")
        elif section_id == "fix_results":
            allowed.update(("status", "kind"))
            if status == "ok":
                allowed.update(("findings", "files_changed", "notes"))
        elif section_id == "fix_blocked":
            allowed.update(("status", "kind"))
            if status == "blocked":
                allowed.add("blocked_reason")
        elif section_id == "discussion_turn_envelope":
            allowed.update(("kind", "markdown", "ready"))
        elif section_id == "questioner_turn_envelope":
            allowed.update(("kind", "markdown", "ready"))
        elif section_id == "questioner_readiness":
            allowed.add("ready")
        elif section_id == "reclassify_result":
            allowed.update((
                "status", "kind", "drift_risk", "drift_damage", "reason",
            ))
        elif section_id == "suite_checkpoint_result":
            allowed.update(("status", "kind", "commands", "results"))
            if status in ("passed", "failed", "no_suite"):
                allowed.add("authority")
            if status == "failed":
                allowed.add("failure_account")
            if status == "blocked":
                allowed.add("blocked_reason")
        elif section_id == "merge_repair_result":
            allowed.update(("status", "kind", "files_changed", "notes"))
            if status == "blocked":
                allowed.add("blocked_reason")
    if (
        bound.question_ids
        or "questions_output" in bound.registered_section_ids
    ):
        allowed.add("questions")
    return allowed


def _validate_fields(bound, obj, extension_fields=()):
    mounted = set(bound.registered_section_ids)
    if not mounted.intersection(_FIELD_CONTRACT_SECTIONS):
        return
    allowed = _allowed_fields(bound, obj)
    if mounted.intersection(_STRICT_FIELD_SECTIONS):
        unexpected = set(obj) - allowed - set(extension_fields)
    else:
        unexpected = (set(obj) & _PROTOCOL_FIELDS) - allowed
    if unexpected:
        raise contracts.ContractError(
            "reply has forbidden or status-incompatible fields %s"
            % sorted(unexpected)
        )


def reserved_output_fields(bound):
    """Return routed protocol names owned or forbidden by this contract."""
    if not isinstance(bound, BoundContract):
        raise contracts.ContractError("bound must be a BoundContract")
    registered = set(bound.registered_section_ids)
    reserved = set()
    if registered.intersection(_FIELD_CONTRACT_SECTIONS):
        reserved.update(_PROTOCOL_FIELDS)
    if bound.question_ids or "questions_output" in registered:
        reserved.add("questions")
    return frozenset(reserved)


def _section(section, ctx):
    if not isinstance(section, dict):
        raise contracts.ContractError("%s must be an object" % ctx)
    if set(section) != {"id", "text", "variables"}:
        raise contracts.ContractError(
            "%s must contain exactly id, text, and variables" % ctx
        )
    section_id = _text(section, "id", ctx)
    text = _require(section, "text", list, ctx)
    if not text or any(not isinstance(line, str) for line in text):
        raise contracts.ContractError("%s.text must be non-empty string lines" % ctx)
    _require(section, "variables", list, ctx)
    return section_id


def bind(prompt, consumer_sections=(), consumer_instructions=()):
    """Copy a served prompt and bind its registered reply obligations."""
    if not isinstance(prompt, dict):
        raise contracts.ContractError("prompt must be an object")
    bound_prompt = copy.deepcopy(prompt)
    kind = _text(bound_prompt, "kind", "prompt")
    del kind
    sections = _require(bound_prompt, "output_contract", list, "prompt")
    seen = set()
    for index, section in enumerate(sections):
        section_id = _section(section, "prompt.output_contract[%d]" % index)
        if section_id in seen:
            raise contracts.ContractError(
                "prompt has duplicate output-contract id %r" % section_id
            )
        seen.add(section_id)
    if isinstance(consumer_instructions, (str, bytes, dict)):
        raise contracts.ContractError("consumer_instructions must be a sequence")
    consumer_instructions = tuple(consumer_instructions)
    instructions = bound_prompt.get("instructions")
    if instructions is None:
        instructions = []
        bound_prompt["instructions"] = instructions
    elif not isinstance(instructions, list):
        raise contracts.ContractError("prompt.instructions must be a list")
    if isinstance(consumer_sections, (str, bytes, dict)):
        raise contracts.ContractError("consumer_sections must be a sequence")
    consumer_sections = tuple(consumer_sections)
    incoming_ids = []
    for index, section in enumerate(consumer_sections):
        incoming_ids.append(_section(
            section, "consumer_sections[%d]" % index
        ))
    if NEED_RETHINK_SECTION_ID in incoming_ids:
        retired = sorted(seen & RETIRED_RETHINK_SECTION_IDS)
        if retired:
            raise contracts.ContractError(
                "served prompt mounts retired rethink section %r" % retired[0]
            )
        if any(
            "need_rethink" in line
            for unit in instructions + sections
            for line in unit["text"]
        ):
            raise contracts.ContractError(
                "served prompt owns a retired need_rethink fragment"
            )
    for index, instruction in enumerate(consumer_instructions):
        instruction = copy.deepcopy(instruction)
        instruction_ctx = "consumer_instructions[%d]" % index
        try:
            prompt_sets.validate_unit(instruction, instruction_ctx)
        except prompt_sets.PromptSetError as exc:
            raise contracts.ContractError(str(exc)) from exc
        instructions.append(instruction)
    for index, section in enumerate(consumer_sections):
        section = copy.deepcopy(section)
        section_ctx = "consumer_sections[%d]" % index
        section_id = _section(section, section_ctx)
        try:
            prompt_sets.validate_unit(section, section_ctx)
        except prompt_sets.PromptSetError as exc:
            raise contracts.ContractError(str(exc)) from exc
        if section_id not in REGISTERED_SECTIONS:
            raise contracts.ContractError(
                "consumer section %r has no registered validator" % section_id
            )
        if section_id in seen:
            raise contracts.ContractError(
                "consumer section %r duplicates a served section" % section_id
            )
        seen.add(section_id)
        sections.append(section)

    questions = _require(bound_prompt, "questions", dict, "prompt")
    items = _require(questions, "items", list, "prompt.questions")
    question_ids = []
    for index, item in enumerate(items):
        qctx = "prompt.questions.items[%d]" % index
        if not isinstance(item, dict):
            raise contracts.ContractError("%s must be an object" % qctx)
        question_id = _text(item, "id", qctx)
        if question_id in question_ids:
            raise contracts.ContractError(
                "prompt has duplicate question id %r" % question_id
            )
        question_ids.append(question_id)
    registered = tuple(
        section["id"] for section in sections
        if section["id"] in REGISTERED_SECTIONS
    )
    return BoundContract(bound_prompt, registered, tuple(question_ids))


def validate(bound, obj, *, queued_findings=None,
             configured_suite_commands=None, workspace=None,
             expected_artifact=None, extension_fields=()):
    """Validate one parsed reply against one previously bound prompt."""
    if not isinstance(bound, BoundContract):
        raise contracts.ContractError("bound must be a BoundContract")
    if not isinstance(obj, dict):
        raise contracts.ContractError("reply must be an object")
    options = {
        "queued_findings": queued_findings,
        "configured_suite_commands": configured_suite_commands,
        "workspace": workspace,
        "expected_artifact": expected_artifact,
    }
    for section_id in bound.registered_section_ids:
        REGISTERED_SECTIONS[section_id](
            obj, bound, options, "reply[%s]" % section_id
        )
    if bound.question_ids and "questions_output" not in (
        bound.registered_section_ids
    ):
        _questions(obj, bound, options, "reply[questions_output]")
    if isinstance(extension_fields, (str, bytes, dict)) or any(
        not isinstance(field, str) or not field
        for field in extension_fields
    ):
        raise contracts.ContractError(
            "extension_fields must be a sequence of non-empty strings"
        )
    _validate_fields(bound, obj, extension_fields)
    return obj
