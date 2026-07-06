"""Local programming service: one panel over many orchestrator runs.

    python3 -m orchestrator.service [--home ~/.impl_roadmap] [--port 8700]

Serves a white two-pane panel (left: launched milestones; right: selected
run's live state) and a JSON API:

    GET    /api/runs               all runs + derived status
    GET    /api/fs                 read-only listing for the panel pickers:
                                   ?path=&mode=dir|file&ext=&hidden=1&nearest=1
                                   (nearest walks up to the closest existing
                                   directory instead of 404-ing)
    GET    /api/recents            MRU workspaces/goal docs (form memory)
    POST   /api/runs               launch: {name?, workspace, goal? | goal_doc?,
                                   config?, autostart?, attach?}; attach adopts
                                   an existing state exactly as it is on disk
                                   (goal/goal_doc/config are rejected with it)
    GET    /api/runs/<id>          entry + full state summary + log tail
    POST   /api/runs/<id>/start    spawn the driver loop in background
    POST   /api/runs/<id>/stop     SIGTERM the driver's process group (the
                                   driver forwards the stop to in-flight
                                   worker CLI process groups)
    GET    /api/runs/<id>/log      {"lines": [...]} tail of driver output
    DELETE /api/runs/<id>          forget the run (workspace files untouched;
                                   ?purge=1 also removes the run's state file
                                   + lock so the workspace can launch fresh)

Process bookkeeping: drivers spawned by this service are kept as Popen
handles and polled (reaped) on every API operation — an exited driver never
lingers as a zombie that os.kill(pid, 0) would misreport as running — and
their registry pid is cleared once the exit is observed. A pid recorded by a
PREVIOUS service process (service restart) is only trusted while it is a
live session leader, which a real driver always is (start_new_session) and
an OS-recycled pid almost never is.

Trust model: binds 127.0.0.1 only, no auth — it spawns full-permission LLM
CLIs on your machine, exactly like running the driver yourself. Do not bind
it to anything else.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import driver, errclass, gitops, registry, state as st

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAX_BODY = 1 * 1024 * 1024  # 1 MiB request cap
TAIL_CHUNK = 64 * 1024      # bytes per backwards read when tailing logs
STOP_WAIT_S = 5.0           # how long stop_run waits for the driver to die

# Filesystem browser (panel pickers): read-only listings for the workspace
# directory selector and the work-description (.md) file selector.
FS_FILE_EXTS = (".md", ".markdown", ".txt")
FS_MAX_ENTRIES = 500        # per kind per listing; truncated flag beyond


class ApiError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


# ---------------------------------------------------------------------------
# Driver process bookkeeping
#
# Drivers spawned by THIS service process are direct children: dropping the
# Popen would leave every exited driver a zombie whose pid still passes
# os.kill(pid, 0), i.e. a closed run shown as "running" forever (start 409,
# delete 409, stop a no-op). So the Popen handles are kept here and polled
# (which reaps) before any liveness decision; observed exits clear the
# registry pid so it cannot go stale and get recycled onto a stranger.

_CHILDREN = {}  # driver pid -> (run_id, subprocess.Popen)
_CHILDREN_LOCK = threading.Lock()


def driver_alive(entry):
    """Is the run's recorded driver pid a live driver?

    Our own children are polled directly (poll() reaps, so a zombie is NOT
    alive). A pid we did not spawn (previous service process) is trusted
    only while it is a live session leader — drivers always are
    (start_new_session=True), OS-recycled pids almost never; this also
    guarantees stop_run's killpg(pid) can only reach the driver's own
    group, never an innocent process's job group."""
    pid = entry.get("pid")
    if not pid:
        return False
    with _CHILDREN_LOCK:
        tracked = _CHILDREN.get(pid)
    if tracked is not None:
        return tracked[1].poll() is None
    return registry.session_leader_alive(pid)


def reap_exited_drivers(home):
    """Poll every driver this service spawned; drop exited ones (reaping
    the zombie) and clear their registry pid if it still points at them."""
    with _CHILDREN_LOCK:
        exited = [
            (pid, run_id)
            for pid, (run_id, proc) in _CHILDREN.items()
            if proc.poll() is not None
        ]
        for pid, _ in exited:
            del _CHILDREN[pid]
    for pid, run_id in exited:
        _clear_pid(home, run_id, pid)


def _clear_pid(home, run_id, pid):
    """Clear the entry's pid only if it still records the exited pid (a
    concurrent restart may already have written a fresh one)."""
    try:
        with registry.locked(home):
            reg = registry.load(home)
            entry = registry.get(reg, run_id)
            if entry is not None and entry.get("pid") == pid:
                entry["pid"] = None
                registry.save(home, reg)
    except OSError:  # pragma: no cover - registry write hiccup; retried on
        pass         # the next reap


# ---------------------------------------------------------------------------
# State summary cache
#
# The panel polls GET /api/runs every 2s and run_status/run_detail need
# st.summary; without a cache that is a full parse of EVERY run's ledger on
# every tick. Keyed by (mtime_ns, size): drivers write states atomically
# via os.replace, so any change moves the key.

_SUMMARY_CACHE = {}  # state_path -> ((mtime_ns, size), summary)
_SUMMARY_CACHE_LOCK = threading.Lock()


def load_summary(state_path):
    stat = os.stat(state_path)
    key = (stat.st_mtime_ns, stat.st_size)
    with _SUMMARY_CACHE_LOCK:
        cached = _SUMMARY_CACHE.get(state_path)
    if cached is not None and cached[0] == key:
        return cached[1]
    summ = st.summary(st.load(state_path))
    with _SUMMARY_CACHE_LOCK:
        _SUMMARY_CACHE[state_path] = (key, summ)
    return summ


def _evict_summary(state_path):
    with _SUMMARY_CACHE_LOCK:
        _SUMMARY_CACHE.pop(state_path, None)


# ---------------------------------------------------------------------------
# Filesystem browsing + form memory (panel pickers)


def browse_fs(path, mode="dir", exts=None, show_hidden=False, nearest=False):
    """Read-only directory listing for the panel pickers.

    mode "dir" lists directories only (workspace picker); mode "file" also
    lists files filtered by `exts` (work-description picker). Hidden entries
    are skipped unless show_hidden. With `nearest`, a path that is not an
    existing directory (a file, or a workspace that will be "created if
    missing") is walked up to its closest existing ancestor instead of
    failing — the picker always opens somewhere useful, and the server does
    the walking because only it knows the host's path rules (os.sep). Same
    trust model as the rest of the service: localhost-only, the operator
    browsing their own machine."""
    raw = path or "~"
    p = os.path.abspath(os.path.expanduser(raw))
    if nearest:
        while not os.path.isdir(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    if not os.path.exists(p):
        raise ApiError(404, "path not found: %s" % p)
    if not os.path.isdir(p):
        raise ApiError(400, "not a directory: %s" % p)
    if mode not in ("dir", "file"):
        raise ApiError(400, "mode must be 'dir' or 'file'")
    if mode == "file" and exts is None:
        exts = FS_FILE_EXTS
    try:
        with os.scandir(p) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except PermissionError:
        raise ApiError(403, "permission denied: %s" % p)
    except OSError as exc:
        raise ApiError(400, "cannot list %s: %s" % (p, exc))
    dirs, files, truncated = [], [], False
    for entry in entries:
        name = entry.name
        if not show_hidden and name.startswith("."):
            continue
        try:
            name.encode("utf-8")
        except UnicodeEncodeError:
            # PEP-383 surrogate escapes: raw non-UTF-8 bytes on disk (Linux
            # ext4/NFS/FUSE; APFS refuses such names). The name cannot
            # survive _json's UTF-8 encode, so one bad entry would 500 the
            # whole listing — skip it instead; it could never round-trip
            # through the JSON API for selection anyway.
            continue
        try:
            is_dir = entry.is_dir(follow_symlinks=True)
        except OSError:
            continue
        if is_dir:
            if len(dirs) < FS_MAX_ENTRIES:
                dirs.append(name)
            else:
                truncated = True
        elif mode == "file":
            if exts and not any(name.lower().endswith(x) for x in exts):
                continue
            if len(files) < FS_MAX_ENTRIES:
                files.append(name)
            else:
                truncated = True
    parent = os.path.dirname(p)
    if parent == p:
        parent = None
    return {
        "path": p,
        "parent": parent,
        "sep": os.sep,
        "dirs": dirs,
        "files": files,
        "truncated": truncated,
    }


def recent_paths(home):
    """Form memory: MRU workspaces/goal docs from recents.json, extended
    with workspaces of currently registered runs (covers pre-recents
    entries and other-service creates)."""
    rec = registry.load_recents(home)
    workspaces = list(rec["workspaces"])
    seen = set(workspaces)
    try:
        for entry in registry.load(home)["runs"]:
            ws = entry.get("workspace")
            if ws and ws not in seen:
                workspaces.append(ws)
                seen.add(ws)
    except Exception:
        pass  # recents are convenience; never fail the endpoint over them
    return {
        "workspaces": workspaces[: registry.RECENTS_MAX],
        "goal_docs": rec["goal_docs"],
    }


# ---------------------------------------------------------------------------
# Core operations (HTTP-independent; unit-testable directly)


def read_in_flight(entry, alive):
    """The driver's cosmetic in-flight marker (what call is executing right
    now). Only meaningful while the driver is alive; a stale marker from a
    crashed driver is ignored."""
    if not alive:
        return None
    path = os.path.join(
        os.path.dirname(entry["state_path"]), "current.json"
    )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "label": data.get("label"),
        "kind": data.get("kind"),
        "family": data.get("family"),
        "started_at": data.get("started_at"),
    }


def run_status(entry):
    """Derived, cheap status for the run list."""
    alive = driver_alive(entry)
    info = {
        "id": entry["id"],
        "name": entry["name"],
        "workspace": entry["workspace"],
        "created_at": entry["created_at"],
        "goal_doc": entry.get("goal_doc"),
        "process": "running" if alive else "stopped",
        "pid": entry.get("pid") if alive else None,
        "in_flight": read_in_flight(entry, alive),
        "milestone_status": None,
        "current_unit": None,
        "current_unit_status": None,
        "current_family": None,
        "failure_reason": None,
        "events_total": 0,
        "state_error": None,
    }
    try:
        summ = load_summary(entry["state_path"])
        info["milestone_status"] = summ["milestone_status"]
        info["current_unit"] = summ["current_unit"]
        info["current_unit_status"] = summ["current_unit_status"]
        info["current_family"] = summ.get("current_family")
        info["failure_reason"] = (summ["failure"] or {}).get("reason")
        info["events_total"] = summ["events_total"]
    except Exception as exc:
        info["state_error"] = str(exc)
    return info


def list_runs(home):
    reap_exited_drivers(home)
    reg = registry.load(home)
    return [run_status(e) for e in reg["runs"]]


def create_run(home, payload):
    workspace = payload.get("workspace")
    if not workspace or not isinstance(workspace, str):
        raise ApiError(400, "workspace (string) is required")
    workspace = os.path.abspath(os.path.expanduser(workspace))

    attach = bool(payload.get("attach"))
    state_path = driver.default_state_path(workspace)
    goal_doc = None

    if attach:
        # Attach adopts the on-disk state exactly as it is; a supplied
        # goal/goal_doc/config would be silently ignored — reject instead
        # of pretending it was honored.
        for key in ("goal", "goal_doc", "config"):
            if payload.get(key) is not None:
                raise ApiError(
                    400,
                    "attach adopts the existing state as-is; %r cannot be "
                    "combined with it" % key,
                )
        if not os.path.exists(state_path):
            raise ApiError(400, "attach requested but no state at %s" % state_path)
    else:
        goal = payload.get("goal")
        goal_doc = payload.get("goal_doc")
        if goal_doc:
            goal_doc = os.path.abspath(os.path.expanduser(goal_doc))
            if not os.path.isfile(goal_doc):
                raise ApiError(400, "goal_doc not found: %s" % goal_doc)
            try:
                with open(goal_doc, "r", encoding="utf-8") as fh:
                    goal = fh.read().strip()
            except OSError as exc:
                raise ApiError(400, "cannot read goal_doc: %s" % exc)
        if not goal or not isinstance(goal, str) or not goal.strip():
            raise ApiError(400, "goal text or goal_doc is required")
        config = driver.load_config(None)
        # Panel runs get the FULL enforced flow: gate commits, the amend
        # discipline, delta reviews of every fix, and revertible tamper
        # recovery all require git (README, "Git gates and the amend
        # discipline"), so service launches enable it by default — same as
        # the demo config, and matching driver.DEFAULT_CONFIG's own note.
        # An explicit {"git": {"enabled": false}} in the advanced config
        # still wins (merged below), for deliberate pure-state runs.
        driver.merge_config(config, {"git": {"enabled": True}})
        user_cfg = payload.get("config")
        if user_cfg is not None:
            if not isinstance(user_cfg, dict):
                raise ApiError(400, "config must be a JSON object")
            driver.merge_config(config, user_cfg)  # same semantics as the CLI
        if gitops.enabled(config):
            # The gate ledger must land in a repo the operator created on
            # purpose: no auto-init, no adopting parents. This also catches
            # the picked-the-parent-directory mistake at launch time
            # instead of writing run history into the wrong repository.
            if not os.path.isdir(workspace):
                raise ApiError(
                    400,
                    "workspace does not exist: %s — create it and run "
                    "`git init` in it first (or disable git in the advanced "
                    "config for a pure-state run)" % workspace,
                )
            if not gitops.is_repo_root(workspace):
                raise ApiError(
                    400,
                    "workspace must be the ROOT of an existing git "
                    "repository (gate commits and the fix loop live there; "
                    "this prevents run history landing in a parent or "
                    "unrelated repo). Run: git -C %s init" % workspace,
                )
        name_for_init = (
            payload.get("name")
            or os.path.basename(workspace.rstrip("/"))
            or "run"
        )
        try:
            driver.init_run(
                goal.strip(), workspace, config=config, name=name_for_init
            )
        except FileExistsError as exc:
            raise ApiError(409, str(exc) + ' (use "attach": true to adopt it)')

    name = payload.get("name") or os.path.basename(workspace.rstrip("/")) or "run"
    run_id = registry.make_run_id()
    entry = registry.new_entry(run_id, name, workspace, state_path, goal_doc=goal_doc)
    try:
        registry.add(home, entry)
    except ValueError as exc:
        raise ApiError(409, str(exc))
    registry.remember_recent(home, "workspaces", workspace)
    if goal_doc:
        registry.remember_recent(home, "goal_docs", goal_doc)
    if payload.get("autostart", True):
        entry = start_run(home, run_id)
    return entry


def start_run(home, run_id):
    reap_exited_drivers(home)
    os.makedirs(registry.logs_dir(home), exist_ok=True)
    # Check-spawn-record is one atomic section under the registry lock:
    # two concurrent starts (double-click; autostart racing a manual start)
    # must not both spawn a driver, and a concurrent DELETE must not slip
    # between the spawn and the pid write (which would orphan an
    # unregistered driver and 500 on the update).
    with registry.locked(home):
        reg = registry.load(home)
        entry = registry.get(reg, run_id)
        if entry is None:
            raise ApiError(404, "unknown run %r" % run_id)
        if driver_alive(entry):
            raise ApiError(
                409, "run %s is already running (pid %s)" % (run_id, entry["pid"])
            )
        info = run_status(entry)
        if info["milestone_status"] == "closed":
            raise ApiError(409, "run %s is already closed" % run_id)
        if info["state_error"]:
            raise ApiError(409, "state unreadable: %s" % info["state_error"])
        log_file = open(registry.log_path(home, run_id), "a")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "orchestrator.driver", "run",
                 "--state", entry["state_path"]],
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_file.close()
        with _CHILDREN_LOCK:
            _CHILDREN[proc.pid] = (run_id, proc)
        entry["pid"] = proc.pid
        entry["last_spawn_at"] = registry.now_iso()
        registry.save(home, reg)
        return entry


def stop_run(home, run_id):
    reap_exited_drivers(home)
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    pid = entry.get("pid")
    if not driver_alive(entry):
        return {"stopped": False, "note": "not running"}
    # driver_alive guarantees pid is (or was spawned as) a session leader,
    # so killpg(pid) reaches exactly the driver's own group — never an
    # innocent process's job group via getpgid() on a recycled pid. The
    # driver's SIGTERM handler forwards the stop to any in-flight worker
    # CLI process group (workers run in their own sessions).
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            if driver_alive(entry):  # signal failed AND it is still there
                return {"stopped": False, "note": "signal failed: %s" % exc}
            reap_exited_drivers(home)
            return {"stopped": False, "note": "not running"}
    exited = _wait_driver_exit(entry, STOP_WAIT_S)
    if exited:
        reap_exited_drivers(home)
        _clear_pid(home, run_id, pid)
    return {"stopped": True, "pid": pid, "exited": exited}


def _wait_driver_exit(entry, timeout_s):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not driver_alive(entry):
            return True
        time.sleep(0.05)
    return not driver_alive(entry)


def resume_run(home, run_id):
    """Revive a failed run (clears the failure, restores unit status) and
    start its driver again."""
    reap_exited_drivers(home)
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    if driver_alive(entry):
        raise ApiError(409, "run %s is already running" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    try:
        st.resume_run(state)
    except ValueError as exc:
        raise ApiError(409, str(exc))
    st.save(entry["state_path"], state)
    _evict_summary(entry["state_path"])
    return start_run(home, run_id)


def delete_run(home, run_id, purge=False):
    reap_exited_drivers(home)
    # Check-and-remove under ONE registry lock: the auto-resume guard (or
    # an operator Resume) could otherwise spawn a driver between our
    # aliveness check and the removal, purging state under a live driver.
    with registry.locked(home):
        reg = registry.load(home)
        entry = registry.get(reg, run_id)
        if entry is None:
            raise ApiError(404, "unknown run %r" % run_id)
        if driver_alive(entry):
            raise ApiError(409, "stop the run before deleting it")
        # Inline removal under the SAME lock (registry.remove takes its
        # own lock; flock on a second fd would deadlock this process).
        reg["runs"] = [e for e in reg["runs"] if e["id"] != run_id]
        registry.save(home, reg)
    _evict_summary(entry["state_path"])
    if not purge:
        return {"deleted": run_id, "note": "workspace files untouched"}
    purged, purge_errors = _purge_state_files(entry["state_path"])
    out = {"deleted": run_id, "purged": purged}
    if purge_errors:
        out["purge_errors"] = purge_errors
    return out


def _purge_state_files(state_path):
    """Best-effort removal of a discarded run's on-disk state claim — the
    state file and its driver lock — so a fresh launch can re-claim the same
    workspace path (state.init refuses to overwrite an existing file). Only
    these two exact files; nothing else in the workspace is touched."""
    purged, errors = [], []
    for path in (state_path, state_path + ".lock"):
        try:
            os.unlink(path)
            purged.append(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append("%s: %s" % (path, exc))
    return purged, errors


def _amendments_path(entry):
    return os.path.join(
        entry["workspace"], ".orchestrator", "amendments.json"
    )


def read_amendments(entry):
    try:
        with open(_amendments_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return [
            a
            for a in (data.get("amendments") or [])
            if isinstance(a, dict) and str(a.get("text") or "").strip()
        ]
    except (OSError, ValueError):
        return []


def add_amendment(home, run_id, body):
    """Append an operator amendment to the run's amendments file. The
    driver re-reads the file before every worker call, so a note added
    here binds the next call (drivers older than the feature pick it up
    on their next restart). Atomic write; the driver only ever reads."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise ApiError(400, "amendment text is required")
    if len(text) > 4000:
        raise ApiError(400, "amendment text too long (max 4000 chars)")
    amendments = read_amendments(entry)
    # Ids never reuse a deleted slot: a re-used id would be silently
    # matched by the driver's amendment_seen dedup and skip its ledger
    # trail event.
    highest = 0
    for a in amendments:
        aid = str(a.get("id") or "")
        if aid.startswith("A") and aid[1:].isdigit():
            highest = max(highest, int(aid[1:]))
    amendments.append(
        {
            "id": "A%d" % (highest + 1),
            "text": text,
            "at": st.now_iso(),
        }
    )
    _write_amendments(entry, amendments)
    return amendments


def delete_amendment(home, run_id, amendment_id):
    """Remove an operator amendment; subsequent worker calls simply stop
    carrying it (the ledger keeps the historical amendment_seen trail)."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    amendments = read_amendments(entry)
    kept = [a for a in amendments if str(a.get("id")) != amendment_id]
    if len(kept) == len(amendments):
        raise ApiError(404, "unknown amendment %r" % amendment_id)
    _write_amendments(entry, kept)
    return kept


def _write_amendments(entry, amendments):
    path = _amendments_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"amendments": amendments}, fh, indent=1)
    os.replace(tmp, path)


ACT_KEYS = ("drafter", "implementer", "fixer", "delta_review",
            "consultation")


def _acts_path(entry):
    return os.path.join(entry["workspace"], ".orchestrator", "acts.json")


def read_acts(entry):
    try:
        with open(_acts_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_acts(home, run_id, body):
    """Write the operator's hot act assignments (who drafts / implements /
    fixes, with which model/effort). Same lock-free pattern as
    amendments: this file is operator-owned; the driver re-reads it
    before every act resolution, so a change binds the next call (for
    drivers new enough to read it)."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    if not isinstance(body, dict):
        raise ApiError(400, "acts body must be an object")
    acts = {}
    for key, val in body.items():
        if key not in ACT_KEYS:
            raise ApiError(400, "unknown act %r (allowed: %s)"
                           % (key, ", ".join(ACT_KEYS)))
        if val in (None, "", {}):
            continue  # cleared -> fall back to config/defaults
        if isinstance(val, str):
            acts[key] = val.strip()
            continue
        if not isinstance(val, dict):
            raise ApiError(400, "act %r must be a string or object" % key)
        entry_out = {}
        for f in ("agent", "model", "effort"):
            v = (val.get(f) or "").strip() if isinstance(
                val.get(f), str) else val.get(f)
            if v:
                if not isinstance(v, str) or len(v) > 100:
                    raise ApiError(
                        400, "act %r field %r must be a short string"
                        % (key, f))
                entry_out[f] = v
        if entry_out:
            acts[key] = entry_out
    path = _acts_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(acts, fh, indent=1)
    os.replace(tmp, path)
    return acts


def run_story(home, run_id, item):
    """The full record behind one pipeline chip — fetched on click, so
    the 2s-poll summary stays lean. item forms: round:<round_id>,
    seal:<unit>:<attempt>, draft:<unit>."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    kind, _, ref = (item or "").partition(":")
    if kind == "round":
        for unit in state["units"]:
            for r in unit["rounds"]:
                if r["id"] == ref:
                    return {
                        "story": "round",
                        "unit": st.unit_key(unit),
                        "id": r["id"],
                        "family": r["family"],
                        "kind": r["kind"],
                        "at": r["at"],
                        "duration_s": r.get("duration_s"),
                        "model": r.get("model"),
                        "effort": r.get("effort"),
                        "invalidated": r.get("invalidated"),
                        "raw_path": r.get("raw_path"),
                        "source_round_id": r.get("source_round_id"),
                        "queued": r.get("queued"),
                        "result": r.get("result"),
                    }
        raise ApiError(404, "unknown round %r" % ref)
    if kind == "seal":
        unit_key, _, attempt = ref.rpartition(":")
        for unit in state["units"]:
            if st.unit_key(unit) != unit_key:
                continue
            for s_ in unit["seals"]:
                if str(s_["attempt"]) == attempt:
                    return {
                        "story": "seal",
                        "unit": unit_key,
                        "attempt": s_["attempt"],
                        "passed": s_["passed"],
                        "at": s_["at"],
                        "invalidated": s_.get("invalidated"),
                        "halves": s_.get("halves"),
                    }
        raise ApiError(404, "unknown seal %r" % ref)
    if kind == "draft":
        for unit in state["units"]:
            if st.unit_key(unit) == ref and unit.get("draft"):
                d = unit["draft"]
                return {
                    "story": "draft",
                    "unit": ref,
                    "kind": d.get("kind"),
                    "family": d.get("family"),
                    "model": d.get("model"),
                    "effort": d.get("effort"),
                    "duration_s": d.get("duration_s"),
                    "at": d.get("at"),
                    "raw_path": d.get("raw_path"),
                    "artifact": unit.get("artifact"),
                    "result": d.get("result"),
                }
        raise ApiError(404, "unknown draft %r" % ref)
    raise ApiError(400, "item must be round:/seal:/draft:")


def run_detail(home, run_id, log_tail=80):
    reap_exited_drivers(home)
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    detail = {"entry": entry, "status": run_status(entry), "summary": None}
    try:
        detail["summary"] = load_summary(entry["state_path"])
    except Exception as exc:
        detail["summary_error"] = str(exc)
    detail["log"] = read_log_tail(home, run_id, log_tail)
    detail["amendments"] = read_amendments(entry)
    detail["acts"] = read_acts(entry)
    return detail


def run_log(home, run_id, lines):
    if registry.get(registry.load(home), run_id) is None:
        raise ApiError(404, "unknown run %r" % run_id)
    return read_log_tail(home, run_id, lines)


def read_log_tail(home, run_id, lines):
    """Last `lines` lines of the driver log, reading only a bounded tail —
    driver logs grow without limit (all worker stdout/stderr) and the panel
    polls every 2s, so the whole file must never be read per poll."""
    path = registry.log_path(home, run_id)
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            pos = fh.tell()
            data = b""
            while pos > 0 and data.count(b"\n") <= lines:
                step = min(TAIL_CHUNK, pos)
                pos -= step
                fh.seek(pos)
                data = fh.read(step) + data
                if len(data) >= 8 * TAIL_CHUNK:
                    break  # pathological line lengths; return what we have
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out[-lines:]


# ---------------------------------------------------------------------------
# HTTP layer


def make_handler(home):
    class Handler(BaseHTTPRequestHandler):
        def _route(self):
            """Split the request target into (path, query dict)."""
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            return parsed.path, {k: v[-1] for k, v in query.items()}

        def do_GET(self):
            try:
                route, query = self._route()
                if route in ("/", "/index.html"):
                    self._static("panel.html", "text/html; charset=utf-8")
                elif route == "/api/runs":
                    self._json(200, {"ok": True, "runs": list_runs(home)})
                elif route == "/api/recents":
                    self._json(200, {"ok": True, **recent_paths(home)})
                elif route == "/api/fs":
                    exts = None
                    if "ext" in query:
                        exts = tuple(
                            e if e.startswith(".") else "." + e
                            for e in (
                                x.strip().lower()
                                for x in query["ext"].split(",")
                            )
                            if e and e != "."
                        ) or None
                    listing = browse_fs(
                        query.get("path"),
                        mode=query.get("mode", "dir"),
                        exts=exts,
                        show_hidden=query.get("hidden") == "1",
                        nearest=query.get("nearest") == "1",
                    )
                    self._json(200, {"ok": True, **listing})
                elif route.startswith("/api/runs/"):
                    parts = route.rstrip("/").split("/")
                    # /api/runs/<id>  or  /api/runs/<id>/log
                    if len(parts) == 4:
                        self._json(200, {"ok": True, **run_detail(home, parts[3])})
                    elif len(parts) == 5 and parts[4] == "log":
                        self._json(200, {"ok": True, "lines": run_log(home, parts[3], 200)})
                    elif len(parts) == 5 and parts[4] == "story":
                        self._json(200, {
                            "ok": True,
                            **run_story(home, parts[3],
                                        query.get("item", "")),
                        })
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except Exception as exc:  # panel must never crash the service
                self._json(500, {"ok": False, "error": str(exc)})

        def do_POST(self):
            try:
                route, _query = self._route()
                if route == "/api/runs":
                    entry = create_run(home, self._body())
                    self._json(201, {"ok": True, "run": run_status(entry)})
                elif route.startswith("/api/runs/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) == 5 and parts[4] == "start":
                        entry = start_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry)})
                    elif len(parts) == 5 and parts[4] == "stop":
                        self._json(200, {"ok": True, **stop_run(home, parts[3])})
                    elif len(parts) == 5 and parts[4] == "resume":
                        entry = resume_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry)})
                    elif len(parts) == 5 and parts[4] == "amendments":
                        amendments = add_amendment(
                            home, parts[3], self._body()
                        )
                        self._json(
                            200, {"ok": True, "amendments": amendments}
                        )
                    elif len(parts) == 5 and parts[4] == "acts":
                        acts = set_acts(home, parts[3], self._body())
                        self._json(200, {"ok": True, "acts": acts})
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        def do_DELETE(self):
            try:
                route, query = self._route()
                parts = route.rstrip("/").split("/")
                if (len(parts) == 6 and route.startswith("/api/runs/")
                        and parts[4] == "amendments"):
                    amendments = delete_amendment(home, parts[3], parts[5])
                    self._json(200, {"ok": True, "amendments": amendments})
                elif len(parts) == 4 and route.startswith("/api/runs/"):
                    self._json(200, {"ok": True, **delete_run(
                        home, parts[3], purge=query.get("purge") == "1")})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        # -- plumbing ------------------------------------------------------

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ApiError(400, "invalid Content-Length header")
            if length < 0:
                # read(negative) would read until EOF: unbounded memory and
                # a handler thread pinned until the client closes.
                raise ApiError(400, "invalid Content-Length header")
            if length > MAX_BODY:
                raise ApiError(413, "request body too large")
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiError(400, "request body must be a JSON object")
            if not isinstance(payload, dict):
                raise ApiError(400, "request body must be a JSON object")
            return payload

        def _json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _static(self, name, ctype):
            path = os.path.join(STATIC_DIR, name)
            try:
                with open(path, "rb") as fh:
                    body = fh.read()
            except OSError:
                self.send_error(500, "%s missing" % name)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):  # quiet
            pass

    return Handler


# ---------------------------------------------------------------------------
# Auto-resume guard: the service is the long-lived process, so IT watches
# for typed recoverable failures and revives runs — a quota window that
# resets at 04:00 must not cost five sleeping-operator hours.

GUARD_INTERVAL_S = 60
# Consecutive auto-resumes per failure type before the guard stands down
# and waits for the operator (quota windows genuinely move, so they get
# a generous budget; transient types get a short one).
AUTO_RESUME_CAPS = {"quota": 12, "network": 4, "busy": 4, "timeout": 4}


def append_log(home, run_id, text):
    try:
        with open(registry.log_path(home, run_id), "a",
                  encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


def guard_scan(home):
    """One pass: auto-resume every failed run whose typed failure is due.
    Never raises. Returns a list of (run_id, action) for logging/tests.

    Budget discipline (adversarial-review hardened): the consecutive
    counter resets only on demonstrated PROGRESS (events beyond the
    post-resume baseline), never on mere liveness — a doomed attempt
    that hangs for minutes must not refill its own budget. Consecutive
    resumes of one type also space out linearly (10min * count) so a
    mis-scheduled quota window probes, not machine-guns."""
    actions = []
    try:
        reap_exited_drivers(home)
        reg = registry.load(home)
        runs = list(reg.get("runs") or [])
    except Exception as exc:
        print("[guard] registry scan failed: %s" % exc, file=sys.stderr)
        return actions
    now = time.time()
    for entry in runs:
        try:
            run_id = entry["id"]
            summ = load_summary(entry["state_path"])
            if summ is None:
                continue
            if driver_alive(entry):
                baseline = entry.get("resume_baseline")
                if (
                    entry.get("auto_resumes")
                    and baseline is not None
                    and (summ.get("events_total") or 0) > baseline + 2
                ):
                    # resumed + a couple of bookkeeping events is not
                    # progress; anything beyond is real work.
                    registry.update(
                        home, run_id, auto_resumes={}, resume_baseline=None
                    )
                continue
            failure = summ.get("failure")
            if not failure:
                continue
            ftype = failure.get("type") or "unknown"
            if ftype not in errclass.AUTO_RESUMABLE:
                continue
            resume_at = failure.get("resume_at")
            if resume_at:
                due_at = st._epoch(resume_at)
                if due_at is not None and due_at > now:
                    continue
            counts = dict(entry.get("auto_resumes") or {})
            used = int(counts.get(ftype, 0))
            cap = AUTO_RESUME_CAPS.get(ftype, 3)
            if used >= cap:
                if not entry.get("capped_logged"):
                    append_log(
                        home, run_id,
                        "[guard] %s auto-resume budget exhausted (%d); "
                        "waiting for the operator\n" % (ftype, cap),
                    )
                    registry.update(home, run_id, capped_logged=True)
                actions.append((run_id, "capped:%s" % ftype))
                continue
            last = entry.get("last_auto_resume_at") or 0
            gap = 600 * max(1, used)  # 10min, 20min, 30min...
            if used and now - last < gap:
                actions.append((run_id, "spaced:%s" % ftype))
                continue
            resume_run(home, run_id)
            counts[ftype] = used + 1
            registry.update(
                home, run_id,
                auto_resumes=counts,
                resume_baseline=(summ.get("events_total") or 0),
                last_auto_resume_at=now,
                capped_logged=False,
            )
            append_log(
                home, run_id,
                "[guard] auto-resume %d/%d after %s failure\n"
                % (used + 1, cap, ftype),
            )
            actions.append((run_id, "resumed:%s" % ftype))
        except Exception as exc:
            append_log(
                home, entry.get("id") or "unknown",
                "[guard] error: %s\n" % exc,
            )
            actions.append((entry.get("id"), "error:%s" % exc))
    return actions


def start_guard(home, interval=GUARD_INTERVAL_S):
    """Daemon thread: periodic guard_scan for as long as the service
    lives."""
    def loop():
        while True:
            time.sleep(interval)
            guard_scan(home)

    t = threading.Thread(target=loop, name="auto-resume-guard", daemon=True)
    t.start()
    return t


def make_server(home, port):
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(home))


def serve(home, port, open_browser=False):
    server = make_server(home, port)
    start_guard(home)
    actual_port = server.server_address[1]
    url = "http://127.0.0.1:%d" % actual_port
    print("impl_roadmap local service: %s  (home: %s)" % (url, home))
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orchestrator-service")
    parser.add_argument("--home", default=registry.DEFAULT_HOME)
    parser.add_argument("--port", type=int, default=8700)
    parser.add_argument("--open", action="store_true", help="open the browser")
    args = parser.parse_args(argv)
    os.makedirs(args.home, exist_ok=True)
    return serve(args.home, args.port, open_browser=args.open)


if __name__ == "__main__":
    sys.exit(main())
