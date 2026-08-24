"""Editable prompt-set storage with a total, whole-set fallback.

A set is the canonical JSON corpus below ``<home>/prompt_sets/<name>``.  Each
load reads every member afresh and validates the corpus as one unit; callers
never receive documents mixed from different sets.  Resolution tries the
requested set, the stored ``default``, then the built-in seed.

This module deliberately owns no rendering, routing, history, cache, version,
or edit protocol.  Stored prompt prose is trusted authoring data.  Validation
only establishes that the declared corpus can be consumed coherently.
"""

import collections
import copy
import json
import os
import re
import shutil
import tempfile

from .prompt_set_seed import DEFAULT_PROMPT_SET


PROMPT_SETS_DIRNAME = "prompt_sets"
DEFAULT_SET_NAME = "default"

MILESTONE_KINDS = (
    "draft_skeleton",
    "draft_slice_note",
    "implement",
    "review_round",
    "delta_review",
    "reclassify",
    "fix_findings",
    "suite_checkpoint",
    "merge_repair",
)
BRAINSTORMING_KINDS = ("discussion_turn", "questioner_turn")
LEAD_TURN_CHARGE_KINDS = ("draft_slice_note", "implement")
MOUNT_TAGS = frozenset((
    "executor:agent_call",
    "role:initial_position",
    "role:contrary_position",
    "role:common_sense",
    "target:document",
    "target:implementation",
))
CANONICAL_MEMBERS = (
    "shared/shared.json",
    *("milestone/%s.json" % kind for kind in MILESTONE_KINDS),
    *("brainstorming/%s.json" % kind for kind in BRAINSTORMING_KINDS),
)

PROMPT_SET_FALLBACK_DEFAULT = "stored_default"
PROMPT_SET_FALLBACK_SEED = "in_code_seed"

PromptSet = collections.namedtuple("PromptSet", ("name", "documents"))
Resolution = collections.namedtuple(
    "Resolution", ("prompt_set", "prompt_set_fallback")
)

_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_VARIABLE_NAME = re.compile(r"^[A-Za-z_]\w*$")
_PLACEHOLDER = re.compile(r"\{\{([^{}]*)\}\}")


class PromptSetError(RuntimeError):
    """One stored prompt set is absent, unreadable, or invalid as a whole."""


class _DuplicateKey(ValueError):
    pass


def _reject_json_constant(value):
    raise ValueError("non-standard JSON constant %r" % value)


def prompt_sets_dir(home):
    return os.path.join(home, PROMPT_SETS_DIRNAME)


def validate_name(name):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise PromptSetError("invalid prompt-set name %r" % (name,))
    return name


def prompt_set_dir(home, name):
    validate_name(name)
    return os.path.join(prompt_sets_dir(home), name)


def list_names(home):
    """Return bindable prompt-set names without reading prompt documents."""
    names = set()
    try:
        with os.scandir(prompt_sets_dir(home)) as entries:
            for entry in entries:
                if entry.is_dir() and _NAME.fullmatch(entry.name):
                    names.add(entry.name)
    except FileNotFoundError:
        pass
    names.discard(DEFAULT_SET_NAME)
    return [DEFAULT_SET_NAME, *sorted(names)]


def _member_path(directory, member):
    return os.path.join(directory, *member.split("/"))


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey("duplicate object key %r" % key)
        value[key] = item
    return value


def _read_member(directory, member, set_name):
    path = _member_path(directory, member)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(
                fh,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
    except FileNotFoundError as exc:
        condition = "unavailable" if os.path.lexists(path) else "missing"
        raise PromptSetError(
            "prompt set %r has %s member %r" % (set_name, condition, member)
        ) from exc
    except OSError as exc:
        raise PromptSetError(
            "prompt set %r member %r is unreadable: %s"
            % (set_name, member, exc)
        ) from exc
    except UnicodeError as exc:
        raise PromptSetError(
            "prompt set %r member %r is not UTF-8" % (set_name, member)
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise PromptSetError(
            "prompt set %r member %r is not valid JSON: %s"
            % (set_name, member, exc)
        ) from exc


def _mapping(value, ctx):
    if not isinstance(value, dict):
        raise PromptSetError("%s must be an object" % ctx)
    return value


def _array(value, ctx):
    if not isinstance(value, list):
        raise PromptSetError("%s must be an array" % ctx)
    return value


def _validate_unit(unit, ctx):
    unit = _mapping(unit, ctx)
    text = _array(unit.get("text"), "%s.text" % ctx)
    if any(not isinstance(line, str) for line in text):
        raise PromptSetError("%s.text must contain only strings" % ctx)
    variables = _array(unit.get("variables"), "%s.variables" % ctx)
    declared = set()
    allowed = {
        "name", "required", "default", "drop_unit_if_absent", "description"
    }
    for index, declaration in enumerate(variables):
        vctx = "%s.variables[%d]" % (ctx, index)
        declaration = _mapping(declaration, vctx)
        unknown = sorted(set(declaration) - allowed)
        if unknown:
            raise PromptSetError(
                "%s has unknown field %r" % (vctx, unknown[0])
            )
        name = declaration.get("name")
        if not isinstance(name, str) or not _VARIABLE_NAME.fullmatch(name):
            raise PromptSetError("%s.name is invalid" % vctx)
        if name in declared:
            raise PromptSetError("%s declares duplicate variable %r" % (ctx, name))
        declared.add(name)
        required = declaration.get("required")
        if not isinstance(required, bool):
            raise PromptSetError("%s.required must be boolean" % vctx)
        has_default = "default" in declaration
        has_drop = "drop_unit_if_absent" in declaration
        if has_drop and declaration["drop_unit_if_absent"] is not True:
            raise PromptSetError(
                "%s.drop_unit_if_absent must be true when present" % vctx
            )
        if required and (has_default or has_drop):
            raise PromptSetError(
                "%s required variable cannot default or drop its unit" % vctx
            )
        if not required and has_default == has_drop:
            raise PromptSetError(
                "%s optional variable needs exactly one default or drop rule"
                % vctx
            )
        if "description" in declaration and not isinstance(
            declaration["description"], str
        ):
            raise PromptSetError("%s.description must be a string" % vctx)

    placeholders = []
    for line in text:
        for name in _PLACEHOLDER.findall(line):
            if not _VARIABLE_NAME.fullmatch(name):
                raise PromptSetError("%s has invalid placeholder %r" % (ctx, name))
            placeholders.append(name)
    used = set(placeholders)
    if used != declared:
        raise PromptSetError(
            "%s variable declarations do not match placeholders "
            "(undeclared: %s; unused: %s)"
            % (ctx, ", ".join(sorted(used - declared)) or "none",
               ", ".join(sorted(declared - used)) or "none")
        )
    if "questions" in unit:
        _question_ids(unit["questions"], "%s.questions" % ctx)
    return declared


def _question_ids(items, ctx):
    ids = []
    for index, item in enumerate(_array(items, ctx)):
        qctx = "%s[%d]" % (ctx, index)
        item = _mapping(item, qctx)
        if set(item) != {"id", "text"}:
            raise PromptSetError("%s must contain exactly id and text" % qctx)
        question_id = item.get("id")
        if not isinstance(question_id, str) or not question_id:
            raise PromptSetError("%s.id must be a non-empty string" % qctx)
        if not isinstance(item.get("text"), str) or not item["text"]:
            raise PromptSetError("%s.text must be a non-empty string" % qctx)
        if question_id in ids:
            raise PromptSetError(
                "%s declares duplicate id %r" % (ctx, question_id)
            )
        ids.append(question_id)
    return set(ids)


def _validate_defaults(part, variables, ctx):
    defaults = part.get("defaults", {})
    if not isinstance(defaults, dict):
        raise PromptSetError("%s.defaults must be an object" % ctx)
    unknown = sorted(set(defaults) - variables)
    if unknown:
        raise PromptSetError(
            "%s defaults undeclared variable %r" % (ctx, unknown[0])
        )


def _validate_mount(part, ctx):
    if "optional" in part or "note" in part:
        raise PromptSetError(
            "%s uses retired optional-unit metadata" % ctx
        )
    if "mount" not in part:
        return
    tags = _array(part["mount"], "%s.mount" % ctx)
    if not tags or any(not isinstance(tag, str) for tag in tags):
        raise PromptSetError("%s.mount must contain tag strings" % ctx)
    if len(tags) != len(set(tags)):
        raise PromptSetError("%s.mount contains duplicate tags" % ctx)
    unknown = sorted(set(tags) - MOUNT_TAGS)
    if unknown:
        raise PromptSetError("%s.mount has unknown tag %r" % (ctx, unknown[0]))
    if "executor:agent_call" in tags and any(
        tag.startswith("role:") for tag in tags
    ):
        raise PromptSetError("%s.mount cannot match a canonical route" % ctx)
    for prefix in ("role:", "target:"):
        if sum(tag.startswith(prefix) for tag in tags) > 1:
            raise PromptSetError(
                "%s.mount has conflicting %s tags" % (ctx, prefix[:-1])
            )


def _validate_parts(doc, section, key, shared, shared_variables, ctx):
    container = _mapping(doc.get(section), "%s.%s" % (ctx, section))
    parts = _array(container.get(key), "%s.%s.%s" % (ctx, section, key))
    declared_ids = []
    variant_id_sets = []
    variants = _mapping(doc.get("variants", {}), "%s.variants" % ctx)
    for index, part in enumerate(parts):
        pctx = "%s.%s.%s[%d]" % (ctx, section, key, index)
        part = _mapping(part, pctx)
        _validate_mount(part, pctx)
        sources = [name for name in ("ref", "one_of", "text") if name in part]
        if len(sources) != 1:
            raise PromptSetError(
                "%s must declare exactly one of ref, one_of, or text" % pctx
            )
        source = sources[0]
        if source == "ref":
            ref = part["ref"]
            if not isinstance(ref, str) or ref not in shared:
                raise PromptSetError("%s has unresolved ref %r" % (pctx, ref))
            _validate_defaults(part, shared_variables[ref], pctx)
            declared_ids.append(ref)
        elif source == "one_of":
            group = part["one_of"]
            if not isinstance(group, str) or group not in variants:
                raise PromptSetError("%s has unresolved one_of %r" % (pctx, group))
            if section == "output_contract":
                possible_ids = set()
                for choice, unit in variants[group].items():
                    section_id = unit.get("id")
                    if not isinstance(section_id, str) or not section_id:
                        raise PromptSetError(
                            "%s variant %r id must be a non-empty string"
                            % (pctx, choice)
                        )
                    possible_ids.add(section_id)
                variant_id_sets.append((pctx, possible_ids))
        else:
            _validate_unit(part, pctx)
            if section == "output_contract":
                section_id = part.get("id")
                if not isinstance(section_id, str) or not section_id:
                    raise PromptSetError("%s.id must be a non-empty string" % pctx)
                declared_ids.append(section_id)
    if section == "output_contract":
        definite_ids = set(declared_ids)
        if len(declared_ids) != len(definite_ids):
            raise PromptSetError("%s.output_contract declares duplicate ids" % ctx)
        for index, (vctx, possible_ids) in enumerate(variant_id_sets):
            if definite_ids & possible_ids:
                raise PromptSetError(
                    "%s can select a duplicate output-contract id" % vctx
                )
            for other_ctx, other_ids in variant_id_sets[index + 1:]:
                if possible_ids & other_ids:
                    raise PromptSetError(
                        "%s and %s can select duplicate output-contract ids"
                        % (vctx, other_ctx)
                    )


def _validate_material_layers(shared_doc, units, unit_variables,
                              contracts, contract_variables, ctx):
    layers = _mapping(
        shared_doc.get("material_layers"), "%s shared.material_layers" % ctx
    )
    for job, materials in layers.items():
        jctx = "%s shared.material_layers.%s" % (ctx, job)
        if not isinstance(job, str) or not job:
            raise PromptSetError("%s has an empty job id" % jctx)
        materials = _mapping(materials, jctx)
        for material, layer in materials.items():
            lctx = "%s.%s" % (jctx, material)
            if not isinstance(material, str) or not material:
                raise PromptSetError("%s has an empty material id" % lctx)
            layer = _mapping(layer, lctx)
            if set(layer) != {"instructions", "questions", "output_contract"}:
                raise PromptSetError(
                    "%s must contain instructions, questions, and output_contract"
                    % lctx
                )
            _validate_parts(
                layer, "instructions", "parts", units, unit_variables, lctx
            )
            questions = _mapping(layer["questions"], "%s.questions" % lctx)
            if set(questions) != {"intro", "items"}:
                raise PromptSetError(
                    "%s.questions must contain intro and items" % lctx
                )
            intro = _array(questions["intro"], "%s.questions.intro" % lctx)
            if any(not isinstance(line, str) for line in intro):
                raise PromptSetError(
                    "%s.questions.intro must contain strings" % lctx
                )
            _question_ids(questions["items"], "%s.questions.items" % lctx)
            _validate_parts(
                layer, "output_contract", "sections", contracts,
                contract_variables, lctx
            )


def _validate_kind(doc, process, kind, shared, shared_variables,
                   contract_sections, contract_variables, ctx):
    doc = _mapping(doc, ctx)
    if doc.get("kind") != kind or doc.get("process") != process:
        raise PromptSetError(
            "%s must identify kind %r and process %r" % (ctx, kind, process)
        )
    questions = _mapping(doc.get("questions"), "%s.questions" % ctx)
    intro = _array(questions.get("intro", []), "%s.questions.intro" % ctx)
    if any(not isinstance(line, str) for line in intro):
        raise PromptSetError("%s.questions.intro must contain strings" % ctx)
    base_questions = _question_ids(
        questions.get("items", []), "%s.questions.items" % ctx
    )

    variants = _mapping(doc.get("variants", {}), "%s.variants" % ctx)
    possible_by_group = {}
    for group, choices in variants.items():
        choices = _mapping(choices, "%s.variants.%s" % (ctx, group))
        if not choices:
            raise PromptSetError("%s.variants.%s must not be empty" % (ctx, group))
        possible = {}
        for choice, unit in choices.items():
            uctx = "%s.variants.%s.%s" % (ctx, group, choice)
            _validate_unit(unit, uctx)
            ids = _question_ids(unit.get("questions", []), "%s.questions" % uctx)
            duplicate = base_questions & ids
            if duplicate:
                raise PromptSetError(
                    "%s declares duplicate id %r" % (uctx, sorted(duplicate)[0])
                )
            possible[choice] = ids
        possible_by_group[group] = possible
    groups = list(possible_by_group)
    for index, group in enumerate(groups):
        for other in groups[index + 1:]:
            for ids in possible_by_group[group].values():
                for other_ids in possible_by_group[other].values():
                    duplicate = ids & other_ids
                    if duplicate:
                        raise PromptSetError(
                            "%s variants can mount duplicate id %r"
                            % (ctx, sorted(duplicate)[0])
                        )

    _validate_parts(
        doc, "instructions", "parts", shared, shared_variables, ctx
    )
    _validate_parts(
        doc, "output_contract", "sections", contract_sections,
        contract_variables, ctx
    )
    return base_questions, possible_by_group


def _validate_documents(documents, ctx):
    documents = _mapping(documents, ctx)
    missing = [member for member in CANONICAL_MEMBERS if member not in documents]
    extra = sorted(set(documents) - set(CANONICAL_MEMBERS))
    if missing or extra:
        raise PromptSetError(
            "%s has the wrong canonical inventory (missing: %s; unknown: %s)"
            % (ctx, ", ".join(missing) or "none", ", ".join(extra) or "none")
        )
    shared_doc = _mapping(documents["shared/shared.json"], "%s shared" % ctx)
    units = _mapping(shared_doc.get("units"), "%s shared.units" % ctx)
    contracts = _mapping(
        shared_doc.get("contract_sections"), "%s shared.contract_sections" % ctx
    )
    unit_variables = {
        name: _validate_unit(unit, "%s shared.units.%s" % (ctx, name))
        for name, unit in units.items()
    }
    contract_variables = {
        name: _validate_unit(unit, "%s shared.contract_sections.%s" % (ctx, name))
        for name, unit in contracts.items()
    }
    _validate_material_layers(
        shared_doc, units, unit_variables, contracts, contract_variables, ctx
    )
    question_ids = {}
    for member in CANONICAL_MEMBERS[1:]:
        process, filename = member.split("/")
        kind = filename[:-5]
        question_ids[member] = _validate_kind(
            documents[member], process, kind, units, unit_variables,
            contracts, contract_variables, "%s %s" % (ctx, member)
        )
    discussion_member = "brainstorming/discussion_turn.json"
    discussion_base, discussion_variants = question_ids[discussion_member]
    lead_role_choices = discussion_variants.get("role_stance")
    if not lead_role_choices or "initial_position" not in lead_role_choices:
        raise PromptSetError(
            "%s %s must declare role_stance.initial_position"
            % (ctx, discussion_member)
        )
    lead_questions = discussion_base | lead_role_choices["initial_position"]
    for kind in LEAD_TURN_CHARGE_KINDS:
        member = "milestone/%s.json" % kind
        charge_questions, _ = question_ids[member]
        duplicate = lead_questions & charge_questions
        if duplicate:
            raise PromptSetError(
                "%s canonical lead-turn composition declares duplicate "
                "question id %r" % (ctx, sorted(duplicate)[0])
            )
    return documents


def load(home, name):
    """Read and validate one complete stored set, fresh on every call."""
    directory = prompt_set_dir(home, name)
    documents = {
        member: _read_member(directory, member, name)
        for member in CANONICAL_MEMBERS
    }
    _validate_documents(documents, "prompt set %r" % name)
    return PromptSet(name=name, documents=documents)


def default_seed():
    """Return an isolated copy of the built-in, validated default corpus."""
    return PromptSet(
        name=DEFAULT_SET_NAME,
        documents=copy.deepcopy(DEFAULT_PROMPT_SET),
    )


def ensure_default(home):
    """Install the complete stored ``default`` once, without repairing it."""
    target = prompt_set_dir(home, DEFAULT_SET_NAME)
    if os.path.lexists(target):
        return False
    parent = prompt_sets_dir(home)
    try:
        os.makedirs(parent, exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".prompt-set-default-", dir=parent)
    except OSError as exc:
        raise PromptSetError("cannot prepare the default prompt set: %s" % exc) from exc
    try:
        for member, document in DEFAULT_PROMPT_SET.items():
            path = _member_path(staging, member)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "x", encoding="utf-8") as fh:
                json.dump(document, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
        try:
            os.rename(staging, target)
        except OSError as exc:
            if os.path.lexists(target):
                return False
            raise PromptSetError(
                "cannot install the default prompt set: %s" % exc
            ) from exc
        staging = None
        return True
    except OSError as exc:
        raise PromptSetError("cannot write the default prompt set: %s" % exc) from exc
    finally:
        if staging is not None and os.path.isdir(staging):
            shutil.rmtree(staging)


def resolve(home, name=DEFAULT_SET_NAME, *, validator=None):
    """Resolve one whole accepted rung, optionally applying a consumer lint."""
    def accepted(prompt_set):
        if validator is not None:
            validator(prompt_set)
        return prompt_set

    if name != DEFAULT_SET_NAME:
        try:
            return Resolution(accepted(load(home, name)), None)
        except PromptSetError:
            pass
    try:
        stored = accepted(load(home, DEFAULT_SET_NAME))
    except PromptSetError:
        return Resolution(
            accepted(default_seed()), PROMPT_SET_FALLBACK_SEED
        )
    fallback = None if name == DEFAULT_SET_NAME else PROMPT_SET_FALLBACK_DEFAULT
    return Resolution(stored, fallback)


# A damaged built-in corpus is a development error, not a runtime fallback
# state.  Validate it once when the package is loaded; every returned seed is
# then a deep copy and cannot be changed by a caller.
_validate_documents(DEFAULT_PROMPT_SET, "in-code prompt-set seed")
