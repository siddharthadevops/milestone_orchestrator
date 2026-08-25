"""Prepared prompt and reply boundary for direct milestone judgments.

The driver owns scheduling and repository transitions.  This adapter owns the
fresh routed charge, the complete current authority block, and the validator
bound to exactly the sections, questions, safeguards, and roots served to one
physical review, delta-review, fixer, or rating attempt.
"""

from __future__ import annotations

import collections
import copy
import json

from . import (
    contracts,
    prompt_contracts,
    prompt_router,
    prompt_sets,
    prompts,
    verifiers,
    workareas,
)


JUDGMENT_JOBS = frozenset((
    "review_round@skeleton",
    "review_round@slice_doc",
    "review_round@slice_impl",
    "delta_review@skeleton",
    "delta_review@slice_doc",
    "delta_review@slice_impl",
    "fix_findings@skeleton",
    "fix_findings@slice_doc",
    "fix_findings@slice_impl",
    "reclassify@doc",
))

_REQUIRED_JOB_PAYLOADS = {
    "review_round@skeleton": frozenset((
        "workspace", "task", "goal_path", "skeleton_path",
    )),
    "review_round@slice_doc": frozenset((
        "workspace", "task", "goal_path", "skeleton_path", "target",
        "reference_path",
    )),
    "review_round@slice_impl": frozenset((
        "workspace", "task", "goal_path", "skeleton_path", "target",
        "reference_path",
    )),
    "delta_review@skeleton": frozenset((
        "workspace", "delta_base_revision", "goal_path",
    )),
    "delta_review@slice_doc": frozenset((
        "workspace", "delta_base_revision", "goal_path", "skeleton_path",
        "reference_path",
    )),
    "delta_review@slice_impl": frozenset((
        "workspace", "delta_base_revision", "goal_path", "skeleton_path",
        "reference_path",
    )),
    "fix_findings@skeleton": frozenset((
        "workspace", "goal_path", "skeleton_path", "queued_findings",
        "consultation_family", "consultation_command", "scratch_path",
    )),
    "fix_findings@slice_doc": frozenset((
        "workspace", "task_subject", "goal_path", "skeleton_path",
        "editable_path", "queued_findings", "consultation_family",
        "consultation_command", "scratch_path",
    )),
    "fix_findings@slice_impl": frozenset((
        "workspace", "task_subject", "goal_path", "skeleton_path",
        "editable_path", "queued_findings", "consultation_family",
        "consultation_command", "scratch_path",
    )),
    "reclassify@doc": frozenset((
        "workspace", "artifact_path", "builders",
        "finding_severity",
        "finding_id",
        "finding_summary",
        "finding_plain",
        "finding_example",
    )),
}

_REQUIRED_CONTRACT_SECTIONS = {
    "review_round": frozenset((
        "review_contract", "review_blocked", "review_need_rethink",
    )),
    "delta_review": frozenset((
        "review_contract", "review_blocked", "review_need_rethink",
    )),
    "fix_findings": frozenset((
        "fix_results", "fix_blocked", "fix_retry", "fix_need_rethink",
    )),
    "reclassify": frozenset(("reclassify_result",)),
}

_SHARED_CONTRACT_SECTIONS = frozenset((
    "envelope_compact", "envelope_verbose", "questions_output",
))

_PROJECT_AUTHORITY_FIELDS = frozenset((
    "project",
    "work_area",
    "primary",
    "additional",
    "reuse_sources",
    "safeguards",
))

PreparedJudgmentCall = collections.namedtuple(
    "PreparedJudgmentCall",
    ("prompt", "validate", "prompt_set_fallback", "bound", "complete"),
)
PreparedJudgmentCall.__new__.__defaults__ = (None,)


def _current_amendments(amendments, operator_complete):
    """Render one unconditional, replacing mutable-authority block."""
    if operator_complete is not True:
        raise prompt_router.PromptRouterError(
            "current mutable operator amendments are unavailable"
        )
    if not isinstance(amendments, (list, tuple)):
        raise prompt_router.PromptRouterError(
            "current amendments must be a sequence"
        )
    operator = []
    design = []
    for item in amendments:
        if not isinstance(item, dict):
            raise prompt_router.PromptRouterError(
                "current amendments contain a malformed entry"
            )
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise prompt_router.PromptRouterError(
                "current amendments contain a malformed entry"
            )
        target = (
            design
            if item.get("authority") == "brainstorming_design"
            else operator
        )
        target.append(item)

    lines = [
        "CURRENT MUTABLE OPERATOR AMENDMENTS (complete replacement set)",
        "This set replaces every mutable operator amendment shown earlier.",
    ]
    if operator:
        for item in operator:
            label = str(item.get("id") or "?")
            lines.append("[%s] %s" % (label, item["text"].strip()))
    else:
        lines.append("CURRENT MUTABLE OPERATOR AMENDMENTS: none.")
    if design:
        lines.extend((
            "",
            "ACCEPTED BRAINSTORMING DESIGN AMENDMENTS (append-only)",
        ))
        for item in design:
            label = str(item.get("id") or "?")
            lines.append("[%s]\n%s" % (label, item["text"]))
    return "\n".join(lines)


def _validate_project_authority(authority):
    missing = sorted(_PROJECT_AUTHORITY_FIELDS - set(authority))
    if missing:
        raise prompt_router.PromptRouterError(
            "project_context is missing authority field %r" % missing[0]
        )
    for field in ("project", "work_area"):
        if not isinstance(authority[field], str) or not authority[field]:
            raise prompt_router.PromptRouterError(
                "project_context.%s must be a non-empty string" % field
            )
    if not isinstance(authority["primary"], dict):
        raise prompt_router.PromptRouterError(
            "project_context.primary must be an object"
        )
    if not isinstance(authority["additional"], list):
        raise prompt_router.PromptRouterError(
            "project_context.additional must be a list"
        )
    if not isinstance(authority["safeguards"], list):
        raise prompt_router.PromptRouterError(
            "project_context.safeguards must be a list"
        )
    reuse_sources = authority["reuse_sources"]
    if reuse_sources is not None:
        try:
            workareas._meta_value({"reuse_sources": reuse_sources})
        except ValueError as exc:
            raise prompt_router.PromptRouterError(
                "project_context.%s" % exc
            ) from exc


def _mounted_variable_declarations(prompt):
    declarations = collections.Counter()
    for section in ("instructions", "output_contract"):
        for unit in prompt[section]:
            for declaration in unit["variables"]:
                declarations[declaration["name"]] += 1
    return declarations


def _mounted_variable_substitutions(prompt, variable):
    placeholder = "{{%s}}" % variable
    return sum(
        line.count(placeholder)
        for section in ("instructions", "output_contract")
        for unit in prompt[section]
        for line in unit["text"]
    )


def prepare(
    home,
    *,
    job,
    material,
    values,
    amendments,
    operator_complete,
    prompt_set="default",
    project_context=None,
    workspace=None,
    queued_findings=None,
):
    """Freshly resolve, render, bind, and pair one judgment charge."""
    if job not in JUDGMENT_JOBS:
        raise prompt_router.PromptRouterError(
            "job %r is not a direct milestone judgment charge" % job
        )
    if not isinstance(values, dict):
        raise prompt_router.PromptRouterError("values must be an object")
    if set(values).intersection((
        "operator_amendments", "ecosystem_map", "queued_findings",
    )):
        raise prompt_router.PromptRouterError(
            "judgment-owned values are adapter-owned"
        )
    kind = prompt_router.DIRECT_ROUTES[job][0]
    if kind == "fix_findings":
        if not isinstance(queued_findings, list):
            raise prompt_router.PromptRouterError(
                "fix_findings requires its queued findings"
            )
        frozen_queued_findings = copy.deepcopy(queued_findings)
    elif queued_findings is not None:
        raise prompt_router.PromptRouterError(
            "only fix_findings accepts queued findings"
        )
    else:
        frozen_queued_findings = None

    charge_values = dict(values)
    if frozen_queued_findings is not None:
        charge_values["queued_findings"] = json.dumps(
            frozen_queued_findings,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
    amendments_block = _current_amendments(
        amendments, operator_complete
    )
    charge_values["operator_amendments"] = amendments_block

    frozen_extensions = ()
    frozen_roots = ()
    authority_body = None
    if project_context is not None:
        if not isinstance(project_context, dict):
            raise prompt_router.PromptRouterError(
                "project_context must be an authority snapshot object"
            )
        authority = copy.deepcopy(project_context)
        _validate_project_authority(authority)
        frozen_extensions = tuple(
            verifiers.compile_extensions(authority["safeguards"])
        )
        primary = authority["primary"]
        additional = authority["additional"]
        roots = [primary.get("path")] + [
            root.get("path") if isinstance(root, dict) else None
            for root in additional
        ]
        if any(not isinstance(root, str) or not root for root in roots):
            raise prompt_router.PromptRouterError(
                "project_context has incomplete granted roots"
            )
        frozen_roots = tuple(roots)
        verifiers.preflight_operator_roots(
            frozen_extensions, frozen_roots
        )
        authority_body = prompts.project_context_body(authority)
        charge_values["ecosystem_map"] = authority_body

    def validate_judgment_prompt(prompt, defaulted_variables):
        required_payloads = _REQUIRED_JOB_PAYLOADS[job]
        mounted_variable_declarations = _mounted_variable_declarations(prompt)
        missing_payloads = sorted(
            required_payloads - set(mounted_variable_declarations)
        )
        if missing_payloads:
            raise prompt_sets.PromptSetError(
                "routed %s prompt omits required job payload %r"
                % (kind, missing_payloads[0])
            )
        defaulted_payloads = sorted(required_payloads & defaulted_variables)
        if defaulted_payloads:
            raise prompt_sets.PromptSetError(
                "routed %s prompt defaults required job payload %r"
                % (kind, defaulted_payloads[0])
            )
        authority_variables = ["operator_amendments"]
        if authority_body is not None:
            authority_variables.append("ecosystem_map")
        for variable in authority_variables:
            declarations = mounted_variable_declarations[variable]
            substitutions = _mounted_variable_substitutions(prompt, variable)
            if declarations != 1 or substitutions != 1:
                raise prompt_sets.PromptSetError(
                    "routed %s prompt must mount exactly one declaration and "
                    "one substitution of adapter-owned authority variable %r"
                    % (kind, variable)
                )
        try:
            bound_prompt = prompt_contracts.bind(prompt)
        except contracts.ContractError as exc:
            raise prompt_sets.PromptSetError(
                "routed judgment prompt cannot bind its served contract: %s"
                % exc
            ) from exc
        missing_sections = sorted(
            _REQUIRED_CONTRACT_SECTIONS[kind]
            - set(bound_prompt.registered_section_ids)
        )
        if missing_sections:
            raise prompt_sets.PromptSetError(
                "routed %s prompt omits required contract section %r"
                % (kind, missing_sections[0])
            )
        incompatible_sections = sorted(
            set(bound_prompt.registered_section_ids)
            - _REQUIRED_CONTRACT_SECTIONS[kind]
            - _SHARED_CONTRACT_SECTIONS
        )
        if incompatible_sections:
            raise prompt_sets.PromptSetError(
                "routed %s prompt mounts incompatible contract section %r"
                % (kind, incompatible_sections[0])
            )

    resolution = prompt_router.resolve(
        home,
        job=job,
        executor="agent_call",
        material=material,
        values=charge_values,
        prompt_set=prompt_set,
        prompt_validator=validate_judgment_prompt,
    )
    bound = prompt_contracts.bind(resolution.prompt)
    reserved = prompt_contracts.reserved_output_fields(bound)
    for extension in frozen_extensions:
        if extension.field in reserved:
            raise verifiers.PolicyConfigError(
                "policy %r contract field %r collides with the routed %s "
                "reply protocol"
                % (extension.policy_id, extension.field, bound.prompt["kind"])
            )
    rendered = prompt_router.render(bound.prompt, charge_values)
    validation_workspace = workspace or charge_values.get("workspace")
    extension_fields = tuple(
        extension.field for extension in frozen_extensions
    )

    def validate(reply):
        return verifiers.validate_merged_output(
            reply,
            bound.prompt["kind"],
            frozen_extensions,
            frozen_roots,
            base_validator=lambda candidate: prompt_contracts.validate(
                bound,
                candidate,
                queued_findings=frozen_queued_findings,
                workspace=validation_workspace,
                extension_fields=extension_fields,
            ),
        )

    return PreparedJudgmentCall(
        rendered,
        validate,
        resolution.prompt_set_fallback,
        bound,
        None,
    )
