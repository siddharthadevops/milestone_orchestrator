"""Staffing documents: the numbered staffing catalogue that replaces the
model profile.

This module owns the staffing document — its closed schema, its loud
save-time validation, and the store that keeps it. A staffing document is a
JSON file under ``<home>/staffing_documents/<name>.json`` with EXACTLY eight
keys (closed schema — no version, snapshot, sealing flag, description, or any
other metadata)::

    {"name": "default",
     "families": {"1": {"name": "codex",
                        "models":  ["gpt-5.6-luna", ...],   # weakest first
                        "efforts": ["low", "medium", ...]}},
     "roles": {"plan": {}, ..., "review": {"distinct_families": true}},
     "materials": {"prose": {"examples": ["contracts", ...]}},
     "tuning": {"low": {...},
                "medium": {"1": {"plan": [3, 5], ...}, "2": {...}},
                "high": {...}},
     "assignment": {"plan": {"1": 1}, "review": {"1": 1, "2": 2}, ...},
     "overrides": {"prose": {"assignment": {"plan": {"1": 2}}}},
     "rules": [{"type": "step_up", "role": "review", "min_round": 3}]}

Everything that selects is a NUMBER: ``assignment`` names a family slot and
``tuning`` names 1-based rungs on that slot's own ladders. A document is
therefore readable, diffable and editable without knowing how resolution
works, and this module needs no resolver to validate one.

The models ladder runs weakest to strongest by CAPABILITY as the operator
judges it, never by price. That order is operator data written into the
document; nothing in this module treats it as a code constant, and only a
document save reorders it.

Validation is loud and it is what makes a stored document COMPLETE: every
role carries an assignment for index 1 and every rigor x slot x role carries
a tuning pair. That is exactly what completeness buys :func:`base_staffing`:
over any stored document it always FINDS its seat — a slot for every role at
index 1 and a pair for every rigor x slot x role — so nothing it needs can be
missing. A rank BEYOND a ladder is deliberately still valid — saturation is
resolution's job, not the schema's — and so is a document whose family names
this machine does not have; reading such a saturated cell is the one thing
this lookup refuses loudly, because inventing its answer here would be
resolution's work done in the wrong place.

Store behaviour follows the model-profile store exactly, because the
operator-facing semantics are the same: validation before any byte changes
plus an atomic same-directory replacement, so a refused document leaves the
prior definition untouched; listing loads AND validates every candidate and
raises on the first damaged one, so a damaged catalogue never looks merely
shorter; and names are case-insensitively unique, so the same API semantics
hold on case-sensitive and case-insensitive filesystems alike.
"""

import json
import os
import tempfile

STAFFING_DOCUMENTS_DIRNAME = "staffing_documents"

RIGORS = ("low", "medium", "high")

# The closed process-step vocabulary. Roles name the STEP, never the content:
# no domain word enters this list, and no consumer may add one.
ROLES = (
    "plan", "draft", "implement", "fix", "classify", "review", "brainstorm",
    "consult", "sync",
)

# Typed rules. The goal defines exactly one type; a second one would be a
# further typed entry in future work, never an expression language.
RULE_TYPES = ("step_up",)

DEFAULT_DOCUMENT_NAME = "default"

# The model-profile store's existing input cap for short catalogue strings —
# reused, not tightened.
_MAX_FIELD_LEN = 100

_DIGITS = frozenset("0123456789")


class StaffingError(RuntimeError):
    """Invalid staffing document or unreadable stored definition."""


def staffing_documents_dir(home):
    return os.path.join(home, STAFFING_DOCUMENTS_DIRNAME)


def _path(home, name):
    return os.path.join(staffing_documents_dir(home), "%s.json" % name)


# ---------------------------------------------------------------------------
# Scalar helpers


def _short_string(ctx, label, value):
    """One catalogue string: non-empty and short, stripped."""
    if not isinstance(value, str) or len(value) > _MAX_FIELD_LEN:
        raise StaffingError(
            "%s: %s must be a short non-empty string" % (ctx, label))
    value = value.strip()
    if not value:
        raise StaffingError(
            "%s: %s must be a short non-empty string" % (ctx, label))
    return value


def _positive_int(ctx, label, value):
    """A 1-based number. ``True`` is not 1: booleans are an input error."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StaffingError(
            "%s: %s must be a positive integer, got %r" % (ctx, label, value))
    return value


def _index_key(ctx, label, key):
    """One numbered key ("1", "2", ...) as it is written in JSON.

    Plain ASCII decimals with no leading zero, so a key has exactly one
    spelling and slot references cannot silently miss.
    """
    if (
        not isinstance(key, str)
        or not key
        or key[0] == "0"
        or not set(key) <= _DIGITS
    ):
        raise StaffingError(
            "%s: %s key %r must be a 1-based number written in decimal"
            % (ctx, label, key))
    return int(key)


def _numbered_keys(ctx, label, mapping):
    """Validate every key of a numbered map, then order it numerically.

    Validation precedes ordering so an unnumbered key is refused as an input
    error rather than raising while the map is being sorted.
    """
    for key in mapping:
        _index_key(ctx, label, key)
    return sorted(mapping, key=int)


def _object(ctx, label, value):
    if not isinstance(value, dict):
        raise StaffingError("%s: %s must be an object" % (ctx, label))
    return value


def _exact_keys(ctx, label, value, expected):
    """A closed key set: anything missing or unknown is an input error."""
    missing = [key for key in expected if key not in value]
    unknown = sorted(set(value) - set(expected))
    if missing or unknown:
        raise StaffingError(
            "%s: %s must carry exactly %s (missing: %s; unknown: %s)"
            % (ctx, label, ", ".join(expected),
               ", ".join(missing) or "none", ", ".join(unknown) or "none"))


# ---------------------------------------------------------------------------
# Block validators


def _validate_ladder(ctx, label, values):
    """One family ladder: ordered, non-empty, no repeated rung.

    A repeated rung would give the same staffing two different ranks, which
    makes `step_up` climb in place; refuse it rather than resolve it.
    """
    if not isinstance(values, list) or not values:
        raise StaffingError(
            "%s: %s must be a non-empty ordered array" % (ctx, label))
    out = []
    for position, value in enumerate(values, start=1):
        rung = _short_string(ctx, "%s rung %d" % (label, position), value)
        if rung in out:
            raise StaffingError(
                "%s: %s repeats %r" % (ctx, label, rung))
        out.append(rung)
    return out


def _validate_families(ctx, families):
    """Numbered family slots, each with its own two ladders."""
    _object(ctx, "families", families)
    if not families:
        raise StaffingError("%s: families must carry at least one slot" % ctx)
    out = {}
    for slot in _numbered_keys(ctx, "families", families):
        label = "families.%s" % slot
        entry = _object(ctx, label, families[slot])
        _exact_keys(ctx, label, entry, ("name", "models", "efforts"))
        out[slot] = {
            "name": _short_string(ctx, "%s.name" % label, entry["name"]),
            "models": _validate_ladder(
                ctx, "%s.models" % label, entry["models"]),
            "efforts": _validate_ladder(
                ctx, "%s.efforts" % label, entry["efforts"]),
        }
    return out


def _validate_roles(ctx, roles):
    """The closed role vocabulary, each role optionally declaring
    `distinct_families`. An absent flag means false."""
    _object(ctx, "roles", roles)
    _exact_keys(ctx, "roles", roles, ROLES)
    out = {}
    for role in ROLES:
        label = "roles.%s" % role
        entry = _object(ctx, label, roles[role])
        unknown = sorted(set(entry) - {"distinct_families"})
        if unknown:
            raise StaffingError(
                "%s: %s carries unknown key %r — a role declares only "
                "distinct_families" % (ctx, label, unknown[0]))
        if "distinct_families" in entry:
            flag = entry["distinct_families"]
            if not isinstance(flag, bool):
                raise StaffingError(
                    "%s: %s.distinct_families must be true or false"
                    % (ctx, label))
            out[role] = {"distinct_families": flag}
        else:
            out[role] = {}
    return out


def _validate_materials(ctx, materials):
    """The owner's own words for kinds of work, with their usage phrases."""
    _object(ctx, "materials", materials)
    out = {}
    for name in sorted(materials):
        material = _short_string(ctx, "materials key", name)
        if material != name:
            raise StaffingError(
                "%s: material name %r must be written without surrounding "
                "whitespace" % (ctx, name))
        label = "materials.%s" % name
        entry = _object(ctx, label, materials[name])
        _exact_keys(ctx, label, entry, ("examples",))
        examples = entry["examples"]
        if not isinstance(examples, list) or not examples:
            raise StaffingError(
                "%s: %s.examples must be a non-empty array of usage phrases"
                % (ctx, label))
        out[name] = {
            "examples": [
                _short_string(ctx, "%s.examples entry" % label, example)
                for example in examples
            ],
        }
    return out


def _validate_pair(ctx, label, value):
    """One `[model_rank, effort_rank]` cell.

    A rank beyond its ladder stays valid: saturation is resolution's answer,
    not a save-time refusal.
    """
    if not isinstance(value, list) or len(value) != 2:
        raise StaffingError(
            "%s: %s must be a [model_rank, effort_rank] pair" % (ctx, label))
    return [
        _positive_int(ctx, "%s model rank" % label, value[0]),
        _positive_int(ctx, "%s effort rank" % label, value[1]),
    ]


def _validate_tuning(ctx, tuning, slots):
    """Every rigor x slot x role cell. Completeness is the guarantee."""
    _object(ctx, "tuning", tuning)
    _exact_keys(ctx, "tuning", tuning, RIGORS)
    out = {}
    for rigor in RIGORS:
        label = "tuning.%s" % rigor
        by_slot = _object(ctx, label, tuning[rigor])
        _exact_keys(ctx, label, by_slot, slots)
        out[rigor] = {}
        for slot in slots:
            slot_label = "%s.%s" % (label, slot)
            by_role = _object(ctx, slot_label, by_slot[slot])
            _exact_keys(ctx, slot_label, by_role, ROLES)
            out[rigor][slot] = {
                role: _validate_pair(
                    ctx, "%s.%s" % (slot_label, role), by_role[role])
                for role in ROLES
            }
    return out


def _validate_seats(ctx, label, seats, slots, require_first=True):
    """One role's seats: index -> family slot."""
    by_index = _object(ctx, label, seats)
    if not by_index:
        raise StaffingError(
            "%s: %s must assign at least one seat" % (ctx, label))
    out = {}
    for index in _numbered_keys(ctx, label, by_index):
        slot = by_index[index]
        _positive_int(ctx, "%s.%s" % (label, index), slot)
        if str(slot) not in slots:
            raise StaffingError(
                "%s: %s.%s names family slot %r, which the document does "
                "not carry" % (ctx, label, index, slot))
        out[index] = slot
    if require_first and "1" not in out:
        raise StaffingError(
            "%s: %s must assign index 1 — every role is staffable"
            % (ctx, label))
    return out


def _validate_assignment(ctx, assignment, slots):
    """Who does what: every role, index 1 at least."""
    _object(ctx, "assignment", assignment)
    _exact_keys(ctx, "assignment", assignment, ROLES)
    return {
        role: _validate_seats(
            ctx, "assignment.%s" % role, assignment[role], slots)
        for role in ROLES
    }


def _validate_partial_tuning(ctx, label, tuning, slots):
    """An override's tuning delta: only the cells that differ are written."""
    by_rigor = _object(ctx, label, tuning)
    unknown = sorted(set(by_rigor) - set(RIGORS))
    if unknown or not by_rigor:
        raise StaffingError(
            "%s: %s must name at least one of the rigors %s (unknown: %s)"
            % (ctx, label, ", ".join(RIGORS), ", ".join(unknown) or "none"))
    out = {}
    for rigor in sorted(by_rigor):
        rigor_label = "%s.%s" % (label, rigor)
        by_slot = _object(ctx, rigor_label, by_rigor[rigor])
        unknown = sorted(set(by_slot) - set(slots))
        if unknown or not by_slot:
            raise StaffingError(
                "%s: %s must name at least one carried family slot "
                "(unknown: %s)"
                % (ctx, rigor_label, ", ".join(unknown) or "none"))
        out[rigor] = {}
        for slot in _numbered_keys(ctx, rigor_label, by_slot):
            slot_label = "%s.%s" % (rigor_label, slot)
            by_role = _object(ctx, slot_label, by_slot[slot])
            unknown = sorted(set(by_role) - set(ROLES))
            if unknown or not by_role:
                raise StaffingError(
                    "%s: %s must name at least one role (unknown: %s)"
                    % (ctx, slot_label, ", ".join(unknown) or "none"))
            out[rigor][slot] = {
                role: _validate_pair(
                    ctx, "%s.%s" % (slot_label, role), by_role[role])
                for role in sorted(by_role)
            }
    return out


def _validate_overrides(ctx, overrides, materials, slots):
    """Per material, what changes: an assignment, and rarely a tuning delta.

    Overrides are partial by design — everything not written inherits — so
    completeness is NOT required here; what is required is that every key
    names something the document carries.
    """
    _object(ctx, "overrides", overrides)
    out = {}
    for material in sorted(overrides):
        if material not in materials:
            raise StaffingError(
                "%s: overrides names material %r, which the document's "
                "materials do not carry" % (ctx, material))
        label = "overrides.%s" % material
        entry = _object(ctx, label, overrides[material])
        unknown = sorted(set(entry) - {"assignment", "tuning"})
        if unknown:
            raise StaffingError(
                "%s: %s carries unknown key %r — an override carries an "
                "assignment and rarely a tuning" % (ctx, label, unknown[0]))
        if not entry:
            raise StaffingError(
                "%s: %s must change an assignment or a tuning" % (ctx, label))
        written = {}
        if "assignment" in entry:
            by_role = _object(
                ctx, "%s.assignment" % label, entry["assignment"])
            unknown = sorted(set(by_role) - set(ROLES))
            if unknown or not by_role:
                raise StaffingError(
                    "%s: %s.assignment must name at least one role "
                    "(unknown: %s)"
                    % (ctx, label, ", ".join(unknown) or "none"))
            written["assignment"] = {
                role: _validate_seats(
                    ctx, "%s.assignment.%s" % (label, role), by_role[role],
                    slots, require_first=False)
                for role in sorted(by_role)
            }
        if "tuning" in entry:
            written["tuning"] = _validate_partial_tuning(
                ctx, "%s.tuning" % label, entry["tuning"], slots)
        out[material] = written
    return out


def _validate_rules(ctx, rules):
    """The typed rule list. Exactly one type exists."""
    if not isinstance(rules, list):
        raise StaffingError("%s: rules must be an array" % ctx)
    out = []
    for position, rule in enumerate(rules, start=1):
        label = "rules[%d]" % position
        entry = _object(ctx, label, rule)
        kind = entry.get("type")
        if kind not in RULE_TYPES:
            raise StaffingError(
                "%s: %s has type %r; the only rule type is %s"
                % (ctx, label, kind, ", ".join(RULE_TYPES)))
        _exact_keys(ctx, label, entry, ("type", "role", "min_round"))
        role = entry["role"]
        if role not in ROLES:
            raise StaffingError(
                "%s: %s names unknown role %r (allowed: %s)"
                % (ctx, label, role, ", ".join(ROLES)))
        out.append({
            "type": kind,
            "role": role,
            "min_round": _positive_int(
                ctx, "%s.min_round" % label, entry["min_round"]),
        })
    return out


def _validate(doc, ctx):
    """Validate one whole document; returns the normalized copy to store."""
    if not isinstance(doc, dict):
        raise StaffingError("%s: staffing document must be an object" % ctx)
    _exact_keys(
        ctx, "a staffing document", doc,
        ("name", "families", "roles", "materials", "tuning", "assignment",
         "overrides", "rules"))
    name = doc["name"]
    if not name or not isinstance(name, str):
        raise StaffingError(
            "%s: staffing document needs a non-empty name" % ctx)
    if not all(c.isalnum() or c in "-_" for c in name):
        raise StaffingError(
            "%s: staffing document name must be alphanumeric/-/_ : %r"
            % (ctx, name))
    families = _validate_families(ctx, doc["families"])
    slots = tuple(_numbered_keys(ctx, "families", families))
    materials = _validate_materials(ctx, doc["materials"])
    return {
        "name": name,
        "families": families,
        "roles": _validate_roles(ctx, doc["roles"]),
        "materials": materials,
        "tuning": _validate_tuning(ctx, doc["tuning"], slots),
        "assignment": _validate_assignment(ctx, doc["assignment"], slots),
        "overrides": _validate_overrides(
            ctx, doc["overrides"], materials, slots),
        "rules": _validate_rules(ctx, doc["rules"]),
    }


def validate_document(doc, ctx=None):
    """Validate one staffing document without storing it."""
    return _validate(
        doc,
        ctx or "staffing document %r" % (doc.get("name")
                                         if isinstance(doc, dict) else None))


# ---------------------------------------------------------------------------
# Reading a stored document


def _rung(document, family, ladder, rank, rigor, slot, role):
    """One 1-based rung of a family ladder, refused when it saturates.

    The rank is valid — the schema deliberately accepts one beyond its
    ladder — but the family has no such rung, and choosing the top instead is
    saturation, which belongs to resolution. Refuse in this module's own
    error rather than let an ``IndexError`` out.
    """
    rungs = family[ladder]
    if rank > len(rungs):
        raise StaffingError(
            "staffing document %r tunes %s.%s.%s at %s rank %d, beyond that "
            "family's %d-rung ladder; a saturated rank is resolution's "
            "answer, not this lookup's"
            % (document.get("name"), rigor, slot, role, ladder[:-1], rank,
               len(rungs)))
    return rungs[rank - 1]


def base_staffing(document, rigor, role, index=1):
    """The document's OWN answer for one seat: ``(family, model, effort)``.

    A pure lookup over a stored document — ``assignment[role][index]`` gives
    the slot, that slot's ``name`` the family, and
    ``tuning[rigor][slot][role]`` the two 1-based rungs. It reads no
    session, applies no material, no rule
    and no fallback, so it is computable from the document alone; collapse,
    saturation and the seat fallbacks belong to resolution.

    Completeness makes this lookup TOTAL in exactly the sense completeness is
    defined: the index-1 assignment and the rigor x slot x role pair are
    always present, so nothing it reads can be missing. That is not a promise
    that every valid document answers. A rank that stands beyond its ladder is
    a valid document saying something only saturation answers, so this lookup
    raises :class:`StaffingError` naming the rank rather than clamping it —
    the resolver's job — or letting an ``IndexError`` escape.
    """
    if rigor not in RIGORS:
        raise StaffingError(
            "unknown rigor %r (allowed: %s)" % (rigor, ", ".join(RIGORS)))
    if role not in ROLES:
        raise StaffingError(
            "unknown role %r (allowed: %s)" % (role, ", ".join(ROLES)))
    slot = document["assignment"][role].get(str(index))
    if slot is None:
        raise StaffingError(
            "staffing document %r assigns no %s seat %s"
            % (document.get("name"), role, index))
    family = document["families"][str(slot)]
    model_rank, effort_rank = document["tuning"][rigor][str(slot)][role]
    return (
        family["name"],
        _rung(document, family, "models", model_rank, rigor, slot, role),
        _rung(document, family, "efforts", effort_rank, rigor, slot, role),
    )


def load(home, name):
    """Load and validate one staffing document by name. Loud on corruption."""
    path = _path(home, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError as exc:
        if os.path.lexists(path):
            raise StaffingError(
                "staffing document %r is unavailable: %s" % (name, exc)
            ) from exc
        raise StaffingError("unknown staffing document %r" % name)
    except OSError as exc:
        raise StaffingError(
            "staffing document %r is unreadable: %s" % (name, exc)
        ) from exc
    except ValueError as exc:
        raise StaffingError(
            "staffing document %r is not valid JSON: %s" % (name, exc))
    doc = _validate(doc, "staffing document %r" % name)
    if doc["name"] != name:
        raise StaffingError(
            "staffing document file %r names %r — the stored catalogue is "
            "damaged" % (name, doc["name"]))
    return doc


def document_names(home):
    """Stored document names, sorted, without loading any of them."""
    d = staffing_documents_dir(home)
    if not os.path.isdir(d):
        return []
    return sorted(fn[:-5] for fn in os.listdir(d) if fn.endswith(".json"))


def list_staffing_documents(home):
    """All staffing documents, sorted by name.

    Every candidate is loaded AND validated; the first invalid one raises
    instead of being skipped, so a damaged store fails visibly rather than
    presenting a silently shortened catalogue."""
    return [load(home, name) for name in document_names(home)]


def _case_variant(home, name):
    """Existing differently cased spelling of *name*, if any.

    Names are the operator-facing identity, while filenames are only the
    storage mechanism. Detect the collision explicitly instead of letting a
    case-insensitive filesystem turn a create into an overwrite.
    """
    folded = name.casefold()
    for filename in os.listdir(staffing_documents_dir(home)):
        if not filename.endswith(".json"):
            continue
        stored_name = filename[:-5]
        if stored_name != name and stored_name.casefold() == folded:
            return stored_name
    return None


def save(home, doc):
    """Create or WHOLLY replace one staffing document under its name.

    Validation happens before any byte changes; the write is an atomic
    same-directory replacement, so a refused document leaves the prior
    definition untouched. There is no compare-and-set and no version: two
    saves of one name each land atomically and the last completed one wins,
    exactly as the model-profile store behaves."""
    doc = _validate(
        doc,
        "staffing document %r" % (doc.get("name")
                                  if isinstance(doc, dict) else None))
    os.makedirs(staffing_documents_dir(home), exist_ok=True)
    variant = _case_variant(home, doc["name"])
    if variant is not None:
        raise StaffingError(
            "staffing document %r conflicts with existing catalogue name "
            "%r; names are case-insensitively unique"
            % (doc["name"], variant))
    path = _path(home, doc["name"])
    # Staging files share the target directory for atomic replacement, but
    # stay outside the ``*.json`` catalogue namespace, so a half-written
    # document is never a listable candidate.
    fd, tmp = tempfile.mkstemp(
        prefix=".staffing-document-", suffix=".tmp",
        dir=staffing_documents_dir(home),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return doc
