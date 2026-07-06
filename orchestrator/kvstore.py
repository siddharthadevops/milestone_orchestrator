"""Local project KV store and key grammar.

This module is intentionally standalone: later project slices can build raw
work-area records and enveloped project families on the same point-KV client
without wiring this into run state, prompts, service APIs, or ledgers yet.
"""

from __future__ import annotations

from dataclasses import dataclass
import contextlib
import json
import os
import tempfile
import threading
import unicodedata

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None


DEFAULT_NAMESPACE = "milestone_orchestrator"
STORE_FILENAME = "kv.json"


class _Absent:
    def __repr__(self):
        return "ABSENT"


ABSENT = _Absent()


@dataclass(frozen=True)
class PointCasResult:
    ok: bool
    current: object = ABSENT
    rev: int | None = None


@dataclass(frozen=True)
class EnvelopeCasResult:
    ok: bool
    record: dict
    reason: str | None = None


@dataclass(frozen=True)
class Atom:
    name: str

    def __post_init__(self):
        if not isinstance(self.name, str) or self.name == "":
            raise ValueError("atom name must be a non-empty string")


def atom(name):
    return Atom(name)


_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path):
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _is_control(ch):
    return unicodedata.category(ch) == "Cc"


def _validate_segment(value, label):
    if not isinstance(value, str):
        raise ValueError("%s must be a string" % label)
    if not value.strip():
        raise ValueError("%s must be non-blank" % label)
    if "/" in value:
        raise ValueError("%s must not contain '/'" % label)
    if any(_is_control(ch) for ch in value):
        raise ValueError("%s must not contain control characters" % label)
    return value


def validate_namespace(namespace):
    return _validate_segment(namespace, "namespace")


def validate_fragment(fragment, label="fragment"):
    return _validate_segment(fragment, label)


def work_area_meta_key(name, namespace=DEFAULT_NAMESPACE):
    return "%s/work_area_meta:%s" % (
        validate_namespace(namespace),
        validate_fragment(name, "name"),
    )


def policy_key(policy_id, namespace=DEFAULT_NAMESPACE):
    return "%s/policy:%s" % (
        validate_namespace(namespace),
        validate_fragment(policy_id, "id"),
    )


def run_status_key(run_id, namespace=DEFAULT_NAMESPACE):
    return "%s/run:%s/status" % (
        validate_namespace(namespace),
        validate_fragment(run_id, "run_id"),
    )


def run_digest_key(run_id, namespace=DEFAULT_NAMESPACE):
    return "%s/run:%s/digest" % (
        validate_namespace(namespace),
        validate_fragment(run_id, "run_id"),
    )


def raw_work_area_key(name):
    return "refs/work_area:%s" % validate_fragment(name, "name")


class KeyBuilder:
    def __init__(self, namespace=DEFAULT_NAMESPACE):
        self.namespace = validate_namespace(namespace)

    def work_area_meta(self, name):
        return work_area_meta_key(name, self.namespace)

    def policy(self, policy_id):
        return policy_key(policy_id, self.namespace)

    def run_status(self, run_id):
        return run_status_key(run_id, self.namespace)

    def run_digest(self, run_id):
        return run_digest_key(run_id, self.namespace)

    def raw_work_area(self, name):
        return raw_work_area_key(name)


def _validate_key(key):
    if not isinstance(key, str):
        raise ValueError("key must be a string")
    if key == "":
        raise ValueError("key must be non-empty")
    return key


def _validate_json_plain(value):
    if value is ABSENT:
        raise ValueError("ABSENT is not a storable value")
    if value is None or isinstance(value, (str, bool, int, float)):
        # json.dumps below rejects NaN/Infinity via allow_nan=False.
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_plain(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            _validate_json_plain(item)
        return
    raise ValueError("value must be JSON-plain")


def canonical_json_value(value):
    """Return a serialization-stable JSON-plain copy of value."""
    _validate_json_plain(value)
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )
    return json.loads(raw)


def _canonical_json_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _canonical_term_bytes(value):
    encoding, encoded = _encode_point_value(value)
    return json.dumps(
        {"value_encoding": encoding, "value": encoded},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _point_values_match(expected, current):
    if expected is ABSENT or current is ABSENT:
        return expected is current
    return _canonical_term_bytes(expected) == _canonical_term_bytes(current)


def _is_positive_int(value):
    return type(value) is int and value > 0


def canonical_point_value(value):
    """Return a safe-term copy for the point KV primitive."""
    encoding, encoded = _encode_point_value(value)
    return _decode_point_value(encoding, encoded)


def _encode_point_value(value):
    try:
        return "json", canonical_json_value(value)
    except ValueError:
        return "term", _encode_term(value)


def _decode_point_value(encoding, value):
    if encoding == "json":
        return canonical_json_value(value)
    if encoding == "term":
        return _decode_term(value)
    raise RuntimeError("invalid KV store file")


def _encode_term(value):
    if value is ABSENT:
        raise ValueError("ABSENT is not a storable value")
    if value is None:
        return {"type": "null", "value": None}
    if isinstance(value, bool):
        return {"type": "bool", "value": value}
    if type(value) is int:
        return {"type": "int", "value": value}
    if isinstance(value, float):
        json.dumps(value, allow_nan=False)
        return {"type": "float", "value": value}
    if isinstance(value, str):
        return {"type": "str", "value": value}
    if isinstance(value, Atom):
        return {"type": "atom", "value": value.name}
    if isinstance(value, list):
        return {"type": "list", "value": [_encode_term(item) for item in value]}
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(key, (str, Atom)):
                raise ValueError("safe KV map keys must be strings or Atom")
            items.append([_encode_term(key), _encode_term(item)])
        items.sort(key=lambda item: _canonical_json_bytes(item[0]))
        return {"type": "map", "value": items}
    raise ValueError("value must be JSON-plain or a safe KV term")


def _decode_term(value):
    if not isinstance(value, dict) or set(value) != {"type", "value"}:
        raise RuntimeError("invalid KV store file")
    typ = value["type"]
    raw = value["value"]
    if typ == "null":
        if raw is not None:
            raise RuntimeError("invalid KV store file")
        return None
    if typ == "bool":
        if type(raw) is not bool:
            raise RuntimeError("invalid KV store file")
        return raw
    if typ == "int":
        if type(raw) is not int:
            raise RuntimeError("invalid KV store file")
        return raw
    if typ == "float":
        if not isinstance(raw, float):
            raise RuntimeError("invalid KV store file")
        json.dumps(raw, allow_nan=False)
        return raw
    if typ == "str":
        if not isinstance(raw, str):
            raise RuntimeError("invalid KV store file")
        return raw
    if typ == "atom":
        if not isinstance(raw, str) or raw == "":
            raise RuntimeError("invalid KV store file")
        return Atom(raw)
    if typ == "list":
        if not isinstance(raw, list):
            raise RuntimeError("invalid KV store file")
        return [_decode_term(item) for item in raw]
    if typ == "map":
        if not isinstance(raw, list):
            raise RuntimeError("invalid KV store file")
        result = {}
        for pair in raw:
            if not isinstance(pair, list) or len(pair) != 2:
                raise RuntimeError("invalid KV store file")
            key = _decode_term(pair[0])
            if not isinstance(key, (str, Atom)) or key in result:
                raise RuntimeError("invalid KV store file")
            result[key] = _decode_term(pair[1])
        return result
    raise RuntimeError("invalid KV store file")


class LocalKVClient:
    """File-backed point KV with whole-value CAS and LPC-shaped listings."""

    def __init__(self, directory, filename=STORE_FILENAME):
        self.directory = os.path.abspath(directory)
        self.path = os.path.join(self.directory, filename)
        self.lock_path = self.path + ".lock"
        self._thread_lock = _thread_lock_for(self.path)

    def get(self, key):
        key = _validate_key(key)
        with self._locked_doc() as doc:
            entry = doc["entries"].get(key)
            if entry is None:
                return ABSENT
            return self._entry_value(entry)

    def put(self, key, value):
        key = _validate_key(key)
        value = canonical_point_value(value)

        def update(doc):
            current = doc["entries"].get(key)
            rev = 1 if current is None else current["rev"] + 1
            self._set_entry(doc, key, value, rev)
            return rev, True

        return self._mutate(update)

    def cas(self, key, expected, value):
        key = _validate_key(key)
        if expected is not ABSENT:
            expected = canonical_point_value(expected)
        value = canonical_point_value(value)

        def update(doc):
            current = doc["entries"].get(key)
            current_value = ABSENT if current is None else self._entry_value(current)
            current_rev = None if current is None else current["rev"]
            if not _point_values_match(expected, current_value):
                return PointCasResult(False, current_value, current_rev), False
            rev = 1 if current is None else current["rev"] + 1
            self._set_entry(doc, key, value, rev)
            return PointCasResult(True, value, rev), True

        return self._mutate(update)

    def list_entries(
        self, prefix=None, cursor=None, limit=None, include_values=False
    ):
        if prefix is not None:
            prefix = _validate_key(prefix)
        if cursor is not None:
            cursor = _validate_key(cursor)
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive")

        with self._locked_doc() as doc:
            keys = sorted(doc["entries"])
            if prefix is not None:
                keys = [key for key in keys if key.startswith(prefix)]
            if cursor is not None:
                keys = [key for key in keys if key > cursor]
            page_keys = keys if limit is None else keys[:limit]
            more = limit is not None and len(keys) > limit
            items = []
            for key in page_keys:
                entry = doc["entries"][key]
                item = {"key": key, "rev": entry["rev"]}
                if include_values:
                    item["value"] = self._entry_value(entry)
                items.append(item)
            return {
                "items": items,
                "next_cursor": page_keys[-1] if more and page_keys else None,
            }

    def _mutate(self, fn):
        with self._locked_doc() as doc:
            result, changed = fn(doc)
            if changed:
                self._save_doc(doc)
            return result

    @contextlib.contextmanager
    def _locked_doc(self):
        os.makedirs(self.directory, exist_ok=True)
        with self._thread_lock:
            fh = open(self.lock_path, "a+")
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                doc = self._load_doc()
                yield doc
            finally:
                fh.close()

    def _load_doc(self):
        if not os.path.exists(self.path):
            return {"entries": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                doc = json.load(fh)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("invalid KV store file") from exc
        if not isinstance(doc.get("entries"), dict):
            raise RuntimeError("invalid KV store file")
        return doc

    @staticmethod
    def _entry_value(entry):
        if (
            not isinstance(entry, dict)
            or not _is_positive_int(entry.get("rev"))
            or "value" not in entry
            or "value_encoding" not in entry
        ):
            raise RuntimeError("invalid KV store file")
        return _decode_point_value(entry["value_encoding"], entry["value"])

    @staticmethod
    def _set_entry(doc, key, value, rev):
        encoding, encoded = _encode_point_value(value)
        doc["entries"][key] = {
            "value": encoded,
            "value_encoding": encoding,
            "rev": rev,
        }

    def _save_doc(self, doc):
        fd, tmp = tempfile.mkstemp(
            prefix=".kv-", suffix=".json", dir=self.directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(
                    doc, fh, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False,
                )
                fh.write("\n")
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


class RevisionEnvelopeStore:
    """LPC-style revision envelope over LocalKVClient for our families."""

    def __init__(self, client):
        self.client = client

    def read(self, key):
        key = _validate_key(key)
        raw = self.client.get(key)
        return self._public_from_raw(raw)

    def put(self, key, value):
        key = _validate_key(key)
        value = canonical_json_value(value)

        def update(doc):
            raw = self._raw_from_doc(doc, key)
            revision = 1 if raw is ABSENT else raw["revision"] + 1
            env = {
                "revision": revision,
                "value": value,
                "deleted?": False,
            }
            current = doc["entries"].get(key)
            native_rev = 1 if current is None else current["rev"] + 1
            self.client._set_entry(doc, key, env, native_rev)
            return self._public_from_raw(env), True

        return self.client._mutate(update)

    def cas(self, key, expected_revision, value):
        key = _validate_key(key)
        if expected_revision is not None:
            self._validate_positive_revision(expected_revision)
        value = canonical_json_value(value)

        def update(doc):
            raw = self._raw_from_doc(doc, key)
            public = self._public_from_raw(raw)
            current_revision = public["revision"]
            never_written = raw is ABSENT
            matches = (
                expected_revision is None and never_written
            ) or (
                expected_revision is not None
                and expected_revision == current_revision
            )
            if not matches:
                return EnvelopeCasResult(
                    False, public, reason="revision_mismatch"
                ), False
            revision = 1 if never_written else raw["revision"] + 1
            env = {
                "revision": revision,
                "value": value,
                "deleted?": False,
            }
            current = doc["entries"].get(key)
            native_rev = 1 if current is None else current["rev"] + 1
            self.client._set_entry(doc, key, env, native_rev)
            return EnvelopeCasResult(True, self._public_from_raw(env)), True

        return self.client._mutate(update)

    def delete(self, key, expected_revision=None):
        key = _validate_key(key)
        if expected_revision is not None:
            self._validate_positive_revision(expected_revision)

        def update(doc):
            raw = self._raw_from_doc(doc, key)
            public = self._public_from_raw(raw)
            if expected_revision is not None and public["revision"] != expected_revision:
                return EnvelopeCasResult(
                    False, public, reason="revision_mismatch"
                ), False
            revision = 1 if raw is ABSENT else raw["revision"] + 1
            env = {
                "revision": revision,
                "value": None,
                "deleted?": True,
            }
            current = doc["entries"].get(key)
            native_rev = 1 if current is None else current["rev"] + 1
            self.client._set_entry(doc, key, env, native_rev)
            return EnvelopeCasResult(True, self._public_from_raw(env)), True

        return self.client._mutate(update)

    def list_entries(
        self, prefix=None, cursor=None, limit=None, include_values=False
    ):
        return self.client.list_entries(
            prefix=prefix, cursor=cursor, limit=limit,
            include_values=include_values,
        )

    @staticmethod
    def _validate_positive_revision(revision):
        if not _is_positive_int(revision):
            raise ValueError("revision must be a positive integer or None")

    @staticmethod
    def _raw_from_doc(doc, key):
        entry = doc["entries"].get(key)
        return ABSENT if entry is None else LocalKVClient._entry_value(entry)

    @classmethod
    def _public_from_raw(cls, raw):
        if raw is ABSENT:
            return {"exists?": False, "revision": None, "value": None}
        cls._validate_stored_envelope(raw)
        if raw["deleted?"]:
            return {
                "exists?": False,
                "revision": raw["revision"],
                "value": None,
            }
        return {
            "exists?": True,
            "revision": raw["revision"],
            "value": raw["value"],
        }

    @staticmethod
    def _validate_stored_envelope(raw):
        if not isinstance(raw, dict):
            raise RuntimeError("invalid stored envelope")
        if set(raw) != {"revision", "value", "deleted?"}:
            raise RuntimeError("invalid stored envelope")
        if not _is_positive_int(raw["revision"]):
            raise RuntimeError("invalid stored envelope")
        if not isinstance(raw["deleted?"], bool):
            raise RuntimeError("invalid stored envelope")


def path_is_inside_roots(candidate_path, roots):
    if not roots:
        return False
    for root in roots:
        if not os.path.isabs(root):
            continue
        root_real = os.path.realpath(root)
        if os.path.isabs(candidate_path):
            candidate_real = os.path.realpath(candidate_path)
        else:
            candidate_real = os.path.realpath(os.path.join(root_real, candidate_path))
        try:
            if os.path.commonpath([root_real, candidate_real]) == root_real:
                return True
        except ValueError:
            continue
    return False
