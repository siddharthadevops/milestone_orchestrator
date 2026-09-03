"""Fresh routed prompt and reply boundary for every Brainstorming turn."""

from __future__ import annotations

import collections
import copy
import os

from . import (
    brainstorming,
    contracts,
    prompt_authority,
    prompt_contracts,
    prompt_router,
    prompt_sets,
    prompts,
    session_repository,
    staffing,
    verifiers,
)


SESSION_JOBS = frozenset((
    "draft_slice_note@slice_doc",
    "implement@slice_impl",
    "rethink",
))
ROUTED_SESSION_JOBS = SESSION_JOBS | frozenset((
    prompt_router.STANDALONE_SESSION_JOB,
    prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
))
_CHARGE_REQUIRED = frozenset((
    "job", "prompt_set", "values", "amendments_path",
    "accepted_amendments", "repository",
))
_CHARGE_OPTIONAL = frozenset((
    "artifact_type", "project_context",
))
_STANDALONE_REPOSITORY_CHARGE_REQUIRED = frozenset((
    "job", "prompt_set", "values", "repository",
))
_STANDALONE_REPOSITORY_CHARGE_OPTIONAL = frozenset(("project_context",))
_REPOSITORY_REVIEW_SCOPE = (
    "no target selected; review the repository named by WORKSPACE"
)

PreparedSessionCall = collections.namedtuple(
    "PreparedSessionCall",
    ("prompt", "validate", "prompt_set_fallback", "bound", "complete"),
)

QUESTIONER_READINESS_SECTION_ID = "questioner_readiness"


def questioner_readiness_instruction():
    """The session rule that makes Dante's judgment binding."""
    return {
        "text": [
            "BINDING COMMON-SENSE JUDGMENT",
            "- Your questions remain your spoken contribution; do not propose",
            "  or defend a solution.",
            "- Also judge the current repository revision. Return ready: true",
            "  only when no material anti-drift question or objection remains;",
            "  otherwise return ready: false. This judgment is a binding vote",
            "  and the session cannot close without it.",
        ],
        "variables": [],
    }


def questioner_readiness_section():
    return {
        "id": QUESTIONER_READINESS_SECTION_ID,
        "text": [
            "SESSION CONTROL",
            "In addition to the fields above, return a top-level boolean ready.",
        ],
        "variables": [],
    }


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


def _prior_decisions(items):
    """Render prior Brainstorming decisions as revisable context."""
    if not isinstance(items, (list, tuple)):
        raise prompt_router.PromptRouterError(
            "prior decisions must be a sequence"
        )
    lines = []
    for item in items:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
        ):
            raise prompt_router.PromptRouterError(
                "prior decisions contain a malformed entry"
            )
        decision_id = item.get("id")
        if decision_id is not None and (
            not isinstance(decision_id, str) or not decision_id.strip()
        ):
            raise prompt_router.PromptRouterError(
                "prior decisions contain a malformed id"
            )
        label = "[%s] " % decision_id.strip() if decision_id else ""
        lines.append("- %s%s" % (label, item["text"].strip()))
    return "\n".join(lines)


def read_current_amendments(path, accepted=()):
    """Read mutable authority now and combine it with accepted design law."""
    return prompt_authority.current_amendments(
        prompt_authority.read_mutable_amendments(path), accepted
    )


def _validate_charge(charge, *, legacy_material):
    """Validate one route identity, optionally reading its retired material."""
    if not isinstance(charge, dict):
        raise prompt_router.PromptRouterError(
            "milestone session charge must be an object"
        )
    if charge.get("job") == prompt_router.STANDALONE_REPOSITORY_SESSION_JOB:
        keys = set(charge)
        missing = sorted(_STANDALONE_REPOSITORY_CHARGE_REQUIRED - keys)
        unexpected = sorted(
            keys
            - _STANDALONE_REPOSITORY_CHARGE_REQUIRED
            - _STANDALONE_REPOSITORY_CHARGE_OPTIONAL
        )
        if missing or unexpected:
            detail = (
                "missing %r" % missing[0]
                if missing else "unexpected %r" % unexpected[0]
            )
            raise prompt_router.PromptRouterError(
                "standalone repository session charge is invalid: %s"
                % detail
            )
        if (
            not isinstance(charge["prompt_set"], str)
            or not charge["prompt_set"].strip()
        ):
            raise prompt_router.PromptRouterError(
                "standalone repository session charge.prompt_set must be "
                "non-empty"
            )
        if not isinstance(charge["values"], dict):
            raise prompt_router.PromptRouterError(
                "standalone repository session charge.values must be an "
                "object"
            )
        session_repository.validate_context(charge["repository"])
        return copy.deepcopy(charge)
    keys = set(charge)
    missing = sorted(_CHARGE_REQUIRED - keys)
    optional = _CHARGE_OPTIONAL | ({"material"} if legacy_material else set())
    unexpected = sorted(keys - _CHARGE_REQUIRED - optional)
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
    for field in ("prompt_set", "amendments_path"):
        if not isinstance(charge[field], str) or not charge[field].strip():
            raise prompt_router.PromptRouterError(
                "milestone session charge.%s must be non-empty" % field
            )
    if legacy_material and "material" in charge and (
        not isinstance(charge["material"], str)
        or not charge["material"].strip()
    ):
        raise prompt_router.PromptRouterError(
            "milestone session charge.material must be non-empty"
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
        problem = charge["values"].get("rethink_problem")
        if not isinstance(problem, str) or not problem.strip():
            raise prompt_router.PromptRouterError(
                "rethink session charge requires its complete problem"
            )
    elif artifact_type is not None:
        raise prompt_router.PromptRouterError(
            "producer session charge derives its artifact type from its job"
        )
    elif "rethink_problem" in charge["values"]:
        raise prompt_router.PromptRouterError(
            "producer session charge cannot carry a rethink problem"
        )
    checked = copy.deepcopy(charge)
    checked.pop("material", None)
    return checked


def validate_charge(charge):
    """Validate a newly admitted milestone session charge."""
    return _validate_charge(charge, legacy_material=False)


def read_charge(charge):
    """Read an existing pre-cutover charge, ignoring retired material."""
    return _validate_charge(charge, legacy_material=True)


def charge_from_state(state):
    """Return a validated milestone charge, or None for a standalone session."""
    try:
        payload = state["request"]["context"].get("source_payload") or {}
    except (KeyError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    charge = payload.get("session_charge")
    return None if charge is None else read_charge(charge)


def prepare_turn(
    home, state, participant, round_number, target_revision,
    correction=None, staffing_session=None,
    prompt_set=prompt_sets.DEFAULT_SET_NAME,
    project_context=None,
):
    """Prepare one routed seat attempt from durable session identity."""
    charge = charge_from_state(state)
    role = participant.get("role") if isinstance(participant, dict) else None
    seat = {
        "initial_position": True,
        "contrary_position": False,
        "common_sense": False,
    }
    if role not in seat:
        raise prompt_router.PromptRouterError(
            "Brainstorming participant has an unknown role"
        )
    if isinstance(round_number, bool) or not isinstance(round_number, int) \
            or round_number <= 0:
        raise prompt_router.PromptRouterError(
            "Brainstorming round must be positive"
        )
    references = state["request"]["context"].get("references") or []
    reference_lines = (
        "\n".join("  - %s" % item for item in references)
        if references else "  - none"
    )
    common_values = {
        "workspace": state["request"]["workspace_path"],
        "chat_path": state["transcript_ref"],
        "reference_documents": reference_lines,
        "participant_id": participant["id"],
        "role": role,
        "round": str(round_number),
    }

    if charge is None:
        target = brainstorming.validate_target_revision(target_revision)
        request = state["request"]
        accepted = state.get("accepted_target_revision")
        authority = "%s %s" % (
            (
                "accepted revision"
                if accepted is not None else
                "unaccepted recovery baseline"
            ),
            target["revision"],
        )
        amendments = copy.deepcopy(
            request["context"].get("amendments") or []
        )
        values = dict(common_values)
        target_path = request["target_path"]
        if not os.path.isabs(target_path):
            target_path = os.path.join(request["workspace_path"], target_path)
        values.update({
            "target_path": os.path.abspath(target_path),
            "target_authority": authority,
            "target_state": "present" if target["exists"] else "absent",
        })
        return prepare(
            home,
            job=prompt_router.STANDALONE_SESSION_JOB,
            material=staffing.session_material(home, staffing_session),
            role=role,
            lead=seat[role],
            values=values,
            prompt_set=prompt_set,
            operator_amendments=(),
            prior_decisions=amendments,
            project_context=project_context,
            workspace=os.path.abspath(request["workspace_path"]),
            correction=correction,
        )

    run_config = state.get("run_config") if isinstance(state, dict) else None
    binding_agreement = (
        isinstance(run_config, dict)
        and run_config.get(
            "agreement_version",
            brainstorming.LEGACY_AGREEMENT_VERSION,
        ) == brainstorming.CURRENT_AGREEMENT_VERSION
    )
    repository_backed = "repository" in charge
    standalone_repository = (
        charge["job"] == prompt_router.STANDALONE_REPOSITORY_SESSION_JOB
    )
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
    values = dict(charge["values"])
    values.update(common_values)
    if charge["job"] in (
        "rethink",
        prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
    ):
        values["repository_authority"] = "Git commit %s" % target_revision
        if standalone_repository:
            values.update({
                "target_path": _REPOSITORY_REVIEW_SCOPE,
                "target_authority": "Git commit %s" % target_revision,
                "target_state": "current checkout",
            })
    else:
        authority, target_state, _repository = (
            session_repository.live_target_authority(state, charge)
        )
        values.update({
            "target_path": state["request"]["target_path"],
            "target_authority": authority,
            "target_state": target_state,
        })
    if standalone_repository:
        operator = ()
        accepted_amendments = ()
        prior_decisions = copy.deepcopy(
            state["request"]["context"].get("amendments") or []
        )
        routed_project_context = (
            charge.get("project_context")
            if "project_context" in charge else project_context
        )
    else:
        operator = prompt_authority.read_mutable_amendments(
            charge["amendments_path"]
        )
        accepted_amendments = charge["accepted_amendments"]
        prior_decisions = ()
        routed_project_context = charge.get("project_context")
    prepared = prepare(
        home,
        job=charge["job"],
        material=staffing.session_material(home, staffing_session),
        role=role,
        lead=seat[role],
        values=values,
        prompt_set=charge["prompt_set"],
        artifact_type=charge.get("artifact_type"),
        operator_amendments=operator,
        accepted_amendments=accepted_amendments,
        prior_decisions=prior_decisions,
        project_context=routed_project_context,
        workspace=state["request"]["workspace_path"],
        correction=correction,
        require_questioner_readiness=(
            role == "common_sense" and binding_agreement
        ),
        binding_agreement=binding_agreement,
    )
    attempt = session_repository.begin_attempt(state, charge, role)
    return prepared._replace(
        complete=lambda: session_repository.complete_attempt(
            attempt, participant["id"], round_number
        )
    )


def _project_authority(project_context, *, repository_backed=True):
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
    return (
        prompts.project_context_body(
            authority, repository_backed=repository_backed
        ),
        extensions,
        tuple(roots),
    )


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
    prior_decisions=(),
    project_context=None,
    workspace=None,
    correction=None,
    require_questioner_readiness=False,
    binding_agreement=False,
):
    """Resolve and bind one physical Brainstorming turn attempt."""
    if job not in ROUTED_SESSION_JOBS:
        raise prompt_router.PromptRouterError(
            "job %r is not a routed Brainstorming job" % job
        )
    if not isinstance(values, dict):
        raise prompt_router.PromptRouterError("values must be an object")
    if job == "rethink" and (
        not isinstance(values.get("rethink_problem"), str)
        or not values["rethink_problem"].strip()
    ):
        raise prompt_router.PromptRouterError(
            "rethink requires its complete source problem"
        )
    if type(require_questioner_readiness) is not bool:
        raise prompt_router.PromptRouterError(
            "require_questioner_readiness must be a boolean"
        )
    if type(binding_agreement) is not bool:
        raise prompt_router.PromptRouterError(
            "binding_agreement must be a boolean"
        )
    if require_questioner_readiness and role != "common_sense":
        raise prompt_router.PromptRouterError(
            "binding questioner readiness requires the common-sense seat"
        )
    if require_questioner_readiness and not binding_agreement:
        raise prompt_router.PromptRouterError(
            "binding questioner readiness requires binding agreement"
        )
    if job != "rethink" and "rethink_problem" in values:
        raise prompt_router.PromptRouterError(
            "producer session cannot carry a rethink problem"
        )
    owned = {
        "operator_amendments", "prior_decisions", "ecosystem_map",
        "contract_correction",
    }
    collision = sorted(owned.intersection(values))
    if collision:
        raise prompt_router.PromptRouterError(
            "session-owned value %r was supplied by its caller" % collision[0]
        )
    charge_values = dict(values)
    standalone = job in (
        prompt_router.STANDALONE_SESSION_JOB,
        prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
    )
    repository_backed = job != prompt_router.STANDALONE_SESSION_JOB
    rendered_prior_decisions = None
    if standalone:
        if operator_amendments or accepted_amendments:
            raise prompt_router.PromptRouterError(
                "standalone prior decisions are not operator amendments"
            )
        rendered_prior_decisions = _prior_decisions(prior_decisions)
        if rendered_prior_decisions:
            charge_values["prior_decisions"] = rendered_prior_decisions
    else:
        if prior_decisions:
            raise prompt_router.PromptRouterError(
                "milestone sessions do not accept standalone prior decisions"
            )
        charge_values["operator_amendments"] = (
            prompt_authority.current_amendments(
                operator_amendments, accepted_amendments
            )
        )
    authority_body, extensions, roots = _project_authority(
        project_context, repository_backed=repository_backed
    )
    if authority_body is not None:
        charge_values["ecosystem_map"] = authority_body
    if correction is not None:
        if not isinstance(correction, str) or not correction.strip():
            raise prompt_router.PromptRouterError(
                "contract correction must be non-empty text"
            )
        charge_values["contract_correction"] = correction

    consumer_instructions = (
        (questioner_readiness_instruction(),)
        if require_questioner_readiness else ()
    )
    consumer_sections = (
        (questioner_readiness_section(),)
        if require_questioner_readiness else ()
    )

    def validate_selected(prompt, _defaulted_variables):
        try:
            bound = prompt_contracts.bind(
                prompt,
                consumer_sections=consumer_sections,
                consumer_instructions=consumer_instructions,
            )
        except contracts.ContractError as exc:
            raise prompt_sets.PromptSetError(
                "routed session prompt cannot bind its served contract: %s"
                % exc
            ) from exc
        declarations = _mounted_variable_declarations(prompt)
        required_mounts = (
            ["prior_decisions"]
            if standalone and rendered_prior_decisions else
            ([] if standalone else ["operator_amendments"])
        )
        if job == "rethink":
            required_mounts.extend((
                "rethink_problem", "repository_authority",
            ))
            retired = sorted(
                name for name in (
                    "rethink_finding", "target_path", "target_authority",
                    "target_state",
                )
                if declarations[name]
            )
            if retired:
                raise prompt_sets.PromptSetError(
                    "routed rethink prompt mounts retired target payload %r"
                    % retired[0]
                )
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
        rendered_prompt = prompt_router.render(bound.prompt, charge_values)
        if standalone and role != "common_sense":
            boundary = (
                prompt_router.STANDALONE_WORKAREA_BOUNDARY
                if job == prompt_router.STANDALONE_SESSION_JOB else
                prompt_router.REPOSITORY_WORKAREA_BOUNDARY
            )
            if rendered_prompt.count(boundary) != 1:
                scope = (
                    "target-only"
                    if job == prompt_router.STANDALONE_SESSION_JOB else
                    "repository-charge"
                )
                raise prompt_sets.PromptSetError(
                    "standalone discussion prompt must carry its %s editing "
                    "boundary exactly once" % scope
                )

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
    bound = prompt_contracts.bind(
        resolution.prompt,
        consumer_sections=consumer_sections,
        consumer_instructions=consumer_instructions,
    )
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
