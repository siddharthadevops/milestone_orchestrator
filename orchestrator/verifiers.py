"""Closed verifier vocabulary and project contract-extension merge.

Slice 4 of the project concept: turns a Slice-3-validated safeguard policy
(projects.validate_policy_value) into an enforceable contract EXTENSION and
validates worker output against the base kind contract PLUS the in-scope
extensions, inside the existing repair-retry path (runners.call_worker).

Two closed vocabularies — extending either is an orchestrator milestone,
never project config (no code, shell, regex, or callable can be injected):

- entry type-specs: {"type": "string"} · {"type": "citation"} ·
  {"enum": [<strings>]} (non-empty list). Value matching is TYPE-EXACT: a
  bool/int/float/list/object/null never satisfies a string/citation spec
  and never matches an enum member by truthiness.
- checks: non_empty(field) · enum(field, values) · path_exists(field) ·
  citation_exists(field) · dir_listing_matches(root, match_field). Each
  quantifies over the entries of the extension field; filesystem checks
  resolve paths through kvstore.path_is_inside_roots against the granted
  work-area roots.

Error split (who must act, not who was talking):

- contracts.ContractError — the WORKER authored the violation (missing or
  malformed extension field, failed check, escaping or ambiguous citation).
  Raised at the same point as the base validation, so call_worker's single
  repair retry applies unchanged.
- PolicyConfigError — the OPERATOR's policy is outside the closed
  vocabulary or inconsistent (reserved-key collision, duplicate fields,
  escaping/ambiguous dir_listing_matches root).
- OperationalError — the ENVIRONMENT cannot satisfy a check (the
  dir_listing_matches root is absent or not a directory).

PolicyConfigError and OperationalError share the VerifierError base, which
is deliberately NOT a ValueError/ContractError: they are outside
call_worker's repairable exception family and surface to the operator
without burning a worker repair retry.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from orchestrator import contracts
from orchestrator import kvstore
from orchestrator import projects


class VerifierError(RuntimeError):
    """Non-repairable extension fault: never the worker's doing, never part
    of call_worker's repairable exception family (hence RuntimeError, not
    ValueError)."""


class PolicyConfigError(VerifierError):
    """The operator's policy is outside the closed vocabulary or
    inconsistent with the base contract / granted roots."""


class OperationalError(VerifierError):
    """The environment cannot satisfy an operator-declared check (e.g. a
    missing reuse-source directory) — no worker output can repair it."""


@dataclass(frozen=True)
class CompiledExtension:
    """An enforceable extension compiled from a Slice-3-validated policy:
    the required output field, the per-entry type-specs, and the checks —
    all vocabulary-legal."""

    policy_id: str
    policy_version: int
    field: str
    entry: dict
    checks: tuple


# ---------------------------------------------------------------------------
# Policy compile (config-error class; vocabulary legality Slice 3 deferred)

_TYPE_SPEC_TYPES = ("string", "citation")

# Exact parameter set per check kind (beyond "kind" itself). The whole V1
# vocabulary; a new kind is an orchestrator milestone, never project config.
_CHECK_PARAMS = {
    "non_empty": frozenset({"field"}),
    "enum": frozenset({"field", "values"}),
    "path_exists": frozenset({"field"}),
    "citation_exists": frozenset({"field"}),
    "dir_listing_matches": frozenset({"root", "match_field"}),
}


def _require_enum_values(values, ctx):
    if not isinstance(values, list) or not values:
        raise PolicyConfigError(
            "%s: enum values must be a non-empty list of strings" % ctx
        )
    for v in values:
        if type(v) is not str:
            raise PolicyConfigError(
                "%s: enum values must be a non-empty list of strings, "
                "got member %r" % (ctx, v)
            )


def _compile_type_spec(spec, ctx):
    keys = set(spec)
    if keys == {"type"}:
        if spec["type"] in _TYPE_SPEC_TYPES:
            return
        raise PolicyConfigError(
            "%s: unknown type %r (closed set: 'string', 'citation')"
            % (ctx, spec["type"])
        )
    if keys == {"enum"}:
        _require_enum_values(spec["enum"], ctx)
        return
    raise PolicyConfigError(
        "%s: a type-spec is exactly {'type': 'string'|'citation'} or "
        "{'enum': [...]} — got keys %s" % (ctx, sorted(keys, key=str))
    )


def _compile_check(check, entry, ctx):
    kind = check["kind"]
    if kind not in _CHECK_PARAMS:
        raise PolicyConfigError(
            "%s: unknown check kind %r (closed vocabulary: %s)"
            % (ctx, kind, ", ".join(sorted(_CHECK_PARAMS)))
        )
    params = set(check) - {"kind"}
    if params != _CHECK_PARAMS[kind]:
        raise PolicyConfigError(
            "%s: check %r takes exactly parameters %s, got %s"
            % (ctx, kind, sorted(_CHECK_PARAMS[kind]),
               sorted(params, key=str))
        )
    for param in ("field", "match_field"):
        if param in _CHECK_PARAMS[kind]:
            name = check[param]
            if not isinstance(name, str) or name not in entry:
                raise PolicyConfigError(
                    "%s: check %r %s %r does not name a declared entry field"
                    % (ctx, kind, param, name)
                )
    if kind == "enum":
        _require_enum_values(check["values"], "%s: check 'enum'" % ctx)
    if kind == "dir_listing_matches":
        root = check["root"]
        if type(root) is not str or not root.strip():
            raise PolicyConfigError(
                "%s: check 'dir_listing_matches' root must be a non-empty "
                "string" % ctx
            )
    return dict(check)


def compile_policy(policy):
    """Compile one Slice-3-shaped policy into a CompiledExtension.

    Runs the vocabulary legality Slice 3 deferred here (entry type-specs,
    check kinds/parameters) plus the reserved-key collision rule. Any
    violation is a PolicyConfigError — the operator's mistake, never sent
    to a worker as a repair prompt.
    """
    try:
        policy = projects.validate_policy_value(policy)
    except projects.PolicyValidationError as exc:
        raise PolicyConfigError(
            "policy is not a valid policy value: %s" % exc.reason
        ) from exc
    ctx = "policy %r" % policy["id"]
    contract = policy["contract"]
    entry = contract["entry"]
    for name in entry:
        _compile_type_spec(entry[name], "%s: entry field %r" % (ctx, name))
    checks = tuple(
        _compile_check(check, entry, ctx) for check in contract["checks"]
    )
    field = contract["field"]
    # Reserved names come from contracts (the protocol's single source),
    # never from a list kept here.
    for kind in policy["scope"]["kinds"]:
        if field in contracts.reserved_output_keys(kind):
            raise PolicyConfigError(
                "%s: contract field %r collides with a reserved output key "
                "of worker kind %r" % (ctx, field, kind)
            )
    return CompiledExtension(
        policy_id=policy["id"],
        policy_version=policy["version"],
        field=field,
        entry=entry,
        checks=checks,
    )


def _require_distinct_fields(extensions):
    seen = {}
    for ext in extensions:
        if ext.field in seen:
            raise PolicyConfigError(
                "policies %r and %r both declare contract field %r: the "
                "merge is ambiguous" % (seen[ext.field], ext.policy_id,
                                        ext.field)
            )
        seen[ext.field] = ext.policy_id


def compile_extensions(policies):
    """Compile a caller-selected in-scope policy set; two extensions
    sharing a field make the merge ambiguous (config error)."""
    extensions = [compile_policy(policy) for policy in policies]
    _require_distinct_fields(extensions)
    return extensions


# ---------------------------------------------------------------------------
# Citation shape (structural; existence is citation_exists' job)


def _parse_citation(value):
    """The path half of a `<path>:<line>` citation, or None when ill-shaped:
    split on the LAST colon, non-empty path half, line half a positive
    integer (ASCII digits only — no sign, spaces, or unicode digits)."""
    if type(value) is not str or ":" not in value:
        return None
    path_half, line_half = value.rsplit(":", 1)
    if not path_half or not line_half:
        return None
    if any(ch not in "0123456789" for ch in line_half):
        return None
    if int(line_half) == 0:
        return None
    return path_half


# ---------------------------------------------------------------------------
# Path resolution against the granted work-area roots

_RESOLVED = "resolved"
_MISSING = "missing"
_ESCAPES = "escapes"
_AMBIGUOUS = "ambiguous"


def _resolve_against_roots(value, roots):
    """Deterministic multi-root resolution over path_is_inside_roots.

    Absolute paths are evaluated as written. A relative path must be
    unambiguous: exactly one granted root may contain an EXISTING target at
    that relative path. Returns (status, resolved_realpath_or_None) with
    status one of _RESOLVED / _MISSING (contained but no existing target) /
    _ESCAPES (outside every granted root) / _AMBIGUOUS.
    """
    roots = [r for r in (roots or []) if isinstance(r, str)]
    if os.path.isabs(value):
        if not kvstore.path_is_inside_roots(value, roots):
            return _ESCAPES, None
        real = os.path.realpath(value)
        if os.path.exists(real):
            return _RESOLVED, real
        return _MISSING, None
    candidates = set()
    for root in roots:
        if not os.path.isabs(root):
            continue
        candidate = os.path.realpath(
            os.path.join(os.path.realpath(root), value)
        )
        if not kvstore.path_is_inside_roots(candidate, [root]):
            continue
        if os.path.exists(candidate):
            candidates.add(candidate)
    if len(candidates) > 1:
        return _AMBIGUOUS, None
    if candidates:
        return _RESOLVED, candidates.pop()
    if kvstore.path_is_inside_roots(value, roots):
        return _MISSING, None
    return _ESCAPES, None


# ---------------------------------------------------------------------------
# Worker-side validation: entry shape, then checks


def _validate_entry_value(spec, value, ctx):
    if "type" in spec:
        if spec["type"] == "string":
            if type(value) is not str:
                raise contracts.ContractError(
                    "%s: must be a string, got %s"
                    % (ctx, type(value).__name__)
                )
            return
        # citation — the only other type token the compiler admits.
        if _parse_citation(value) is None:
            raise contracts.ContractError(
                "%s: must be a '<path>:<line>' citation with a positive "
                "integer line, got %r" % (ctx, value)
            )
        return
    if type(value) is not str or value not in spec["enum"]:
        raise contracts.ContractError(
            "%s: must be one of %s, got %r" % (ctx, spec["enum"], value)
        )


def _validate_extension_shape(obj, ext, ctx):
    """Presence and per-entry shape of the extension field on an ok output;
    returns the entry list."""
    fctx = "%s.%s" % (ctx, ext.field)
    if ext.field not in obj:
        raise contracts.ContractError(
            "%s: missing required project-contract field %r (policy %s v%d):"
            " provide a list of entry objects, each with exactly the fields "
            "%s" % (ctx, ext.field, ext.policy_id, ext.policy_version,
                    sorted(ext.entry))
        )
    value = obj[ext.field]
    if not isinstance(value, list):
        raise contracts.ContractError(
            "%s: must be a list of entry objects, got %s"
            % (fctx, type(value).__name__)
        )
    declared = set(ext.entry)
    for i, item in enumerate(value):
        ictx = "%s[%d]" % (fctx, i)
        if not isinstance(item, dict):
            raise contracts.ContractError("%s: entry must be an object" % ictx)
        if set(item) != declared:
            raise contracts.ContractError(
                "%s: entry keys must be exactly %s, got %s"
                % (ictx, sorted(declared), sorted(item, key=str))
            )
        for name in ext.entry:
            _validate_entry_value(
                ext.entry[name], item[name], "%s.%s" % (ictx, name)
            )
    return value


def _require_existing_path(value, roots, ctx, check_name):
    """Worker-authored path/citation containment: every failure here is the
    worker's to repair (ContractError), including root escapes — an audit
    must never 'prove' reuse against a file the run was not granted."""
    status, _ = _resolve_against_roots(value, roots)
    if status == _RESOLVED:
        return
    reasons = {
        _MISSING: "no such path under the granted work-area roots",
        _ESCAPES: "the path escapes every granted work-area root",
        _AMBIGUOUS: "the relative path exists under more than one granted "
                    "root — cite it unambiguously",
    }
    raise contracts.ContractError(
        "%s: check %s failed for %r: %s"
        % (ctx, check_name, value, reasons[status])
    )


def _resolve_dir_listing_root(check, ext, roots):
    root = check["root"]
    status, resolved = _resolve_against_roots(root, roots)
    # The root is operator-authored: escape/ambiguity is the policy's
    # mistake (config), a missing or non-directory target is the
    # environment's (operational) — never the worker's.
    if status == _ESCAPES:
        raise PolicyConfigError(
            "policy %r: dir_listing_matches root %r resolves outside every "
            "granted work-area root" % (ext.policy_id, root)
        )
    if status == _AMBIGUOUS:
        raise PolicyConfigError(
            "policy %r: dir_listing_matches root %r exists under more than "
            "one granted work-area root" % (ext.policy_id, root)
        )
    if status == _MISSING:
        raise OperationalError(
            "policy %r: dir_listing_matches root %r does not exist under "
            "the granted work-area roots (missing reuse-source directory?)"
            % (ext.policy_id, root)
        )
    if not os.path.isdir(resolved):
        raise OperationalError(
            "policy %r: dir_listing_matches root %r is not a directory"
            % (ext.policy_id, root)
        )
    return resolved


def _preflight_operator_roots(extensions, roots):
    """Validate operator-authored filesystem inputs before ok-output shape.

    A bad dir_listing_matches root cannot be repaired by changing the
    extension field's value, so it must not be hidden behind a worker
    ContractError that would trigger the repair retry. A valid blocked
    output has already returned before this preflight: blocked remains
    exempt from project-extension enforcement.
    """
    for ext in extensions:
        for check in ext.checks:
            if check["kind"] == "dir_listing_matches":
                _resolve_dir_listing_root(check, ext, roots)


def _run_dir_listing_matches(check, entries, ext, roots, fctx):
    root = check["root"]
    match_field = check["match_field"]
    resolved = _resolve_dir_listing_root(check, ext, roots)
    listing = set(os.listdir(resolved))
    enumerated = {entry[match_field] for entry in entries}
    if enumerated == listing:
        return
    missing = sorted(listing - enumerated)
    invented = sorted(enumerated - listing, key=str)
    raise contracts.ContractError(
        "%s: check dir_listing_matches failed against %r: the %r values "
        "must equal the directory's immediate children exactly; missing "
        "from your enumeration: %s; not present in the directory: %s"
        % (fctx, root, match_field, missing or "(none)", invented or "(none)")
    )


def _run_check(check, entries, ext, roots, ctx):
    kind = check["kind"]
    fctx = "%s.%s" % (ctx, ext.field)
    if kind == "non_empty":
        field = check["field"]
        if not entries:
            raise contracts.ContractError(
                "%s: check non_empty(%s) failed: the list is empty — "
                "enumerate at least one entry" % (fctx, field)
            )
        for i, entry in enumerate(entries):
            value = entry[field]
            if type(value) is not str or not value.strip():
                raise contracts.ContractError(
                    "%s[%d].%s: check non_empty failed: must be a non-blank "
                    "string, got %r" % (fctx, i, field, value)
                )
    elif kind == "enum":
        field = check["field"]
        values = check["values"]
        for i, entry in enumerate(entries):
            value = entry[field]
            if type(value) is not str or value not in values:
                raise contracts.ContractError(
                    "%s[%d].%s: check enum failed: %r is not one of %s"
                    % (fctx, i, field, value, values)
                )
    elif kind == "path_exists":
        field = check["field"]
        for i, entry in enumerate(entries):
            _require_existing_path(
                entry[field], roots, "%s[%d].%s" % (fctx, i, field),
                "path_exists",
            )
    elif kind == "citation_exists":
        field = check["field"]
        for i, entry in enumerate(entries):
            value = entry[field]
            path_half = _parse_citation(value)
            if path_half is None:
                raise contracts.ContractError(
                    "%s[%d].%s: check citation_exists failed: %r is not a "
                    "'<path>:<line>' citation" % (fctx, i, field, value)
                )
            # Only the path half is verified; the LINE is not checked
            # against the file's length (a moved line stays citable).
            _require_existing_path(
                path_half, roots, "%s[%d].%s" % (fctx, i, field),
                "citation_exists",
            )
    else:
        # dir_listing_matches — the compiler admits no other kind.
        _run_dir_listing_matches(check, entries, ext, roots, fctx)


def validate_merged_output(obj, kind, extensions, roots,
                           require_plain=False, battery_questions=None,
                           require_drift_damage=False):
    """Validate a worker output against the base kind contract PLUS the
    in-scope compiled extensions.

    Returns the object unchanged on success. Worker-authored violations
    raise contracts.ContractError at the same point as the base validation,
    so call_worker's single repair retry applies unchanged. A validly
    blocked output is exempt from extension enforcement (it produced no
    artifact to audit); with no extensions the validation is exactly the
    base one. require_plain/battery_questions (the reform's plain/example
    hard-require and question battery) ride through to every base
    validation call — including the blocked early path, harmless there,
    keeping one shape.
    """
    extensions = list(extensions or [])
    # Output-independent config sanity first: a broken merge is the
    # operator's fault and must not depend on what the worker said.
    for ext in extensions:
        if not isinstance(ext, CompiledExtension):
            raise PolicyConfigError(
                "extensions must be CompiledExtension objects (use "
                "compile_policy/compile_extensions), got %s"
                % type(ext).__name__
            )
    _require_distinct_fields(extensions)
    if isinstance(obj, dict) and obj.get("status") == "blocked":
        contracts.validate_worker_output(
            obj, kind, require_plain=require_plain,
            battery_questions=battery_questions,
            require_drift_damage=require_drift_damage,
        )
        return obj
    if extensions:
        _preflight_operator_roots(extensions, roots)
    contracts.validate_worker_output(
        obj, kind, require_plain=require_plain,
        battery_questions=battery_questions,
        require_drift_damage=require_drift_damage,
    )
    if not extensions:
        return obj
    ctx = "worker[%s]" % kind
    for ext in extensions:
        entries = _validate_extension_shape(obj, ext, ctx)
        for check in ext.checks:
            _run_check(check, entries, ext, roots, ctx)
    return obj
