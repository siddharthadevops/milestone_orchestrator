"""Staffing documents and sessions: the numbered staffing catalogue that
replaces the model profile, and the live selection an owner opens over it.

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

A SESSION is the owner's live selection over that catalogue — the work
area, the families this machine actually has, a document REFERENCE, the
rigor, and optionally a default material and an unconditional override in
the document's own shape. Its store follows the document store for the same
reason: the operator-facing semantics are the same.

:func:`resolve` is the one question and the one answer. It reads the stored
session and the stored document on every call, layers base, material
override and session override, collapses a family this machine does not
have, saturates a rank past the end of a ladder, applies ``step_up``, and
answers EXACTLY ``{"agent": ..., "model": ..., "effort": ...}``. Only two
conditions are surfaced — nobody to call at all, and a `distinct_families`
role that cannot be split — and an input it cannot read resolves on the
default document and says so. It writes nothing. Sessions and the resolver
are documented at their own sections below; no dispatch reads any of this
yet, because every consumer is cut over in its own later slice.
"""

import collections
import json
import os
import secrets
import tempfile

from . import model_profiles, workareas

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
RULE_STEP_UP = "step_up"
RULE_TYPES = (RULE_STEP_UP,)

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


def _shown(value):
    """One REJECTED value as an error message can carry it.

    `%r` is not total: past CPython's int/str conversion limit an integer
    cannot be formatted at all, and the attempt raises while the refusal is
    still being built — replacing a declared :class:`StaffingError` with a
    raw conversion failure no caller of this module expects. A number that
    long is a number no seat, round, rank or stored id could ever be, so
    the message names its size instead of its digits and THAT refusal
    leaves through its own class.

    That conversion limit is the one limit handled here, because it is a
    property of the value alone: the same integer fails to format in any
    caller at any depth. The interpreter's RECURSION limit is not — it is
    a property of the value AND the stack left when formatting starts, so
    no single depth is the deep one. A value nested deeply enough exhausts
    the stack from any caller, however shallow; and a caller near the
    limit raises `RecursionError` out of `open`, `json.load` or validation
    on an ordinary request carrying no deep value at all. Catching it here
    would normalize one frame of many without making this module's
    operations total against recursion exhaustion, so it is deliberately
    left alone.
    STORED bytes nested past that limit are a different matter — damage in
    an artifact this module owns — and :func:`load` and
    :func:`read_session` do normalize those.
    """
    try:
        return "%r" % (value,)
    except ValueError:
        if isinstance(value, int):
            return "<integer of %d bits>" % value.bit_length()
        return "<unprintable %s>" % type(value).__name__


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
            "%s: %s must be a positive integer, got %s"
            % (ctx, label, _shown(value)))
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
    try:
        return int(key)
    except ValueError as exc:
        # More digits than the interpreter converts (CPython's int/str
        # conversion limit). A key no arithmetic can reach is damage like
        # any other, and it leaves through the same loud class rather than
        # as a raw conversion failure no caller of this module expects.
        raise StaffingError(
            "%s: %s key %r is too long to be a number" % (ctx, label, key)
        ) from exc


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


def _exact_keys(ctx, label, value, expected, optional=()):
    """A closed key set: anything missing or unknown is an input error.

    Everything in *expected* is required; an *optional* key may be present
    or absent; anything outside both is unknown.
    """
    missing = [key for key in expected if key not in value]
    unknown = sorted(set(value) - set(expected) - set(optional))
    if missing or unknown:
        shape = ", ".join(expected)
        if optional:
            shape += " (optional: %s)" % ", ".join(optional)
        raise StaffingError(
            "%s: %s must carry exactly %s (missing: %s; unknown: %s)"
            % (ctx, label, shape,
               ", ".join(missing) or "none", ", ".join(unknown) or "none"))


def _name_token(ctx, label, value):
    """One path-safe catalogue identity: a non-empty alphanumeric/-/_ name.

    The staffing document's own name rule, reused for the session id and for
    a session's document reference. It satisfies the store's path-fragment
    rule (:func:`kvstore.validate_fragment`) with room to spare — no
    separator, no control character, never blank — so a stored name is a
    filename and nothing else, and a reference cannot reach outside its
    catalogue directory.
    """
    if not value or not isinstance(value, str):
        raise StaffingError("%s: %s must be a non-empty name" % (ctx, label))
    if not all(c.isalnum() or c in "-_" for c in value):
        raise StaffingError(
            "%s: %s must be alphanumeric/-/_ : %r" % (ctx, label, value))
    return value


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
    """One role's seats: index -> family slot.

    *slots* are the family slots the document carries, or ``None`` where
    there is no document to check against — a session override, whose
    document is a live reference that may be edited or replaced between two
    calls. A slot such an override names but the document does not carry is
    answered by collapse at resolution, never by a refusal here.
    """
    by_index = _object(ctx, label, seats)
    if not by_index:
        raise StaffingError(
            "%s: %s must assign at least one seat" % (ctx, label))
    out = {}
    for index in _numbered_keys(ctx, label, by_index):
        slot = by_index[index]
        _positive_int(ctx, "%s.%s" % (label, index), slot)
        if slots is not None and str(slot) not in slots:
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
    """An override's tuning delta: only the cells that differ are written.

    *slots* is ``None`` where there is no document to check against; see
    :func:`_validate_seats`.
    """
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
        carried = "carried family slot" if slots is not None else "family slot"
        unknown = ([] if slots is None
                   else sorted(set(by_slot) - set(slots)))
        if unknown or not by_slot:
            raise StaffingError(
                "%s: %s must name at least one %s (unknown: %s)"
                % (ctx, rigor_label, carried, ", ".join(unknown) or "none"))
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
    name = _name_token(ctx, "staffing document name", doc["name"])
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
    except RecursionError as exc:
        # Deeper nesting than the interpreter decodes (CPython's recursion
        # limit). A document no reader can reach is damage like any other,
        # and it leaves through the same loud class rather than as a raw
        # recursion failure the resolver's mandatory fallback would not
        # recognize.
        raise StaffingError(
            "staffing document %r is nested too deeply to be read"
            % name) from exc
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


def _atomic_write(directory, path, prefix, payload):
    """Write one record by atomic same-directory replacement.

    Staging files share the target directory so the replacement is atomic,
    but stay outside the ``*.json`` catalogue namespace, so a half-written
    record is never a listable candidate. Validation has already happened
    when a caller reaches here, which is what makes a refused write leave
    the previous record byte-identical.
    """
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


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
    _atomic_write(
        staffing_documents_dir(home), _path(home, doc["name"]),
        ".staffing-document-", doc)
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


# ---------------------------------------------------------------------------
# Sessions: what an owner opens for a piece of work
#
# A session is the OWNER'S half of staffing — which document to use, how hard
# to work, which families this machine actually has, and, when the owner
# wants one, an unconditional delta on top of that document. It holds a
# REFERENCE to the document and never a copy, so editing either one reaches
# the next call and rewrites no call already made. There is no snapshot and
# no freeze, because a session is a live selection and not a transaction.
#
# The record is small and closed and the store is the document store's own
# pattern again: validation before any byte changes, then an atomic
# same-directory replacement, so a refused edit leaves the stored session
# byte-identical. Exactly create, read and edit: no delete, no expiry, no
# lease, no liveness, no version. Nothing here staffs a call — the resolver
# is what reads a session, and every dispatch still reads model profiles
# until its own slice cuts it over.

STAFFING_SESSIONS_DIRNAME = "staffing_sessions"

# The owner's existing handles for where the work happens, exactly as the
# service and the Brainstorming adapter already carry them: the two
# path-free ones as one authority, and/or the workspace path. Recorded
# verbatim; nothing in this module reads them.
WORK_AREA_HANDLES = ("project", "work_area", "workspace_path")

# The store that already owns each path-free handle. Its rule is the whole
# rule: a handle the owner's work-area store accepts opens a session, and
# one it refuses does not.
WORK_AREA_AUTHORITIES = {
    "project": workareas.validate_project_slug,
    "work_area": workareas.validate_name,
}

SESSION_FIELDS = ("id", "work_area", "families", "document", "rigor")
SESSION_OPTIONAL_FIELDS = ("material", "overrides")

# Exactly what the owner may change while work runs. `work_area` and
# `families` are facts — where the work happens, and what this machine has —
# rather than choices, and `id` is the record's identity; an edit that could
# move them would quietly make a session somebody else's.
SESSION_EDITABLE_FIELDS = ("document", "rigor", "material", "overrides")


def staffing_sessions_dir(home):
    """The session directory: beside the documents, never inside them.

    Two catalogues with two lifetimes — documents are the operator's
    library, sessions are open pieces of work — so a session file is never
    a candidate the document store would try to load and validate.
    """
    return os.path.join(home, STAFFING_SESSIONS_DIRNAME)


def _session_path(home, session_id):
    return os.path.join(staffing_sessions_dir(home), "%s.json" % session_id)


def _new_session_id():
    """The opaque id the STORE assigns, never one a caller supplies.

    An id is the store's identity for a record, so honouring a caller's
    would let one owner name — and so overwrite — another owner's session.
    The token is `brainstorming_lifecycle._new_session_id`'s, prefixed for
    this catalogue.
    """
    return "stf-" + secrets.token_hex(16)


def _path_string(ctx, label, value):
    """One filesystem path, recorded verbatim.

    Deliberately not `_short_string`: a real workspace path is longer than
    a catalogue name and the filesystem's own limit is the only meaningful
    one. A NUL is the single byte no path can carry, which is the check
    `brainstorming` already makes on its own paths.
    """
    if not isinstance(value, str) or not value.strip():
        raise StaffingError("%s: %s must be a non-empty path" % (ctx, label))
    if "\x00" in value:
        raise StaffingError(
            "%s: %s is not a valid filesystem path" % (ctx, label))
    return value


def _handle_string(ctx, label, value, authority):
    """One path-free handle, checked by its own store and recorded as given.

    `workareas` already owns what a project slug and a work-area name may
    be — non-blank, no separator, no control character, and the work-area
    name's byte cap — and both of its validators return their input
    UNCHANGED. Reusing them is what makes "verbatim" true: a catalogue rule
    of this module's own would trim a handle into a DIFFERENT work area or
    refuse a name the owner's store accepts, and either one puts a session
    somewhere its owner never named.
    """
    try:
        return authority(value)
    except ValueError as exc:
        raise StaffingError(
            "%s: %s is not a valid handle (%s)" % (ctx, label, exc)) from exc


def _validate_work_area(ctx, work_area):
    """The owner's handles for where the work happens, recorded verbatim.

    `project` and `work_area` are one authority and are supplied together —
    the rule `brainstorming_tasks._execution_context` already enforces — and
    a `workspace_path` may stand alone or beside them. Nothing in this
    module reads any of them; they are refused only for a shape no consumer
    could use, which is why the pair is checked, each handle is left to the
    store that owns it, and nothing else is.
    """
    entry = _object(ctx, "work_area", work_area)
    unknown = sorted(set(entry) - set(WORK_AREA_HANDLES))
    if unknown:
        raise StaffingError(
            "%s: work_area carries unknown handle %r (allowed: %s)"
            % (ctx, unknown[0], ", ".join(WORK_AREA_HANDLES)))
    out = {}
    for handle in WORK_AREA_HANDLES:
        if handle not in entry:
            continue
        label = "work_area.%s" % handle
        out[handle] = (
            _path_string(ctx, label, entry[handle])
            if handle == "workspace_path"
            else _handle_string(ctx, label, entry[handle],
                                WORK_AREA_AUTHORITIES[handle]))
    if ("project" in out) != ("work_area" in out):
        raise StaffingError(
            "%s: work_area names a project without its work area, or the "
            "reverse — the two are one authority and are supplied together"
            % ctx)
    if not out:
        raise StaffingError(
            "%s: work_area must carry a project with its work area, a "
            "workspace_path, or both" % ctx)
    return out


def _validate_available_families(ctx, families):
    """The family names this machine has, in the owner's order.

    A machine FACT rather than a choice, so it is recorded as given and an
    empty list is stored as the fact it is. Having nobody to call surfaces
    at resolution as `staffing_unavailable` — the request is the moment
    that matters — and refusing the save instead would make a session
    unopenable on a machine whose families are configured afterwards.
    """
    if not isinstance(families, list):
        raise StaffingError(
            "%s: families must be an array of family names" % ctx)
    return [_short_string(ctx, "families entry", name) for name in families]


def _validate_session_overrides(ctx, overrides):
    """The session's own delta on the document, in the document's own inner
    shape: an `assignment`, a `tuning`, at least one of the two written.

    Unconditional — never keyed by material — because it sits ABOVE the
    material layer: "for this run, the fixer runs on the other family" is
    the whole of it. Validated for shape only, never against the referenced
    document, which is a live reference that may be edited, replaced or
    absent between two calls; a slot it does not carry collapses at
    resolution. It is explicit configuration, written by any authorized
    session owner — the operator or a calling product — through the store,
    the API or the panel, under the caller identity and project access the
    service already enforces.
    """
    entry = _object(ctx, "overrides", overrides)
    unknown = sorted(set(entry) - {"assignment", "tuning"})
    if unknown:
        raise StaffingError(
            "%s: overrides carries unknown key %r — a session override "
            "carries an assignment and a tuning" % (ctx, unknown[0]))
    if not entry:
        raise StaffingError(
            "%s: overrides must change an assignment or a tuning" % ctx)
    written = {}
    if "assignment" in entry:
        by_role = _object(ctx, "overrides.assignment", entry["assignment"])
        unknown = sorted(set(by_role) - set(ROLES))
        if unknown or not by_role:
            raise StaffingError(
                "%s: overrides.assignment must name at least one role "
                "(unknown: %s)" % (ctx, ", ".join(unknown) or "none"))
        written["assignment"] = {
            role: _validate_seats(
                ctx, "overrides.assignment.%s" % role, by_role[role],
                None, require_first=False)
            for role in sorted(by_role)
        }
    if "tuning" in entry:
        written["tuning"] = _validate_partial_tuning(
            ctx, "overrides.tuning", entry["tuning"], None)
    return written


def _session_ctx(session_id):
    """The context prefix for one session id, whatever a caller passed.

    Built BEFORE :func:`_name_token` gets to refuse the id, so it renders
    through :func:`_shown` rather than `%r`: an id past CPython's int/str
    conversion limit would otherwise raise while the refusal was still
    being built, and the mandatory fallback would see a raw conversion
    failure where it expects the one declared class.
    """
    return "staffing session %s" % (_shown(session_id),)


def validate_session(record, ctx=None):
    """Validate one whole session record; returns the normalized copy.

    The shape is closed exactly as a document's is: the five facts an owner
    supplies plus the two optional selections. `document` is validated as a
    NAME and not against the catalogue — a session may reference a document
    that does not exist yet, or no longer does, and the mandatory fallback
    is what answers that at resolution.
    """
    if not isinstance(record, dict):
        raise StaffingError(
            "%s: staffing session must be an object"
            % (ctx or "staffing session"))
    ctx = ctx or _session_ctx(record.get("id"))
    _exact_keys(ctx, "a staffing session", record, SESSION_FIELDS,
                SESSION_OPTIONAL_FIELDS)
    rigor = record["rigor"]
    if rigor not in RIGORS:
        raise StaffingError(
            "%s: rigor %r is not one of %s"
            % (ctx, rigor, ", ".join(RIGORS)))
    out = {
        "id": _name_token(ctx, "staffing session id", record["id"]),
        "work_area": _validate_work_area(ctx, record["work_area"]),
        "families": _validate_available_families(ctx, record["families"]),
        "document": _name_token(ctx, "document", record["document"]),
        "rigor": rigor,
    }
    if "material" in record:
        out["material"] = _short_string(ctx, "material", record["material"])
    if "overrides" in record:
        out["overrides"] = _validate_session_overrides(
            ctx, record["overrides"])
    return out


def create_session(home, body):
    """Open one session and return the stored record.

    The body carries everything but the id, which the store assigns; a
    supplied one is refused rather than honoured. Validation happens before
    any byte changes, so a refused create writes nothing at all.
    """
    entry = _object("staffing session", "the create body", body)
    if "id" in entry:
        raise StaffingError(
            "staffing session: id is assigned by the store and is never "
            "supplied by a caller")
    record = validate_session(dict(entry, id=_new_session_id()))
    _atomic_write(
        staffing_sessions_dir(home), _session_path(home, record["id"]),
        ".staffing-session-", record)
    return record


def read_session(home, session_id):
    """Load and validate one session by id. Loud on corruption.

    Every failure — unknown, unreadable, malformed, damaged — is one
    :class:`StaffingError`, because the resolver's mandatory fallback treats
    "cannot be read" as one condition and answers it the same way.
    """
    ctx = _session_ctx(session_id)
    path = _session_path(home, _name_token(ctx, "id", session_id))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            record = json.load(fh)
    except FileNotFoundError as exc:
        if os.path.lexists(path):
            raise StaffingError(
                "staffing session %r is unavailable: %s" % (session_id, exc)
            ) from exc
        raise StaffingError("unknown staffing session %r" % session_id)
    except OSError as exc:
        raise StaffingError(
            "staffing session %r is unreadable: %s" % (session_id, exc)
        ) from exc
    except ValueError as exc:
        raise StaffingError(
            "staffing session %r is not valid JSON: %s" % (session_id, exc))
    except RecursionError as exc:
        # Deeper nesting than the interpreter decodes (CPython's recursion
        # limit). A record no reader can reach is damage like any other, and
        # it leaves through the same loud class rather than as a raw
        # recursion failure the mandatory fallback would not recognize.
        raise StaffingError(
            "staffing session %r is nested too deeply to be read"
            % session_id) from exc
    record = validate_session(record, ctx)
    if record["id"] != session_id:
        raise StaffingError(
            "staffing session file %r names %r — the stored record is "
            "damaged" % (session_id, record["id"]))
    return record


def edit_session(home, session_id, changes):
    """Change a live session's selection: `document`, `rigor`, `material`,
    `overrides`, and nothing else.

    A field absent from *changes* is left alone; an explicit ``None`` clears
    an optional one, which is how a default material or an override is
    withdrawn. The work area, the families this machine has and the id are
    refused, so an edit cannot quietly move a session somewhere else.

    Optimistic, exactly as the document and profile stores are: no
    compare-and-set and no version, so two saves of one session each land
    atomically and the last completed one governs the next call.
    """
    ctx = _session_ctx(session_id)
    record = read_session(home, session_id)
    entry = _object(ctx, "an edit", changes)
    unknown = sorted(set(entry) - set(SESSION_EDITABLE_FIELDS))
    if unknown:
        raise StaffingError(
            "%s: %r is not editable (editable: %s)"
            % (ctx, unknown[0], ", ".join(SESSION_EDITABLE_FIELDS)))
    for field in SESSION_EDITABLE_FIELDS:
        if field not in entry:
            continue
        value = entry[field]
        if value is None:
            if field not in SESSION_OPTIONAL_FIELDS:
                raise StaffingError(
                    "%s: %s is part of the selection and cannot be cleared"
                    % (ctx, field))
            record.pop(field, None)
        else:
            record[field] = value
    record = validate_session(record, ctx)
    _atomic_write(
        staffing_sessions_dir(home), _session_path(home, session_id),
        ".staffing-session-", record)
    return record


# ---------------------------------------------------------------------------
# Resolution: one request, one answer
#
# This is the strict half of the milestone. Every request the resolver ADMITS
# comes back with a staffing except the two surfaced conditions; everything
# a caller could get wrong in the other direction is ANSWERED rather than
# refused — a family this machine does not have collapses, a rank past the
# end of a ladder saturates, a material nobody defined counts as none, a seat
# nobody assigned falls back to the role's first, and a session or a document
# that cannot be read at all resolves on the default document and says so.
#
# The order is fixed, and nothing in it can fail:
#
#   material  the request's, else the session's default, else none — a name
#             the document does not carry is not a material at all
#   slot      the layered assignment (base, then the material's override,
#             then the session's) for `(role, index)`; an index no layer
#             assigns is that role's index 1
#   collapse  the lowest-numbered slot whose family this machine has,
#             whenever the assigned slot's is not one of them
#   ranks     the layered `tuning[rigor][slot][role]` for the slot that
#             actually runs, saturating at each ladder's top
#   step_up   one step per matching rule entry, after saturation
#
# Every call reads the stored session and the stored document; nothing is
# kept between calls, which is the whole of "live" — the last completed write
# governs the next call, and a call already made is never rewritten because
# nothing rewrites it. Nothing is written either: what actually ran is the
# consumer's marker, in the consumer's own slice.

# The two SURFACED conditions, as their public tokens. Their HTTP statuses,
# and what a consumer does with either, belong to slice 5 and after.
STAFFING_UNAVAILABLE = "staffing_unavailable"
DISTINCT_FAMILIES_UNSATISFIABLE = "distinct_families_unsatisfiable"

# What the mandatory fallback reports beside the answer. The consumer's
# marker carries it in its own slice; nothing here stores it.
STAFFING_FALLBACK_DEFAULT_DOCUMENT = "default_document"

# The rigor an unreadable session resolves at. Rigor is chosen ON the
# session, so when there is no session to read there is no choice to honour
# and the middle of the three is the one the goal names.
FALLBACK_RIGOR = "medium"

_REQUEST_CTX = "staffing request"


class StaffingConditionError(StaffingError):
    """One of the two SURFACED conditions, carrying its public token.

    The established `(code, detail)` shape (`tasks.TaskRequestError`): the
    token is the classification a route or a consumer switches on, the
    message is for a human reading a log. It stays INSIDE
    :class:`StaffingError` because this module has one error family — a
    caller that only wants "this request did not answer" needs no second
    except clause, and one that wants the token asks for it.
    """

    def __init__(self, code, detail):
        StaffingError.__init__(self, detail)
        self.code = code


#: One resolution: the answer, and the fallback note when it was resolved on
#: the default document because an input could not be read. ``answer`` is
#: EXACTLY ``{"agent", "model", "effort"}`` — the dict the Brainstorming seat
#: seam already consumes — so the note travels BESIDE it rather than as a
#: fourth key every consumer would have to strip before dispatching.
#: ``staffing_fallback`` is ``None`` on an ordinary answer.
Resolution = collections.namedtuple(
    "Resolution", ("answer", "staffing_fallback"))

# What resolution needs from a session: the families this machine has, the
# rigor, the default material, the session's own override, and the name of
# the document it references (``None`` when there was no session to read).
_Selection = collections.namedtuple(
    "_Selection", ("families", "rigor", "material", "overrides", "document"))

# One read of a session and its document, as resolution sees them: the
# selection, the document actually in force, the delta stack weakest-first,
# the slots whose family this machine has in numbered order, and the fallback
# note. Both readers below and the resolver share it, so a seat reader and a
# dispatch can never disagree about which document is in force.
_Effective = collections.namedtuple(
    "_Effective",
    ("selection", "document", "layers", "available", "staffing_fallback"))


# ---------------------------------------------------------------------------
# Admitting a request


def _request_index(label, value):
    """One 1-based seat index or round number.

    A non-positive one is an INPUT error and not a collapse: seats and
    rounds are counted from 1 by every consumer that passes them, so a zero
    or a negative is a caller bug, and answering it would hide the bug
    behind a plausible staffing forever.
    """
    return _positive_int(_REQUEST_CTX, label, value)


def _request_material(material):
    """The request's material: a string, or nothing.

    A NAME is all the request carries. Whether the document carries a
    material of that name is resolution's business — an unknown one counts
    as absent — so nothing here checks it against a catalogue.
    """
    if material is None:
        return None
    if not isinstance(material, str):
        raise StaffingError(
            "%s: material must be a string or absent, got %s"
            % (_REQUEST_CTX, _shown(material)))
    return material


def _admit(role, index, round_number, material):
    """Refuse a request nothing could answer, BEFORE resolution.

    Exactly three things are input errors: an unknown role, a non-positive
    index or round, and a non-string material. None of them is a surfaced
    condition and none of them reaches the mandatory fallback, which exists
    for inputs that cannot be READ and not for a request that says something
    no vocabulary contains.

    `brief` is not here on purpose: it is accepted, read by no rule and
    never stored, so there is nothing about it to refuse.
    """
    if role not in ROLES:
        raise StaffingError(
            "%s: unknown role %s (allowed: %s)"
            % (_REQUEST_CTX, _shown(role), ", ".join(ROLES)))
    return (role,
            _request_index("index", index),
            _request_index("round", round_number),
            _request_material(material))


# ---------------------------------------------------------------------------
# The mandatory fallback: what resolution reads when an input cannot be read


def _selection_for(home, session, families):
    """The owner's selection, or the fallback selection when there is none.

    "Cannot be read" is ONE condition — unknown, unreadable, malformed,
    damaged alike — which is exactly why :func:`read_session` raises one
    class for all of them: the fallback answers them the same way and has
    nothing to tell apart. The fallback selection is the `default` document
    at `medium` with the families the CALLER passed, because families and
    rigor live on the session and there is no session to read them from.
    """
    try:
        record = read_session(home, session)
    except StaffingError:
        return _Selection(tuple(families or ()), FALLBACK_RIGOR,
                          None, None, None), True
    return _Selection(tuple(record["families"]), record["rigor"],
                      record.get("material"), record.get("overrides"),
                      record["document"]), False


def _document_for(home, name):
    """The document actually in force, and whether it is the fallback.

    Three levels, and the last one cannot fail: the session's own document;
    else the stored `default`; else the in-code seed. The caller's families
    and rigor are not touched here — an unreadable DOCUMENT loses only the
    document, so the session's own rigor, families, material and override
    all still govern; it is an unreadable SESSION that loses those, and
    :func:`_selection_for` has already answered that.

    A damaged stored `default` is answered, never repaired: healing it would
    revert whatever an operator wrote, and slice 2's loud initialization is
    a different moment which stays exactly as loud as it is.
    """
    if name is not None:
        try:
            return load(home, name), False
        except StaffingError:
            pass
    try:
        return load(home, DEFAULT_DOCUMENT_NAME), True
    except StaffingError:
        return default_document_seed(), True


# ---------------------------------------------------------------------------
# The layers, and the seat they give


def _material_in_force(document, requested, session_material):
    """The material this call resolves under, or ``None``.

    The request's, else the session's default, else none — and a name the
    document does not carry counts as ABSENT, so the chain simply moves on
    to the next one rather than dropping to base. That is one rule applied
    to every mention: a material the document has no entry for is not a
    material, wherever it was named, so renaming one in the document
    degrades a stale request onto the session's standing choice instead of
    off the material layer altogether.
    """
    for candidate in (requested, session_material):
        if candidate and candidate in document["materials"]:
            return candidate
    return None


def _layers(document, selection, material):
    """The delta stack, WEAKEST FIRST: base, material override, session
    override.

    Each layer carries an `assignment`, a `tuning`, or both, in the
    document's own inner shape, and each is read CELL BY CELL: a layer
    silent about one seat or one tuning cell inherits the layer below rather
    than replacing a whole role. Layer 0 is always the document itself,
    which save-time completeness makes total.
    """
    stack = [document]
    override = document["overrides"].get(material) if material else None
    if override:
        stack.append(override)
    if selection.overrides:
        stack.append(selection.overrides)
    return stack


def _assigned_seats(layers, role):
    """Every index any layer assigns for *role*, in index order.

    The union rather than the topmost layer's set: an override adds a seat
    without restating the ones below it, and a role's seats are what the
    layered document says altogether. Index keys are validated decimals, so
    the ordering is arithmetic and not lexicographic.
    """
    indices = set()
    for layer in layers:
        indices.update(
            int(key) for key in (layer.get("assignment") or {}).get(role, {}))
    return sorted(indices)


def _slot_for(layers, role, index):
    """The family slot the layered assignment gives `(role, index)`.

    Strongest layer first, then the role's index 1 the same way: a seat no
    layer assigns is that role's FIRST seat, layered like any other, so a
    session override that moves index 1 moves the fallback with it. The base
    document always assigns index 1 for every role — that is exactly what
    save-time completeness buys — so this lookup is total over any document
    resolution can reach.
    """
    try:
        keys = (str(index), "1")
    except ValueError:
        # More digits than the interpreter converts (CPython's int/str
        # conversion limit), which `_index_key` already refuses to store as
        # a key: no layer can be spelling this seat, so it is unassigned by
        # construction and takes the role's index 1 like any other rather
        # than escaping as a raw conversion failure.
        keys = ("1",)
    for key in keys:
        for layer in reversed(layers):
            slot = (layer.get("assignment") or {}).get(role, {}).get(key)
            if slot is not None:
                return slot
    return layers[0]["assignment"][role]["1"]


def _ranks(layers, rigor, slot, role):
    """The layered `[model_rank, effort_rank]` for one cell.

    Strongest layer first again, ending at the base document, whose tuning
    completeness covers every rigor x slot x role it carries — and the slot
    asked for here is always one it carries, because collapse only ever
    lands on a slot of this document.
    """
    for layer in reversed(layers[1:]):
        cell = (((layer.get("tuning") or {}).get(rigor) or {})
                .get(slot) or {}).get(role)
        if cell is not None:
            return cell
    return layers[0]["tuning"][rigor][slot][role]


# ---------------------------------------------------------------------------
# Collapse, saturation and the one rule


def _available_slots(document, families):
    """The document's slots whose family this machine has, lowest first.

    An empty result is the whole of `staffing_unavailable`: there is nobody
    to call. An empty *families* list reaches here as the machine fact it
    is, which is why the session store stores one rather than refusing it.
    """
    present = set(families)
    return [slot for slot in sorted(document["families"], key=int)
            if document["families"][slot]["name"] in present]


def _running_slot(slot, available):
    """The slot that actually runs.

    A slot whose family this machine does not have collapses to the
    lowest-numbered slot whose family it does — INCLUDING a slot the
    document does not carry at all, which a session override written against
    a document since edited may well name. One rule answers both, because
    from the machine's side they are the same fact: no such family here.
    """
    key = str(slot)
    return key if key in available else available[0]


def _step_up_steps(document, role, round_number):
    """How many steps `step_up` takes for this request.

    One step per matching ENTRY — a rule whose role is this one and whose
    `min_round` the request has reached — and not one per round beyond it,
    so a role stuck at round nine climbs no further than at round three
    unless the operator wrote a second entry. Progression is data.
    """
    return sum(1 for rule in document["rules"]
               if rule["type"] == RULE_STEP_UP and rule["role"] == role
               and rule["min_round"] <= round_number)


def _rungs(family, model_rank, effort_rank, steps):
    """The model and effort a seat actually runs at.

    Saturation first: a rank past the end of its ladder is that ladder's
    top, which is how an out-of-range rank answers instead of failing. Then
    `step_up`, one step at a time, on the SATURATED position: effort + 1;
    when effort already stands at the top, the next model at its first
    effort; when both stand at the top, nothing moves. It climbs the ladders
    the operator ordered by capability, so it adds intelligence and never
    cost.
    """
    models, efforts = family["models"], family["efforts"]
    model_at = min(model_rank, len(models)) - 1
    effort_at = min(effort_rank, len(efforts)) - 1
    for _step in range(steps):
        if effort_at + 1 < len(efforts):
            effort_at += 1
        elif model_at + 1 < len(models):
            model_at += 1
            effort_at = 0
        else:
            break
    return models[model_at], efforts[effort_at]


# ---------------------------------------------------------------------------
# The two surfaced conditions


def _seat_families(effective, role, seats):
    """The family each of *seats* actually runs on, collapse included."""
    return [
        effective.document["families"][
            _running_slot(_slot_for(effective.layers, role, index),
                          effective.available)]["name"]
        for index in seats
    ]


def _honours_distinct_families(effective, role):
    """Whether *role*'s own assigned seats can be pairwise-distinct families.

    Judged on the role's OWN seats and on nothing else: a role that declares
    nothing is honoured by definition, one assigned seat is trivially
    honoured — a single-family machine reviews with one family today — and
    no relationship between two different roles is ever checked. Collapse
    happens first, because two seats that collapse onto one slot are one
    family however the document numbered them.
    """
    if not (effective.document["roles"].get(role) or {}).get(
            "distinct_families"):
        return True
    seats = _assigned_seats(effective.layers, role)
    if len(seats) < 2:
        return True
    if not effective.available:
        # Nobody to call at all, so two seats cannot be two families. The
        # resolver never reaches this — `staffing_unavailable` is raised
        # before any seat is resolved — but the projection is a read that
        # answers rather than refuses.
        return False
    families = _seat_families(effective, role, seats)
    return len(set(families)) == len(seats)


def _unavailable(effective):
    return StaffingConditionError(
        STAFFING_UNAVAILABLE,
        "staffing document %r names families %s; this machine has %s"
        % (effective.document["name"],
           ", ".join(sorted({slot["name"]
                             for slot in effective.document["families"]
                             .values()})),
           ", ".join(effective.selection.families) or "none"))


def _unsatisfiable(effective, role):
    seats = _assigned_seats(effective.layers, role)
    return StaffingConditionError(
        DISTINCT_FAMILIES_UNSATISFIABLE,
        "staffing document %r declares distinct_families for %r, whose "
        "seats %s run on %s with the families this machine has (%s)"
        % (effective.document["name"], role,
           ", ".join(str(index) for index in seats),
           ", ".join(_seat_families(effective, role, seats))
           if effective.available else "nothing",
           ", ".join(effective.selection.families) or "none"))


# ---------------------------------------------------------------------------
# One read of a session, shared by the resolver and the three readers


def _effective(home, session, material, families):
    """Read the session and its document once, and layer them.

    The resolver and all three document readers go through here, so a
    seat reader and the dispatch that follows it can never disagree about
    which document is in force — including when it is the fallback's — and
    every seat one reader describes comes from a single reading.
    """
    selection, fell_back = _selection_for(home, session, families)
    document, document_fell_back = _document_for(home, selection.document)
    fell_back = fell_back or document_fell_back
    return _Effective(
        selection=selection,
        document=document,
        layers=_layers(
            document, selection,
            _material_in_force(document, material, selection.material)),
        available=_available_slots(document, selection.families),
        staffing_fallback=(
            STAFFING_FALLBACK_DEFAULT_DOCUMENT if fell_back else None))


# ---------------------------------------------------------------------------
# The question and the answer


def resolve(home, session, role, index=1, round=1, material=None, brief=None,
            families=()):
    """Staff one call: who runs it, on which model, at which effort.

    *session* is a stored session id, *role* one of :data:`ROLES`, *index*
    the 1-based seat of that role and *round* the 1-based round the consumer
    is on — both consumer facts the router keeps no history of. *material*
    and *brief* are optional; *families* are the CALLER'S own configured
    families and are used only when the session cannot be read, since that
    is the one case where the machine's families cannot be read either.

    Returns a :data:`Resolution`: an answer of exactly ``agent``, ``model``
    and ``effort``, plus ``staffing_fallback`` when an input could not be
    read and the default document answered instead.

    It refuses in exactly three ways and no others. An unknown role, a
    non-positive index or round, and a non-string material are INPUT errors
    (:class:`StaffingError`), refused before resolution. `staffing_unavailable`
    and `distinct_families_unsatisfiable` are the two surfaced conditions
    (:class:`StaffingConditionError`, carrying the token). Everything else
    answers: collapse, saturation, an unknown material, an unassigned seat,
    a slot the document does not carry, and an unreadable session or
    document all have an answer rather than a failure.

    `brief` is accepted, read by no rule and never stored. Resolving writes
    nothing at all — no record, no history, no repair of a damaged file.
    """
    role, index, round_number, material = _admit(role, index, round, material)
    effective = _effective(home, session, material, families)
    if not effective.available:
        raise _unavailable(effective)
    if not _honours_distinct_families(effective, role):
        raise _unsatisfiable(effective, role)
    slot = _running_slot(
        _slot_for(effective.layers, role, index), effective.available)
    family = effective.document["families"][slot]
    model_rank, effort_rank = _ranks(
        effective.layers, effective.selection.rigor, slot, role)
    model, effort = _rungs(
        family, model_rank, effort_rank,
        _step_up_steps(effective.document, role, round_number))
    return Resolution(
        answer={"agent": family["name"], "model": model, "effort": effort},
        staffing_fallback=effective.staffing_fallback)


# ---------------------------------------------------------------------------
# Three live document reads over a session
#
# Milestone law decides WHICH seat runs — the review cycle iterates the seats
# the document assigns, walks the family each of them runs on, and surfaces a
# `distinct_families` role it cannot honour — so it needs to read those three
# facts without dispatching. They are document reads over a session, never
# part of an answer: no seat, no cycle and no projection ever appears in a
# `resolve` response.
#
# A read refuses nothing it can answer. `staffing_unavailable` is the one
# exception, and only where it leaves nothing TO answer.


def session_seats(home, session, role, material=None, families=()):
    """A role's assigned seat indices over this session, in index order.

    The layered assignment's own index set — base, the material's override
    and the session's override together — so a seat an override adds is a
    seat the consumer iterates. Reads the same effective document
    :func:`resolve` would, fallback included, so the seats a consumer
    iterates are the seats its dispatches will actually staff.
    """
    if role not in ROLES:
        raise StaffingError(
            "%s: unknown role %s (allowed: %s)"
            % (_REQUEST_CTX, _shown(role), ", ".join(ROLES)))
    effective = _effective(
        home, session, _request_material(material), families)
    return _assigned_seats(effective.layers, role)


def session_seat_families(home, session, role, material=None, families=()):
    """The family each assigned seat of *role* runs on, in index order.

    :func:`session_seats` with each seat's collapse already applied — the
    cycle a consumer walks, described without dispatching anything. Reads
    the same effective document :func:`resolve` would, fallback included,
    and every seat comes from ONE reading of it, so what comes back is
    always a cycle some document assigns and never a list built from two.

    It refuses nothing it can answer. A role whose declared
    `distinct_families` this session cannot honour still HAS a family per
    seat — that list is the very thing the judgement is made on — so this
    read hands it back and leaves `distinct_families_unsatisfiable` to the
    dispatches it affects. `staffing_unavailable` remains, because with no
    family available there is no answer to give: an empty list is not the
    honest substitute, since a consumer reads it as a cycle with no seat
    left rather than as a machine with nobody to call.
    """
    if role not in ROLES:
        raise StaffingError(
            "%s: unknown role %s (allowed: %s)"
            % (_REQUEST_CTX, _shown(role), ", ".join(ROLES)))
    effective = _effective(
        home, session, _request_material(material), families)
    if not effective.available:
        raise _unavailable(effective)
    return _seat_families(
        effective, role, _assigned_seats(effective.layers, role))


def distinct_families_projection(home, session, material=None, families=()):
    """The roles whose declared `distinct_families` this session cannot
    honour, in the role vocabulary's order.

    The same judgement :func:`resolve` refuses each affected dispatch with,
    read ahead of any dispatch — the same check, because the document may
    change live between the two. A read ANSWERS rather than refuses, so a
    machine with no family at all comes back with every declaring role of
    two seats or more rather than with `staffing_unavailable`.
    """
    effective = _effective(
        home, session, _request_material(material), families)
    return [role for role in ROLES
            if not _honours_distinct_families(effective, role)]
