"""Named, editable review-strategy documents and their decision catalogue.

The catalogue is the single source for accepted semantic keys, values, and
support status.  Reserved decisions remain stored content; validation does not
make them operative.

A profile is a JSON document under `<home>/profiles/<name>.json`:

    {"name": "light", "version": 1, "sealed": false,
     "description": "...",
     "profile": { ...semantic content: stages, dials... }}

Identity and run retention:

- The IDENTITY of a profile is the content hash of its CANONICAL
  SEMANTIC CONTENT — the `profile` object only, serialized as canonical
  JSON (sorted keys, no whitespace). `name`, `version`, `description`,
  and legacy `sealed` metadata are outside the hash.
- Reusable definitions remain editable after use. A run resolves one
  complete `{name, version, hash}` plus semantic-content pair and retains
  that pair, so later source edits never re-govern it.
- Legacy `sealed` metadata is accepted on read but has no authority. An
  ordinary save normalizes it away; selecting a profile never mutates the
  reusable source.

The two composable seeds (`strict`, `light`) use the complete eight-decision
catalogue.  Their fixed open-action envelope is structural seed content, not
an operator decision.  The `legacy` seed is an exact compatibility fence and
is never composable.
"""

import hashlib
import json
import os
import tempfile

from . import contracts

PROFILES_DIRNAME = "profiles"

FAMILY_UNTIL_CLEAN = "family_until_clean"
_FIXED_ACTION_SCOPE = "open"

_DECISION_SPECS = (
    ("stages[0].loop", "active", (FAMILY_UNTIL_CLEAN,)),
    ("doc_reclassify_from", "active", contracts.RECLASSIFY_FROM_LEVELS),
    ("impl_reclassify_from", "active", contracts.RECLASSIFY_FROM_LEVELS),
    ("p3_defer_max_risk", "active", contracts.DRIFT_RISK_LEVELS),
    ("p3_reclassify_debt", "active", (False, True)),
    ("doc_register", "active", ("dense", "lay+hard-table")),
    ("fuser_discard", "reserved", ("evidence", "evidence+concur")),
    ("final_open_pass", "reserved", (False, True)),
)
_DECISION_VALUES = {key: values for key, _status, values in _DECISION_SPECS}
_TOP_LEVEL_DECISIONS = {
    key for key in _DECISION_VALUES if "[" not in key
}


class ProfileError(RuntimeError):
    """Invalid profile document or retained identity/content mismatch."""


def profiles_dir(home):
    return os.path.join(home, PROFILES_DIRNAME)


def decision_catalogue():
    """Return the closed composable inventory in its API-ready shape."""
    return [
        {"key": key, "status": status, "values": list(values)}
        for key, status, values in _DECISION_SPECS
    ]


def _canonical_semantic(profile_content):
    return json.dumps(
        profile_content, sort_keys=True, separators=(",", ":")
    )


def semantic_hash(profile_content):
    """Identity hash over the canonical semantic content ONLY."""
    canon = _canonical_semantic(profile_content)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _validate_value(value, key, ctx):
    values = _DECISION_VALUES[key]
    if not any(type(value) is type(candidate) and value == candidate
               for candidate in values):
        raise ProfileError(
            "%s: %s %r is not one of %s"
            % (ctx, key, value, "|".join(map(str, values)))
        )


def _validate_stages(stages, ctx):
    if not isinstance(stages, list) or len(stages) != 1:
        raise ProfileError("%s: stages must contain exactly one stage" % ctx)
    stage = stages[0]
    if not isinstance(stage, dict) or not stage:
        raise ProfileError("%s: stages[0] must be a non-empty object" % ctx)
    unknown = set(stage) - {"loop", "actions"}
    if unknown:
        raise ProfileError(
            "%s: unknown stages[0] decision(s): %s"
            % (ctx, ", ".join(sorted(unknown)))
        )
    if "loop" not in stage:
        raise ProfileError(
            "%s: stages[0] must include the stages[0].loop decision" % ctx
        )
    _validate_value(stage["loop"], "stages[0].loop", ctx)
    if "actions" in stage:
        actions = stage["actions"]
        if not isinstance(actions, list) or len(actions) != 1:
            raise ProfileError(
                "%s: stages[0].actions must contain exactly one action" % ctx
            )
        action = actions[0]
        if not isinstance(action, dict) or set(action) != {"scope"}:
            raise ProfileError(
                "%s: stages[0].actions[0] must contain only scope" % ctx
            )
        if action["scope"] != _FIXED_ACTION_SCOPE:
            raise ProfileError(
                "%s: stages[0].actions[0].scope must be the fixed %r value"
                % (ctx, _FIXED_ACTION_SCOPE)
            )


def _validate_semantic(name, content, ctx):
    if name == "legacy":
        if _canonical_semantic(content) != _canonical_semantic(
            SEEDS["legacy"]["profile"]
        ):
            raise ProfileError(
                "%s: legacy semantic content must match its compatibility fence"
                % ctx
            )
        return
    unknown = set(content) - (_TOP_LEVEL_DECISIONS | {"stages"})
    if unknown:
        raise ProfileError(
            "%s: unknown strategy decision(s): %s"
            % (ctx, ", ".join(sorted(unknown)))
        )
    for key in _TOP_LEVEL_DECISIONS & set(content):
        _validate_value(content[key], key, ctx)
    if "stages" in content:
        _validate_stages(content["stages"], ctx)


def validate_semantic_content(content, name=None, ctx="strategy profile"):
    """Validate semantic content without requiring a catalogue document."""
    if not isinstance(content, dict) or not content:
        raise ProfileError("%s must be a non-empty object" % ctx)
    _validate_semantic(name, content, ctx)
    return content


def _validate(doc, ctx):
    if not isinstance(doc, dict):
        raise ProfileError("%s: profile document must be an object" % ctx)
    name = doc.get("name")
    if not name or not isinstance(name, str):
        raise ProfileError("%s: profile needs a non-empty name" % ctx)
    if not all(c.isalnum() or c in "-_" for c in name):
        raise ProfileError(
            "%s: profile name must be alphanumeric/-/_ : %r" % (ctx, name)
        )
    if name.casefold() == "legacy" and name != "legacy":
        raise ProfileError(
            "%s: the legacy compatibility name must be exactly 'legacy'"
            % ctx
        )
    version = doc.get("version")
    if not isinstance(version, int) or version < 1:
        raise ProfileError("%s: version must be a positive integer" % ctx)
    if not isinstance(doc.get("sealed"), bool):
        raise ProfileError("%s: sealed must be a boolean" % ctx)
    content = doc.get("profile")
    if not isinstance(content, dict) or not content:
        raise ProfileError(
            "%s: profile (the semantic content) must be a non-empty object"
            % ctx
        )
    validate_semantic_content(content, name=name, ctx=ctx)
    return doc


def _path(home, name):
    return os.path.join(profiles_dir(home), "%s.json" % name)


def load(home, name):
    """Load and validate one profile document by name."""
    path = _path(home, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise ProfileError("unknown profile %r" % name)
    except ValueError as exc:
        raise ProfileError("profile %r is not valid JSON: %s" % (name, exc))
    doc = _validate(doc, "profile %r" % name)
    if doc["name"] != name:
        raise ProfileError(
            "profile file %r names %r — the stored catalogue is damaged"
            % (name, doc["name"])
        )
    return doc


def list_profiles(home):
    """All profile documents, sorted by name; invalid content fails loudly."""
    d = profiles_dir(home)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        out.append(load(home, fn[:-5]))
    return out


def _existing_profile_name(home, name):
    """Return the stored spelling addressed by ``name``, if any."""
    directory = profiles_dir(home)
    requested = "%s.json" % name
    filenames = os.listdir(directory)
    if requested in filenames:
        return name
    target = _path(home, name)
    for filename in filenames:
        if not filename.endswith(".json"):
            continue
        try:
            if os.path.samefile(os.path.join(directory, filename), target):
                return filename[:-5]
        except FileNotFoundError:
            continue
    return None


def save(home, doc):
    """Create or wholly replace an editable profile document.

    The legacy ``sealed`` member remains accepted for stored-file
    compatibility but never blocks an edit and is normalized to false by an
    ordinary save.
    """
    doc = dict(_validate(
        doc,
        "profile %r" % (doc.get("name") if isinstance(doc, dict) else None),
    ))
    doc["sealed"] = False
    os.makedirs(profiles_dir(home), exist_ok=True)
    path = _path(home, doc["name"])
    fd, tmp = tempfile.mkstemp(
        prefix=".strategy-profile-", suffix=".tmp", dir=profiles_dir(home)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
        try:
            # Claim a new path with the complete staged document. This also
            # exposes a case-only alias before it can overwrite another entry.
            os.link(tmp, path)
        except FileExistsError:
            existing_name = _existing_profile_name(home, doc["name"])
            if existing_name != doc["name"]:
                if existing_name is None:
                    raise ProfileError(
                        "profile %r target changed during save" % doc["name"]
                    )
                raise ProfileError(
                    "profile %r conflicts with existing catalogue name %r"
                    % (doc["name"], existing_name)
                )
            os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return doc


def resolve(home, name):
    """Resolve one self-consistent retained identity/content pair.

    ``load`` observes one complete file replacement. Both the identity and
    the detached semantic content are derived from that single document, so
    a concurrent catalogue edit may win before or after this read but cannot
    mix the two definitions.
    """
    doc = load(home, name)
    content = json.loads(json.dumps(doc["profile"]))
    ref = {
        "name": doc["name"],
        "version": doc["version"],
        "hash": semantic_hash(content),
    }
    return ref, content


def reference(home, name):
    """Return the current identity without mutating the reusable source."""
    ref, _content = resolve(home, name)
    return ref


def verify_retained(ref, content):
    """Validate one retained pair without consulting mutable catalogue data."""
    if not isinstance(ref, dict) or not isinstance(content, dict) or not content:
        raise ProfileError("retained profile needs identity and content objects")
    if not isinstance(ref.get("name"), str) or not ref["name"]:
        raise ProfileError("retained profile identity needs a name")
    if not isinstance(ref.get("version"), int) or ref["version"] < 1:
        raise ProfileError("retained profile identity needs a valid version")
    actual = semantic_hash(content)
    if actual != ref.get("hash"):
        raise ProfileError(
            "retained profile %r content hash %s does not match identity %s"
            % (ref["name"], actual, ref.get("hash"))
        )
    return True


# ---------------------------------------------------------------------------
# Seed profiles (spec decision 5: two hardcoded seeds; the constructor UI
# lands in a later phase over this same store).

SEEDS = {
    "strict": {
        "name": "strict",
        "version": 1,
        "sealed": False,
        "description": (
            "Cost-of-being-wrong: high (storage/contract work; the canon "
            "itself). Documentation classifies from P2, implementation from "
            "P1, and only low-rated findings defer; dense contract register. "
            "Reserved fuser-discard and final-pass choices are retained but "
            "non-operative."
        ),
        "profile": {
            "doc_reclassify_from": "P2",
            "impl_reclassify_from": "P1",
            "p3_defer_max_risk": "low",
            "p3_reclassify_debt": True,
            "doc_register": "dense",
            "fuser_discard": "evidence+concur",
            "final_open_pass": True,
            "stages": [
                {"loop": "family_until_clean",
                 "actions": [{"scope": "open"}]},
            ],
        },
    },
    "light": {
        "name": "light",
        "version": 1,
        "sealed": False,
        "description": (
            "Cost-of-being-wrong: low (UI shell work). Findings rated "
            "at-or-below medium record as debt; documentation classifies "
            "from P2 and implementation from P1; lay register + hard table. "
            "Reserved fuser-discard and final-pass choices are retained but "
            "non-operative."
        ),
        "profile": {
            "doc_reclassify_from": "P2",
            "impl_reclassify_from": "P1",
            "p3_defer_max_risk": "medium",
            "p3_reclassify_debt": True,
            "doc_register": "lay+hard-table",
            "fuser_discard": "evidence",
            "final_open_pass": False,
            "stages": [
                {"loop": "family_until_clean",
                 "actions": [{"scope": "open"}]},
            ],
        },
    },
    # The fenced compatibility artifact carries the pre-reform prompt and
    # interpretation posture. Runtime topology is universal: it uses the same
    # deterministic review-derived seal as every other profile.
    "legacy": {
        "name": "legacy",
        "version": 1,
        "sealed": False,
        "description": (
            "Compatibility posture for pre-reform prompts and review "
            "interpretation. It still uses the universal deterministic "
            "seal derived from current clean reviews; excluded from the "
            "reform constitution and never composable into new profiles."
        ),
        "profile": {
            "compat": True,
            "stages": [
                {"loop": "family_until_clean",
                 "actions": [{"scope": "open"}]},
            ],
        },
    },
}


def ensure_seeds(home):
    """Write any missing seed profile. Existing files are never touched
    (a seeded profile the operator edited stays as-is)."""
    created = []
    for name, doc in SEEDS.items():
        if not os.path.exists(_path(home, name)):
            save(home, json.loads(json.dumps(doc)))
            created.append(name)
    return created
