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

Nobody rewrites a profile by hand. :func:`ensure_documents` runs at
catalogue initialization — the moment ``model_profiles.ensure_default``
already runs — and converts every readable, valid stored profile into a
document of the SAME NAME, missing-only. Conversion is a normalization, not
a copy: a profile can say things a document has no way to hold ("the family
opposite whoever is calling", "the caller's own effort", a family that
differs from rigor to rigor), so those become explicit numbers, taken from
the profile's ``medium`` configuration and from the same seams today's
resolution uses, and the converted document staffs each seat the way that
profile staffs it today. Nothing here reads a document to staff a call: the
documents appear beside the profiles and wait for their consumers.
"""

import json
import os
import tempfile

from . import model_profiles

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


# ---------------------------------------------------------------------------
# Conversion: one stored model profile -> one staffing document
#
# A profile says what to do in the acts vocabulary, where several answers are
# STRUCTURAL rather than written down: "the family opposite whoever is
# calling", "the caller's own effort", "whatever this family defaults to".
# A document has no way to hold those, so conversion resolves each seat of the
# design's Conversion Reference through the DRIVER'S OWN act-resolution seam —
# the same function every dispatch uses — and writes the numbers it produces.
# Today's answer is therefore MEASURED, not restated here; the seat-by-seat
# drift alarm re-measures it through a real Driver.
#
# Two normalizations the shape forces, both settled by the design: assignment
# is one table for all rigors, so it is taken from the profile's `medium`
# configuration; and where today's answer turns on who was calling, the
# document holds one of those answers — `classify 1` is shared with the
# failure classifier, and `consult 1` is resolved with the converted `fix 1`
# family as origin rather than with the no-origin fallback.

# Each family's whole model and effort vocabulary. It lives here because
# today that vocabulary exists ONLY in the panel's JavaScript
# (static/panel.html MODEL_OPTS / EFFORT_OPTS), which lists models
# strongest-first for DISPLAY. Amendment A1 fixes the ladder order instead:
# least -> most capable as the OPERATOR judges it, never by price, because
# `step_up` exists to add intelligence when work is stuck and never to change
# cost. What is written here is the seed of operator DATA inside each
# converted document — nothing in this module or any later one consults it to
# resolve a call, and only a document save reorders a stored ladder.
# A converted slot carries the WHOLE vocabulary, not only the values its
# profile used, so `step_up` has rungs above today's choice to climb into.
# test_ladders_are_whole_vocabulary_in_operator_order guards this copy against
# the panel's until the panel slice retires that one.
FAMILY_MODELS = {
    "codex": ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"),
    "claude": ("claude-sonnet-5", "claude-opus-5", "claude-fable-5"),
}
FAMILY_EFFORTS = {
    "codex": ("low", "medium", "high", "xhigh", "max"),
    "claude": ("low", "medium", "high", "xhigh", "max"),
}


def _shipped_config(config):
    """The configuration conversion reads today's staffing from.

    The SHIPPED configuration, not a run's: documents are a home-wide
    catalogue, so a profile must convert to the same document whichever run
    happens to initialize first. The parameter exists for tests and for a
    caller that already holds the shipped copy.

    Imported lazily because the driver imports this module to initialize the
    catalogue; the cycle is only in the import graph, never at call time.
    """
    if config is not None:
        return config
    from . import driver
    return driver.load_config(None)


def _resolve_act(config, act_map, act, origin_family=None,
                 default_family=None):
    """One act, resolved by the driver's own act-resolution seam.

    The profile's rigor configuration is the current-state layer and the live
    overlay is empty: a run's `acts.json` is a live per-run override, never
    profile content, so it converts nothing. Using this seam rather than a
    second copy of its rules is what makes the conversion reproduce today
    instead of agreeing with a restatement of today.
    """
    from . import driver
    return driver._resolve_act_from_layers(
        config, True, {}, act_map, act,
        origin_family=origin_family, default_family=default_family)


def _family_defaults(config, family):
    """That family's ordinary model and effort — what a call on it resolves
    to when nothing is pinned (driver._family_defaults)."""
    entry = (config.get("model_defaults") or {}).get(family) or {}
    return entry.get("model"), entry.get("effort")


def _opposite_family(config, family):
    families = config["families_order"]
    return next((f for f in families if f != family), family)


def _slot_family(config, family):
    """The family of the SLOT this seat converts onto.

    Every configured family has its own slot; a seat naming a family the
    configuration has no slot for — a profile that cannot run today either —
    converts onto slot 1, whose family is the first configured one. This is
    the one definition `convert_profile`'s slot map and every DERIVED seat
    both read, so a seat derived from another seat is derived from the
    family that seat actually converts onto, never from one the document has
    no way to hold. For a configured family it is the identity, so every
    profile that can run today converts exactly as before.
    """
    families = config["families_order"]
    return family if family in families else families[0]


def _conversion_seats(config, act_map):
    """Every Conversion Reference seat for ONE rigor configuration.

    Returns ``{(role, index): (family, model, effort)}`` with model and
    effort filled exactly as each dispatch fills them: from the seat's own
    resolved family defaults, except where the dispatch itself takes a half
    from another seat — `consult 1` carries the FIXER'S effort and
    `brainstorm 2` the lead's. A half stays `None` when the family it falls
    back to carries no defaults, whatever family the seat itself lands on,
    exactly as that dispatch would carry nothing for it; `convert_profile`
    resolves what is left against the slot the seat lands on.
    """
    from . import driver

    families = config["families_order"]

    def resolve(act, origin_family=None, default_family=None):
        return _resolve_act(
            config, act_map, act, origin_family=origin_family,
            default_family=default_family)

    def filled(family, model, effort):
        default_model, default_effort = _family_defaults(config, family)
        return (family, model or default_model, effort or default_effort)

    seats = {}

    # plan 1 <- the `skeletoner` act as a SKELETON dispatch resolves it:
    # _skeletoner_profile re-asserts the skeleton's own family and effort
    # (a partial override replaces the whole act entry), and the dispatch
    # then fills the model from the RESOLVED family's defaults.
    skeleton = driver.DEFAULT_CONFIG["acts"]["skeletoner"]
    family, model, effort = resolve(
        "skeletoner", default_family=skeleton.get("agent"))
    seats[("plan", 1)] = filled(
        family, model, effort or skeleton.get("effort"))

    # draft 1 / implement 1 <- the `drafter` / `implementer` acts, model and
    # effort filled from the resolved family's defaults.
    seats[("draft", 1)] = filled(*resolve("drafter"))
    lead = filled(*resolve("implementer"))
    seats[("implement", 1)] = lead

    # fix 1 <- the `fixer` act with `codex` as its default family and no
    # origin. Its family is also `consult 1`'s origin below.
    fix_family, fix_model, fix_effort = resolve(
        "fixer", default_family="codex")
    seats[("fix", 1)] = filled(fix_family, fix_model, fix_effort)

    # classify 1 <- the `reclassifier` act with no origin, so `self` resolves
    # to the first family and `opposite` to the second. The failure
    # classifier has no profile act and takes the family opposite the call
    # that failed; it shares this seat and so reproduces one of its two
    # answers.
    seats[("classify", 1)] = filled(*resolve("reclassifier"))

    # review i <- the fixed review families in configured order. The family
    # is structural (review leadership stays family-rotated); only
    # `review_<family>`'s model and effort are operator-tunable.
    for index, family in enumerate(families, start=1):
        _fixed, model, effort = resolve(
            "review_%s" % family, origin_family=family, default_family=family)
        seats[("review", index)] = filled(family, model, effort)

    # brainstorm 1/2/3 <- Initial Position / Contrary Position / Dante.
    # The lead IS the implementer seat, and Dante is pinned from the lead
    # profile, so seats 1 and 3 carry the same staffing.
    seats[("brainstorm", 1)] = lead
    seats[("brainstorm", 3)] = lead
    # The counterpart is derived from the lead's CONVERTED slot family, not
    # from the raw resolved one: the policy is applied to that converted
    # seat. Where the lead names a family the configuration has no slot for
    # the two differ, and deriving from the raw family would put the
    # Contrary Position on the very slot the lead itself collapses onto —
    # one voice arguing with itself. For every family that has a slot this
    # is the identity.
    lead_family = _slot_family(config, lead[0])
    opposite = _opposite_family(config, lead_family)
    pinned_family, model, effort = resolve(
        "brainstorming_counterpart", origin_family=lead_family,
        default_family=opposite)
    if pinned_family != opposite:
        # A same-family pin cannot move the second voice back onto the
        # lead's family, and a model pinned for that other family goes with
        # it; the effort survives.
        model = None
    counterpart_model, _counterpart_effort = _family_defaults(config, opposite)
    seats[("brainstorm", 2)] = (
        opposite, model or counterpart_model, effort or lead[2])

    # consult 1 <- the consultation the fixer runs: the `consultation`
    # policy resolved with the converted `fix 1` family as ORIGIN (never the
    # no-origin fallback), the CONSULTED family's default model, and the
    # FIXER'S effort — a rejection is never argued by a lighter opponent
    # than the one rejecting.
    # ORIGIN is the converted `fix 1` family, the same normalization the
    # counterpart takes: a fixer on a family with no slot converts onto
    # slot 1, so its consultant is slot 1's opposite and not the opposite of
    # a family the document cannot hold — which would seat the consultation
    # on the fixer's own slot. Its effort likewise falls back to the family
    # the fix seat converts onto, since that is the fixer the document
    # holds. Identity for every configured family.
    fix_seat_family = _slot_family(config, fix_family)
    consulted, _model, _effort = resolve(
        "consultation", origin_family=fix_seat_family)
    consulted_model, _consulted_effort = _family_defaults(config, consulted)
    _fix_default_model, fix_default_effort = _family_defaults(
        config, fix_seat_family)
    seats[("consult", 1)] = (
        consulted, consulted_model, fix_effort or fix_default_effort)

    # sync 1 <- work-area git alignment: the first configured family with
    # that family's defaults. It reads no profile act today.
    seats[("sync", 1)] = (families[0],) + _family_defaults(
        config, families[0])

    return seats


def _append_rung(ladder, value):
    """Add one value a profile named that the family's vocabulary does not
    carry, AFTER its known rungs.

    Appending keeps A1's order of the named models untouched and keeps the
    converted staffing exact: the value is neither dropped nor silently
    replaced by a different model. A value already on the ladder is a
    no-op."""
    if isinstance(value, str) and value and value not in ladder:
        ladder.append(value)


def _rank(ladder, value):
    """The 1-based rung of *value*, which conversion has already put on the
    ladder — its own vocabulary, its family's defaults, and anything a
    profile named beyond them. Rung 1 is the floor for a value nothing put
    there at all, which needs a family the configuration carries no defaults
    for; an absent value is resolved against the slot's defaults before it
    gets here, never written as the weakest rung."""
    try:
        return ladder.index(value) + 1
    except ValueError:
        return 1


def convert_profile(profile, config=None):
    """Convert one validated model profile into a staffing document.

    Deterministic and total for a valid profile: it never fails and never
    invents. Every configured family becomes a numbered slot in configured
    order, carrying its whole vocabulary in amendment A1's capability order
    plus — appended after those known rungs — any model or effort the
    profile names that the vocabulary does not carry. Assignment comes from
    the profile's `medium` configuration; each rigor's tuning comes from
    that rigor's. A rigor x slot x role cell no seat staffs carries that
    family's ordinary defaults today, which is what a call on that family
    resolves to when nothing is pinned. A seat whose act names a family the
    configuration has no slot for — a profile that cannot run today either —
    seats on slot 1, and whichever of model and effort it does not name
    takes slot 1's ordinary defaults by the same rule; a half it does name
    is still its own. A seat derived from another seat — `brainstorm 2` from
    the lead, `consult 1` from the fixer — is derived from the slot that
    origin converts onto, so the derivation lands beside the converted
    origin rather than on top of it.

    No materials, no overrides, no rules: a profile carries nothing that maps
    to them, and inventing an owner's vocabulary is not conversion.
    """
    config = _shipped_config(config)
    families = list(config["families_order"])
    slot_of = {family: str(index)
               for index, family in enumerate(families, start=1)}
    per_rigor = {
        rigor: _conversion_seats(config, profile["configurations"][rigor])
        for rigor in RIGORS
    }

    def slot_for(family):
        # One definition of where a family lands, shared with the derived
        # seats: `_slot_family` already sends a family with no slot to the
        # first configured one, so this lookup never misses.
        return slot_of[_slot_family(config, family)]

    # Ladders first: every rank below is a position on one of these.
    ladders = {}
    for family in families:
        slot = slot_of[family]
        ladders[slot] = {
            "models": list(FAMILY_MODELS.get(family, ())),
            "efforts": list(FAMILY_EFFORTS.get(family, ())),
        }
        default_model, default_effort = _family_defaults(config, family)
        _append_rung(ladders[slot]["models"], default_model)
        _append_rung(ladders[slot]["efforts"], default_effort)
    for rigor in RIGORS:
        for _seat, (family, model, effort) in sorted(per_rigor[rigor].items()):
            slot = slot_for(family)
            _append_rung(ladders[slot]["models"], model)
            _append_rung(ladders[slot]["efforts"], effort)

    # That slot family's ordinary defaults today — what a call on it resolves
    # to when nothing is pinned. It fills every cell no seat staffs, and the
    # halves a seat leaves unsaid.
    slot_defaults = {slot_of[family]: _family_defaults(config, family)
                     for family in families}

    tuning = {}
    for rigor in RIGORS:
        tuning[rigor] = {}
        for slot, (default_model, default_effort) in slot_defaults.items():
            unstaffed = [_rank(ladders[slot]["models"], default_model),
                         _rank(ladders[slot]["efforts"], default_effort)]
            tuning[rigor][slot] = {role: list(unstaffed) for role in ROLES}
        # One cell per rigor x slot x role, so where two seats of one role
        # share a slot the LOWEST seat index writes it — the primary seat,
        # and a deterministic choice rather than whichever came last. In a
        # two-family configuration the seats that share a slot (`brainstorm`
        # 1 and 3) carry the same staffing anyway: Dante is pinned from the
        # lead profile.
        staffed = set()
        for (role, _index), (family, model, effort) in sorted(
                per_rigor[rigor].items()):
            slot = slot_for(family)
            if (slot, role) in staffed:
                continue
            staffed.add((slot, role))
            # A seat on a family the configuration has no slot for keeps
            # any model or effort it names, but the configuration holds no
            # defaults for a family it does not have — so once it seats on
            # slot 1 the half it leaves unsaid takes THAT slot family's
            # ordinary defaults, the same fill a cell no seat staffs takes.
            # Rung 1 would pin the weakest model and the lowest effort,
            # which A1 makes an explicit choice and no profile made.
            default_model, default_effort = slot_defaults[slot]
            tuning[rigor][slot][role] = [
                _rank(ladders[slot]["models"], model or default_model),
                _rank(ladders[slot]["efforts"], effort or default_effort),
            ]

    assignment = {role: {} for role in ROLES}
    for (role, index), (family, _model, _effort) in sorted(
            per_rigor["medium"].items()):
        assignment[role][str(index)] = int(slot_for(family))

    return validate_document({
        "name": profile["name"],
        "families": {
            slot_of[family]: {
                "name": family,
                "models": ladders[slot_of[family]]["models"],
                "efforts": ladders[slot_of[family]]["efforts"],
            }
            for family in families
        },
        # Cross-family review is the standing law; no second role declares
        # distinct families.
        "roles": {
            role: ({"distinct_families": True} if role == "review" else {})
            for role in ROLES
        },
        "materials": {},
        "tuning": tuning,
        "assignment": assignment,
        "overrides": {},
        "rules": [],
    })


def default_document_seed(config=None):
    """The in-code `default` document: the conversion of the model-profile
    store's own `default` seed.

    Expressed as that conversion rather than as a second literal so the two
    cannot drift apart: the seed IS what an unconfigured run's
    `default@medium` staffs today, and one definition of that cannot
    disagree with itself.
    """
    return convert_profile(model_profiles.DEFAULT_SEED, config)


def ensure_documents(home, config=None):
    """Convert every stored model profile into a document of the same name.

    Missing-only and one-time: a document that already exists — a converted
    one the operator has since edited, or one written by hand — is never
    rewritten, so nothing an operator changed is reverted and a profile
    created later is converted at the next initialization. Profile files are
    only READ: never edited, moved, or deleted.

    A profile that cannot be read or validated is SKIPPED — it produces no
    document and does not fail initialization — so reading the whole
    catalogue at start-up never turns a damaged non-`default` profile into a
    start-up failure that does not exist today.

    "Already exists" is read on the catalogue's own identity, which is
    case-insensitive, so conversion neither rewrites a document an operator
    owns under a different spelling nor trips over the store's
    case-collision refusal.

    After it RETURNS, a valid `default` document always exists: converted
    from the stored `default` profile when there is one, which is never
    seeded over, and otherwise from the in-code seed. A stored `default`
    that cannot be loaded is therefore neither counted as that guarantee by
    its filename nor healed — healing would revert an operator's own
    document and conversion is no repair step — so it makes initialization
    fail loudly here, exactly as an invalid stored `default` profile makes
    `model_profiles.ensure_default` fail at the same moment. Returns the
    names written, newest catalogue entries only; the guarantee is the
    floor, not the return value.
    """
    config = _shipped_config(config)
    held = {name.casefold() for name in document_names(home)}
    written = []
    # Names only: list_model_profiles deliberately raises on the first
    # damaged candidate, and initialization must skip that one and continue.
    for name in model_profiles.model_profile_names(home):
        if name.casefold() in held:
            continue
        try:
            profile = model_profiles.load(home, name)
        except model_profiles.ModelProfileError:
            continue
        save(home, convert_profile(profile, config))
        held.add(name.casefold())
        written.append(name)
    # The floor is the one entry initialization must leave USABLE, so a
    # stored `default` is READ rather than counted: a name in the directory
    # is what the missing-only rule needs, and not what a consumer of
    # `default` gets. Same guard as `model_profiles.ensure_default`'s
    # stored-`default` branch — lexists, then load — so the two catalogues
    # answer a damaged floor the same way at the same moment. Named rather
    # than numbered: that function has already moved once.
    if os.path.lexists(_path(home, DEFAULT_DOCUMENT_NAME)):
        load(home, DEFAULT_DOCUMENT_NAME)
    else:
        save(home, default_document_seed(config))
        written.append(DEFAULT_DOCUMENT_NAME)
    return written
