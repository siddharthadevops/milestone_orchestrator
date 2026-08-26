"""Project records and project safeguard policy configuration.

Slice 3 stays purely in the configuration model: it stores versioned policy
objects, matches scopes, and assembles the project read model from already
sealed work-area storage.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from orchestrator import contracts
from orchestrator import kvstore
from orchestrator import state
from orchestrator import workareas


POLICY_KEYS = {"id", "version", "enabled", "scope", "prompt", "contract"}
SCOPE_KEYS = {"kinds", "unit_kinds"}
CONTRACT_KEYS = {"field", "required", "entry", "checks"}

UNIT_KINDS = (
    state.UNIT_SKELETON,
    state.UNIT_SLICE_DOC,
    state.UNIT_SLICE_IMPL,
)

UNKNOWN = "unknown_policy"
MALFORMED = "malformed_policy"
INVALID_POLICY = "invalid_policy"
INVALID_DEFAULTS = "invalid_defaults"
RETIRED_SCOPE_KINDS = frozenset({"seal_half"})
POLICY_SCOPE_KINDS = frozenset(
    contracts.KINDS + (
        contracts.KIND_MERGE_REPAIR,
        contracts.KIND_SUITE_CHECKPOINT,
    )
)


@dataclass(frozen=True)
class ProjectResult:
    ok: bool
    value: object = None
    reason: str | None = None


class PolicyValidationError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _ok(value=None):
    return ProjectResult(True, value=value)


def _err(reason):
    return ProjectResult(False, reason=reason)


def _raise(reason):
    raise PolicyValidationError(reason)


def _is_bool(value):
    return type(value) is bool


def _is_positive_int(value):
    return type(value) is int and value > 0


def _non_blank_string(value):
    return isinstance(value, str) and value.strip() != ""


def _validate_policy_id(policy_id):
    try:
        return kvstore.validate_fragment(policy_id, "id")
    except ValueError as exc:
        raise PolicyValidationError(INVALID_POLICY) from exc


def _validate_scope(scope, allow_retired=False):
    if not isinstance(scope, dict) or set(scope) != SCOPE_KEYS:
        _raise(MALFORMED)
    kinds = scope["kinds"]
    unit_kinds = scope["unit_kinds"]
    if not isinstance(kinds, list) or not kinds:
        _raise(MALFORMED)
    if not isinstance(unit_kinds, list) or not unit_kinds:
        _raise(MALFORMED)
    allowed = set(POLICY_SCOPE_KINDS)
    if allow_retired:
        allowed.update(RETIRED_SCOPE_KINDS)
    if any(kind not in allowed for kind in kinds):
        _raise(MALFORMED)
    if any(unit_kind not in UNIT_KINDS for unit_kind in unit_kinds):
        _raise(MALFORMED)
    return {
        # Read migration only: old stored policies may name the retired seal
        # worker. Drop that inert scope entry without re-advertising it or
        # accepting it on new writes.
        "kinds": [kind for kind in kinds if kind not in RETIRED_SCOPE_KINDS],
        "unit_kinds": list(unit_kinds),
    }


def _validate_contract(contract):
    if not isinstance(contract, dict) or set(contract) != CONTRACT_KEYS:
        _raise(MALFORMED)
    field = contract["field"]
    if not _non_blank_string(field):
        _raise(MALFORMED)
    if contract["required"] is not True:
        _raise(MALFORMED)
    entry = contract["entry"]
    if not isinstance(entry, dict) or not entry:
        _raise(MALFORMED)
    normalized_entry = {}
    for key, spec in entry.items():
        if not isinstance(key, str) or not isinstance(spec, dict):
            _raise(MALFORMED)
        normalized_entry[key] = dict(spec)
    checks = contract["checks"]
    if not isinstance(checks, list):
        _raise(MALFORMED)
    normalized_checks = []
    for check in checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("kind"), str)
        ):
            _raise(MALFORMED)
        normalized_checks.append(dict(check))
    return {
        "field": field,
        "required": True,
        "entry": normalized_entry,
        "checks": normalized_checks,
    }


def validate_policy_value(policy, policy_id=None, allow_retired=False):
    """Return a serialization-stable policy value or raise.

    ``policy_id`` is the id derived from the ``policy:<id>`` key when reading.
    """
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        _raise(MALFORMED)
    raw_id = policy["id"]
    validated_id = _validate_policy_id(raw_id)
    if policy_id is not None and validated_id != policy_id:
        _raise(MALFORMED)
    if not _is_positive_int(policy["version"]):
        _raise(MALFORMED)
    if not _is_bool(policy["enabled"]):
        _raise(MALFORMED)
    if not _non_blank_string(policy["prompt"]):
        _raise(MALFORMED)

    normalized = {
        "id": validated_id,
        "version": policy["version"],
        "enabled": policy["enabled"],
        "scope": _validate_scope(
            policy["scope"], allow_retired=allow_retired
        ),
        "prompt": policy["prompt"],
        "contract": _validate_contract(policy["contract"]),
    }
    try:
        return kvstore.canonical_json_value(normalized)
    except ValueError as exc:
        raise PolicyValidationError(MALFORMED) from exc


def policy_matches(policy, worker_kind, unit_kind):
    return (
        policy.get("enabled") is True
        and worker_kind in policy.get("scope", {}).get("kinds", [])
        and unit_kind in policy.get("scope", {}).get("unit_kinds", [])
    )


class PolicyStore:
    """Project-bound store for enveloped ``policy:<id>`` entries."""

    def __init__(self, directory, project, namespace=kvstore.DEFAULT_NAMESPACE):
        self.project = workareas.validate_project_slug(project)
        self.directory = os.path.join(os.path.abspath(directory), self.project)
        self.keys = kvstore.KeyBuilder(namespace=namespace)
        self.client = kvstore.LocalKVClient(self.directory)
        self.envelopes = kvstore.RevisionEnvelopeStore(self.client)

    def put(self, policy):
        value = validate_policy_value(policy)
        return self.envelopes.put(self.keys.policy(value["id"]), value)

    def read(self, policy_id):
        try:
            policy_id = _validate_policy_id(policy_id)
            record = self.envelopes.read(self.keys.policy(policy_id))
        except PolicyValidationError as exc:
            return _err(exc.reason)
        except RuntimeError:
            return _err(MALFORMED)
        if not record["exists?"]:
            return _err(UNKNOWN)
        try:
            return _ok(validate_policy_value(
                record["value"], policy_id=policy_id, allow_retired=True
            ))
        except PolicyValidationError:
            return _err(MALFORMED)

    get = read

    def list_policies(self):
        prefix = "%s/policy:" % self.keys.namespace
        try:
            listing = self.envelopes.list_entries(
                prefix=prefix, include_values=True
            )
        except RuntimeError:
            return _err(MALFORMED)
        policies = []
        for item in listing["items"]:
            key = item.get("key")
            if not isinstance(key, str) or not key.startswith(prefix):
                return _err(MALFORMED)
            policy_id = key[len(prefix) :]
            try:
                _validate_policy_id(policy_id)
                record = kvstore.RevisionEnvelopeStore._public_from_raw(
                    item.get("value")
                )
            except (PolicyValidationError, RuntimeError):
                return _err(MALFORMED)
            if not record["exists?"]:
                continue
            try:
                policies.append(
                    validate_policy_value(
                        record["value"], policy_id=policy_id,
                        allow_retired=True,
                    )
                )
            except PolicyValidationError:
                return _err(MALFORMED)
        return _ok(policies)

    list = list_policies

    def delete(self, policy_id):
        try:
            policy_id = _validate_policy_id(policy_id)
            return self.envelopes.delete(self.keys.policy(policy_id))
        except PolicyValidationError as exc:
            raise ValueError(exc.reason) from exc

    def in_scope(self, worker_kind, unit_kind):
        listed = self.list_policies()
        if not listed.ok:
            return listed
        return _ok(
            [
                policy
                for policy in listed.value
                if policy_matches(policy, worker_kind, unit_kind)
            ]
        )


class ProjectStore:
    """Assemble the workspace-shaped project read model."""

    def __init__(self, directory, project, namespace=kvstore.DEFAULT_NAMESPACE):
        self.project = workareas.validate_project_slug(project)
        self.work_areas = workareas.WorkAreaStore(
            directory, self.project, namespace=namespace
        )
        self.policy = PolicyStore(directory, self.project, namespace=namespace)

    def read(self, defaults=None):
        work_area_list = self.work_areas.list_records()
        if not work_area_list.ok:
            return _err(work_area_list.reason)
        policy_list = self.policy.list_policies()
        if not policy_list.ok:
            return policy_list

        record = {
            "work_areas": work_area_list.value,
            "policy": policy_list.value,
        }
        if defaults is not None:
            if not isinstance(defaults, dict):
                return _err(INVALID_DEFAULTS)
            try:
                record["defaults"] = kvstore.canonical_json_value(defaults)
            except ValueError:
                return _err(INVALID_DEFAULTS)
        return _ok(record)
