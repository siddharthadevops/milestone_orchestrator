"""Pure charge resolution and assembled prompt JSON.

The router selects one complete prompt-set rung, derives all mounted units from
canonical charge and seat coordinates, and returns inlined templates with their
local substitution declarations.  It owns no dispatch, state, trace, or reply
validation.
"""

import collections
import copy
import re

from . import prompt_sets


class PromptRouterError(ValueError):
    """A charge, seat, or supplied substitution is invalid."""


Resolution = collections.namedtuple(
    "Resolution", ("prompt", "prompt_set_fallback")
)
_Route = collections.namedtuple(
    "_Route", ("kind", "target_type", "variants", "mount_tags",
               "borrow_questions")
)

DIRECT_ROUTES = {
    "draft_skeleton@skeleton": ("draft_skeleton", "document"),
    "review_round@skeleton": ("review_round", "document"),
    "fix_findings@skeleton": ("fix_findings", "document"),
    "delta_review@skeleton": ("delta_review", "document"),
    "draft_slice_note@slice_doc": ("draft_slice_note", "document"),
    "review_round@slice_doc": ("review_round", "document"),
    "fix_findings@slice_doc": ("fix_findings", "document"),
    "delta_review@slice_doc": ("delta_review", "document"),
    "implement@slice_impl": ("implement", "implementation"),
    "review_round@slice_impl": ("review_round", "implementation"),
    "fix_findings@slice_impl": ("fix_findings", "implementation"),
    "delta_review@slice_impl": ("delta_review", "implementation"),
    "reclassify@doc": ("reclassify", "document"),
    "suite_checkpoint@workspace": ("suite_checkpoint", None),
    "merge_repair@workspace": ("merge_repair", None),
}
STANDALONE_SESSION_JOB = "standalone@document"
STANDALONE_WORKAREA_BOUNDARY = (
    "TARGET ONLY — the Initial Position may edit only the primary target "
    "named in TURN; this is not a repository-wide edit grant. The driver "
    "retains each completed target revision."
)
REPOSITORY_WORKAREA_BOUNDARY = (
    "REPOSITORY CHARGE — the Initial Position may make only the repository "
    "changes allowed by this session's charge. The driver commits each "
    "completed author turn."
)
_PRODUCER_SESSION_JOBS = frozenset((
    "draft_slice_note@slice_doc",
    "implement@slice_impl",
))
SESSION_JOBS = {
    STANDALONE_SESSION_JOB: None,
    "draft_slice_note@slice_doc": "document",
    "implement@slice_impl": "implementation",
    "rethink": None,
}
SEATS = {
    ("initial_position", True): "discussion_turn",
    ("contrary_position", False): "discussion_turn",
    ("common_sense", False): "questioner_turn",
}
_REVIEW_KINDS = frozenset(("review_round", "fix_findings", "delta_review"))
_FORBIDDEN_VALUES = frozenset((
    "_continuation_may_plan_slices",
    "artifact_type",
    "design_update",
    "kind_file",
    "optional_units",
    "options",
    "plan_authoring_authorized",
    "producer_planning",
    "producer_planning_replan",
    "questions_from",
    "role_stance",
    "slices",
    "target_frame",
    "target_type",
    "variant",
    "variants",
    "workarea_boundary",
))
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_]\w*)\}\}")


def _route(job, executor, material, role, lead, artifact_type):
    if not isinstance(job, str) or not job:
        raise PromptRouterError("job must be a non-empty string")
    if not isinstance(material, str) or not material:
        raise PromptRouterError("material must be a non-empty string")
    if executor == "agent_call":
        if job not in DIRECT_ROUTES:
            raise PromptRouterError("unknown agent-call job %r" % job)
        if role is not None or lead is not None or artifact_type is not None:
            raise PromptRouterError(
                "agent calls do not accept seat or artifact-type coordinates"
            )
        kind, target_type = DIRECT_ROUTES[job]
        variants = {}
        if kind in _REVIEW_KINDS:
            variants["target_frame"] = (
                "skeleton_unit" if job.endswith("@skeleton") else "slice_unit"
            )
        tags = {"executor:agent_call"}
        if target_type:
            tags.add("target:%s" % target_type)
        return _Route(kind, target_type, variants, frozenset(tags), None)

    if executor != "brainstorming":
        raise PromptRouterError("unknown executor %r" % executor)
    if job not in SESSION_JOBS:
        raise PromptRouterError("unknown brainstorming job %r" % job)
    if not isinstance(lead, bool):
        raise PromptRouterError("brainstorming lead coordinate must be boolean")
    kind = SEATS.get((role, lead))
    if kind is None:
        raise PromptRouterError("invalid brainstorming seat coordinates")
    target_type = SESSION_JOBS[job]
    if job == "rethink":
        if artifact_type not in ("document", "implementation"):
            raise PromptRouterError(
                "rethink requires document or implementation artifact type"
            )
        target_type = artifact_type
    elif artifact_type is not None:
        raise PromptRouterError(
            "non-rethink jobs do not accept an artifact-type coordinate"
        )
    tags = {"role:%s" % role}
    if target_type is not None:
        tags.add("target:%s" % target_type)
    if job == STANDALONE_SESSION_JOB:
        # Standalone discussions are target-backed like producer sessions,
        # but they borrow no producer-kind questions or artifact craft law.
        tags.add("job:producer")
    else:
        tags.add(
            "job:%s" % ("rethink" if job == "rethink" else "producer")
        )
    variants = {"role_stance": role} if kind == "discussion_turn" else {}
    borrowed = (
        job.split("@", 1)[0]
        if lead and job in _PRODUCER_SESSION_JOBS else None
    )
    return _Route(kind, target_type, variants, frozenset(tags), borrowed)


def _values_for(job, values):
    if not isinstance(values, dict) or any(
        not isinstance(key, str) for key in values
    ):
        raise PromptRouterError("values must be an object with string keys")
    forbidden = sorted(set(values) & _FORBIDDEN_VALUES)
    if forbidden:
        raise PromptRouterError(
            "values contain retired or raw routing control %r" % forbidden[0]
        )
    if job != "draft_skeleton@skeleton" and "task_executor_catalogue" in values:
        raise PromptRouterError(
            "only draft_skeleton accepts the executor catalogue"
        )
    return values


def _document(prompt_set, kind):
    process = "brainstorming" if kind in prompt_sets.BRAINSTORMING_KINDS else "milestone"
    return prompt_set.documents["%s/%s.json" % (process, kind)]


def _mounted(part, tags):
    return set(part.get("mount", ())).issubset(tags)


def _raw_unit(part, document, shared, section, route):
    if "ref" in part:
        source = shared[
            "contract_sections" if section == "output_contract" else "units"
        ]
        unit = source[part["ref"]]
        section_id = part["ref"] if section == "output_contract" else None
    elif "one_of" in part:
        group = part["one_of"]
        choice = route.variants.get(group)
        if choice is None or choice not in document["variants"][group]:
            raise PromptRouterError("canonical route has no %s selector" % group)
        unit = document["variants"][group][choice]
        section_id = unit.get("id") if section == "output_contract" else None
    else:
        unit = part
        section_id = part.get("id") if section == "output_contract" else None
    return unit, section_id


def _prepared_unit(
    unit,
    values,
    fixed,
    part_defaults=None,
    section_id=None,
    defaulted_variables=None,
):
    declarations = copy.deepcopy(unit.get("variables", []))
    declared = {item["name"]: item for item in declarations}
    text = list(unit["text"])
    pinned = {**(part_defaults or {}), **fixed}
    for name, fixed_value in pinned.items():
        if name not in declared:
            continue
        if name in values and values[name] != fixed_value:
            raise PromptRouterError("fixed value %r cannot be overridden" % name)
    if any(
        item.get("drop_unit_if_absent") and item["name"] not in values
        for item in declarations
        if item["name"] not in pinned
    ):
        return None
    missing = [
        item["name"] for item in declarations
        if item["name"] not in pinned
        and item["required"] and item["name"] not in values
    ]
    if missing:
        raise PromptRouterError("missing required value %r" % missing[0])

    if defaulted_variables is not None:
        defaulted_variables.update(
            name for name in (part_defaults or {})
            if name in declared and name not in values
        )

    closed = {
        name: value for name, value in pinned.items() if name in declared
    }
    protected = {
        name
        for value in closed.values()
        for name in _PLACEHOLDER.findall(str(value))
    }
    while protected:
        name = protected.pop()
        if name in closed or name not in declared:
            continue
        declaration = declared[name]
        if name in values:
            value = values[name]
        else:
            value = declaration["default"]
            if defaulted_variables is not None:
                defaulted_variables.add(name)
        closed[name] = value
        protected.update(_PLACEHOLDER.findall(str(value)))

    declarations = [
        item for item in declarations if item["name"] not in closed
    ]
    if defaulted_variables is not None:
        defaulted_variables.update(
            item["name"] for item in declarations
            if item["name"] not in values and "default" in item
        )

    def substitute_closed(match):
        name = match.group(1)
        if name not in closed:
            return match.group(0)
        return str(closed[name])

    # Close route and part constants in one pass.  If their opaque bytes look
    # like another local placeholder, close that declaration in the same pass
    # too so the final renderer cannot reinterpret the inserted bytes.
    text = [_PLACEHOLDER.sub(substitute_closed, line) for line in text]
    result = {"text": text, "variables": declarations}
    if section_id is not None:
        result = {"id": section_id, **result}
    return result


def _parts(
    document,
    shared,
    section,
    key,
    route,
    values,
    fixed,
    defaulted_variables=None,
):
    assembled = []
    questions = []
    for part in document[section][key]:
        if not _mounted(part, route.mount_tags):
            continue
        unit, section_id = _raw_unit(
            part, document, shared, section, route
        )
        defaults = part.get("defaults", {})
        conflicts = sorted(
            name for name, value in defaults.items()
            if name in fixed and value != fixed[name]
        )
        if conflicts:
            raise PromptRouterError(
                "stored default conflicts with fixed value %r" % conflicts[0]
            )
        prepared = _prepared_unit(
            unit,
            values,
            fixed,
            defaults,
            section_id,
            defaulted_variables,
        )
        if prepared is not None:
            assembled.append(prepared)
            questions.extend(copy.deepcopy(unit.get("questions", [])))
    return assembled, questions


def _layer(prompt_set, job, material):
    shared = prompt_set.documents["shared/shared.json"]
    return shared["material_layers"].get(job, {}).get(material)


def _assemble(
    prompt_set,
    route,
    job,
    material,
    values,
    role,
    defaulted_variables=None,
):
    shared = prompt_set.documents["shared/shared.json"]
    document = _document(prompt_set, route.kind)
    fixed = {"kind": route.kind}
    if role is not None:
        fixed["role"] = role
        fixed["workarea_boundary"] = (
            STANDALONE_WORKAREA_BOUNDARY
            if job == STANDALONE_SESSION_JOB else
            REPOSITORY_WORKAREA_BOUNDARY
        )
    instructions, variant_questions = _parts(
        document,
        shared,
        "instructions",
        "parts",
        route,
        values,
        fixed,
        defaulted_variables,
    )
    intro = list(document["questions"].get("intro", []))
    questions = copy.deepcopy(document["questions"].get("items", []))
    questions.extend(variant_questions)
    if route.borrow_questions:
        borrowed = _document(prompt_set, route.borrow_questions)
        questions.extend(copy.deepcopy(borrowed["questions"].get("items", [])))
    output_contract, unused = _parts(
        document,
        shared,
        "output_contract",
        "sections",
        route,
        values,
        fixed,
        defaulted_variables,
    )
    del unused

    layer = _layer(prompt_set, job, material)
    if layer is not None:
        added, layer_variant_questions = _parts(
            layer,
            shared,
            "instructions",
            "parts",
            route,
            values,
            fixed,
            defaulted_variables,
        )
        instructions.extend(added)
        intro.extend(layer["questions"]["intro"])
        questions.extend(copy.deepcopy(layer["questions"]["items"]))
        questions.extend(layer_variant_questions)
        added, unused = _parts(
            layer,
            shared,
            "output_contract",
            "sections",
            route,
            values,
            fixed,
            defaulted_variables,
        )
        output_contract.extend(added)
        del unused

    question_ids = [item["id"] for item in questions]
    if len(question_ids) != len(set(question_ids)):
        raise PromptRouterError("assembled prompt has duplicate question ids")
    section_ids = [section["id"] for section in output_contract]
    if len(section_ids) != len(set(section_ids)):
        raise PromptRouterError(
            "assembled prompt has duplicate output-contract ids"
        )
    return {
        "kind": route.kind,
        "instructions": instructions,
        "questions": {"intro": intro, "items": questions},
        "output_contract": output_contract,
    }


def _validate_mounted_route(prompt):
    """Reject retired controls only when the selected route mounts them."""
    names = {
        declaration.get("name")
        for unit in prompt["instructions"] + prompt["output_contract"]
        for declaration in unit["variables"]
    }
    forbidden = sorted(names & _FORBIDDEN_VALUES)
    if forbidden:
        raise PromptRouterError(
            "mounted route declares caller-forbidden variable %r"
            % forbidden[0]
        )


def _assemble_mounted_route(prompt_set, route, job, material, values, role):
    prompt = _assemble(prompt_set, route, job, material, values, role)
    _validate_mounted_route(prompt)
    return prompt


def assemble(prompt_set, *, job, executor, material, values, role=None,
             lead=None, artifact_type=None):
    """Assemble one already selected prompt set without reading storage."""
    route = _route(job, executor, material, role, lead, artifact_type)
    values = _values_for(job, values)
    return _assemble_mounted_route(
        prompt_set, route, job, material, values, role
    )


def resolve(home, *, job, executor, material, values, prompt_set="default",
            role=None, lead=None, artifact_type=None, prompt_validator=None):
    """Fresh-select one whole rung and assemble one canonical charge."""
    route = _route(job, executor, material, role, lead, artifact_type)
    values = _values_for(job, values)

    def validate_selected(candidate):
        defaulted_variables = set()
        try:
            prompt = _assemble(
                candidate,
                route,
                job,
                material,
                values,
                role,
                defaulted_variables,
            )
            _validate_mounted_route(prompt)
        except (KeyError, TypeError, PromptRouterError) as exc:
            raise prompt_sets.PromptSetError(
                "prompt set cannot assemble the mounted canonical route: %s"
                % exc
            ) from exc
        if prompt_validator is not None:
            prompt_validator(
                prompt,
                frozenset(defaulted_variables),
            )

    selected = prompt_sets.resolve(
        home, prompt_set, validator=validate_selected
    )
    prompt = _assemble_mounted_route(
        selected.prompt_set, route, job, material, values, role
    )
    return Resolution(prompt, selected.prompt_set_fallback)


def _render_unit(unit, values, context):
    """Substitute one already-assembled unit into its served text."""
    try:
        lines = unit["text"]
        declarations = unit["variables"]
    except (KeyError, TypeError) as exc:
        raise PromptRouterError("%s is not an assembled prompt unit" % context) \
            from exc
    if (
        not isinstance(lines, list)
        or any(not isinstance(line, str) for line in lines)
        or not isinstance(declarations, list)
    ):
        raise PromptRouterError("%s is not an assembled prompt unit" % context)
    text = "\n".join(lines)
    substitutions = {}
    for declaration in declarations:
        if not isinstance(declaration, dict):
            raise PromptRouterError(
                "%s has an invalid variable declaration" % context
            )
        name = declaration.get("name")
        if not isinstance(name, str) or not name:
            raise PromptRouterError(
                "%s has an invalid variable declaration" % context
            )
        if name in values:
            value = values[name]
        elif "default" in declaration:
            value = declaration["default"]
        elif declaration.get("drop_unit_if_absent"):
            return None
        else:
            raise PromptRouterError("missing required value %r" % name)
        substitutions[name] = str(value)

    def substitute(match):
        name = match.group(1)
        if name not in substitutions:
            return match.group(0)
        return substitutions[name]

    # Only declared substitutions are open at this boundary.  One pass keeps
    # undeclared placeholder-looking bytes and replacement values opaque.
    return _PLACEHOLDER.sub(substitute, text)


def render(prompt, values):
    """Render assembled JSON into the exact text sent to one worker call."""
    if not isinstance(prompt, dict) or not isinstance(values, dict):
        raise PromptRouterError("render requires an assembled prompt and values")
    blocks = []
    for section in ("instructions", "output_contract"):
        units = prompt.get(section)
        if not isinstance(units, list):
            raise PromptRouterError("assembled prompt.%s must be a list" % section)
        if section == "output_contract":
            questions = prompt.get("questions")
            if not isinstance(questions, dict):
                raise PromptRouterError("assembled prompt.questions must be an object")
            items = questions.get("items")
            intro = questions.get("intro")
            if not isinstance(items, list) or not isinstance(intro, list):
                raise PromptRouterError("assembled prompt.questions is malformed")
            if items:
                if any(not isinstance(line, str) for line in intro):
                    raise PromptRouterError("assembled question intro is malformed")
                question_lines = list(intro)
                for index, item in enumerate(items):
                    if (
                        not isinstance(item, dict)
                        or not isinstance(item.get("id"), str)
                        or not isinstance(item.get("text"), str)
                    ):
                        raise PromptRouterError(
                            "assembled question %d is malformed" % index
                        )
                    question_lines.append(
                        "- %s: %s" % (item["id"], item["text"])
                    )
                blocks.append("\n".join(question_lines))
        for index, unit in enumerate(units):
            rendered = _render_unit(
                unit, values, "assembled prompt.%s[%d]" % (section, index)
            )
            if rendered is not None:
                blocks.append(rendered)
    if not blocks:
        raise PromptRouterError("assembled prompt rendered no text")
    return "\n\n".join(blocks) + "\n"
