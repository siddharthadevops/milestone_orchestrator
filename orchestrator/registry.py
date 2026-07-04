"""Run registry for the local service panel.

The service home (default ~/.impl_roadmap) holds a registry of runs — plain
pointers to per-workspace state files, plus process bookkeeping — and the
spawned drivers' log files. Workspaces keep owning their own state; deleting
a registry entry never touches workspace files.

Writes are atomic (temp + rename) and serialized by an advisory flock so
concurrent panel actions cannot corrupt the registry.
"""

import contextlib
import json
import os
import secrets
import tempfile
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

SCHEMA_VERSION = 1

DEFAULT_HOME = os.path.expanduser("~/.impl_roadmap")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def make_run_id(when=None, token=None):
    stamp = when or time.strftime("%Y%m%d-%H%M%S")
    suffix = token or secrets.token_hex(3)
    return "r-%s-%s" % (stamp, suffix)


def registry_path(home):
    return os.path.join(home, "registry.json")


def logs_dir(home):
    return os.path.join(home, "logs")


def log_path(home, run_id):
    return os.path.join(logs_dir(home), "%s.log" % run_id)


def load(home):
    path = registry_path(home)
    if not os.path.exists(path):
        return {"schema_version": SCHEMA_VERSION, "runs": []}
    with open(path, "r", encoding="utf-8") as fh:
        reg = json.load(fh)
    if reg.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            "registry schema_version %r != %d"
            % (reg.get("schema_version"), SCHEMA_VERSION)
        )
    return reg


def save(home, reg):
    os.makedirs(home, exist_ok=True)
    path = registry_path(home)
    fd, tmp = tempfile.mkstemp(prefix=".registry-", suffix=".json", dir=home)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextlib.contextmanager
def locked(home):
    """Advisory exclusive lock for read-modify-write cycles."""
    os.makedirs(home, exist_ok=True)
    if fcntl is None:  # pragma: no cover - non-POSIX
        yield
        return
    fh = open(os.path.join(home, "registry.lock"), "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fh.close()


def new_entry(run_id, name, workspace, state_path, goal_doc=None):
    return {
        "id": run_id,
        "name": name,
        "workspace": workspace,
        "state_path": state_path,
        "goal_doc": goal_doc,
        "created_at": now_iso(),
        "pid": None,
        "last_spawn_at": None,
    }


def get(reg, run_id):
    for entry in reg["runs"]:
        if entry["id"] == run_id:
            return entry
    return None


def add(home, entry):
    with locked(home):
        reg = load(home)
        if get(reg, entry["id"]) is not None:
            raise ValueError("duplicate run id %r" % entry["id"])
        for existing in reg["runs"]:
            if existing["state_path"] == entry["state_path"]:
                raise ValueError(
                    "state %s is already registered as run %s"
                    % (entry["state_path"], existing["id"])
                )
        reg["runs"].append(entry)
        save(home, reg)
        return entry


def update(home, run_id, **fields):
    with locked(home):
        reg = load(home)
        entry = get(reg, run_id)
        if entry is None:
            raise KeyError("unknown run id %r" % run_id)
        entry.update(fields)
        save(home, reg)
        return entry


def remove(home, run_id):
    with locked(home):
        reg = load(home)
        entry = get(reg, run_id)
        if entry is None:
            raise KeyError("unknown run id %r" % run_id)
        reg["runs"] = [e for e in reg["runs"] if e["id"] != run_id]
        save(home, reg)
        return entry


def pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - exists but not ours
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Recents (panel form memory: previously used workspaces / goal docs)

RECENTS_MAX = 20
RECENT_KINDS = ("workspaces", "goal_docs")


def recents_path(home):
    return os.path.join(home, "recents.json")


def load_recents(home):
    """MRU lists for the panel form. Tolerant: a missing or corrupt file is
    just empty memory, never an error."""
    empty = {kind: [] for kind in RECENT_KINDS}
    try:
        with open(recents_path(home), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    out = {}
    for kind in RECENT_KINDS:
        values = data.get(kind, [])
        out[kind] = [v for v in values if isinstance(v, str)][:RECENTS_MAX] \
            if isinstance(values, list) else []
    return out


def remember_recent(home, kind, value):
    """Record value as most-recent of its kind (deduped, capped).

    Best-effort like load_recents: recents are panel form memory only, so a
    write failure (unwritable home, disk full, clobbered recents.json) must
    never fail the operation that recorded the path — by the time create_run
    calls this the run is already registered, and a 500 here would skip
    autostart and turn the client's retry into a spurious 409."""
    if kind not in RECENT_KINDS:
        raise ValueError("unknown recents kind %r" % kind)
    if not value or not isinstance(value, str):
        return
    try:
        with locked(home):
            rec = load_recents(home)
            items = [v for v in rec[kind] if v != value]
            items.insert(0, value)
            rec[kind] = items[:RECENTS_MAX]
            fd, tmp = tempfile.mkstemp(
                prefix=".recents-", suffix=".json", dir=home
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh, indent=2, ensure_ascii=False)
                    fh.write("\n")
                os.replace(tmp, recents_path(home))
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    except (OSError, ValueError):
        # ValueError covers UnicodeEncodeError from a value carrying lone
        # surrogates (JSON \uXXXX escapes in a crafted request body).
        pass  # never fail the caller over form memory


def session_leader_alive(pid):
    """True only when pid exists AND leads its own process group (pgid ==
    pid). Drivers are always spawned with start_new_session=True, so a real
    driver pid satisfies this; a pid recycled by the OS after a service
    restart almost never does (ordinary processes are not group leaders).
    Used for liveness of pids this service process did not spawn itself —
    it both avoids treating strangers as drivers and guarantees that
    killpg(pid) can only ever reach the driver's own group, never an
    innocent process's job/session group. An EPERM (other user's process)
    is conservatively 'not a driver': wedging would otherwise be permanent."""
    if not pid:
        return False
    try:
        return os.getpgid(pid) == pid
    except (ProcessLookupError, PermissionError, OSError):
        return False
