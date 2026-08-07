"""Agent99-compatible work-area store over the local project KV.

The raw ``refs/work_area:<name>`` family is intentionally stored as
atom-keyed point-KV terms, not revision envelopes. The sibling metadata
family uses the revision envelope from ``kvstore``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import unicodedata

from orchestrator import kvstore


A_NAME = kvstore.Atom("name")
A_DISPLAY_NAME = kvstore.Atom("display_name")
A_PRIMARY = kvstore.Atom("primary")
A_ADDITIONAL = kvstore.Atom("additional")
A_EXECUTOR_ID = kvstore.Atom("executor_id")
A_VERSION = kvstore.Atom("version")
A_STATUS = kvstore.Atom("status")
A_PATH = kvstore.Atom("path")
A_DEVICE = kvstore.Atom("device")
A_DELETED = kvstore.Atom("deleted")

RECORD_KEYS = {
    A_NAME,
    A_DISPLAY_NAME,
    A_PRIMARY,
    A_ADDITIONAL,
    A_EXECUTOR_ID,
    A_VERSION,
    A_STATUS,
}
ROOT_KEYS = {A_PATH, A_DEVICE}
TOMBSTONE_KEYS = {A_NAME, A_DELETED, A_VERSION}

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_UNAVAILABLE = "unavailable"
VALID_STATUSES = {STATUS_PENDING, STATUS_READY, STATUS_UNAVAILABLE}

UNKNOWN = "unknown_work_area"
MALFORMED = "malformed_work_area"
NOT_READY = "work_area_not_ready"
DESCRIPTOR_MISMATCH = "descriptor_mismatch"
CONFLICT = "conflict"
INVALID_NAME = "invalid_name"
INVALID_DISPLAY_NAME = "invalid_display_name"
INVALID_DESCRIPTOR = "invalid_descriptor"
INVALID_EXECUTOR_ID = "invalid_executor_id"
DUPLICATE_ROOT = "duplicate_root"
INVALID_PROJECT = "invalid_project"

MAX_NAME_BYTES = 128
RAW_PREFIX = "refs/work_area:"


@dataclass(frozen=True)
class WorkAreaResult:
    ok: bool
    value: object = None
    reason: str | None = None


class WorkAreaValidationError(ValueError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _ok(value=None):
    return WorkAreaResult(True, value=value)


def _err(reason):
    return WorkAreaResult(False, reason=reason)


def _is_control(ch):
    return unicodedata.category(ch) == "Cc"


def _is_int(value):
    return type(value) is int


def _byte_len(value, invalid_reason):
    try:
        return len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise WorkAreaValidationError(invalid_reason) from exc


def _raise(reason):
    raise WorkAreaValidationError(reason)


def validate_project_slug(project):
    try:
        project = kvstore.validate_fragment(project, "project")
    except ValueError as exc:
        raise WorkAreaValidationError(INVALID_PROJECT) from exc
    if project in (".", ".."):
        _raise(INVALID_PROJECT)
    return project


def validate_name(name):
    if not isinstance(name, str):
        _raise(INVALID_NAME)
    if name.strip() == "":
        _raise(INVALID_NAME)
    if _byte_len(name, INVALID_NAME) > MAX_NAME_BYTES:
        _raise(INVALID_NAME)
    if "/" in name:
        _raise(INVALID_NAME)
    if any(_is_control(ch) for ch in name):
        _raise(INVALID_NAME)
    return name


def normalize_display_name(display_name):
    if not isinstance(display_name, str):
        _raise(INVALID_DISPLAY_NAME)
    display_name = display_name.strip()
    if display_name == "":
        _raise(INVALID_DISPLAY_NAME)
    if _byte_len(display_name, INVALID_DISPLAY_NAME) > MAX_NAME_BYTES:
        _raise(INVALID_DISPLAY_NAME)
    if any(_is_control(ch) for ch in display_name):
        _raise(INVALID_DISPLAY_NAME)
    return display_name


def validate_executor_id(executor_id):
    if not isinstance(executor_id, str) or executor_id.strip() == "":
        _raise(INVALID_EXECUTOR_ID)
    return executor_id


def _valid_status(status):
    return status in VALID_STATUSES


def _canonical_path(path):
    if not isinstance(path, str):
        return False
    if not path.startswith("/"):
        return False
    if path == "/":
        return True
    if path.endswith("/"):
        return False
    segments = path.split("/")[1:]
    return all(segment not in ("", ".", "..") for segment in segments)


def _scalar_device(device):
    if _is_int(device):
        return True
    return isinstance(device, str) and device.strip() != ""


def _root_key(root):
    return (root["path"], root["device"])


def _ensure_distinct(roots):
    seen = set()
    for root in roots:
        key = _root_key(root)
        if key in seen:
            _raise(DUPLICATE_ROOT)
        seen.add(key)


def _normalize_input_root(root):
    if isinstance(root, dict):
        if "path" in root and "device" in root and len(root) == 2:
            path = root["path"]
            device = root["device"]
        elif A_PATH in root and A_DEVICE in root and len(root) == 2:
            path = root[A_PATH]
            device = root[A_DEVICE]
        else:
            _raise(INVALID_DESCRIPTOR)
    elif isinstance(root, (list, tuple)) and len(root) == 2:
        path, device = root
    else:
        _raise(INVALID_DESCRIPTOR)

    if not _canonical_path(path) or not _scalar_device(device):
        _raise(INVALID_DESCRIPTOR)
    return {"path": path, "device": device}


def _normalize_input_roots(primary, additional):
    if not isinstance(additional, list):
        _raise(INVALID_DESCRIPTOR)
    primary = _normalize_input_root(primary)
    additional = [_normalize_input_root(root) for root in additional]
    _ensure_distinct([primary] + additional)
    return primary, additional


def _raw_root(root):
    return {A_PATH: root["path"], A_DEVICE: root["device"]}


def _public_root(root):
    return {"path": root["path"], "device": root["device"]}


def _store_map(
    name,
    primary,
    additional,
    executor_id,
    version,
    status,
    display_name,
):
    return {
        A_NAME: name,
        A_DISPLAY_NAME: display_name,
        A_PRIMARY: _raw_root(primary),
        A_ADDITIONAL: [_raw_root(root) for root in additional],
        A_EXECUTOR_ID: executor_id,
        A_VERSION: version,
        A_STATUS: status,
    }


def _tombstone_map(record):
    return {
        A_NAME: record["name"],
        A_DELETED: True,
        A_VERSION: record["version"] + 1,
    }


def _public_from_parts(
    name,
    display_name,
    primary,
    additional,
    executor_id,
    version,
    status,
):
    return {
        "name": name,
        "display_name": display_name,
        "primary": _public_root(primary),
        "additional": [_public_root(root) for root in additional],
        "executor_id": executor_id,
        "version": version,
        "status": status,
    }


def _root_from_raw(value):
    if not isinstance(value, dict) or set(value) != ROOT_KEYS:
        _raise(INVALID_DESCRIPTOR)
    root = {"path": value[A_PATH], "device": value[A_DEVICE]}
    if not _canonical_path(root["path"]) or not _scalar_device(root["device"]):
        _raise(INVALID_DESCRIPTOR)
    return root


def _interpret(value):
    if isinstance(value, dict) and set(value) == TOMBSTONE_KEYS:
        name = value[A_NAME]
        version = value[A_VERSION]
        if (
            isinstance(name, str)
            and value[A_DELETED] is True
            and _is_int(version)
            and version > 0
        ):
            return "deleted", name
        return "malformed", None

    if not isinstance(value, dict) or set(value) != RECORD_KEYS:
        return "malformed", None

    try:
        name = validate_name(value[A_NAME])
        display_name = normalize_display_name(value[A_DISPLAY_NAME])
        primary = _root_from_raw(value[A_PRIMARY])
        additional_raw = value[A_ADDITIONAL]
        if not isinstance(additional_raw, list):
            return "malformed", None
        additional = [_root_from_raw(root) for root in additional_raw]
        _ensure_distinct([primary] + additional)
        executor_id = validate_executor_id(value[A_EXECUTOR_ID])
    except WorkAreaValidationError:
        return "malformed", None

    version = value[A_VERSION]
    status = value[A_STATUS]
    if not (_is_int(version) and version >= 0 and _valid_status(status)):
        return "malformed", None

    return "live", _public_from_parts(
        name,
        display_name,
        primary,
        additional,
        executor_id,
        version,
        status,
    )


def _interpret_named(value, name):
    kind, payload = _interpret(value)
    if kind == "live" and payload["name"] == name:
        return kind, payload
    if kind == "deleted" and payload == name:
        return kind, payload
    return "malformed", None


def _content_matches(record, primary, additional):
    return (
        _root_key(record["primary"]) == _root_key(primary)
        and {_root_key(root) for root in record["additional"]}
        == {_root_key(root) for root in additional}
    )


def _meta_value(value):
    if not isinstance(value, dict) or set(value) != {"reuse_sources"}:
        raise ValueError("meta value must contain exactly reuse_sources")
    sources = value["reuse_sources"]
    if not isinstance(sources, list):
        raise ValueError("reuse_sources must be a list")
    normalized = []
    expected = {"root", "inventory", "registry", "consumption"}
    for source in sources:
        if not isinstance(source, dict) or set(source) != expected:
            raise ValueError("reuse source has invalid fields")
        item = {}
        for key in ["root", "inventory", "registry", "consumption"]:
            raw = source[key]
            if not isinstance(raw, str):
                raise ValueError("reuse source fields must be strings")
            item[key] = raw
        normalized.append(item)
    return {"reuse_sources": normalized}


class WorkAreaStore:
    """Project-bound work-area store.

    ``directory`` is a service-level backing directory; each project opens an
    independent point-KV inside it. The project slug is not encoded in keys.
    """

    def __init__(
        self,
        directory,
        project,
        namespace=kvstore.DEFAULT_NAMESPACE,
        cas_retries=3,
    ):
        self.project = validate_project_slug(project)
        self.directory = os.path.join(os.path.abspath(directory), self.project)
        self.keys = kvstore.KeyBuilder(namespace=namespace)
        self.client = kvstore.LocalKVClient(self.directory)
        self.envelopes = kvstore.RevisionEnvelopeStore(self.client)
        self.cas_retries = cas_retries

    def read(self, name):
        try:
            name = validate_name(name)
        except WorkAreaValidationError as exc:
            return _err(exc.reason)
        current = self.client.get(self.keys.raw_work_area(name))
        if current is kvstore.ABSENT:
            return _err(UNKNOWN)
        kind, payload = _interpret_named(current, name)
        if kind == "live":
            return _ok(payload)
        if kind == "deleted":
            return _err(UNKNOWN)
        return _err(MALFORMED)

    def resolve(self, name):
        result = self.read(name)
        if not result.ok:
            return result
        if result.value["status"] != STATUS_READY:
            return _err(NOT_READY)
        return _ok(
            {
                "primary": result.value["primary"],
                "additional": result.value["additional"],
            }
        )

    def list_records(self):
        listing = self.client.list_entries(
            prefix=RAW_PREFIX, include_values=True
        )
        records = []
        for item in listing["items"]:
            key = item.get("key")
            if not isinstance(key, str) or not key.startswith(RAW_PREFIX):
                return _err(MALFORMED)
            name = key[len(RAW_PREFIX) :]
            try:
                validate_name(name)
            except WorkAreaValidationError:
                return _err(MALFORMED)
            kind, payload = _interpret_named(item.get("value"), name)
            if kind == "live":
                records.append(payload)
            elif kind == "deleted":
                continue
            else:
                return _err(MALFORMED)
        return _ok(records)

    def declare(
        self,
        name,
        primary,
        additional,
        executor_id,
        display_name=None,
    ):
        try:
            name = validate_name(name)
            primary, additional = _normalize_input_roots(primary, additional)
            executor_id = validate_executor_id(executor_id)
            new_display = normalize_display_name(
                name if display_name is None else display_name
            )
        except WorkAreaValidationError as exc:
            return _err(exc.reason)

        key = self.keys.raw_work_area(name)
        for _attempt in range(self.cas_retries + 1):
            current = self.client.get(key)
            if current is kvstore.ABSENT:
                raw = _store_map(
                    name,
                    primary,
                    additional,
                    executor_id,
                    1,
                    STATUS_PENDING,
                    new_display,
                )
                result = self.client.cas(key, kvstore.ABSENT, raw)
                if result.ok:
                    return _ok(_interpret(raw)[1])
                continue

            kind, record = _interpret_named(current, name)
            if kind == "live":
                if (
                    _content_matches(record, primary, additional)
                    and record["executor_id"] == executor_id
                ):
                    return _ok(record)
                raw = _store_map(
                    name,
                    primary,
                    additional,
                    executor_id,
                    record["version"] + 1,
                    STATUS_PENDING,
                    record["display_name"],
                )
            else:
                raw = _store_map(
                    name,
                    primary,
                    additional,
                    executor_id,
                    1,
                    STATUS_PENDING,
                    new_display,
                )

            result = self.client.cas(key, current, raw)
            if result.ok:
                return _ok(_interpret(raw)[1])
        return _err(CONFLICT)

    def confirm(self, name, primary, additional, executor_id):
        try:
            name = validate_name(name)
            primary, additional = _normalize_input_roots(primary, additional)
            executor_id = validate_executor_id(executor_id)
        except WorkAreaValidationError as exc:
            return _err(exc.reason)

        def decide(record):
            if not _content_matches(record, primary, additional):
                return _err(DESCRIPTOR_MISMATCH)
            version = (
                record["version"]
                if record["status"] == STATUS_READY
                and record["executor_id"] == executor_id
                else record["version"] + 1
            )
            return _ok(
                _store_map(
                    record["name"],
                    record["primary"],
                    record["additional"],
                    executor_id,
                    version,
                    STATUS_READY,
                    record["display_name"],
                )
            )

        return self._transition(name, decide)

    def mark_unavailable(self, name, primary, additional, executor_id):
        """Record the other half of what a launcher's verification found.

        `confirm` records "these roots are here"; this records "they are
        not". Status is the RESULT of a verification, never a permission
        checked before one: no launch consults it to decide whether it may
        proceed, so recording an absence blocks nothing — it only stops the
        record from claiming a readiness this host just disproved.

        The verified roots are supplied and guarded exactly as `confirm`
        guards them: an absence is a statement about the descriptor that
        was checked, so a descriptor that changed underneath (the operator
        repointed the area between the check and this write) refuses
        rather than condemning roots this host never looked at. Version
        follows `confirm`'s rule: a repeat observation under the same
        identity is version-silent."""
        try:
            name = validate_name(name)
            primary, additional = _normalize_input_roots(primary, additional)
            executor_id = validate_executor_id(executor_id)
        except WorkAreaValidationError as exc:
            return _err(exc.reason)

        def decide(record):
            if not _content_matches(record, primary, additional):
                return _err(DESCRIPTOR_MISMATCH)
            version = (
                record["version"]
                if record["status"] == STATUS_UNAVAILABLE
                and record["executor_id"] == executor_id
                else record["version"] + 1
            )
            return _ok(
                _store_map(
                    record["name"],
                    record["primary"],
                    record["additional"],
                    executor_id,
                    version,
                    STATUS_UNAVAILABLE,
                    record["display_name"],
                )
            )

        return self._transition(name, decide)

    def relabel(self, name, display_name):
        try:
            name = validate_name(name)
            display_name = normalize_display_name(display_name)
        except WorkAreaValidationError as exc:
            return _err(exc.reason)

        def decide(record):
            return _ok(
                _store_map(
                    record["name"],
                    record["primary"],
                    record["additional"],
                    record["executor_id"],
                    record["version"],
                    record["status"],
                    display_name,
                )
            )

        return self._transition(name, decide)

    def delete(self, name):
        try:
            name = validate_name(name)
        except WorkAreaValidationError as exc:
            return _err(exc.reason)

        def decide(record):
            return _ok(_tombstone_map(record))

        return self._transition(name, decide)

    def read_meta(self, name):
        name = validate_name(name)
        return self.envelopes.read(self.keys.work_area_meta(name))

    def put_meta(self, name, value):
        name = validate_name(name)
        return self.envelopes.put(
            self.keys.work_area_meta(name), _meta_value(value)
        )

    def _transition(self, name, decide):
        key = self.keys.raw_work_area(name)
        for _attempt in range(self.cas_retries + 1):
            current = self.client.get(key)
            if current is kvstore.ABSENT:
                return _err(UNKNOWN)
            kind, record = _interpret_named(current, name)
            if kind == "deleted":
                return _err(UNKNOWN)
            if kind != "live":
                return _err(MALFORMED)

            decision = decide(record)
            if not decision.ok:
                return decision

            result = self.client.cas(key, current, decision.value)
            if result.ok:
                kind, payload = _interpret(decision.value)
                if kind == "live":
                    return _ok(payload)
                if kind == "deleted":
                    return _ok(
                        {
                            "name": decision.value[A_NAME],
                            "deleted": True,
                            "version": decision.value[A_VERSION],
                        }
                    )
                return _err(MALFORMED)
        return _err(CONFLICT)
