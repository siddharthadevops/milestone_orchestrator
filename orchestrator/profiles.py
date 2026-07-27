"""Strategy profiles: named, sealed, reusable review-strategy documents.

Phase 1 of the build-driven review reform (see
implementation/brainstorming/build-driven-review-and-strategy-profiles.md).
This module is deliberately INERT for existing runs: nothing reads a
profile unless a run was created with one.

A profile is a JSON document under `<home>/profiles/<name>.json`:

    {"name": "light", "version": 1, "sealed": false,
     "description": "...",
     "profile": { ...semantic content: stages, dials... }}

Identity and sealing (the spec's decision 15, hash-vs-seal corrected):

- The IDENTITY of a profile is the content hash of its CANONICAL
  SEMANTIC CONTENT — the `profile` object only, serialized as canonical
  JSON (sorted keys, no whitespace). `name`, `version`, `description`,
  and `sealed` are METADATA outside the hash: sealing flips metadata
  and never changes identity.
- A profile SEALS on first production use (a run created with it). A
  sealed profile is immutable: saving over it with different semantic
  content is refused — editing means CLONING to a new name@version.
- Runs snapshot `{name, version, hash}` into their config at creation;
  loaders verify the stored hash against the file and fail loudly on
  divergence (a hand-mutated sealed profile cannot silently govern).

The two SEED profiles (`strict`, `light`) express today's flow plus the
reform's first dials. Their stage vocabulary is interpreted by later
phases; unknown fields are carried, not validated, so seeds can name
machinery that lands in phase 2+ without breaking phase 1.
"""

import hashlib
import json
import os

PROFILES_DIRNAME = "profiles"

# Ordered drift-risk scale lives in contracts; profiles reference it by
# value only, so no import cycle.
_RISK_LEVELS = ("low", "medium", "high", "xhigh")


class ProfileError(RuntimeError):
    """Invalid profile document, identity mismatch, or sealed-mutation."""


def profiles_dir(home):
    return os.path.join(home, PROFILES_DIRNAME)


def semantic_hash(profile_content):
    """Identity hash over the canonical semantic content ONLY."""
    canon = json.dumps(
        profile_content, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


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
    thr = content.get("p3_defer_max_risk")
    if thr is not None and thr not in _RISK_LEVELS:
        raise ProfileError(
            "%s: p3_defer_max_risk %r not in %s"
            % (ctx, thr, "|".join(_RISK_LEVELS))
        )
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
    return _validate(doc, "profile %r" % name)


def list_profiles(home):
    """All profile documents, sorted by name; unreadable files skipped."""
    d = profiles_dir(home)
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        try:
            out.append(load(home, fn[:-5]))
        except ProfileError:
            continue
    return out


def save(home, doc):
    """Create or update a profile document.

    A SEALED profile's semantic content is immutable: overwriting is
    allowed only when the semantic hash is unchanged (metadata edits —
    e.g. description — stay legal). Changing sealed content requires
    clone()."""
    doc = _validate(doc, "profile %r" % (doc.get("name") if isinstance(doc, dict) else None))
    path = _path(home, doc["name"])
    if os.path.exists(path):
        existing = load(home, doc["name"])
        if existing["sealed"]:
            if semantic_hash(existing["profile"]) != semantic_hash(doc["profile"]):
                raise ProfileError(
                    "profile %r is sealed; its semantic content is "
                    "immutable — clone it to a new name/version instead"
                    % doc["name"]
                )
            doc = dict(doc, sealed=True)  # a seal is never un-flipped
    os.makedirs(profiles_dir(home), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return doc


def clone(home, name, new_name):
    """Copy a profile's semantic content to a new UNSEALED document."""
    src = load(home, name)
    if os.path.exists(_path(home, new_name)):
        raise ProfileError("profile %r already exists" % new_name)
    doc = {
        "name": new_name,
        "version": 1,
        "sealed": False,
        "description": "cloned from %s@%s (%s)" % (
            src["name"], src["version"], semantic_hash(src["profile"])
        ),
        "profile": json.loads(json.dumps(src["profile"])),
    }
    return save(home, doc)


def seal(home, name):
    """Seal a profile (first production use does this). Idempotent."""
    doc = load(home, name)
    if not doc["sealed"]:
        doc["sealed"] = True
        path = _path(home, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    return doc


def reference(home, name):
    """The snapshot a run stores at creation: {name, version, hash}.
    SEALS the profile — a referenced profile is in production."""
    doc = seal(home, name)
    return {
        "name": doc["name"],
        "version": doc["version"],
        "hash": semantic_hash(doc["profile"]),
    }


def verify_reference(home, ref):
    """Check a run's stored profile reference against the file on disk.
    Returns the profile document; raises ProfileError on divergence."""
    doc = load(home, ref["name"])
    actual = semantic_hash(doc["profile"])
    if actual != ref.get("hash"):
        raise ProfileError(
            "profile %r on disk (hash %s) no longer matches the run's "
            "snapshot (hash %s) — a sealed profile was mutated by hand"
            % (ref["name"], actual, ref.get("hash"))
        )
    return doc


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
            "itself). Every finding opens a fix cycle; dense contract "
            "register; fuser discards need evidence + opposite-family "
            "concur."
        ),
        "profile": {
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
            "at-or-below medium record as debt; lay register + hard "
            "table; fuser discards need citing evidence."
        ),
        "profile": {
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
    (a seeded profile the operator edited or sealed stays as-is)."""
    created = []
    for name, doc in SEEDS.items():
        if not os.path.exists(_path(home, name)):
            save(home, json.loads(json.dumps(doc)))
            created.append(name)
    return created
