"""Prepared prompt and reply boundary for direct milestone authors.

The adapter owns no scheduling or Git transition.  A caller supplies one
canonical author charge and receives the exact text plus the validator bound
to the sections and questions served in that same charge.
"""

from __future__ import annotations

import collections
import copy

from . import (
    contracts,
    prompt_contracts,
    prompt_router,
    prompt_sets,
    prompts,
    verifiers,
)


AUTHOR_JOBS = frozenset((
    "draft_skeleton@skeleton",
    "draft_slice_note@slice_doc",
    "implement@slice_impl",
))

PreparedAuthorCall = collections.namedtuple(
    "PreparedAuthorCall",
    ("prompt", "validate", "prompt_set_fallback", "bound", "complete"),
)
PreparedAuthorCall.__new__.__defaults__ = (None,)


def prepare(
    home,
    *,
    job,
    material,
    values,
    prompt_set="default",
    consumer_sections=(),
    project_context=None,
    workspace=None,
):
    """Freshly resolve, render, bind, and pair one direct author charge."""
    if job not in AUTHOR_JOBS:
        raise prompt_router.PromptRouterError(
            "job %r is not a direct milestone author charge" % job
        )
    charge_values = dict(values)
    recovery = charge_values.get("author_recovery")
    if recovery is None:
        charge_values.pop("author_recovery", None)
    elif not isinstance(recovery, str) or not recovery.strip():
        raise prompt_router.PromptRouterError(
            "author_recovery must be a non-empty string"
        )
    meter_values = (
        charge_values.get("soft_lines"), charge_values.get("hard_lines")
    )
    if (meter_values[0] is None) != (meter_values[1] is None):
        raise prompt_router.PromptRouterError(
            "soft_lines and hard_lines must be supplied together"
        )
    if meter_values[0] is None:
        charge_values.pop("soft_lines", None)
        charge_values.pop("hard_lines", None)
    if meter_values[0] is not None and job != "implement@slice_impl":
        raise prompt_router.PromptRouterError(
            "only implement accepts implementation meter limits"
        )
    implementation_scope = charge_values.get("implementation_scope")
    if implementation_scope is None:
        charge_values.pop("implementation_scope", None)
    elif job != "implement@slice_impl":
        raise prompt_router.PromptRouterError(
            "only implement accepts an implementation scope"
        )
    elif isinstance(implementation_scope, dict):
        charge_values["implementation_scope"] = (
            prompts._implementation_scope_block(implementation_scope).rstrip(
                "\n"
            )
        )
    elif not isinstance(implementation_scope, str) \
            or not implementation_scope.strip():
        raise prompt_router.PromptRouterError(
            "implementation_scope must be a non-empty string or object"
        )
    else:
        charge_values["implementation_scope"] = (
            implementation_scope.rstrip("\n")
        )
    amendments_block = charge_values.get("operator_amendments")
    if amendments_block is not None and (
        not isinstance(amendments_block, str)
        or not amendments_block.strip()
    ):
        raise prompt_router.PromptRouterError(
            "operator_amendments must be a non-empty block"
        )
    frozen_extensions = ()
    frozen_roots = ()
    authority_body = None
    if project_context is not None:
        if not isinstance(project_context, dict):
            raise prompt_router.PromptRouterError(
                "project_context must be an authority snapshot object"
            )
        authority = copy.deepcopy(project_context)
        safeguards = authority.get("safeguards") or []
        frozen_extensions = tuple(verifiers.compile_extensions(safeguards))
        primary = authority.get("primary") or {}
        additional = authority.get("additional") or []
        roots = [primary.get("path")] + [
            root.get("path") if isinstance(root, dict) else None
            for root in additional
        ]
        if any(not isinstance(root, str) or not root for root in roots):
            raise prompt_router.PromptRouterError(
                "project_context has incomplete granted roots"
            )
        frozen_roots = tuple(roots)
        authority_body = prompts.project_context_body(authority)
        charge_values["ecosystem_map"] = authority_body

    def validate_author_prompt(prompt, defaulted_variables):
        try:
            prompt_contracts.bind(
                prompt, consumer_sections=consumer_sections
            )
        except contracts.ContractError as exc:
            raise prompt_sets.PromptSetError(
                "routed author prompt cannot bind its served contract: %s" % exc
            ) from exc
        rendered_prompt = prompt_router.render(prompt, charge_values)
        absent_runtime_inputs = set()
        if implementation_scope is None:
            absent_runtime_inputs.add("implementation_scope")
        if recovery is None:
            absent_runtime_inputs.add("author_recovery")
        if meter_values[0] is None:
            absent_runtime_inputs.update(("soft_lines", "hard_lines"))

        invented = sorted(
            absent_runtime_inputs.intersection(defaulted_variables)
        )
        if invented:
            raise prompt_sets.PromptSetError(
                "routed author prompt defaults absent runtime input %r"
                % invented[0]
            )
        mounted_variables = {
            declaration.get("name")
            for unit in prompt["instructions"]
            for declaration in unit["variables"]
        }
        scope_is_mounted = any(
            declaration.get("name") == "implementation_scope"
            for unit in prompt["instructions"]
            for declaration in unit["variables"]
        )
        if implementation_scope is not None and (
            not scope_is_mounted
            or charge_values["implementation_scope"] not in rendered_prompt
        ):
            raise prompt_sets.PromptSetError(
                "routed implementation prompt omits its current part scope"
            )
        if implementation_scope is None and scope_is_mounted:
            raise prompt_sets.PromptSetError(
                "routed implementation prompt invents a current part scope"
            )
        if (
            amendments_block is not None
            and amendments_block not in rendered_prompt
        ):
            raise prompt_sets.PromptSetError(
                "routed author prompt omits current operator authority"
            )
        if (
            frozen_extensions
            and authority_body not in rendered_prompt
        ):
            raise prompt_sets.PromptSetError(
                "routed author prompt omits active project safeguards"
            )
        if recovery is not None and "author_recovery" not in mounted_variables:
            raise prompt_sets.PromptSetError(
                "routed author prompt omits its physical-call recovery context"
            )
        if recovery is None and "author_recovery" in mounted_variables:
            raise prompt_sets.PromptSetError(
                "routed author prompt invents physical-call recovery context"
            )
        if meter_values[0] is not None and not {
            "soft_lines", "hard_lines"
        }.issubset(mounted_variables):
            raise prompt_sets.PromptSetError(
                "routed implementation prompt omits its live meter limits"
            )
        if meter_values[0] is None and {
            "soft_lines", "hard_lines"
        }.intersection(mounted_variables):
            raise prompt_sets.PromptSetError(
                "routed implementation prompt invents live meter limits"
            )

    resolution = prompt_router.resolve(
        home,
        job=job,
        executor="agent_call",
        material=material,
        values=charge_values,
        prompt_set=prompt_set,
        prompt_validator=validate_author_prompt,
    )
    bound = prompt_contracts.bind(
        resolution.prompt, consumer_sections=consumer_sections
    )
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
    expected_artifact = (
        charge_values.get("skeleton_path")
        if job == "draft_skeleton@skeleton" else None
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
                workspace=validation_workspace,
                expected_artifact=expected_artifact,
            ),
        )

    return PreparedAuthorCall(
        rendered,
        validate,
        resolution.prompt_set_fallback,
        bound,
        None,
    )
