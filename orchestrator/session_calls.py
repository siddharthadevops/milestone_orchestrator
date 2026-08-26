"""Fresh routed prompt and reply boundary for milestone session seats."""

from __future__ import annotations

import collections
import copy

from . import (
    contracts,
    prompt_authority,
    prompt_contracts,
    prompt_router,
    prompt_sets,
    prompts,
    session_repository,
    verifiers,
)


SESSION_JOBS = frozenset((
    "draft_slice_note@slice_doc",
    "implement@slice_impl",
    "rethink",
))
_CHARGE_REQUIRED = frozenset((
    "job", "material", "prompt_set", "values", "amendments_path",
    "accepted_amendments", "repository",
))
_CHARGE_OPTIONAL = frozenset(("artifact_type", "project_context"))

PreparedSessionCall = collections.namedtuple(
    "PreparedSessionCall",
    ("prompt", "validate", "prompt_set_fallback", "bound", "complete"),
)


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


def read_current_amendments(path, accepted=()):
    """Read mutable authority now and combine it with accepted design law."""
    return prompt_authority.current_amendments(
        prompt_authority.read_mutable_amendments(path), accepted
    )


def validate_charge(charge):
    """Validate the stable route identity persisted with one session."""
    if not isinstance(charge, dict):
        raise prompt_router.PromptRouterError(
            "milestone session charge must be an object"
        )
    keys = set(charge)
    missing = sorted(_CHARGE_REQUIRED - keys)
    unexpected = sorted(keys - _CHARGE_REQUIRED - _CHARGE_OPTIONAL)
    if missing or unexpected:
        detail = (
            "missing %r" % missing[0]
            if missing else "unexpected %r" % unexpected[0]
        )
        raise prompt_router.PromptRouterError(
            "milestone session charge is invalid: %s" % detail
        )
    if charge["job"] not in SESSION_JOBS:
        raise prompt_router.PromptRouterError(
            "unknown milestone session job %r" % charge["job"]
        )
    for field in ("material", "prompt_set", "amendments_path"):
        if not isinstance(charge[field], str) or not charge[field].strip():
            raise prompt_router.PromptRouterError(
                "milestone session charge.%s must be non-empty" % field
            )
    if not isinstance(charge["values"], dict):
        raise prompt_router.PromptRouterError(
            "milestone session charge.values must be an object"
        )
    if not isinstance(charge["accepted_amendments"], list):
        raise prompt_router.PromptRouterError(
            "milestone session charge.accepted_amendments must be a list"
        )
    session_repository.validate_context(charge["repository"])
    artifact_type = charge.get("artifact_type")
    if charge["job"] == "rethink":
        if artifact_type not in ("document", "implementation"):
            raise prompt_router.PromptRouterError(
                "rethink session charge requires its artifact type"
            )
        finding = charge["values"].get("rethink_finding")
        if not isinstance(finding, str) or not finding.strip():
            raise prompt_router.PromptRouterError(
                "rethink session charge requires its complete finding"
            )
    elif artifact_type is not None:
        raise prompt_router.PromptRouterError(
            "producer session charge derives its artifact type from its job"
        )
    elif "rethink_finding" in charge["values"]:
        raise prompt_router.PromptRouterError(
            "producer session charge cannot carry a rethink finding"
        )
    return copy.deepcopy(charge)


def charge_from_state(state):
    """Return a validated milestone charge, or None for a standalone session."""
    try:
        payload = state["request"]["context"].get("source_payload") or {}
    except (KeyError, TypeError):
        return None
    charge = payload.get("session_charge")
    return None if charge is None else validate_charge(charge)


def prepare_turn(
    home, state, participant, round_number, target_revision,
    correction=None,
):
    """Prepare one routed seat attempt from durable session identity."""
    charge = charge_from_state(state)
    if charge is None:
        return None
    role = participant.get("role") if isinstance(participant, dict) else None
    seat = {
        "initial_position": True,
        "contrary_position": False,
        "common_sense": False,
    }
    if role not in seat:
        raise prompt_router.PromptRouterError(
            "milestone session participant has an unknown role"
        )
    if isinstance(round_number, bool) or not isinstance(round_number, int) \
            or round_number <= 0:
        raise prompt_router.PromptRouterError(
            "milestone session round must be positive"
        )
    repository_backed = "repository" in charge
    if repository_backed:
        if (
            not isinstance(target_revision, str)
            or len(target_revision) != 40
            or any(
                character not in "0123456789abcdef"
                for character in target_revision
            )
        ):
            raise prompt_router.PromptRouterError(
                "milestone session Git authority is unavailable"
            )
    elif not isinstance(target_revision, dict):
        raise prompt_router.PromptRouterError(
            "milestone session target authority is unavailable"
        )
    authority, target_state, _repository = (
        session_repository.live_target_authority(state, charge)
    )
    references = state["request"]["context"].get("references") or []
    reference_lines = (
        "\n".join("  - %s" % item for item in references)
        if references else "  - none"
    )
    values = dict(charge["values"])
    values.update({
        "workspace": state["request"]["workspace_path"],
        "chat_path": state["transcript_ref"],
        "reference_documents": reference_lines,
        "participant_id": participant["id"],
        "role": role,
        "round": str(round_number),
        "target_path": state["request"]["target_path"],
        "target_authority": authority,
        "target_state": target_state,
    })
    operator = prompt_authority.read_mutable_amendments(
        charge["amendments_path"]
    )
    prepared = prepare(
        home,
        job=charge["job"],
        material=charge["material"],
        role=role,
        lead=seat[role],
        values=values,
        prompt_set=charge["prompt_set"],
        artifact_type=charge.get("artifact_type"),
        operator_amendments=operator,
        accepted_amendments=charge["accepted_amendments"],
        project_context=charge.get("project_context"),
        workspace=state["request"]["workspace_path"],
        correction=correction,
    )
    attempt = session_repository.begin_attempt(state, charge, role)
    return prepared._replace(
        complete=lambda: session_repository.complete_attempt(
            attempt, participant["id"], round_number
        )
    )


def _project_authority(project_context):
    if project_context is None:
        return None, (), ()
    if not isinstance(project_context, dict):
        raise prompt_router.PromptRouterError(
            "project_context must be an authority snapshot object"
        )
    authority = copy.deepcopy(project_context)
    safeguards = authority.get("safeguards") or []
    extensions = tuple(verifiers.compile_extensions(safeguards))
    primary = authority.get("primary") or {}
    additional = authority.get("additional") or []
    roots = [primary.get("path")] + [
        item.get("path") if isinstance(item, dict) else None
        for item in additional
    ]
    if any(not isinstance(root, str) or not root for root in roots):
        raise prompt_router.PromptRouterError(
            "project_context has incomplete granted roots"
        )
    return prompts.project_context_body(authority), extensions, tuple(roots)


def prepare(
    home,
    *,
    job,
    material,
    role,
    lead,
    values,
    prompt_set="default",
    artifact_type=None,
    operator_amendments,
    accepted_amendments=(),
    project_context=None,
    workspace=None,
    correction=None,
):
    """Resolve and bind one physical milestone Brainstorming seat attempt."""
    if job not in SESSION_JOBS:
        raise prompt_router.PromptRouterError(
            "job %r is not a milestone session charge" % job
        )
    if not isinstance(values, dict):
        raise prompt_router.PromptRouterError("values must be an object")
    if job == "rethink" and (
        not isinstance(values.get("rethink_finding"), str)
        or not values["rethink_finding"].strip()
    ):
        raise prompt_router.PromptRouterError(
            "rethink requires its complete source finding"
        )
    owned = {
        "operator_amendments", "ecosystem_map", "contract_correction",
    }
    collision = sorted(owned.intersection(values))
    if collision:
        raise prompt_router.PromptRouterError(
            "session-owned value %r was supplied by its caller" % collision[0]
        )
    charge_values = dict(values)
    charge_values["operator_amendments"] = prompt_authority.current_amendments(
        operator_amendments, accepted_amendments
    )
    authority_body, extensions, roots = _project_authority(project_context)
    if authority_body is not None:
        charge_values["ecosystem_map"] = authority_body
    if correction is not None:
        if not isinstance(correction, str) or not correction.strip():
            raise prompt_router.PromptRouterError(
                "contract correction must be non-empty text"
            )
        charge_values["contract_correction"] = correction

    def validate_selected(prompt, _defaulted_variables):
        try:
            bound = prompt_contracts.bind(prompt)
        except contracts.ContractError as exc:
            raise prompt_sets.PromptSetError(
                "routed session prompt cannot bind its served contract: %s"
                % exc
            ) from exc
        declarations = _mounted_variable_declarations(prompt)
        required_mounts = ["operator_amendments"]
        if job == "rethink":
            required_mounts.append("rethink_finding")
        if correction is not None:
            required_mounts.append("contract_correction")
        if authority_body is not None:
            required_mounts.append("ecosystem_map")
        for variable in required_mounts:
            if (
                declarations[variable] != 1
                or _mounted_variable_substitutions(prompt, variable) != 1
            ):
                raise prompt_sets.PromptSetError(
                    "routed session prompt must mount adapter-owned payload "
                    "%r exactly once" % variable
                )
        prompt_router.render(bound.prompt, charge_values)

    resolution = prompt_router.resolve(
        home,
        job=job,
        executor="brainstorming",
        material=material,
        values=charge_values,
        prompt_set=prompt_set,
        role=role,
        lead=lead,
        artifact_type=artifact_type,
        prompt_validator=validate_selected,
    )
    bound = prompt_contracts.bind(resolution.prompt)
    reserved = prompt_contracts.reserved_output_fields(bound)
    for extension in extensions:
        if extension.field in reserved:
            raise verifiers.PolicyConfigError(
                "policy %r contract field %r collides with the routed %s reply protocol"
                % (extension.policy_id, extension.field, bound.prompt["kind"])
            )
    rendered = prompt_router.render(bound.prompt, charge_values)
    extension_fields = tuple(extension.field for extension in extensions)

    def validate(reply):
        return verifiers.validate_merged_output(
            reply,
            bound.prompt["kind"],
            extensions,
            roots,
            base_validator=lambda candidate: prompt_contracts.validate(
                bound,
                candidate,
                workspace=workspace,
                extension_fields=extension_fields,
            ),
        )

    return PreparedSessionCall(
        rendered, validate, resolution.prompt_set_fallback, bound, None
    )
