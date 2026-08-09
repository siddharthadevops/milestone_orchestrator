"""Model profiles: named, reusable per-rigor act-staffing catalogues.

Slice 1 of the model-profiles milestone (see
implementation/milestones/model-profiles/skeleton.md). This module owns the
SOURCE catalogue only: the stored document, its validation, whole-document
create/edit, listing, and the missing-only `default` seed. Nothing here
selects a profile for a run, resolves acts, or binds a snapshot — that is
later-slice work; no run consults this store yet.

A model profile is a JSON document under `<home>/model_profiles/<name>.json`
with EXACTLY three keys (closed schema — no version, sealed, description, or
any other metadata):

    {"name": "web-ui",
     "examples": ["public API contract", ...],       # each <= 5 words
     "configurations": {"low": {...}, "medium": {...}, "high": {...}}}

Each rigor value is an act map in the vocabulary the acts channel already
accepts, restricted per act to the fields that act's resolution honors:

- skeletoner / drafter / implementer / fixer / reclassifier: a family-policy
  string ("codex", "claude", "self", "opposite") or a non-empty object with
  only `agent`, `model`, and/or `effort`;
- review_codex / review_claude / brainstorming_counterpart: a non-empty
  object with only `model` and/or `effort` (their family is structurally
  fixed or derived — `agent` is an input error, never a dropped no-op);
- consultation: a family-policy string only (its model and effort are
  derived; carrying them is an input error, unlike the acts channel's
  historical silent acceptance).

An act map may omit acts: an omitted act keeps its existing act-specific
assignment or derivation and then the family default. Every carried value
must be a non-empty string; the store adds no executor-identifier whitelist
stricter than the acts channel's short-string input posture.

Unlike the strategy-profile store, stored corruption is LOUD: listing
validates every candidate and raises on the first invalid one instead of
silently skipping it — a damaged catalogue must never look merely shorter.
Catalogue names are case-insensitively unique: a differently cased spelling
is refused before writing, so the same API semantics are safe on both
case-sensitive and case-insensitive filesystems.
"""

import json
import os

MODEL_PROFILES_DIRNAME = "model_profiles"

RIGORS = ("low", "medium", "high")

# The five acts whose resolution honors a full policy: a family-policy
# string or {agent, model, effort}.
FULL_POLICY_ACTS = (
    "skeletoner", "drafter", "implementer", "fixer", "reclassifier",
)
# Structurally fixed (reviews) or derived (counterpart) families: only
# model/effort are honored, so only they are accepted.
MODEL_EFFORT_ACTS = ("review_codex", "review_claude",
                     "brainstorming_counterpart")
# Consultation derives both model (consulted family's default) and effort
# (the caller's): only the family policy is honored.
FAMILY_ONLY_ACTS = ("consultation",)

PROFILE_ACT_KEYS = FULL_POLICY_ACTS + MODEL_EFFORT_ACTS + FAMILY_ONLY_ACTS

DEFAULT_PROFILE_NAME = "default"

# The acts channel's existing input cap for object fields ("must be a
# short string", service.set_acts) — reused, not tightened.
_MAX_FIELD_LEN = 100


class ModelProfileError(RuntimeError):
    """Invalid model-profile document or unreadable stored definition."""


def model_profiles_dir(home):
    return os.path.join(home, MODEL_PROFILES_DIRNAME)


def _path(home, name):
    return os.path.join(model_profiles_dir(home), "%s.json" % name)


def _field_value(ctx, act, field, value):
    """One carried object field: a non-empty short string, stripped."""
    if not isinstance(value, str) or len(value) > _MAX_FIELD_LEN:
        raise ModelProfileError(
            "%s: act %r field %r must be a short non-empty string"
            % (ctx, act, field))
    value = value.strip()
    if not value:
        raise ModelProfileError(
            "%s: act %r field %r must be a short non-empty string"
            % (ctx, act, field))
    return value


def _validate_entry(ctx, act, value):
    """One act's staffing entry, normalized. Every form outside the act's
    honored surface is an input error — never a dropped or cleared no-op."""
    if act in FAMILY_ONLY_ACTS:
        if not isinstance(value, str) or not value.strip():
            raise ModelProfileError(
                "%s: act %r accepts only a family-policy string (its model "
                "and effort are derived)" % (ctx, act))
        return value.strip()
    if isinstance(value, str):
        if act in MODEL_EFFORT_ACTS:
            raise ModelProfileError(
                "%s: act %r has a fixed or derived family; set a non-empty "
                "object with model and/or effort only" % (ctx, act))
        if not value.strip():
            raise ModelProfileError(
                "%s: act %r family policy must be a non-empty string"
                % (ctx, act))
        return value.strip()
    if not isinstance(value, dict):
        raise ModelProfileError(
            "%s: act %r must be a %s" % (
                ctx, act,
                "non-empty object" if act in MODEL_EFFORT_ACTS
                else "family-policy string or non-empty object"))
    allowed = (("model", "effort") if act in MODEL_EFFORT_ACTS
               else ("agent", "model", "effort"))
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ModelProfileError(
            "%s: act %r field %r is not honored by that act (allowed: %s)"
            % (ctx, act, unknown[0], ", ".join(allowed)))
    if not value:
        raise ModelProfileError(
            "%s: act %r must not be an empty object" % (ctx, act))
    return {field: _field_value(ctx, act, field, value[field])
            for field in allowed if field in value}


def _validate_act_map(ctx, rigor, act_map):
    if not isinstance(act_map, dict):
        raise ModelProfileError(
            "%s: configurations.%s must be an act map object" % (ctx, rigor))
    out = {}
    for act in sorted(act_map):
        if act not in PROFILE_ACT_KEYS:
            raise ModelProfileError(
                "%s: configurations.%s names unknown act %r (allowed: %s)"
                % (ctx, rigor, act, ", ".join(PROFILE_ACT_KEYS)))
        out[act] = _validate_entry(
            "%s: configurations.%s" % (ctx, rigor), act, act_map[act])
    return out


def _validate(doc, ctx):
    """Validate one whole document; returns the normalized copy to store."""
    if not isinstance(doc, dict):
        raise ModelProfileError(
            "%s: model profile document must be an object" % ctx)
    unknown = sorted(set(doc) - {"name", "examples", "configurations"})
    if unknown:
        raise ModelProfileError(
            "%s: unknown key %r — a model profile has exactly name, "
            "examples, and configurations" % (ctx, unknown[0]))
    name = doc.get("name")
    if not name or not isinstance(name, str):
        raise ModelProfileError(
            "%s: model profile needs a non-empty name" % ctx)
    if not all(c.isalnum() or c in "-_" for c in name):
        raise ModelProfileError(
            "%s: model profile name must be alphanumeric/-/_ : %r"
            % (ctx, name))
    examples = doc.get("examples")
    if not isinstance(examples, list) or not examples:
        raise ModelProfileError(
            "%s: examples must be a non-empty array of matching clues" % ctx)
    for item in examples:
        words = item.split() if isinstance(item, str) else ()
        if not words:
            raise ModelProfileError(
                "%s: every example must be a non-empty string" % ctx)
        if len(words) > 5:
            raise ModelProfileError(
                "%s: example %r has more than five words" % (ctx, item))
    configurations = doc.get("configurations")
    if not isinstance(configurations, dict):
        raise ModelProfileError(
            "%s: configurations must be an object with exactly the rigors "
            "%s" % (ctx, ", ".join(RIGORS)))
    missing = [r for r in RIGORS if r not in configurations]
    extra = sorted(set(configurations) - set(RIGORS))
    if missing or extra:
        raise ModelProfileError(
            "%s: configurations must carry exactly the rigors %s (missing: "
            "%s; unknown: %s)"
            % (ctx, ", ".join(RIGORS),
               ", ".join(missing) or "none", ", ".join(extra) or "none"))
    return {
        "name": name,
        "examples": list(examples),
        "configurations": {
            rigor: _validate_act_map(ctx, rigor, configurations[rigor])
            for rigor in RIGORS
        },
    }


def load(home, name):
    """Load and validate one model profile by name. Loud on corruption."""
    path = _path(home, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise ModelProfileError("unknown model profile %r" % name)
    except ValueError as exc:
        raise ModelProfileError(
            "model profile %r is not valid JSON: %s" % (name, exc))
    doc = _validate(doc, "model profile %r" % name)
    if doc["name"] != name:
        raise ModelProfileError(
            "model profile file %r names %r — the stored catalogue is "
            "damaged" % (name, doc["name"]))
    return doc


def list_model_profiles(home):
    """All model profiles, sorted by name.

    Every candidate is loaded AND validated; the first invalid one raises
    instead of being skipped, so a damaged store fails visibly rather than
    presenting a silently shortened catalogue."""
    d = model_profiles_dir(home)
    if not os.path.isdir(d):
        return []
    names = sorted(fn[:-5] for fn in os.listdir(d) if fn.endswith(".json"))
    return [load(home, name) for name in names]


def _case_variant(home, name):
    """Existing differently cased spelling of *name*, if any.

    Names are the operator-facing identity, while filenames are only the
    storage mechanism.  Detect the collision explicitly instead of letting a
    case-insensitive filesystem turn a create into an overwrite.
    """
    folded = name.casefold()
    for filename in os.listdir(model_profiles_dir(home)):
        if not filename.endswith(".json"):
            continue
        stored_name = filename[:-5]
        if stored_name != name and stored_name.casefold() == folded:
            return stored_name
    return None


def save(home, doc):
    """Create or WHOLLY replace one model profile under its name.

    Validation happens before any byte changes; the write is an atomic
    same-directory replacement, so a refused document leaves the prior
    definition untouched."""
    doc = _validate(
        doc,
        "model profile %r" % (doc.get("name")
                              if isinstance(doc, dict) else None))
    os.makedirs(model_profiles_dir(home), exist_ok=True)
    variant = _case_variant(home, doc["name"])
    if variant is not None:
        raise ModelProfileError(
            "model profile %r conflicts with existing catalogue name %r; "
            "names are case-insensitively unique" % (doc["name"], variant))
    path = _path(home, doc["name"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return doc


# ---------------------------------------------------------------------------
# The seeded `default` profile.
#
# Its `medium` configuration mirrors driver.DEFAULT_CONFIG["acts"] (plus
# model_defaults resolution for what those entries leave open) so that
# `default`@medium staffs every act exactly as an unconfigured run does
# today; test_default_medium_matches_current_effective_staffing is the
# drift alarm comparing it against the live defaults.
# `brainstorming_counterpart` is omitted rather than copied: its "opposite"
# policy is the structural derivation the omission already yields, and the
# profile vocabulary rejects the string form for that act. `low` and `high`
# are ordinary editable starting points using only the installed
# model/effort vocabulary — nothing pins their content.

DEFAULT_SEED = {
    "name": DEFAULT_PROFILE_NAME,
    "examples": [
        "any ordinary work",
        "general implementation",
        "unclassified tasks",
    ],
    "configurations": {
        "low": {
            "skeletoner": {"agent": "claude", "model": "claude-sonnet-5",
                           "effort": "medium"},
            "drafter": {"agent": "codex", "effort": "medium"},
            "implementer": {"agent": "claude", "model": "claude-sonnet-5",
                            "effort": "medium"},
            "fixer": {"agent": "codex", "effort": "medium"},
            "review_codex": {"effort": "medium"},
            "review_claude": {"model": "claude-sonnet-5",
                              "effort": "medium"},
            "consultation": "opposite",
            "reclassifier": {"agent": "codex", "effort": "medium"},
        },
        "medium": {
            "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                           "effort": "max"},
            "implementer": {"agent": "claude", "model": "claude-fable-5",
                            "effort": "max"},
            "fixer": "codex",
            "consultation": "opposite",
            "reclassifier": {"agent": "codex", "effort": "xhigh"},
        },
        "high": {
            "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                           "effort": "max"},
            "drafter": {"agent": "codex", "effort": "max"},
            "implementer": {"agent": "claude", "model": "claude-fable-5",
                            "effort": "max"},
            "fixer": {"agent": "codex", "effort": "max"},
            "review_codex": {"effort": "max"},
            "review_claude": {"effort": "max"},
            "consultation": "opposite",
            "reclassifier": {"agent": "codex", "effort": "max"},
        },
    },
}


def ensure_default(home):
    """Ensure a valid `default` model profile exists. Missing-only.

    A missing `default` is written from DEFAULT_SEED. An existing one —
    seeded or operator-edited — is never modified; it is only validated, so
    an invalid stored `default` makes initialization fail loudly instead of
    being silently healed or replaced. Returns True when the seed was
    created."""
    if os.path.exists(_path(home, DEFAULT_PROFILE_NAME)):
        load(home, DEFAULT_PROFILE_NAME)
        return False
    save(home, json.loads(json.dumps(DEFAULT_SEED)))
    return True
