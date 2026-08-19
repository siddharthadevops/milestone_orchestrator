"""Local programming service: one panel over many orchestrator runs.

    python3 -m orchestrator.service [--home ~/.impl_roadmap] [--port 8700]

Serves a white two-pane panel (left: launched milestones; right: selected
run's live state) and a JSON API:

    GET    /api/access             authenticated email, role, assignable users
    GET    /api/runs               all runs + derived status
    GET    /api/fs                 read-only listing for the panel pickers:
                                   ?path=&mode=dir|file&ext=&hidden=1&nearest=1
                                   (nearest walks up to the closest existing
                                   directory instead of 404-ing)
    GET    /api/recents            MRU workspaces/goal docs (form memory)
    POST   /api/runs               launch: {name?, workspace, goal? | goal_doc?,
                                   config?, model_profile?, autostart?, attach?};
                                   attach adopts
                                   an existing state exactly as it is on disk
                                   (goal/goal_doc/config are rejected with it)
    GET    /api/runs/<id>          entry + full state summary + log tail +
                                   commit_web_base (workspace origin as an
                                   https web URL, for gate-commit links)
    GET    /api/runs/<id>/model-profile
                                   current {name, rigor} model-profile choice
    POST   /api/runs/<id>/model-profile
                                   wholly replace that current choice
    POST   /api/runs/<id>/slices/<slice-id>/producer
                                   replace one still-prospective slice producer
    GET    /api/runs/<id>/artifact ?unit=<unit_key> — the unit's recorded
                                   markdown artifact (skeleton/slice doc),
                                   served for the panel's doc viewer
    GET    /api/runs/<id>/commit   ?unit=<unit_key> — the unit's gate
                                   commit as `git show` text (local commit
                                   viewer; works without any push)
    POST   /api/runs/<id>/start    spawn the driver loop in background
    POST   /api/runs/<id>/stop     SIGTERM the driver's process group (the
                                   driver forwards the stop to in-flight
                                   worker CLI process groups)
    POST   /api/runs/<id>/name     rename the display label only: {name}
    GET    /api/runs/<id>/log      {"lines": [...]} tail of driver output
    DELETE /api/runs/<id>          forget the run (workspace files untouched;
                                   ?purge=1 also removes the run's state file
                                   + lock so the workspace can launch fresh)

Standalone Brainstorming (independent from milestone runs and chronology;
sessions render in the panel's right pane — there is no separate page):

    POST   /api/brainstorming/sessions
                                   create and start one bounded discussion
    GET    /api/brainstorming/sessions
                                   {"sessions": [...]} every session the
                                   caller may see, newest creation first —
                                   the panel's unified sidebar listing
    GET    /api/brainstorming/sessions/<id>
                                   poll one complete durable session snapshot
    GET    /api/brainstorming/sessions/<id>/view
                                   render one coherent authorized view revision
    GET    /api/brainstorming/sessions/<id>/intervention
                                   inspect the pending external turn, if any
    POST   /api/brainstorming/sessions/<id>/intervention
                                   submit its exact token and response once
    POST   /api/brainstorming/sessions/<id>/floor
                                   append one out-of-turn intervention into
                                   the discussion record: {text, author_name,
                                   author_id?}
    POST   /api/brainstorming/sessions/<id>/stop
                                   pause participant work, keeping the session
    POST   /api/brainstorming/sessions/<id>/start
                                   resume the same non-terminal session
    DELETE /api/brainstorming/sessions/<id>
                                   forget a stopped session (running: 409;
                                   ?purge=1 also removes its durable state
                                   + transcript; the target artifact is
                                   never touched)

Standing projects (the operator-declared ecosystem surface; every slug and
work-area name rides as a URL-encoded path segment):

    GET    /api/projects           every declared project: ProjectEntry
                                   {slug, work_areas: [{record, meta}],
                                   policy, defaults?} — or, fail-closed per
                                   project, {slug, error: {reason}}
    POST   /api/projects           declare: {slug, defaults?} -> 201
    GET    /api/projects/<slug>    one assembled ProjectEntry
    POST   /api/projects/<slug>    {"defaults": object|null} replace/clear
    DELETE /api/projects/<slug>    guarded: refuses while live work areas,
                                   live policies, or bound/unprovable run
                                   states exist
    GET    /api/projects/<slug>/users
                                   admin + assigned/available users
    POST   /api/projects/<slug>/git-sync
                                   {work_area} — hand that area to the
                                   project's lead family to align it with
                                   its git remote by MERGING (project-admin
                                   rung; refuses 409 work_area_busy while a
                                   milestone driver owns the worktree).
                                   Returns the agent's prose report.
    POST   /api/projects/<slug>/users
                                   replace assigned users (admin only)
    POST   /api/projects/<slug>/work-areas
                                   declare -> pending: {name, display_name?,
                                   primary_path, additional_paths?}
    GET    /api/projects/<slug>/work-areas/<name>        {record, meta}
    POST   /api/projects/<slug>/work-areas/<name>        {"display_name"}
    DELETE /api/projects/<slug>/work-areas/<name>        tombstone (+ meta)
    GET    /api/projects/<slug>/work-areas/<name>/meta   null | value
    POST   /api/projects/<slug>/work-areas/<name>/meta   raw sealed value
                                   {reuse_sources: [{root, inventory,
                                   registry, consumption}]}
    POST   /api/projects/<slug>/policies
                                   safeguard upsert: the body is the FULL
                                   sealed policy object {id, version,
                                   enabled, scope, prompt, contract}, raw;
                                   create and overwrite are one operation
                                   keyed by the body's own id, the object
                                   replaces the stored one WHOLESALE, and
                                   version rides verbatim (never
                                   auto-bumped). The response carries the
                                   stored domain object only — the
                                   envelope's control revision stays
                                   internal to the store.
    DELETE /api/projects/<slug>/policies?id=<url-encoded id>
                                   tombstone one LIVE policy. The id rides
                                   as a query parameter, NEVER a path
                                   segment: the sealed fragment grammar
                                   admits ids like "." and ".." that
                                   browsers normalize away inside URL
                                   paths (amendment A2), and query
                                   components are exempt, so every
                                   sealed-valid id round-trips. A sealed
                                   read gates the raw envelope delete:
                                   unknown/tombstoned/never-written ids
                                   refuse 404 unknown_policy and write
                                   NOTHING (an ungated delete would mint a
                                   junk tombstone key that every listing
                                   carries forever).
    POST   /api/projects/<slug>/policies/reuse-audit
                                   enable the built-in reuse-audit template:
                                   {source, inventory, registry, version?}
                                   -> {"policies": [planning, review]}.
                                   The trailing segment is a fixed affordance
                                   name, never a policy id.

Corrupt-policy recovery (amendment A2 narrows it): a malformed policy
VALUE inside a VALID envelope refuses reads/deletes with malformed_policy
and is recovered by a valid re-put, which replaces it wholesale — the
sealed put validates only the NEW value and reads the prior envelope just
for its revision. An entry whose stored ENVELOPE is itself invalid cannot
ride that path: a gated envelope read before the put — the same sealed
read that gates the delete, at envelope level — refuses 500
malformed_store for EVERY invalid envelope, including corrupt envelopes
whose revision is still readable (which the raw sealed put would silently
overwrite); the delete refuses 500 malformed_policy. Both write nothing.
The remedy there is store-level — descriptors are disposable by
design: remove the project's store file, DELETE the (now storeless)
project, and re-declare it fresh. That delete stays guarded: a lost store
lifts only the standing-law half of the guard, and bound or unprovable
run states still refuse 409 project_in_use until purge-deleted or read
back unbound.

A launch (POST /api/runs) may bind {project, work_area} instead of a bare
workspace path: the stored descriptor's roots are validated against the
real filesystem (the executor-reconcile role) and confirmed ready, the run
executes in the work area's primary root, run status carries the two
path-free handles, and the service pumps the change-driven
run:<run_id>/status projection into the bound project's KV store
(visibility only — a projection write failure never fails a launch, poll,
or run).

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
import copy
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import access as panel_access
from . import brainstorming, brainstorming_lifecycle
from . import brainstorming_tasks
from . import driver, errclass, gitops, gitsync, interpreter, kvstore, model_profiles
from . import profiles
from . import projects, registry, tasks
from . import reuse_audit
from . import staffing
from . import state as st
from . import task_api
from . import workareas

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
# Standing projects: declaration record, assembled reads, work-area CRUD.
#
# Sealed reason tokens ride VERBATIM as the error body of project-scoped
# refusals (no string-matching for the panel); the service mints tokens
# only for conditions no sealed seam owns.

UNKNOWN_PROJECT = "unknown_project"
PROJECT_EXISTS = "project_exists"
MISSING_STORE = "missing_store"
UNREADABLE_STORE = "unreadable_store"
MALFORMED_STORE = "malformed_store"
INVALID_META = "invalid_meta"
PROJECT_IN_USE = "project_in_use"
PROJECTION_TOMBSTONE_FAILED = "projection_tombstone_failed"
PRIMARY_NOT_REPO_ROOT = "primary_not_repo_root"
# A work area whose milestone driver is alive is never handed to a
# git-sync agent: the driver owns that worktree.
WORK_AREA_BUSY = "work_area_busy"
MISSING_ADDITIONAL_ROOT = driver.MISSING_ADDITIONAL_ROOT
FORBIDDEN = "forbidden"

# Slice 2's reason -> HTTP class for the CRUD/read routes: validation
# reasons 400, unknown 404, CAS exhaustion 409, store corruption 5xx.
# (The launch seam maps its causes to 400-class separately, per the
# sealed init contract.)
_WORK_AREA_STATUS = {
    workareas.UNKNOWN: 404,
    workareas.MALFORMED: 500,
    workareas.CONFLICT: 409,
}

# The device value and executor identity the service supplies on
# declare/confirm. Provenance is non-authoritative (agent_99's design);
# nothing interprets them locally — they only need to be non-blank and
# stable across service restarts for the same home, so re-confirms stay
# version-silent (an unstable identity would bump the domain version on
# every relaunch).
_DEVICE = "local"


def _executor_id(home):
    return "orchestrator-service:%s" % os.path.abspath(home)


def _work_area_error(reason):
    return ApiError(_WORK_AREA_STATUS.get(reason, 400), reason)


def _raise_store_error(exc):
    if isinstance(exc, OSError):
        raise ApiError(500, UNREADABLE_STORE) from exc
    raise ApiError(500, MALFORMED_STORE) from exc


def _store_file(home, slug):
    return os.path.join(
        registry.projects_base(home), slug, kvstore.STORE_FILENAME
    )


def _require_declared(home, slug):
    """Common gate of every project-bound route: syntactically invalid
    slugs 400, valid-but-undeclared slugs 404. Returns (validated slug,
    projects record)."""
    try:
        slug = workareas.validate_project_slug(slug)
    except workareas.WorkAreaValidationError as exc:
        raise ApiError(400, exc.reason)
    rec = registry.load_projects_record(home)
    if registry.get_project(rec, slug) is None:
        raise ApiError(404, UNKNOWN_PROJECT)
    return slug, rec


def _require_store_file(home, slug):
    """Fail closed before opening any store client: a declared project
    whose KV file is gone must never be silently recreated as empty by a
    read or (worse) resurrected by a write — a missing zero-entry file is
    an error, not an empty project."""
    if not os.path.isfile(_store_file(home, slug)):
        raise ApiError(500, MISSING_STORE)


def _work_area_store(home, slug):
    return workareas.WorkAreaStore(registry.projects_base(home), slug)


def _work_area_view(store, record):
    """WorkAreaView: the untouched Slice 2 public record, with the meta
    value BESIDE it (never inside — the goal's "rides BESIDE the agent_99
    fields" doctrine)."""
    try:
        meta = store.read_meta(record["name"])
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    return {
        "record": record,
        "meta": meta["value"] if meta["exists?"] else None,
    }


def _project_entry(home, project):
    """Assemble one ProjectEntry via slice-03's fail-closed read model, or
    the per-project error marker {slug, error: {reason}} — never a partial
    record, and never a repair (a broken store must not take the whole
    listing hostage, and must stay visible as broken)."""
    slug = project["slug"]
    defaults = project.get("defaults")
    base = registry.projects_base(home)
    if not os.path.isfile(_store_file(home, slug)):
        return {"slug": slug, "error": {"reason": MISSING_STORE}}
    try:
        read = projects.ProjectStore(base, slug).read(defaults=defaults)
        if not read.ok:
            return {"slug": slug, "error": {"reason": read.reason}}
        store = _work_area_store(home, slug)
        views = [
            _work_area_view(store, record)
            for record in read.value["work_areas"]
        ]
    except ApiError as exc:
        return {"slug": slug, "error": {"reason": str(exc)}}
    except RuntimeError:
        return {"slug": slug, "error": {"reason": MALFORMED_STORE}}
    except OSError:
        return {"slug": slug, "error": {"reason": UNREADABLE_STORE}}
    entry = {
        "slug": slug,
        "work_areas": views,
        "policy": read.value["policy"],
    }
    if "defaults" in read.value:
        entry["defaults"] = read.value["defaults"]
    return entry


def _project_entry_or_error(home, project):
    """Single-project reads fail closed with the marker's reason instead
    of returning an error entry."""
    entry = _project_entry(home, project)
    if "error" in entry:
        raise ApiError(500, entry["error"]["reason"])
    return entry


def list_projects(home, who=None):
    rec = registry.load_projects_record(home)
    visible = rec["projects"]
    if who is not None and not who.get("admin"):
        visible = [
            project for project in visible
            if panel_access.can_access_project(who, project)
        ]
    return [_project_entry(home, p) for p in visible]


def create_project(home, body):
    slug = body.get("slug")
    try:
        slug = workareas.validate_project_slug(slug)
    except workareas.WorkAreaValidationError as exc:
        raise ApiError(400, exc.reason)
    defaults = _validated_defaults(body.get("defaults"))
    with registry.locked(home):
        rec = registry.load_projects_record(home)
        if registry.get_project(rec, slug) is not None:
            # Defaults change through the update surface, never by a
            # silent re-create.
            raise ApiError(409, PROJECT_EXISTS)
        # Declaration's evidence is a READABLE zero-entry store file (no
        # key is written, no key family changes).
        kvstore.initialize_empty_store(
            os.path.join(registry.projects_base(home), slug)
        )
        project = {
            "slug": slug, "defaults": defaults, "users": [], "admins": [],
        }
        rec["projects"].append(project)
        registry.save_projects_record(home, rec)
    return _project_entry_or_error(home, project)


def read_project(home, slug):
    slug, rec = _require_declared(home, slug)
    return _project_entry_or_error(home, registry.get_project(rec, slug))


def _validated_defaults(defaults):
    """None or a serialization-stable JSON-plain object; anything else
    refuses with the sealed defaults reason."""
    if defaults is None:
        return None
    if not isinstance(defaults, dict):
        raise ApiError(400, projects.INVALID_DEFAULTS)
    try:
        return kvstore.canonical_json_value(defaults)
    except ValueError:
        raise ApiError(400, projects.INVALID_DEFAULTS)


def update_project(home, slug, body):
    with registry.locked(home):
        slug, rec = _require_declared(home, slug)
        if "defaults" not in body:
            raise ApiError(400, projects.INVALID_DEFAULTS)
        defaults = _validated_defaults(body["defaults"])
        project = registry.get_project(rec, slug)
        project["defaults"] = defaults
        registry.save_projects_record(home, rec)
    return _project_entry_or_error(home, project)


def read_project_users(home, slug):
    slug, rec = _require_declared(home, slug)
    project = registry.get_project(rec, slug)
    return {
        "admin": panel_access.ADMIN_EMAIL,
        "users": panel_access.project_users(project),
        "admins": panel_access.project_admins(project),
        "available_users": list(panel_access.USER_EMAILS),
    }


def update_project_users(home, slug, body):
    try:
        users = panel_access.validated_users(body.get("users"))
        # Admins ride the same write: a membership change that dropped a
        # user would otherwise leave them privileged over a project they
        # can no longer see. Omitting the field keeps the current list,
        # minus anyone who just stopped being a member.
        if "admins" in body:
            admins = panel_access.validated_project_admins(
                body.get("admins"), users
            )
        else:
            admins = None
    except ValueError as exc:
        raise ApiError(400, str(exc))
    with registry.locked(home):
        slug, rec = _require_declared(home, slug)
        project = registry.get_project(rec, slug)
        project["users"] = users
        project["admins"] = (
            admins
            if admins is not None
            else [
                email for email in panel_access.project_admins(project)
                if email in users
            ]
        )
        registry.save_projects_record(home, rec)
    return read_project_users(home, slug)


def delete_project(home, slug):
    """Guarded delete: removing a project removes its store — standing
    law — so it refuses as a conflict while any live work area or live
    policy exists, while any registered run's state binds the project (or
    is unreadable and thus cannot be proven unbound), and while any
    plain-forgotten retained state recorded from a bound/unproven run still
    binds it or is unreadable
    (slice-06 turns missing law under a bound run into an unrepairable
    recorded failure). Tombstone-only history never blocks: descriptors
    are disposable by design."""
    with registry.locked(home):
        slug, rec = _require_declared(home, slug)
        store_dir = os.path.join(registry.projects_base(home), slug)
        if os.path.isfile(_store_file(home, slug)):
            try:
                live_areas = _work_area_store(home, slug).list_records()
                live_policies = projects.PolicyStore(
                    registry.projects_base(home), slug
                ).list_policies()
            except RuntimeError:
                raise ApiError(500, MALFORMED_STORE)
            except OSError:
                raise ApiError(500, UNREADABLE_STORE)
            if not live_areas.ok or not live_policies.ok:
                # Cannot prove the store holds no standing law.
                raise ApiError(500, MALFORMED_STORE)
            if live_areas.value or live_policies.value:
                raise ApiError(409, PROJECT_IN_USE)
        # else: the store is already lost; there is no law left to
        # protect — only run states can still block below.

        for entry in registry.load(home)["runs"]:
            if _entry_blocks_project_delete(entry, slug):
                raise ApiError(409, PROJECT_IN_USE)
        kept_claims = []
        for state_path in rec["retained_states"]:
            if not os.path.exists(state_path):
                continue  # purged or externally removed: claim is moot
            if _state_blocks_project_delete(state_path, slug):
                raise ApiError(409, PROJECT_IN_USE)
            if _state_project(state_path) is not None:
                kept_claims.append(state_path)  # binds another project
        if os.path.isdir(store_dir):
            shutil.rmtree(store_dir)
        rec["projects"] = [
            p for p in rec["projects"] if p["slug"] != slug
        ]
        rec["retained_states"] = kept_claims
        registry.save_projects_record(home, rec)
    return {"deleted": slug}


def _state_project(state_path):
    """The project handle a run state binds, None when readable and
    unbound. Raises on an unreadable state (the caller decides what
    unprovable means)."""
    summ = load_summary(state_path)
    return summ.get("project")


def _entry_blocks_project_delete(entry, slug):
    """A registered run blocks while its state binds the project, or is
    unreadable AND the registry's durable binding (the same fallback
    delete_run consults) cannot prove it unbound — runs never rebind, so
    the binding recorded at registration stays truthful."""
    try:
        return _state_project(entry["state_path"]) == slug
    except Exception:
        summ = _bound_summary_from_entry(entry)
        if summ is None:
            # Attached already-unreadable: no proof either way, fail closed.
            return True
        return summ.get("project") == slug


def _state_blocks_project_delete(state_path, slug):
    try:
        return _state_project(state_path) == slug
    except Exception:
        # An unreadable retained state cannot be proven unbound, so fail
        # closed (no registry entry survives a forget to prove anything).
        # Callers pre-filter missing paths: a removed forgotten state is a
        # moot claim.
        return True


def declare_work_area(home, slug, body):
    """The Body-declare role: the operator supplies name + roots as
    absolute canonical paths; the service supplies device and executor
    identity. Every agent_99-readable mutation goes through Slice 2's
    sealed store — never a parallel raw-record writer."""
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        additional_paths = body.get("additional_paths")
        if additional_paths is None:
            additional_paths = []
        if not isinstance(additional_paths, list):
            raise ApiError(400, workareas.INVALID_DESCRIPTOR)
        store = _work_area_store(home, slug)
        try:
            # A fresh incarnation starts meta-clean: if the current record
            # is not live (never declared, tombstoned, or malformed), any
            # sibling meta is an orphan of a delete whose final meta write
            # failed — tombstone it BEFORE declaring so stale reuse-source
            # roles never resurrect onto the new record (contract B; the
            # delete ordering in delete_work_area relies on this backstop).
            current = store.read(body.get("name"))
            if not current.ok and current.reason in (
                workareas.UNKNOWN, workareas.MALFORMED
            ):
                if store.read_meta(body.get("name"))["exists?"]:
                    store.envelopes.delete(
                        store.keys.work_area_meta(body.get("name"))
                    )
            declared = store.declare(
                body.get("name"),
                {"path": body.get("primary_path"), "device": _DEVICE},
                [
                    {"path": path, "device": _DEVICE}
                    for path in additional_paths
                ],
                _executor_id(home),
                display_name=body.get("display_name"),
            )
        except (RuntimeError, OSError) as exc:
            _raise_store_error(exc)
        if not declared.ok:
            raise _work_area_error(declared.reason)
        return _work_area_view(store, declared.value)


def read_work_area(home, slug, name):
    slug, _rec = _require_declared(home, slug)
    _require_store_file(home, slug)
    store = _work_area_store(home, slug)
    try:
        record = store.read(name)
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    if not record.ok:
        raise _work_area_error(record.reason)
    return _work_area_view(store, record.value)


def relabel_work_area(home, slug, name, body):
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        store = _work_area_store(home, slug)
        try:
            relabeled = store.relabel(name, body.get("display_name"))
        except (RuntimeError, OSError) as exc:
            _raise_store_error(exc)
        if not relabeled.ok:
            raise _work_area_error(relabeled.reason)
        return _work_area_view(store, relabeled.value)


def delete_work_area(home, slug, name):
    """Sealed positive-version tombstone plus sibling meta cleanup in the
    same locked API operation (contract B), through the sealed store's
    public operations only. Ordering discipline: meta is READ first (an
    unreadable meta envelope aborts with nothing written), the raw
    tombstone is the first WRITE (a failed delete leaves the record live
    WITH its standing reuse-source roles — never a live record whose meta
    was silently erased), and the meta tombstone lands last. If that final
    write fails, the orphaned meta is unreadable through every live-record
    surface and declare_work_area clears it before any re-declare, so
    stale roles never resurrect. The service lock serializes the writes."""
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        store = _work_area_store(home, slug)
        try:
            record = store.read(name)
            if not record.ok:
                raise _work_area_error(record.reason)
            live_name = record.value["name"]
            meta = store.read_meta(live_name)
            deleted = store.delete(live_name)
            if deleted.ok and meta["exists?"]:
                store.envelopes.delete(store.keys.work_area_meta(live_name))
        except RuntimeError:
            raise ApiError(500, MALFORMED_STORE)
        except OSError:
            raise ApiError(500, UNREADABLE_STORE)
        if not deleted.ok:
            raise _work_area_error(deleted.reason)
        return deleted.value


def _live_work_area_store(home, slug, name):
    """Meta get/put are valid only for a live work-area record."""
    slug, _rec = _require_declared(home, slug)
    _require_store_file(home, slug)
    store = _work_area_store(home, slug)
    try:
        record = store.read(name)
    except RuntimeError:
        raise ApiError(500, MALFORMED_STORE)
    except OSError:
        raise ApiError(500, UNREADABLE_STORE)
    if not record.ok:
        raise _work_area_error(record.reason)
    return store, record.value["name"]


def read_work_area_meta(home, slug, name):
    store, name = _live_work_area_store(home, slug, name)
    return _read_work_area_meta_checked(store, name)


def put_work_area_meta(home, slug, name, body):
    with registry.locked(home):
        store, name = _live_work_area_store(home, slug, name)
        _read_work_area_meta_checked(store, name)
        try:
            return store.put_meta(name, body)["value"]
        except ValueError:
            raise ApiError(400, INVALID_META)
        except (KeyError, RuntimeError, TypeError):
            raise ApiError(500, MALFORMED_STORE)
        except OSError:
            raise ApiError(500, UNREADABLE_STORE)


def _read_work_area_meta_checked(store, name):
    try:
        meta = store.read_meta(name)
    except RuntimeError:
        raise ApiError(500, MALFORMED_STORE)
    except OSError:
        raise ApiError(500, UNREADABLE_STORE)
    return meta["value"] if meta["exists?"] else None


# Slice 3's policy reasons -> HTTP class, mirroring _WORK_AREA_STATUS:
# validation 400, unknown 404, store corruption 5xx.
_POLICY_STATUS = {
    projects.UNKNOWN: 404,
    projects.MALFORMED: 500,
}


def _policy_error(reason):
    return ApiError(_POLICY_STATUS.get(reason, 400), reason)


def _policy_store(home, slug):
    return projects.PolicyStore(registry.projects_base(home), slug)


def put_policy(home, slug, body):
    """Safeguard upsert: the body is the FULL sealed policy object,
    validated ONLY by the sealed slice-03 validator (the service adds no
    validation and never reshapes); create and overwrite are one operation
    keyed by the body's own id, and version is operator intent stored
    verbatim. The response carries the stored domain object alone — the
    envelope's control revision is independent of the domain version and
    exposing both invites exactly the confusion slice-03 separates. A
    valid re-put replaces a malformed stored VALUE wholesale (the sealed
    put reads the prior envelope only for its revision, never validating
    the old value). An invalid stored ENVELOPE refuses instead: the gated
    envelope read below owns that refusal, because the raw sealed put
    only fails on its own for envelopes whose revision is unreadable —
    a corrupt envelope that still carries a readable revision would be
    silently overwritten, and amendment A2 reserves invalid envelopes
    for the store-level remedy (see the module docstring)."""
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        store = _policy_store(home, slug)
        try:
            value = projects.validate_policy_value(body)
        except projects.PolicyValidationError as exc:
            raise ApiError(400, exc.reason)
        try:
            # Envelope gate (mirrors the delete's sealed-read gate): the
            # sealed envelope read validates the stored envelope shape and
            # raises RuntimeError on ANY invalid envelope — including ones
            # the raw put would overwrite — while passing live, tombstoned,
            # never-written, and malformed-VALUE entries through untouched.
            store.envelopes.read(store.keys.policy(value["id"]))
            stored = store.put(value)
        except projects.PolicyValidationError as exc:
            raise ApiError(400, exc.reason)
        except (KeyError, RuntimeError, TypeError):
            raise ApiError(500, MALFORMED_STORE)
        except OSError:
            raise ApiError(500, UNREADABLE_STORE)
        return stored["value"]


def enable_reuse_audit(home, slug, body):
    """Instantiate the built-in pair and store it as ordinary policies.

    The route has one extra guard beyond two calls to put_policy: both
    pinned envelopes are read before the first write, so an invalid stored
    envelope at either id cannot leave the project half-enabled.
    """
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        try:
            policies_to_store = [
                projects.validate_policy_value(policy)
                for policy in reuse_audit.instantiate(body)
            ]
        except reuse_audit.TemplateParamError as exc:
            raise ApiError(400, exc.reason) from exc
        except projects.PolicyValidationError as exc:
            raise ApiError(400, exc.reason) from exc

        store = _policy_store(home, slug)
        try:
            for policy in policies_to_store:
                store.envelopes.read(store.keys.policy(policy["id"]))
            stored = [store.put(policy)["value"] for policy in policies_to_store]
        except projects.PolicyValidationError as exc:
            raise ApiError(400, exc.reason) from exc
        except (KeyError, RuntimeError, TypeError):
            raise ApiError(500, MALFORMED_STORE)
        except OSError:
            raise ApiError(500, UNREADABLE_STORE)
        return stored


def delete_policy(home, slug, policy_id):
    """Gated safeguard delete: one sealed read FIRST, because the raw
    envelope delete happily tombstones never-written keys and listings
    include tombstones by the frozen contract — an ungated delete of a
    typo'd id would "succeed" and mint a junk key every listing carries
    forever. Unknown/tombstoned ids refuse 404 writing nothing; a
    malformed stored policy (value OR envelope — the sealed read owns
    this read and answers with its own reason) refuses 5xx writing
    nothing. The id arrives from the URL-encoded `id` query parameter,
    never a path segment (amendment A2: the sealed grammar admits "." and
    "..", which browsers normalize away inside URL paths)."""
    with registry.locked(home):
        slug, _rec = _require_declared(home, slug)
        _require_store_file(home, slug)
        store = _policy_store(home, slug)
        try:
            current = store.read(policy_id)
            if not current.ok:
                raise _policy_error(current.reason)
            deleted = store.delete(current.value["id"])
        except ApiError:
            raise
        except (KeyError, RuntimeError, TypeError):
            raise ApiError(500, MALFORMED_STORE)
        except OSError:
            raise ApiError(500, UNREADABLE_STORE)
        if not deleted.ok:
            raise ApiError(500, MALFORMED_STORE)
        return {"id": current.value["id"], "deleted": True}


def project_route_segments(route):
    """Decoded path segments after /api/projects. Slugs and work-area
    names ride URL-encoded, so every Slice 2-valid value (spaces
    included) round-trips."""
    return [
        urllib.parse.unquote(seg)
        for seg in route.rstrip("/").split("/")[3:]
        if seg != ""
    ]


def projects_api(home, method, segments, body, query=None, task_host=None):
    """Dispatch one /api/projects request. Returns (status, payload).

    `query` carries the decoded query parameters for the one route that
    uses them: the policy delete's `id` (a query parameter by amendment
    A2, so ids the sealed grammar allows but browsers would normalize
    away as path segments still round-trip)."""
    n = len(segments)
    if n == 0:
        if method == "GET":
            return 200, {"ok": True, "projects": list_projects(home)}
        if method == "POST":
            return 201, {"ok": True, "project": create_project(home, body)}
    elif n == 1:
        slug = segments[0]
        if method == "GET":
            return 200, {"ok": True, "project": read_project(home, slug)}
        if method == "POST":
            return 200, {
                "ok": True, "project": update_project(home, slug, body)
            }
        if method == "DELETE":
            return 200, {"ok": True, **delete_project(home, slug)}
    elif n == 2 and segments[1] == "work-areas":
        if method == "POST":
            return 200, {
                "ok": True,
                "work_area": declare_work_area(home, segments[0], body),
            }
    elif n == 2 and segments[1] == "users":
        if method == "GET":
            return 200, {"ok": True, **read_project_users(home, segments[0])}
        if method == "POST":
            return 200, {"ok": True, **update_project_users(
                home, segments[0], body
            )}
    elif n == 2 and segments[1] == "git-sync":
        if method == "POST":
            return 200, {
                "ok": True,
                **sync_project_git(
                    home, segments[0], body, task_host=task_host
                ),
            }
    elif n == 2 and segments[1] == "policies":
        if method == "POST":
            return 200, {
                "ok": True, "policy": put_policy(home, segments[0], body)
            }
        if method == "DELETE":
            return 200, {
                "ok": True,
                "policy": delete_policy(
                    home, segments[0], (query or {}).get("id", "")
                ),
            }
    elif (
        n == 3
        and segments[1] == "policies"
        and segments[2] == reuse_audit.PLANNING_POLICY_ID
    ):
        if method == "POST":
            return 200, {
                "ok": True,
                "policies": enable_reuse_audit(home, segments[0], body),
            }
    elif n == 3 and segments[1] == "work-areas":
        slug, name = segments[0], segments[2]
        if method == "GET":
            return 200, {
                "ok": True, "work_area": read_work_area(home, slug, name)
            }
        if method == "POST":
            return 200, {
                "ok": True,
                "work_area": relabel_work_area(home, slug, name, body),
            }
        if method == "DELETE":
            return 200, {
                "ok": True, "work_area": delete_work_area(home, slug, name)
            }
    elif n == 4 and segments[1] == "work-areas" and segments[3] == "meta":
        slug, name = segments[0], segments[2]
        if method == "GET":
            return 200, {
                "ok": True, "meta": read_work_area_meta(home, slug, name)
            }
        if method == "POST":
            return 200, {
                "ok": True,
                "meta": put_work_area_meta(home, slug, name, body),
            }
    raise ApiError(404, "not found")


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

_SUMMARY_CACHE = {}  # state_path -> ((state/acts/current-profile keys), summary)
_SUMMARY_CACHE_LOCK = threading.Lock()


def _summary_file_key(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _summary_acts(state_path):
    path = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                        "acts.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _summary_model_profile_key(state_path, home):
    selection_path = os.path.join(
        os.path.dirname(os.path.abspath(state_path)), "model_profile.json"
    )
    try:
        selection = driver.read_current_model_profile_selection(state_path)
        name = (
            model_profiles.DEFAULT_PROFILE_NAME
            if selection is None else selection["name"]
        )
        profile_path = os.path.join(
            model_profiles.model_profiles_dir(home), "%s.json" % name
        )
    except model_profiles.ModelProfileError:
        profile_path = None
    return (
        os.path.abspath(home),
        _summary_file_key(selection_path),
        _summary_file_key(profile_path) if profile_path is not None else None,
    )


def load_summary(state_path, model_profiles_home=None):
    acts_path = os.path.join(os.path.dirname(os.path.abspath(state_path)),
                             "acts.json")
    key = (_summary_file_key(state_path), _summary_file_key(acts_path))
    if model_profiles_home is not None:
        key += _summary_model_profile_key(state_path, model_profiles_home)
    with _SUMMARY_CACHE_LOCK:
        cached = _SUMMARY_CACHE.get(state_path)
    if cached is not None and cached[0] == key:
        return cached[1]
    run_state = st.load(state_path)
    current_review_model = None
    if model_profiles_home is not None:
        current_review_model = driver.resolve_current_review_model(
            state_path, model_profiles_home, run_state=run_state
        )
    summ = st.summary(
        run_state,
        acts_overlay=_summary_acts(state_path),
        current_review_model=current_review_model,
    )
    with _SUMMARY_CACHE_LOCK:
        _SUMMARY_CACHE[state_path] = (key, summ)
    return summ


def _evict_summary(state_path):
    with _SUMMARY_CACHE_LOCK:
        _SUMMARY_CACHE.pop(state_path, None)


# ---------------------------------------------------------------------------
# run:<run_id>/status projection
#
# The SERVICE is this family's only writer (local-authoritative); the
# driver's run-critical path never writes it and nothing ever reads it
# back to drive decisions — durable truth stays in state.json; the
# projection is visibility for the future Brain/other-device mirror.
# Writes ride the existing observation paths (the poll's summary refresh
# and the guard's periodic scan) and are CHANGE-DRIVEN: an observation
# whose projected value is unchanged writes nothing, so envelope
# revisions move only when the run's projected status actually changes.

_PROJECTION_LOCK = threading.Lock()

# An absolute path substring: "/" + non-space run, at the start or after
# whitespace. Spaced known paths are replaced exactly; ambiguous tails fail
# closed to the caller's fallback.
_ABS_PATH_RE = re.compile(r"(?<!\S)/\S+")
_TERMINAL_PATH_PUNCTUATION = set(")]}>.,;:!?\"'")


def _sanitize_projection_text(text, fallback, known_paths=()):
    """Path-free Brain-boundary discipline for the two operator-authored
    strings the projection mirrors (run name, failure reason): absolute
    path substrings become <path>; if the result still carries any slash
    the whole string falls back to a fixed token — fail closed, never
    leak a local filesystem path. The raw strings remain in the registry
    and the durable state summary."""
    if not text:
        return fallback
    out = str(text)
    paths = [
        path for path in set(known_paths or ())
        if isinstance(path, str) and os.path.isabs(path) and path != "/"
    ]
    for path in sorted(paths, key=len, reverse=True):
        if _known_path_tail_is_ambiguous(out, path):
            return fallback
        out = out.replace(path, "<path>")
    if _unknown_path_tail_is_ambiguous(out):
        return fallback
    out = _ABS_PATH_RE.sub("<path>", out).strip()
    if not out or "/" in out:
        return fallback
    return out


def _known_path_tail_is_ambiguous(text, path):
    pos = 0
    while True:
        pos = text.find(path, pos)
        if pos == -1:
            return False
        end = pos + len(path)
        if end < len(text) and not _safe_path_tail(text[end:], path):
            return True
        pos = end


def _unknown_path_tail_is_ambiguous(text):
    for match in _ABS_PATH_RE.finditer(text):
        if match.end() < len(text) and not _safe_unknown_path_tail(
            text[match.end():]
        ):
            return True
    return False


def _safe_unknown_path_tail(tail):
    if not tail:
        return True
    if not tail[0].isspace():
        return all(char in _TERMINAL_PATH_PUNCTUATION for char in tail)
    rest = tail.lstrip()
    return not rest or all(
        char in _TERMINAL_PATH_PUNCTUATION for char in rest
    )


def _safe_path_tail(tail, path=None):
    if not tail:
        return True
    if not tail[0].isspace():
        return all(char in _TERMINAL_PATH_PUNCTUATION for char in tail)
    rest = tail.lstrip()
    if not rest:
        return True
    if rest.startswith("("):
        close = rest.find(")")
        body = rest[1:close] if close != -1 else ""
        if close != -1 and path is not None:
            offset = len(tail) - len(rest)
            if os.path.exists(path + tail[:offset + close + 1]):
                return False
        return (
            close != -1
            and (not body or any(char.isspace() for char in body))
            and all(
                char in _TERMINAL_PATH_PUNCTUATION
                for char in rest[close + 1:]
            )
        )
    return all(char in _TERMINAL_PATH_PUNCTUATION for char in rest)


def _projection_value(entry, summ):
    """Exactly {run_id, name, project, work_area, milestone_status,
    current_unit, current_unit_status, failure_reason}, JSON-plain and
    path-free; every field other than the sanitized name/failure_reason
    mirrors the run's summary."""
    failure = (summ.get("failure") or {}).get("reason")
    known_paths = (entry.get("workspace"), summ.get("workspace"))
    return {
        "run_id": entry["id"],
        "name": _sanitize_projection_text(
            entry.get("name") or summ.get("name"),
            "run", known_paths=known_paths
        ),
        "project": summ["project"],
        "work_area": summ["work_area"],
        "milestone_status": summ.get("milestone_status"),
        "current_unit": summ.get("current_unit"),
        "current_unit_status": summ.get("current_unit_status"),
        "failure_reason": (
            None if failure is None
            else _sanitize_projection_text(
                failure, "failure_recorded", known_paths=known_paths
            )
        ),
    }


def _bound_project_envelopes(home, slug):
    """The bound project's own DECLARED KV store — the only valid
    projection authority. No global, workspace-root, or foreign store is
    ever written, and a lost store is a fault to report, never a store to
    silently recreate (re-declaring is the operator's repair)."""
    slug = workareas.validate_project_slug(slug)
    rec = registry.load_projects_record(home)
    if registry.get_project(rec, slug) is None:
        raise RuntimeError("project %r is not declared here" % slug)
    store_file = _store_file(home, slug)
    if not os.path.isfile(store_file):
        raise RuntimeError("no store file at %s" % store_file)
    return kvstore.RevisionEnvelopeStore(
        kvstore.LocalKVClient(os.path.dirname(store_file))
    )


def _pump_projection(home, entry, summ):
    """One change-driven projection observation. Contained: any fault
    logs to the run's service log and returns — a projection write
    failure fails no launch, poll, or run, and the pump self-heals on
    the next observation once the store is writable again. Project-less
    runs project nothing (zero KV access)."""
    if summ is None or "project" not in summ:
        return
    run_id = entry["id"]
    try:
        value = _projection_value(entry, summ)
        with _PROJECTION_LOCK:
            envelopes = _bound_project_envelopes(home, summ["project"])
            key = kvstore.KeyBuilder().run_status(run_id)
            current = envelopes.read(key)
            if current["exists?"] and current["value"] == value:
                return
            envelopes.put(key, value)
    except Exception as exc:
        append_log(home, run_id, "[projection] write failed: %s\n" % exc)


def _tombstone_projection(home, run_id, summ, required=False):
    """Purge-deleting a bound run tombstones its projection through the
    sealed envelope delete (readback exists?: False) in the same
    bound-project store; a plain forget leaves the last truthful snapshot.
    Optional projection observations are contained like writes; purge
    deletion requires the tombstone before it can remove the last observation
    path."""
    if summ is None or "project" not in summ:
        return True
    try:
        with _PROJECTION_LOCK:
            envelopes = _bound_project_envelopes(home, summ["project"])
            envelopes.delete(kvstore.KeyBuilder().run_status(run_id))
        return True
    except Exception as exc:
        append_log(home, run_id, "[projection] tombstone failed: %s\n" % exc)
        if required:
            raise ApiError(500, PROJECTION_TOMBSTONE_FAILED)
        return False


def _bound_summary_from_entry(entry):
    """The registry's durable binding fallback for deletion paths where
    the state document is unreadable. It distinguishes a state that was
    registered after a readable-unbound summary from an attach of an already
    unreadable state, where absence of handles proves nothing."""
    if entry.get("project") is None:
        if entry.get("project_proven_unbound"):
            return {}
        return None
    return {
        "project": entry.get("project"),
        "work_area": entry.get("work_area"),
    }


# ---------------------------------------------------------------------------
# Filesystem browsing + form memory (panel pickers)


def browse_fs(path, mode="dir", exts=None, show_hidden=False, nearest=False,
              roots=None):
    """Read-only directory listing for the panel pickers.

    mode "dir" lists directories only (workspace picker); mode "file" also
    lists files filtered by `exts` (work-description picker). Hidden entries
    are skipped unless show_hidden. With `nearest`, a path that is not an
    existing directory (a file, or a workspace that will be "created if
    missing") is walked up to its closest existing ancestor instead of
    failing — the picker always opens somewhere useful, and the server does
    the walking because only it knows the host's path rules (os.sep).

    Without `roots` the listing spans the whole host: same trust model as
    the rest of the service, localhost-only, the operator browsing their
    own machine — an ADMIN-ONLY shape. With `roots` (a work area's primary
    plus additional roots) the listing is confined to them, so a project
    member browses their own area and nothing else: containment is decided
    by kvstore.path_is_inside_roots, which compares realpaths, so a symlink
    pointing out of the area cannot walk out of it either. A confined
    listing defaults to the first root instead of ~, and `nearest` stops
    there rather than climbing past it.
    """
    if roots is not None and not roots:
        raise ApiError(403, FORBIDDEN)
    raw = path or (roots[0] if roots else "~")
    p = os.path.abspath(os.path.expanduser(raw))
    if roots is not None and not kvstore.path_is_inside_roots(p, roots):
        # An out-of-area request is answered from the area's own root
        # rather than refused: the picker's remembered path, or a "nearest"
        # walk, must never strand a member outside what they may see.
        p = os.path.abspath(roots[0])
    if nearest:
        while not os.path.isdir(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            if roots is not None and not kvstore.path_is_inside_roots(
                parent, roots
            ):
                p = os.path.abspath(roots[0])
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
    if (
        roots is not None
        and parent is not None
        and not kvstore.path_is_inside_roots(parent, roots)
    ):
        # "Up" stops at the area boundary: offering a parent the caller
        # may not list would only render a dead control.
        parent = None
    return {
        "path": p,
        "parent": parent,
        "sep": os.sep,
        "dirs": dirs,
        "files": files,
        "truncated": truncated,
        "roots": None if roots is None else [os.path.abspath(r) for r in roots],
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
        "model": data.get("model"),
        "effort": data.get("effort"),
        "started_at": data.get("started_at"),
    }


def run_status(entry, home=None):
    """Derived, cheap status for the run list. A project-bound run also
    carries its two path-free handles (null when unbound). When `home`
    is given, the freshly observed summary drives the change-driven
    projection pump — the poll is one of its two observation paths."""
    alive = driver_alive(entry)
    info = {
        "id": entry["id"],
        "name": entry["name"],
        "workspace": entry["workspace"],
        "created_at": entry["created_at"],
        "goal_doc": entry.get("goal_doc"),
        "project": entry.get("project"),
        "work_area": entry.get("work_area"),
        "process": "running" if alive else "stopped",
        "pid": entry.get("pid") if alive else None,
        "in_flight": read_in_flight(entry, alive),
        "milestone_status": None,
        "current_unit": None,
        "display_current_unit": None,
        "current_unit_status": None,
        "implementation_stabilization": False,
        "slices_total": 0,
        "current_family": None,
        "current_model": None,
        "failure_reason": None,
        "events_total": 0,
        "work_duration_s": None,
        "work_token_usage": None,
        "work_token_usage_partial": False,
        "work_cost": None,
        "work_cost_partial": False,
        "billing": {},
        "last_action_epoch": None,
        "state_error": None,
    }
    try:
        summ = load_summary(entry["state_path"], model_profiles_home=home)
        info["project"] = summ.get("project")
        info["work_area"] = summ.get("work_area")
        info["milestone_status"] = summ["milestone_status"]
        info["current_unit"] = summ["current_unit"]
        info["display_current_unit"] = summ.get(
            "display_current_unit", summ["current_unit"]
        )
        info["current_unit_status"] = summ["current_unit_status"]
        info["implementation_stabilization"] = bool(
            summ.get("implementation_stabilization")
        )
        info["slices_total"] = len(summ.get("slices") or [])
        info["current_family"] = summ.get("current_family")
        info["current_model"] = summ.get("current_model")
        in_flight = info.get("in_flight")
        if (in_flight and not in_flight.get("model")
                and in_flight.get("family")):
            defaults = summ.get("model_defaults") or {}
            in_flight["model"] = (
                defaults.get(in_flight["family"]) or {}
            ).get("model")
        info["failure_reason"] = (summ["failure"] or {}).get("reason")
        info["events_total"] = summ["events_total"]
        info["work_duration_s"] = summ.get("work_duration_s")
        info["work_token_usage"] = summ.get("work_token_usage")
        info["work_token_usage_partial"] = bool(
            summ.get("work_token_usage_partial", False)
        )
        info["work_cost"] = summ.get("work_cost")
        info["work_cost_partial"] = bool(summ.get("work_cost_partial", False))
        # The panel cannot tell a free seat from a zero-cost call by the
        # amounts alone, so it is told which families are metered.
        info["billing"] = summ.get("billing") or {}
        if home is not None and not info.get("in_flight"):
            current_view = next(
                (
                    unit
                    for unit in summ.get("units") or []
                    if unit.get("unit") == summ.get("current_unit")
                ),
                None,
            )
            waiting = next(
                (
                    item
                    for item in reversed(
                        (current_view or {}).get("brainstormings") or []
                    )
                    if item.get("outcome") == "waiting"
                ),
                None,
            )
            if waiting is not None:
                try:
                    session = brainstorming_lifecycle.inspect_session(
                        home, waiting["session_id"], lambda _record: None
                    )
                    session_work = session.get("work_duration_s")
                    if (
                        waiting.get("duration_s") is None
                        and session_work is not None
                    ):
                        info["work_duration_s"] = (
                            (info.get("work_duration_s") or 0)
                            + session_work
                        )
                    session_tokens = session.get("work_token_usage")
                    if (
                        waiting.get("token_usage") is None
                        and session_tokens is not None
                    ):
                        info["work_token_usage"] = st._add_token_usage(
                            info.get("work_token_usage"), session_tokens
                        )
                    info["work_token_usage_partial"] = bool(
                        info.get("work_token_usage_partial")
                        or session.get("work_token_usage_partial", False)
                    )
                    session_cost = session.get("work_cost")
                    if (
                        waiting.get("cost") is None
                        and session_cost is not None
                    ):
                        info["work_cost"] = st._add_cost(
                            info.get("work_cost"), session_cost
                        )
                    info["work_cost_partial"] = bool(
                        info.get("work_cost_partial")
                        or session.get("work_cost_partial", False)
                    )
                    active = session.get("in_flight")
                    if active is not None:
                        info["in_flight"] = {
                            "label": "Brainstorming %s · %s"
                            % (
                                waiting["session_id"],
                                active.get("stage") or active.get("kind"),
                            ),
                            "kind": "brainstorming",
                            "family": active.get("model_family"),
                            "model": active.get("model"),
                            "effort": active.get("effort"),
                            "started_at": active.get("started_at"),
                        }
                except Exception:
                    # The milestone driver remains the authority for routing
                    # session failures. A list poll must not fail the run.
                    pass
        action_epochs = [
            value
            for value in (
                summ.get("created_epoch"),
                summ.get("last_event_epoch"),
                (info.get("in_flight") or {}).get("started_at"),
            )
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
        ]
        if action_epochs:
            info["last_action_epoch"] = max(action_epochs)
        if home is not None:
            _pump_projection(home, entry, summ)
    except Exception as exc:
        info["state_error"] = str(exc)
    info["pause_after_seal"] = bool(
        read_control(entry).get("stop_after_seal")
    )
    return info


def control_path(entry):
    return os.path.join(
        os.path.dirname(entry["state_path"]), "control.json"
    )


def read_control(entry):
    """The driver-side control file (safe-pause orders). Tolerant like
    every other sidecar read: missing or corrupt means no orders."""
    try:
        with open(control_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def set_pause_after_seal(home, run_id, body):
    """Arm (or cancel) the operator's safe-pause order: the driver stops
    cleanly right after the next unit seals — the one point where the
    worktree equals HEAD equals the reviewed state — leaving the repo
    committed and clean for an out-of-band build. The order rides
    control.json (service-written, driver-read), NEVER state.json, whose
    single writer is the driver."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    enabled = True
    if isinstance(body, dict) and "enabled" in body:
        enabled = bool(body["enabled"])
    ctl = read_control(entry)
    if enabled:
        ctl["stop_after_seal"] = True
        ctl["requested_at"] = registry.now_iso()
    else:
        ctl.pop("stop_after_seal", None)
    path = control_path(entry)
    fd, tmp = tempfile.mkstemp(
        prefix=".control-", suffix=".json", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(ctl, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"pause_after_seal": enabled}


def rename_run(home, run_id, body):
    """Rename only the service-owned display label.

    The driver's durable state, milestone directory and commits keep their
    original identity, so this is safe while a worker is running and cannot
    be overwritten by the driver's next state save.
    """
    name = body.get("name") if isinstance(body, dict) else None
    if not isinstance(name, str):
        raise ApiError(400, "name must be a string")
    name = name.strip()
    if not name:
        raise ApiError(400, "name must not be blank")
    if len(name) > 160:
        raise ApiError(400, "name is too long (max 160 characters)")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ApiError(400, "name contains control characters")
    try:
        entry = registry.update(home, run_id, name=name)
    except KeyError:
        raise ApiError(404, "unknown run %r" % run_id)
    return run_status(entry, home=home)


def list_runs(home):
    reap_exited_drivers(home)
    reg = registry.load(home)
    return [run_status(e, home=home) for e in reg["runs"]]


def _launch_goal(payload):
    """Resolve the launch's goal text (inline goal or goal_doc file).
    Returns (goal, goal_doc)."""
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
    return goal.strip(), goal_doc


def _registered_state_conflict(reg, state_path):
    for existing in reg["runs"]:
        if existing["state_path"] == state_path:
            return (
                "state %s is already registered as run %s"
                % (state_path, existing["id"])
            )
    return None


def _refuse_registered_state_path(home, state_path):
    with registry.locked(home):
        message = _registered_state_conflict(registry.load(home), state_path)
    if message is not None:
        raise ApiError(409, message)


def _report_lost_observation(slug, area, missing, cause):
    """A launch's root observation could not be stored. The launch is not
    affected — the filesystem decided it — but the record now describes an
    earlier launch, so say so where the operator can find it."""
    print(
        "[work-area] %s/%s: could not record %s (%s)"
        % (
            slug,
            area,
            "ready" if missing is None else "%s (%s)" % (
                workareas.STATUS_UNAVAILABLE, missing
            ),
            cause,
        ),
        file=sys.stderr,
    )


def _verify_and_record_roots(home, slug, area, primary, additional):
    """The executor-reconcile role: verify the STORED descriptor's roots
    against the real filesystem — never roots taken from the request — and
    RECORD what was found.

    Root existence is the only requirement every launch shares, so it is
    the only thing the stored status describes: `ready` when the
    descriptor's roots are all here, `unavailable` when one is not. The
    status is the OUTCOME of this verification and is never read back as a
    permission — a launch is stopped by the refusal raised here, at the
    moment of use, with the cause the operator can act on, not by a flag
    some earlier launch left behind. Requirements belonging to one kind of
    launch are verified by that launch and do not reach this record.

    The verification decides; the record only remembers. Recording is
    attempted first, so a launch that proceeds leaves the record agreeing
    with what this host saw — but a record that cannot be written (a
    descriptor repointed underneath, a store that refuses the write) never
    converts a passing verification into a refusal, and never displaces
    the cause of a failing one. Provenance that fails is lost provenance,
    not a veto: the whole point of this reform is that a launch stands or
    falls on the filesystem, not on a stored record.

    Contained is not silent, though — the same rule the projection pump
    follows. A dropped note means the panel's status chip is describing
    some earlier launch, so the failure is reported rather than
    swallowed: the operator is never left with a stale record and no
    trace of why."""
    missing = None
    if not os.path.isdir(primary["path"]):
        missing = driver.MISSING_PRIMARY_PATH
    else:
        for root in additional:
            if not os.path.isdir(root["path"]):
                missing = MISSING_ADDITIONAL_ROOT
                break
    try:
        store = _work_area_store(home, slug)
        executor = _executor_id(home)
        recorded = (
            store.confirm(area, primary, additional, executor)
            if missing is None
            else store.mark_unavailable(area, primary, additional, executor)
        )
        if not recorded.ok:
            _report_lost_observation(slug, area, missing, recorded.reason)
    except (RuntimeError, OSError) as exc:
        _report_lost_observation(slug, area, missing, exc)
    if missing is not None:
        raise ApiError(400, missing)


def _record_launch_roots(home, slug, area):
    """Run the root verification for a launch that addresses a work area
    by name only (it has no resolved descriptor of its own yet).

    A read that does not yield a live record records nothing and refuses
    nothing: the caller's own sealed seam re-reads it a moment later and
    owns that refusal vocabulary. This function exists for the half the
    sealed seam cannot do — writing down what this host found. A project
    whose store file is gone is left alone entirely: writing would
    silently fabricate an empty store for a project that has one, which
    the read routes exist to prevent."""
    if slug is None or not os.path.isfile(_store_file(home, slug)):
        return
    try:
        record = _work_area_store(home, slug).read(area)
    except (RuntimeError, OSError):
        return
    if not record.ok:
        return
    _verify_and_record_roots(
        home, slug, area, record.value["primary"], record.value["additional"]
    )


def _create_bound_run(home, payload, workspace):
    """POST /api/runs {project, work_area}: launch against a declared
    project instead of a bare path. Observable order: (1) addressing —
    declared project, live stored record of ANY status (readiness is
    verified here, never consulted); (2) root verification, recorded
    through the sealed transition (`_verify_and_record_roots`); (3) the
    milestone's own git-repository-root requirement; (4) Slice 5's
    project-bound init. Refusal tokens ride verbatim; every refusal
    creates no state file, no registry entry, and no projection entry (a
    refusal at step 3 truthfully leaves the work area ready — readiness
    describes the descriptor's roots, not this launch's requirements).

    Returns (primary_path, state_path, goal_doc)."""
    try:
        slug = workareas.validate_project_slug(payload.get("project"))
        area = workareas.validate_name(payload.get("work_area"))
    except workareas.WorkAreaValidationError as exc:
        raise ApiError(400, exc.reason)

    # Addressing. An undeclared project (or a declared one whose store is
    # lost) is the sealed launch seam's no-store posture: unknown_work_area,
    # 400-class, no store opened, nothing created. This launch-seam mapping
    # is deliberately distinct from the CRUD routes' 404/5xx mapping.
    rec = registry.load_projects_record(home)
    project = registry.get_project(rec, slug)
    if project is None or not os.path.isfile(_store_file(home, slug)):
        raise ApiError(400, workareas.UNKNOWN)
    store = _work_area_store(home, slug)
    try:
        record = store.read(area)
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    if not record.ok:
        raise ApiError(400, record.reason)
    primary = record.value["primary"]
    additional = record.value["additional"]

    goal, goal_doc = _launch_goal(payload)
    user_cfg = payload.get("config")
    if user_cfg is not None and not isinstance(user_cfg, dict):
        raise ApiError(400, "config must be a JSON object")

    # Launch-time standing defaults are merged BENEATH the persisted project
    # defaults — standing operator law beats a service convention, and the
    # explicit launch config beats both.
    binding_defaults = {
        "git": {"enabled": True},
    }
    if project.get("defaults"):
        driver.merge_config(binding_defaults, project["defaults"])

    # Verification is the reconcile's real-filesystem half, under the
    # launch's effective config (the same order init will apply). A
    # failure refuses 400 with a machine-readable reason and creates
    # nothing.
    effective = driver.load_config(None)
    driver.merge_config(effective, binding_defaults)
    if user_cfg:
        driver.merge_config(effective, user_cfg)
    _verify_and_record_roots(home, slug, area, primary, additional)
    # A milestone's OWN requirement, verified by the milestone: the gate
    # ledger must land in a repo the operator created on purpose (the same
    # predicate as the project-less gate below). It is deliberately not
    # part of readiness — a caller with no ledger to write has no business
    # inheriting it — so it refuses with its own cause and leaves the
    # status just recorded untouched.
    if gitops.enabled(effective) and not gitops.is_repo_root(primary["path"]):
        raise ApiError(400, PRIMARY_NOT_REPO_ROOT)

    resolved_workspace = primary["path"] if workspace is None else workspace
    # The legacy-root state-path guard applies ONLY to a flat/legacy
    # layout, where every run in a workspace shares `.orchestrator/
    # state.json`. A per-milestone layout ({slug} template — the default)
    # resolves to a fresh, uniquified dir per run (init_run), so a new
    # milestone can never collide with a prior run's state; guarding the
    # legacy root there would falsely block EVERY new milestone whenever a
    # closed legacy run stays registered in the same workspace (seen live
    # 2026-07-09: LPC's closed N30 at the legacy path blocked all new
    # per-milestone launches). init_run + registry.add still catch a real
    # collision on the actual resolved path.
    layout_is_legacy = "{slug}" not in ((effective.get("docs_dir") or "docs"))
    if resolved_workspace == primary["path"] and layout_is_legacy:
        _refuse_registered_state_path(
            home, driver.default_state_path(resolved_workspace)
        )

    binding = {
        "directory": registry.projects_base(home),
        "project": slug,
        "work_area": area,
        "defaults": binding_defaults,
    }
    name_for_init = (
        payload.get("name")
        or os.path.basename(primary["path"].rstrip("/"))
        or "run"
    )
    try:
        state_path = driver.init_run(
            goal, workspace, name=name_for_init,
            project=binding, config_override=user_cfg,
            model_profiles_home=home,
        )
    except driver.ProjectResolutionError as exc:
        # The sealed seam built cause for exactly this consumer: the
        # token rides verbatim, no per-cause status remapping.
        raise ApiError(400, exc.cause)
    except ValueError as exc:
        raise ApiError(400, str(exc))
    except FileExistsError as exc:
        raise ApiError(409, str(exc) + ' (use "attach": true to adopt it)')
    return primary["path"], state_path, goal_doc


def _snapshot_profile(state_path, ref, content):
    """Retain a run's resolved identity and complete semantic content.

    The driver can interpret the run self-containedly without consulting the
    later mutable catalogue. Append-only-safe:
    only config keys are added — events and units are untouched — so
    st.save's history guard passes. The state exists but the driver has not
    started yet, so no driver lock is contended."""
    state = st.load(state_path)
    cfg = state.get("config")
    if not isinstance(cfg, dict):
        cfg = {}
        state["config"] = cfg
    cfg["profile_ref"] = ref
    cfg["profile"] = content
    st.save(state_path, state)


#: Exactly what a launch may say about staffing: which document, how hard,
#: and (optionally) the session's default material. Seats are never named
#: here — they are the document's business.
STAFFING_LAUNCH_FIELDS = ("document", "rigor", "material")


def _validated_launch_staffing(value, supplied=True):
    """The launch's staffing selection, refused before any state exists.

    OMITTING `staffing` binds the `default` document at `medium`, which is
    what an unconfigured run staffs today; that is the only launch this
    fills in for. A `staffing` that IS supplied must carry the document and
    the rigor it names — the binding is written once and this slice offers
    no route to change it, so a blank or half-filled selection quietly
    running the whole run on `default@medium` is exactly the misstaffing
    the router exists to end. The shape is then validated by the session
    store's own validator over a probe record, so the launch and the store
    cannot disagree about what a document name or a rigor is; the work area
    and families the real session carries are the run's own and are known
    only once the run exists.
    """
    if not supplied:
        return {
            "document": staffing.DEFAULT_DOCUMENT_NAME,
            "rigor": staffing.FALLBACK_RIGOR,
        }
    if not isinstance(value, dict):
        raise ApiError(
            400,
            "staffing must be an object of {document, rigor, material?}",
        )
    unknown = sorted(set(value) - set(STAFFING_LAUNCH_FIELDS))
    if unknown:
        raise ApiError(
            400,
            "staffing carries unknown key %r (allowed: %s)"
            % (unknown[0], ", ".join(STAFFING_LAUNCH_FIELDS)),
        )
    missing = [key for key in ("document", "rigor") if key not in value]
    if missing:
        raise ApiError(
            400,
            "staffing must name %s (omit 'staffing' entirely for %s at %s)"
            % (" and ".join(missing), staffing.DEFAULT_DOCUMENT_NAME,
               staffing.FALLBACK_RIGOR),
        )
    selection = {"document": value["document"], "rigor": value["rigor"]}
    if value.get("material") is not None:
        selection["material"] = value["material"]
    try:
        staffing.validate_session(dict(
            selection,
            id="probe",
            work_area={"workspace_path": "/"},
            families=[],
        ))
    except staffing.StaffingError as exc:
        raise ApiError(400, str(exc))
    return selection


def staffing_documents_list(home):
    """Every stored staffing document, sorted by name.

    Read-only, and loud on a damaged store exactly as the model-profile
    catalogue is: a shorter list would silently hide the document an
    operator is about to launch on.
    """
    return staffing.list_staffing_documents(home)


# ---------------------------------------------------------------------------
# The staffing API: documents, sessions, and one resolution
#
# Thin adapters over slice 2's document store, slice 3's session store and
# the resolver. Nothing here staffs anything, keeps a record, or holds a
# permission of its own: every route reuses the request identity and the
# project access the service already enforces, and every refusal is one of
# the fixed tokens below, riding verbatim as the error body.

#: A document the store refuses. Validation happens before any byte changes,
#: so the previously stored definition survives a refused save untouched.
INVALID_STAFFING_DOCUMENT = "invalid_staffing_document"

#: A create body or an edit the session store refuses, for the same reason.
INVALID_STAFFING_SESSION = "invalid_staffing_session"

#: A session id no stored record answers. "Cannot be read" is ONE condition
#: in the store — unknown, unreadable, malformed, damaged alike — so it is
#: one condition here too: from a caller's side, the session is not there.
UNKNOWN_STAFFING_SESSION = "unknown_staffing_session"

#: A resolve body the router will not admit: malformed, an unknown key, an
#: unknown role, a non-positive index or round, a non-string material. This
#: rejects a request BEFORE resolution and is not a surfaced condition.
INVALID_STAFFING_REQUEST = "invalid_staffing_request"

#: The two SURFACED conditions, as their HTTP statuses. The tokens are the
#: router's own; this maps them and adds none.
_STAFFING_CONDITION_STATUS = {
    staffing.STAFFING_UNAVAILABLE: 503,
    staffing.DISTINCT_FAMILIES_UNSATISFIABLE: 409,
}

#: Exactly what a resolve request admits. `index` and `round` default to 1
#: when absent. `brief` travels with the request, is read by no rule and is
#: never stored, so — as in the router itself — there is nothing about its
#: value to refuse. `families` is deliberately absent: they are the
#: session's own fact, never a caller's claim.
STAFFING_RESOLVE_FIELDS = ("role", "index", "round", "material", "brief")


def _require_encodable(body, token):
    """Refuse a body no successful response could carry back.

    JSON admits an escaped unpaired surrogate, and the stores record
    strings verbatim — refusing only a shape no consumer could use — so one
    is validated and stored happily. No UTF-8 response can carry it, so the
    write would commit and then answer neither its stored record nor a
    fixed token, and a document holding one makes the whole catalogue
    unreadable until it is replaced. That is this route's own invalid
    input: refused here, before any byte changes, by exactly the encoder
    the response will use.
    """
    try:
        json.dumps(body, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ApiError(400, token) from exc


def save_staffing_document(home, body):
    """Create or WHOLLY replace one staffing document — the catalogue's only
    edit operation, and administrative like the model-profile catalogue.

    Whole replacement, never a merge: a friendly merge would leave a removed
    rule or seat alive in a document its author believes no longer carries
    it. The store validates before any byte changes, so a refused write
    leaves the prior document byte-identical.
    """
    _require_encodable(body, INVALID_STAFFING_DOCUMENT)
    try:
        return staffing.save(home, body)
    except staffing.StaffingError as exc:
        raise ApiError(400, INVALID_STAFFING_DOCUMENT) from exc


def _staffing_session_project(work_area):
    """The project slug a session's work area names, or None.

    Read defensively because it is read on the CREATE body too, before the
    store has looked at it: a body whose work area is missing or misshapen
    names no project, and so takes the administrative path below rather
    than being authorized from something a caller made up.
    """
    if not isinstance(work_area, dict):
        return None
    slug = work_area.get("project")
    return slug if isinstance(slug, str) else None


def require_staffing_session_access(home, who, work_area, stored=True):
    """Authorize one session route from the work area the session names.

    The whole session policy, and no rung of its own: a session bound to a
    project needs the same live project access as the work it names, and a
    session with no project handle stays on the existing local-administrator
    path. Live, because it is re-derived per request — a member whose access
    is withdrawn loses the session with it.

    *stored* says where the handle came from, which is the whole difference
    between the two. A handle the STORE holds was decided once already, so
    the administrator reaches it as they reach every run and every
    discussion (`require_run_access`, `require_brainstorming_access`), and
    a project deleted afterwards leaves no session that nobody can read.
    A handle the CALLER supplies is a claim, so the project gate decides it
    for everyone — the sibling create at `/api/brainstorming/sessions`
    authorizes exactly that way — and only a session naming NO project
    takes the administrative path. Otherwise an undeclared project would
    open a session bound to nothing the service declares, in a record whose
    work area no edit can correct and no route deletes.

    Nothing further is checked. Every caller who passes here may read the
    session and write or clear its overrides: there is no creator check, no
    owner field and no caller identity stored (amendment A3).
    """
    slug = _staffing_session_project(work_area)
    if slug is None:
        if not who.get("admin"):
            raise ApiError(403, FORBIDDEN)
        return None
    if stored and who.get("admin"):
        return None
    return require_project_access(home, who, slug)


def staffing_session_view(home, record):
    """One successful session response: the stored record and, beside it,
    the roles whose declared split this session cannot honour.

    Read LIVE on every response — the document may change under the session
    — and it gates nothing: a role listed here still reads and edits
    normally, and only an actual resolution refuses on that condition.
    """
    return {
        "session": record,
        "distinct_families_unsatisfiable":
            staffing.distinct_families_projection(home, record["id"]),
    }


def read_staffing_session(home, who, session_id):
    """One stored session, authorized from its OWN work-area handle.

    Authorization is derived from what the store holds and never from what
    the request carries, so a caller cannot reach another project's session
    by describing it differently.
    """
    try:
        record = staffing.read_session(home, session_id)
    except staffing.StaffingError as exc:
        raise ApiError(404, UNKNOWN_STAFFING_SESSION) from exc
    require_staffing_session_access(home, who, record["work_area"])
    return record


def create_staffing_session(home, who, body):
    """Open one session for the work area the body names.

    Authorization comes first, from that named work area — a caller who may
    not open work there learns nothing about what else the body got wrong —
    and the handle is the caller's own claim, so a named project is one the
    service declares and this caller may work in, for every identity.
    The id is the store's, never the caller's.
    """
    require_staffing_session_access(
        home, who, body.get("work_area"), stored=False)
    _require_encodable(body, INVALID_STAFFING_SESSION)
    try:
        return staffing.create_session(home, body)
    except staffing.StaffingError as exc:
        raise ApiError(400, INVALID_STAFFING_SESSION) from exc


def edit_staffing_session(home, session_id, changes):
    """Apply one partial edit to an already-authorized session.

    The store owns the shape: exactly `document`, `rigor`, `material` and
    `overrides`, an absent field left alone and an explicit null clearing
    one of the two optional ones. Optimistic, as the stores are — no version
    and no compare-and-set — and byte-stable on refusal.
    """
    _require_encodable(changes, INVALID_STAFFING_SESSION)
    try:
        return staffing.edit_session(home, session_id, changes)
    except staffing.StaffingError as exc:
        raise ApiError(400, INVALID_STAFFING_SESSION) from exc


def resolve_staffing_request(home, record, body):
    """Staff one call through a session the caller has already been
    authorized to read.

    Returns EXACTLY the router's answer — `agent`, `model`, `effort` — and
    nothing beside it: no seat, no cycle, no history and no fallback note.
    A referenced document that cannot be read is not a failure here either;
    the router's mandatory fallback answers it on the default document and
    the answer looks like any other.

    It refuses in exactly three ways: an input the router will not admit,
    and the two surfaced conditions under their own tokens.
    """
    unknown = sorted(set(body) - set(STAFFING_RESOLVE_FIELDS))
    if unknown or "role" not in body:
        raise ApiError(400, INVALID_STAFFING_REQUEST)
    try:
        resolution = staffing.resolve(
            home,
            record["id"],
            body["role"],
            index=body.get("index", 1),
            round=body.get("round", 1),
            material=body.get("material"),
            brief=body.get("brief"),
        )
    except staffing.StaffingConditionError as exc:
        raise ApiError(
            _STAFFING_CONDITION_STATUS[exc.code], exc.code) from exc
    except staffing.StaffingError as exc:
        raise ApiError(400, INVALID_STAFFING_REQUEST) from exc
    return resolution.answer


def create_run(home, payload):
    attach = bool(payload.get("attach"))
    bound = (
        payload.get("project") is not None
        or payload.get("work_area") is not None
    )
    workspace = payload.get("workspace")
    if workspace is not None and not isinstance(workspace, str):
        raise ApiError(400, "workspace (string) is required")
    if workspace:
        workspace = os.path.abspath(os.path.expanduser(workspace))
    else:
        # Only a project-bound launch may omit the workspace (it derives
        # from the work area's primary root).
        workspace = None
        if not bound:
            raise ApiError(400, "workspace (string) is required")

    # Resolve an optional strategy profile before creating state. Identity
    # and content come from one source read, so an edit racing creation may
    # place either complete definition in the run but cannot create a mixed
    # pair. Selection never mutates or freezes the reusable definition.
    profile_name = payload.get("profile")
    profile_binding = None
    if profile_name is not None:
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ApiError(400, "profile must be a non-empty profile name")
        profile_name = profile_name.strip()
        try:
            profile_binding = profiles.resolve(home, profile_name)
        except profiles.ProfileError as exc:
            raise ApiError(400, str(exc))

    # The run's staffing: one session, opened from `staffing` and bound
    # below. Validated here, before any run state is created, so a launch
    # that cannot be honoured leaves nothing behind.
    if "model_profile" in payload:
        raise ApiError(
            400,
            "'model_profile' no longer decides any call of a run: launch "
            "with 'staffing' {document, rigor, material?} instead",
        )
    staffing_supplied = "staffing" in payload
    if attach and staffing_supplied:
        raise ApiError(
            400,
            "attach adopts the existing state as-is; 'staffing' cannot be "
            "combined with it",
        )
    staffing_selection = _validated_launch_staffing(
        payload.get("staffing"), supplied=staffing_supplied
    )

    goal_doc = None
    if attach:
        # Attach adopts the on-disk state exactly as it is; a supplied
        # goal/goal_doc/config — or a project binding, which would
        # re-resolve what the state already records — would be silently
        # ignored: reject instead of pretending it was honored. Adopts the
        # legacy workspace-root state, or an explicit `state_path` for a
        # per-milestone run.
        for key in ("goal", "goal_doc", "config", "project", "work_area",
                    "profile", "staffing"):
            if payload.get(key) is not None:
                raise ApiError(
                    400,
                    "attach adopts the existing state as-is; %r cannot be "
                    "combined with it" % key,
                )
        state_path = payload.get("state_path")
        if state_path:
            state_path = os.path.abspath(os.path.expanduser(state_path))
        else:
            state_path = driver.default_state_path(workspace)
        if not os.path.exists(state_path):
            raise ApiError(400, "attach requested but no state at %s" % state_path)
        # The adopted state must belong to THIS workspace: otherwise the
        # driver would run against `workspace` while mutating another repo's
        # ledger. (Guards an explicit cross-workspace state_path.) An
        # UNREADABLE state proves nothing either way and stays adoptable:
        # the delete-guard machinery depends on re-attaching corrupt
        # states to purge them (refusing here would strand them forever).
        adopted_ws = None
        try:
            adopted_ws = st.load(state_path).get("workspace")
        except Exception:
            pass
        if adopted_ws is not None and (
            os.path.abspath(adopted_ws or "") != os.path.abspath(workspace)
        ):
            raise ApiError(
                400,
                "state at %s belongs to workspace %r, not %r"
                % (state_path, adopted_ws, workspace),
            )
    elif bound:
        workspace, state_path, goal_doc = _create_bound_run(
            home, payload, workspace
        )
    else:
        goal, goal_doc = _launch_goal(payload)
        state_path = driver.default_state_path(workspace)
        config = driver.load_config(None)
        # Panel runs get the FULL enforced flow: gate commits, the amend
        # discipline, delta reviews of every fix, and the sealed-artifact
        # guard all require git (README, "Git gates and the amend
        # discipline"), so service launches enable it by default — same as
        # the demo config, and matching driver.DEFAULT_CONFIG's own note.
        # An explicit {"git": {"enabled": false}} in the advanced config
        # still wins (merged below), for deliberate pure-state runs.
        driver.merge_config(config, {
            "git": {"enabled": True},
        })
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
            # init_run resolves the (uniquified) milestone dir and returns
            # the real state path — for a per-milestone docs_dir that is
            # <milestone>/.run/state.json, so a new run never collides with
            # a closed one in the same repo.
            creation_kwargs = {}
            if isinstance(user_cfg, dict) and "acts" in user_cfg:
                creation_kwargs["creation_acts"] = user_cfg["acts"]
            state_path = driver.init_run(
                goal.strip(), workspace, config=config, name=name_for_init,
                model_profiles_home=home,
                **creation_kwargs
            )
        except ValueError as exc:
            raise ApiError(400, str(exc))
        except FileExistsError as exc:
            raise ApiError(409, str(exc) + ' (use "attach": true to adopt it)')

    if not attach:
        # Exactly one session per run, written once. An attached run adopts
        # the state as it is; its first resume derives one (amendment A2).
        driver.open_run_staffing_session(
            state_path,
            home,
            staffing_selection["document"],
            staffing_selection["rigor"],
            material=staffing_selection.get("material"),
        )

    if profile_name is not None:
        profile_ref, profile_content = profile_binding
        _snapshot_profile(state_path, profile_ref, profile_content)

    name = payload.get("name") or os.path.basename(workspace.rstrip("/")) or "run"
    run_id = registry.make_run_id()
    entry_summ = None
    entry_project = None
    entry_work_area = None
    try:
        entry_summ = load_summary(state_path, model_profiles_home=home)
        entry_project = entry_summ.get("project")
        entry_work_area = entry_summ.get("work_area")
    except Exception:
        pass
    entry = registry.new_entry(
        run_id,
        name,
        workspace,
        state_path,
        goal_doc=goal_doc,
        project=entry_project,
        work_area=entry_work_area,
    )
    if entry_summ is not None and entry_project is None:
        entry["project_proven_unbound"] = True
    try:
        registry.add(home, entry)
    except ValueError as exc:
        raise ApiError(409, str(exc))
    if bound:
        # The initial projection value (envelope revision 1). Contained —
        # a failed initial write never fails the bound launch; the pump
        # self-heals on a later observation.
        try:
            _pump_projection(home, entry, entry_summ)
        except Exception as exc:
            append_log(home, run_id, "[projection] write failed: %s\n" % exc)
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
        # A git sync is merging this tree right now: starting a driver into
        # it is the same collision the sync route refuses in reverse.
        if workspace_sync_in_flight(entry.get("workspace")):
            raise ApiError(409, WORK_AREA_BUSY)
        log_file = open(registry.log_path(home, run_id), "a")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-m", "orchestrator.driver", "run",
                 "--state", entry["state_path"],
                 "--model-profiles-home", os.path.abspath(home)],
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
    # Check, optional purge, retained-state claim, and removal happen under
    # ONE registry lock. Otherwise a concurrent project delete could observe
    # neither the registered run nor the retained attachable state.
    with registry.locked(home):
        reg = registry.load(home)
        entry = registry.get(reg, run_id)
        if entry is None:
            raise ApiError(404, "unknown run %r" % run_id)
        if driver_alive(entry):
            raise ApiError(409, "stop the run before deleting it")
        summ = None
        try:
            # Read while the state is certainly still on disk: the purge
            # tombstone and the retained-state decision below need to know
            # whether (and where) the run was bound.
            summ = load_summary(
                entry["state_path"], model_profiles_home=home
            )
        except Exception:
            summ = _bound_summary_from_entry(entry)
        if purge:
            _tombstone_projection(home, run_id, summ, required=True)
            # Keep the registry entry visible until the purge either removes
            # the state claim or leaves one that we record below.
            purged, purge_errors = _purge_state_files(entry["state_path"])
        else:
            purged, purge_errors = [], []
        _claim_retained_state_locked(home, entry["state_path"], summ)
        # Inline removal under the SAME lock (registry.remove takes its
        # own lock; flock on a second fd would deadlock this process).
        reg["runs"] = [e for e in reg["runs"] if e["id"] != run_id]
        registry.save(home, reg)
    _evict_summary(entry["state_path"])
    if not purge:
        return {"deleted": run_id, "note": "workspace files untouched"}
    out = {"deleted": run_id, "purged": purged}
    if purge_errors:
        out["purge_errors"] = purge_errors
    return out


def _claim_retained_state_locked(home, state_path, summ):
    """Record a deregistered run's still-on-disk, project-bound state file
    in the projects record's retained_states, so project deletion keeps
    seeing its claim. Caller must already hold registry.locked(home)."""
    if not os.path.exists(state_path):
        return
    if summ is not None and "project" not in summ:
        return
    rec = registry.load_projects_record(home)
    if state_path not in rec["retained_states"]:
        rec["retained_states"].append(state_path)
        registry.save_projects_record(home, rec)


def _purge_state_files(state_path):
    """Best-effort removal of a discarded run's on-disk state claim — the
    state file, its driver lock, and its current model-profile settings — so a
    fresh launch can re-claim the same workspace path without inheriting the
    discarded run's selection or act overrides. Only these exact files;
    nothing else in the workspace is touched."""
    purged, errors = [], []
    runtime_dir = os.path.dirname(os.path.abspath(state_path))
    for path in (
        state_path,
        state_path + ".lock",
        os.path.join(runtime_dir, "model_profile.json"),
        os.path.join(runtime_dir, "acts.json"),
    ):
        try:
            os.unlink(path)
            purged.append(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            errors.append("%s: %s" % (path, exc))
    return purged, errors


def _amendments_path(entry):
    # Beside the state file (the run's runtime dir), matching the driver.
    return os.path.join(
        os.path.dirname(entry["state_path"]), "amendments.json"
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


ACT_KEYS = model_profiles.PROFILE_ACT_KEYS


def _acts_path(entry):
    # Beside the state file (the run's runtime dir), matching the driver.
    return os.path.join(os.path.dirname(entry["state_path"]), "acts.json")


def read_acts(entry):
    try:
        with open(_acts_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_acts(home, run_id, body):
    """Write hot act assignments (draft/impl/review/fix model profiles).

    Same lock-free pattern as
    amendments: this file is operator-owned; the driver re-reads it
    before every act resolution, so a change binds the next call (for
    drivers new enough to read it)."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    acts = _validated_acts(body)
    _write_acts(entry, acts)
    return acts


def patch_acts(home, run_id, body):
    """Apply only the supplied live-act changes.

    The panel uses this mutation form so editing one row does not erase an
    untouched creation-time explicit-empty entry.  Empty supplied values keep
    the public clear meaning; omitted keys remain semantically unchanged.
    """
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    changes = _validated_acts(body, retain_clears=True)
    try:
        acts = driver.read_current_acts_overlay(
            entry["state_path"], strict=True
        )
    except model_profiles.ModelProfileError as exc:
        raise ApiError(400, str(exc))
    # A partial mutation must not make malformed omitted state look healthy.
    # Validate the whole current layer, but preserve its original values and
    # meaningful explicit-empty forms byte-for-semantics when merging changes.
    _validated_acts(acts, retain_clears=True)
    for key, val in changes.items():
        if val is None:
            acts.pop(key, None)
        else:
            acts[key] = val
    _write_acts(entry, acts)
    return acts


def _validated_acts(body, retain_clears=False):
    if not isinstance(body, dict):
        raise ApiError(400, "acts body must be an object")
    acts = {}
    for key, val in body.items():
        if key not in ACT_KEYS:
            raise ApiError(400, "unknown act %r (allowed: %s)"
                           % (key, ", ".join(ACT_KEYS)))
        if val in (None, "", {}):
            if retain_clears:
                acts[key] = None
            continue  # cleared -> fall back to profile/config/defaults
        try:
            acts[key] = model_profiles.validate_act_entry(
                "acts", key, val
            )
        except model_profiles.ModelProfileError as exc:
            raise ApiError(400, str(exc))

    return acts


def _write_acts(entry, acts):
    path = _acts_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".acts-", suffix=".json", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(acts, fh, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _profile_overlay_path(entry):
    # Beside the state file (the run's runtime dir), matching acts.json and
    # amendments.json.
    return os.path.join(os.path.dirname(entry["state_path"]),
                        "profile_swap.json")


def read_profile_overlay(entry):
    """The operator's current runtime repoint for this run, or None. An
    operator-owned, lock-free file beside the state (the amendments/acts
    pattern): the operator writes one retained pair, and the driver records
    ``profile_changed`` before its next action decision. Tolerant of an
    unreadable or incomplete file (returns None)."""
    try:
        with open(_profile_overlay_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ref, content = data.get("ref"), data.get("profile")
    try:
        profiles.verify_retained(ref, content)
    except profiles.ProfileError:
        return None
    return {"ref": ref, "profile": content, "at": data.get("at")}


def read_profile(entry):
    """The run's governing strategy profile for the panel, or None for a
    profile-less, never-swapped run. Read straight from state (like
    read_acts) and tolerant of a transiently unreadable state. `base` is
    retained pair stored in the run config at creation; `swap` is the
    operator's runtime repoint (present only after a swap); `governing` is
    the profile selected for the run — the swap when present, else the base.
    The displayed selection reflects operator intent immediately; the driver
    applies its retained content before the next action decision."""
    try:
        state = st.load(entry["state_path"])
        base = (state.get("config") or {}).get("profile_ref")
        applied = interpreter.governing_profile_ref(state)
    except Exception:
        base = applied = None
    overlay = read_profile_overlay(entry)
    if not applied and not overlay:
        return None
    swap = overlay["ref"] if overlay else None
    out = {"base": base, "governing": swap or applied}
    if overlay:
        out["swap"] = overlay
    return out


def _profile_view(doc):
    """The panel-facing shape of one profile document (identity hash
    exposed, semantic content included for the decomposition view)."""
    return {
        "name": doc["name"],
        "version": doc["version"],
        "description": doc.get("description", ""),
        "hash": profiles.semantic_hash(doc["profile"]),
        "profile": doc["profile"],
    }


def profiles_list(home):
    """All strategy profiles for the panel selector, each carrying its
    identity hash and its semantic content (the new-run form shows
    name@version and the decomposition, spec §5)."""
    return [_profile_view(doc) for doc in profiles.list_profiles(home)]


def save_profile(home, body):
    """Create or wholly replace an editable strategy profile.

    An incoming legacy ``sealed`` member is tolerated but has no authority
    and is omitted from the returned view.
    """
    if not isinstance(body, dict):
        raise ApiError(400, "profile document must be an object")
    doc = dict(body)
    doc["sealed"] = False
    try:
        saved = profiles.save(home, doc)
    except profiles.ProfileError as exc:
        raise ApiError(400, str(exc))
    return _profile_view(saved)


def model_profiles_list(home):
    """All model profiles for the catalogue (model-profiles slice 1).

    The API-visible document IS the stored source document — no view
    wrapper, no derived metadata. Unlike the strategy list, a stored but
    invalid definition is NOT skipped: the error propagates and the GET
    fails loudly with the common 500 envelope, so a damaged catalogue never
    looks merely shorter."""
    return model_profiles.list_model_profiles(home)


def save_model_profile(home, body):
    """Create or wholly replace one model profile — the catalogue's only
    edit operation. Validation refuses with 400 before any byte changes,
    so the prior definition survives every rejected input."""
    try:
        return model_profiles.save(home, body)
    except model_profiles.ModelProfileError as exc:
        raise ApiError(400, str(exc))


def _write_model_profile_selection(state_path, selection):
    """Atomically replace one run's exact current selection."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(state_path)), "model_profile.json"
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".model-profile-selection-",
        suffix=".tmp",
        dir=os.path.dirname(path),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(selection, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_model_profile_selection(home, run_id):
    """Return the validated current choice; absence reads default@medium."""
    entry = registry.get(registry.load(home), run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    selection = driver.read_current_model_profile_selection(
        entry["state_path"]
    )
    selected, _configuration = model_profiles.resolve_selection(
        home, selection
    )
    return selected


def set_model_profile_selection(home, run_id, body):
    """Validate, then wholly replace one run's current model-profile choice."""
    entry = registry.get(registry.load(home), run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        selected, _configuration = model_profiles.resolve_selection(home, body)
    except model_profiles.ModelProfileError as exc:
        raise ApiError(400, str(exc))
    _write_model_profile_selection(entry["state_path"], selected)
    _evict_summary(entry["state_path"])
    return selected


def set_slice_producer(home, run_id, slice_id, body):
    """Serialize one prospective producer write against task admission."""
    entry = registry.get(registry.load(home), run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        checked = tasks.validate_producer_override(body)
    except tasks.TaskRequestError as exc:
        raise ApiError(400, exc.code) from exc
    try:
        # Producer choice is best-effort bookkeeping.  Refuse a busy run
        # instead of queuing ahead of its next non-blocking driver step.
        with st.exclusive_mutation(entry["state_path"]):
            state = st.load(entry["state_path"])
            producer_map = tasks.update_slice_producer(
                state, slice_id, checked
            )
            st.save(entry["state_path"], state)
    except st.ConcurrentStateMutation as exc:
        raise ApiError(409, tasks.TASK_UPDATE_BUSY) from exc
    except tasks.TaskRequestError as exc:
        status = 409 if exc.code == tasks.TASK_SELECTION_FROZEN else 400
        raise ApiError(status, exc.code) from exc
    _evict_summary(entry["state_path"])
    return producer_map


def set_profile_swap(home, run_id, body):
    """Repoint a run at another strategy profile at RUNTIME. Swap != edit:
    the profile is never mutated in place. Resolve one complete retained
    identity/content pair and write it to the existing operator-owned overlay
    beside state. The driver applies it before its next action decision,
    records the transition in the generic ledger, and never consults the
    mutable source for that accepted change."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    if not isinstance(body, dict):
        raise ApiError(400, "profile swap body must be an object")
    name = body.get("profile")
    if not isinstance(name, str) or not name.strip():
        raise ApiError(400, "profile (name) is required")
    try:
        ref, content = profiles.resolve(home, name.strip())
    except profiles.ProfileError as exc:
        raise ApiError(400, str(exc))
    overlay = {"ref": ref, "profile": content, "at": registry.now_iso()}
    path = _profile_overlay_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".profile-swap-", suffix=".tmp", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(overlay, fh, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return overlay


MALFORMED_RAW_CLIP = 20000


def run_story(home, run_id, item):
    """The full record behind one pipeline chip — fetched on click, so
    the 2s-poll summary stays lean. item forms: round:<round_id>,
    seal:<unit>:<attempt>, draft:<unit>, repair:<unit>:<event seq>,
    verify:<event seq>, debt:<unit>, malformed:<event seq>."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    kind, _, ref = (item or "").partition(":")
    if kind == "repair":
        unit_key, _, seq = ref.rpartition(":")
        for unit in st.summary(state)["units"]:
            if unit["unit"] != unit_key:
                continue
            for repair in unit.get("repairs") or []:
                if str(repair.get("seq")) == seq:
                    return {
                        "story": "repair",
                        "unit": unit_key,
                        **repair,
                    }
        raise ApiError(404, "unknown repair episode %r" % ref)
    if kind == "malformed":
        # Worker-contract incident viewer: the raw path comes from the
        # run's OWN ledger event (never from the request), so this reads
        # only files the driver itself recorded.
        def _read_raw(rel):
            if not rel:
                return None
            path = rel
            if not os.path.isabs(path):
                # _save_raw records workspace-relative paths.
                path = os.path.join(state["workspace"], path)
            try:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    text = fh.read(MALFORMED_RAW_CLIP + 1)
                if len(text) > MALFORMED_RAW_CLIP:
                    text = text[:MALFORMED_RAW_CLIP] + "\n… (clipped)"
                return text
            except (OSError, TypeError):
                return None  # the raw may be gone; the event still tells

        for e in state["events"]:
            if e.get("type") != "worker_malformed" or str(e.get("seq")) != ref:
                continue
            return {
                "story": "malformed",
                "label": e.get("label"),
                "kind": e.get("kind"),
                "family": e.get("family"),
                "at": e.get("at"),
                "duration_s": e.get("duration_s"),
                "token_usage": e.get("token_usage"),
                "cost": e.get("cost"),
                "cost_partial": bool(e.get("cost_partial", False)),
                "token_usage_partial": bool(
                    e.get("token_usage_partial", False)
                ),
                "error": e.get("error"),
                "fatal": bool(e.get("fatal")),
                "stabilizer_retry": bool(e.get("stabilizer_retry")),
                "controlled_interruption": bool(
                    e.get("controlled_interruption")
                ),
                "infra_retry": bool(e.get("infra_retry")),
                "raw_path": e.get("raw_path"),
                "raw_text": _read_raw(e.get("raw_path")),
                # Fatal and stabilizer-retry strikes carry both attempts.
                "raw_text2": _read_raw(e.get("raw_path2")),
            }
        raise ApiError(404, "unknown malformed event %r" % ref)
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
                        "token_usage": r.get("token_usage"),
                        "cost": r.get("cost"),
                        "cost_partial": bool(r.get("cost_partial", False)),
                        "token_usage_partial": bool(
                            r.get("token_usage_partial", False)
                        ),
                        "model": r.get("model"),
                        "effort": r.get("effort"),
                        "invalidated": r.get("invalidated"),
                        "deferred_clean": bool(r.get("deferred_clean")),
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
                    halves = s_.get("halves") or {}
                    token_usage = None
                    for half in halves.values():
                        if half:
                            token_usage = st._add_token_usage(
                                token_usage, half.get("token_usage")
                            )
                    token_usage_partial = any(
                        (half or {}).get("token_usage_partial", False)
                        or (
                            (half or {}).get("duration_s")
                            and (half or {}).get("token_usage") is None
                        )
                        for half in halves.values()
                    )
                    cost = None
                    for half in halves.values():
                        if half:
                            cost = st._add_cost(cost, half.get("cost"))
                    cost_partial = any(
                        (half or {}).get("cost_partial", False)
                        or (
                            (half or {}).get("duration_s")
                            and (half or {}).get("cost") is None
                        )
                        for half in halves.values()
                    )
                    return {
                        "story": "seal",
                        "unit": unit_key,
                        "attempt": s_["attempt"],
                        "passed": s_["passed"],
                        "at": s_["at"],
                        "duration_s": sum(
                            (half or {}).get("duration_s") or 0
                            for half in halves.values()
                        ) or None,
                        "token_usage": token_usage,
                        "token_usage_partial": token_usage_partial,
                        "cost": cost,
                        "cost_partial": cost_partial,
                        "invalidated": s_.get("invalidated"),
                        # Wave provenance: resealed by the anchor's wave
                        # seal (None for ordinary seals).
                        "wave": s_.get("wave"),
                        "reviews": list(s_.get("reviews") or []),
                        "verification_event_seq": s_.get(
                            "verification_event_seq"
                        ),
                        "verification_recorded": (
                            "verification_event_seq" in s_
                        ),
                        # Historical records may still carry LLM halves;
                        # deterministic seals cite ordinary reviews instead.
                        "halves": halves,
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
                    "token_usage": d.get("token_usage"),
                    "cost": d.get("cost"),
                    "cost_partial": bool(d.get("cost_partial", False)),
                    "token_usage_partial": bool(
                        d.get("token_usage_partial", False)
                    ),
                    "at": d.get("at"),
                    "raw_path": d.get("raw_path"),
                    "artifact": unit.get("artifact"),
                    "result": d.get("result"),
                }
        raise ApiError(404, "unknown draft %r" % ref)
    if kind == "verify":
        for event in state["events"]:
            if (
                event.get("type") == "verification"
                and str(event.get("seq")) == ref
            ):
                return {
                    "story": "verify",
                    "unit": event.get("unit"),
                    "seq": event.get("seq"),
                    "at": event.get("at"),
                    "duration_s": event.get("duration_s"),
                    "boundary": event.get("boundary"),
                    "cadence": event.get("cadence"),
                    "ok": event.get("ok"),
                    "stable": event.get("stable"),
                    "reused": bool(event.get("reused")),
                    "vacuous": bool(event.get("vacuous")),
                    "fixer_certified": bool(
                        event.get("fixer_certified")
                    ),
                    "commands": list(event.get("commands") or []),
                    "output_tail": event.get("output_tail"),
                }
        raise ApiError(404, "unknown verification event %r" % ref)
    if kind == "debt":
        requeued_ids = st.requeued_debt_ids(state)
        for unit in state["units"]:
            if st.unit_key(unit) != ref:
                continue
            reclassify = [
                {
                    "finding_id": e.get("finding_id"),
                    "source_round": e.get("source_round"),
                    "reclassifier": e.get("reclassifier"),
                    "drift_risk": e.get("drift_risk"),
                    "drift_damage": e.get("drift_damage"),
                    "threshold": e.get("threshold"),
                    "defer_ok": e.get("defer_ok"),
                    "reason": e.get("reason"),
                    "at": e.get("at"),
                    "duration_s": e.get("duration_s"),
                    "requeued": bool(
                        e.get("defer_ok")
                        and e.get("finding_id")
                        in requeued_ids.get(ref, set())
                    ),
                    "token_usage": e.get("token_usage"),
                    "cost": e.get("cost"),
                    "cost_partial": bool(e.get("cost_partial", False)),
                    "token_usage_partial": bool(
                        e.get("token_usage_partial", False)
                    ),
                }
                for e in state["events"]
                if e.get("type") == "reclassify_recorded"
                and e.get("unit") == ref
            ]
            token_usage = None
            for event in reclassify:
                token_usage = st._add_token_usage(
                    token_usage, event.get("token_usage")
                )
            token_usage_partial = any(
                event.get("token_usage_partial", False)
                or event.get("token_usage") is None
                for event in reclassify
            )
            cost = None
            for event in reclassify:
                cost = st._add_cost(cost, event.get("cost"))
            cost_partial = any(
                event.get("cost_partial", False) for event in reclassify
            )
            return {
                "story": "debt",
                "cost": cost,
                "cost_partial": cost_partial,
                "unit": ref,
                "debt": st.active_debt(state, unit),
                "reclassify": reclassify,
                "duration_s": sum(
                    event.get("duration_s") or 0
                    for event in reclassify
                ) or None,
                "token_usage": token_usage,
                "token_usage_partial": token_usage_partial,
            }
        raise ApiError(404, "unknown unit %r" % ref)
    raise ApiError(
        400, "item must be round:/seal:/draft:/verify:/debt:"
    )


ARTIFACT_MAX = 1 * 1024 * 1024  # bytes served to the doc viewer per fetch

# workspace -> https web base (or None). Remotes effectively never change
# under a running service, and the panel polls run_detail every 2s, so the
# git subprocess must not run per poll.
_WEB_BASE_CACHE = {}
_WEB_BASE_LOCK = threading.Lock()


def _origin_url(path):
    try:
        proc = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def commit_web_base(workspace):
    """The https web base for linking a workspace's commits
    (<base>/commit/<sha>), derived from its origin remote. A local-path
    origin — the self-hosting clone recipe — is followed one hop so canon
    milestone clones link to the canon's own web remote. None when no web
    remote can be derived (the panel then simply shows no links)."""
    with _WEB_BASE_LOCK:
        if workspace in _WEB_BASE_CACHE:
            return _WEB_BASE_CACHE[workspace]
    base = None
    path = workspace
    for _ in range(2):  # origin, plus at most one local-path hop
        url = _origin_url(path)
        if url.startswith(("http://", "https://")):
            base = url[:-4] if url.endswith(".git") else url
            break
        scpish = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?/?$", url)
        if scpish:
            base = "https://%s/%s" % scpish.group(1, 2)
            break
        if url and os.path.isdir(os.path.expanduser(url)):
            path = os.path.expanduser(url)
            continue
        break
    with _WEB_BASE_LOCK:
        _WEB_BASE_CACHE[workspace] = base
    return base


def run_artifact(home, run_id, unit_key):
    """The markdown artifact recorded on one unit (skeleton doc, slice
    doc), fetched on demand for the panel's doc viewer. The client names
    a UNIT, never a filesystem path: only paths the run's own state
    recorded are ever read."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    unit = next(
        (u for u in state["units"] if st.unit_key(u) == unit_key), None
    )
    if unit is None:
        raise ApiError(404, "unknown unit %r" % unit_key)
    rel = unit.get("artifact")
    if not rel:
        raise ApiError(404, "unit %r has no artifact" % unit_key)
    path = rel if os.path.isabs(rel) else os.path.join(
        state.get("workspace") or entry["workspace"], rel
    )
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read(ARTIFACT_MAX + 1)
    except OSError as exc:
        raise ApiError(404, "artifact unreadable: %s" % exc)
    return {
        "unit": unit_key,
        "artifact": rel,
        "path": path,
        "truncated": len(content) > ARTIFACT_MAX,
        "content": content[:ARTIFACT_MAX],
    }


COMMIT_MAX = 512 * 1024  # bytes of `git show` served per fetch


def run_commit(home, run_id, unit_key):
    """The unit's commit as `git show` text (message + stat + patch), for
    the panel's local commit viewer. Like run_artifact, the client names a
    UNIT; the sha comes from the run's own state, and the diff is read
    from the run's workspace — it works whether or not the commit was ever
    pushed to a web remote. A sealed unit serves its gate commit; a unit
    still in flight serves its current working commit (the wip commit the
    fix loop amends), so the operator can inspect work as it lands."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    unit = next(
        (u for u in state["units"] if st.unit_key(u) == unit_key), None
    )
    if unit is None:
        raise ApiError(404, "unknown unit %r" % unit_key)
    sha, kind = unit.get("gate_commit"), "gate"
    if not sha:
        kind = "wip"
        for e in state["events"]:
            if (e.get("unit") == unit_key
                    and e.get("type") in ("wip_commit", "amended")):
                sha = e.get("sha")  # amends replace it; keep the latest
    if not sha:
        raise ApiError(404, "unit %r has no commit yet" % unit_key)
    workspace = state.get("workspace") or entry["workspace"]
    try:
        proc = subprocess.run(
            ["git", "-C", workspace, "show", "--stat", "--patch",
             "--no-color", sha],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApiError(409, "git show failed: %s" % exc)
    if proc.returncode != 0:
        raise ApiError(
            409, "git show %s failed: %s" % (sha, proc.stderr.strip())
        )
    text = proc.stdout
    return {
        "unit": unit_key,
        "sha": sha,
        "kind": kind,
        "truncated": len(text.encode("utf-8", "replace")) > COMMIT_MAX,
        "text": text[:COMMIT_MAX],
    }


def run_detail(home, run_id, log_tail=80):
    reap_exited_drivers(home)
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    detail = {"entry": entry, "status": run_status(entry, home=home), "summary": None}
    try:
        detail["summary"] = load_summary(
            entry["state_path"], model_profiles_home=home
        )
    except Exception as exc:
        detail["summary_error"] = str(exc)
    detail["log"] = read_log_tail(home, run_id, log_tail)
    detail["amendments"] = read_amendments(entry)
    detail["acts"] = read_acts(entry)
    detail["profile"] = read_profile(entry)
    detail["commit_web_base"] = commit_web_base(entry["workspace"])
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
# Request identity and project authorization


def access_view(who, home=None):
    out = {
        "user": who["email"],
        "admin": bool(who.get("admin")),
        "local": bool(who.get("local")),
        # Slugs where this caller holds the privileged rung, so the panel
        # can offer project-admin actions without probing each project.
        "project_admin": [],
    }
    if who.get("admin"):
        out["users"] = list(panel_access.USER_EMAILS)
    if home is not None and not who.get("admin"):
        try:
            record = registry.load_projects_record(home)
        except Exception:
            record = {"projects": []}
        out["project_admin"] = [
            project["slug"] for project in record.get("projects", [])
            if panel_access.can_administer_project(who, project)
        ]
    return out


def require_project_access(home, who, slug):
    try:
        slug = workareas.validate_project_slug(slug)
    except workareas.WorkAreaValidationError as exc:
        raise ApiError(400, exc.reason)
    rec = registry.load_projects_record(home)
    project = registry.get_project(rec, slug)
    if project is None:
        raise ApiError(404, UNKNOWN_PROJECT)
    if not panel_access.can_access_project(who, project):
        raise ApiError(403, FORBIDDEN)
    return project


def work_area_roots(home, who, slug, area):
    """Every root a caller may browse inside one work area.

    Authorization is the ordinary project gate, decided BEFORE the work
    area store is opened. The area must read as a live record through the
    same sealed seam launches use, so a picker can never reach into an
    area the product itself would refuse to bind — and, like a launch, it
    judges the roots by looking at them (the filter below) rather than by
    trusting a status some earlier launch recorded.
    """
    require_project_access(home, who, slug)
    try:
        store = workareas.WorkAreaStore(registry.projects_base(home), slug)
        resolved = store.read(area or "")
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    if not resolved.ok:
        raise _work_area_error(resolved.reason)
    roots = [resolved.value["primary"]["path"]]
    roots.extend(root["path"] for root in resolved.value["additional"])
    return [root for root in roots if os.path.isdir(root)]


def require_project_admin(home, who, slug):
    """Authorize a privileged project operation.

    Project membership permits ordinary work; this is the rung above it,
    for operations that can rewrite the work area itself. The service
    administrator holds it everywhere.
    """
    project = require_project_access(home, who, slug)
    if not panel_access.can_administer_project(who, project):
        raise ApiError(403, FORBIDDEN)
    return project


_GIT_SYNC_LEASES = set()
_GIT_SYNC_LEASES_GUARD = threading.Lock()


def workspace_sync_in_flight(workspace):
    """Whether a git sync currently holds this tree (or one containing it).

    The launch paths consult this so the exclusion runs BOTH ways: without
    it the lease only stopped a second sync, while a run or a discussion
    started mid-sync walked straight into the merge it was meant to avoid.
    """
    with _GIT_SYNC_LEASES_GUARD:
        held = list(_GIT_SYNC_LEASES)
    return any(gitsync.paths_overlap(path, workspace) for path in held)


@contextlib.contextmanager
def _git_sync_lease(home, workspace):
    """Exclude concurrent syncs, and runs starting, in this work area.

    The lease is TAKEN under the registry lock — the same lock start_run
    holds across its own check-and-spawn — so the two decisions are
    mutually exclusive without inventing a second lock: a run cannot be
    spawned in the gap between the sync's ownership check and the agent's
    first command, nor a sync begin inside a spawn.

    Keyed by realpath so two names for one directory contend. Cross-process
    exclusion is not attempted: the panel is this service, and a second
    orchestrator on the same home is already outside the model.
    """
    key = os.path.realpath(workspace)
    with registry.locked(home):
        with _GIT_SYNC_LEASES_GUARD:
            # Overlap, not equality: two syncs of a tree and a subtree of
            # it are the same collision as two syncs of one directory.
            if any(
                gitsync.paths_overlap(held, key) for held in _GIT_SYNC_LEASES
            ):
                raise ApiError(409, WORK_AREA_BUSY)
            _GIT_SYNC_LEASES.add(key)
    try:
        yield
    finally:
        # Released on every exit, including a watchdog kill or the
        # re-check refusing: a leaked lease would wedge every later sync
        # AND every run start in this tree.
        with _GIT_SYNC_LEASES_GUARD:
            _GIT_SYNC_LEASES.discard(key)


def _require_unowned_workspace(home, workspace, task_host=None):
    """Refuse while any orchestrator work owns this worktree.

    A milestone driver, live Brainstorming session, or actively executing
    standalone task can mutate the tree.  A sync merging underneath any of
    them would either lose an accepted result or commit transient bytes.
    """
    reap_exited_drivers(home)
    runs = [
        {"workspace": entry.get("workspace"), "alive": driver_alive(entry),
         "id": entry["id"], "name": entry.get("name")}
        for entry in registry.load(home)["runs"]
    ]
    if gitsync.active_run_blocking(runs, workspace) is not None:
        raise ApiError(409, WORK_AREA_BUSY)
    owns_workspace = getattr(task_host, "owns_workspace", None)
    if callable(owns_workspace) and owns_workspace(workspace):
        raise ApiError(409, WORK_AREA_BUSY)
    try:
        sessions = brainstorming_lifecycle.list_sessions(
            home, lambda _record: True
        )
    except Exception:
        # A brainstorming registry we cannot read is not evidence that the
        # area is free; refuse rather than merge under an unknown owner.
        raise ApiError(409, WORK_AREA_BUSY)
    for session in sessions:
        # A session with no readable state counts as live: unknown is not
        # evidence of being finished.
        if session.get("status") in ("success", "failure"):
            continue
        if gitsync.paths_overlap(session.get("target_path"), workspace):
            raise ApiError(409, WORK_AREA_BUSY)


def sync_project_git(home, slug, body, task_host=None):
    """Hand one work area to the project's lead family to align with git.

    Authorization happened at the route. The refusal that stays here is
    the deterministic one: a work area with a live milestone driver is
    never handed over, because the driver owns that worktree.
    """
    slug, rec = _require_declared(home, slug)
    project = registry.get_project(rec, slug)
    area = (body or {}).get("work_area")
    if not isinstance(area, str) or not area.strip():
        raise ApiError(400, workareas.INVALID_NAME)
    try:
        store = workareas.WorkAreaStore(registry.projects_base(home), slug)
        resolved = store.read(area)
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    if not resolved.ok:
        raise _work_area_error(resolved.reason)
    # This caller verifies its own requirements below — the primary is
    # here, and it is a repository root — instead of consulting a recorded
    # status for them.
    workspace = resolved.value["primary"]["path"]
    if not os.path.isdir(workspace):
        raise ApiError(400, driver.MISSING_PRIMARY_PATH)
    # The area must be the root of its OWN repository. Git run inside a
    # nested directory discovers the ENCLOSING repo, so an agent told to
    # align "this checkout" would commit and push a tree nobody authorized
    # — the same nesting hazard gitops guards on every other path.
    if not gitops.is_repo_root(workspace):
        raise ApiError(400, PRIMARY_NOT_REPO_ROOT)

    config = driver.load_config(None)
    if project.get("defaults"):
        driver.merge_config(config, project["defaults"])
    families = config.get("families_order") or ["codex"]
    family = families[0]
    seat = (config.get("model_defaults") or {}).get(family) or {}

    # One sync per work area at a time, with the ownership checks re-run
    # under the lease: without it two POSTs both passed a check taken
    # before either agent started, and a run could be launched into the
    # window between the check and the call.
    with _git_sync_lease(home, workspace):
        _require_unowned_workspace(home, workspace, task_host=task_host)
        try:
            outcome = gitsync.run_sync(
                config["commands"],
                config.get("timeouts"),
                family,
                workspace,
                model=seat.get("model"),
                effort=seat.get("effort"),
                stall_window_s=config.get("worker_stall_window_s"),
                stall_min_cpu_s=config.get("worker_stall_min_cpu_s"),
            )
        except runners.RunnerError as exc:
            raise ApiError(502, str(exc)) from exc
    return {
        "work_area": area,
        "workspace": workspace,
        "sync": outcome,
    }


def _run_project(entry):
    """Return the run's durable project binding."""
    slug = entry.get("project")
    if slug is not None:
        return slug
    # Compatibility for runs created before project handles were recorded in
    # the registry.  Newer registry bindings remain authoritative.
    try:
        return (load_summary(entry["state_path"]) or {}).get("project")
    except Exception:
        return None


def require_run_access(home, who, run_id):
    entry = registry.get(registry.load(home), run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    if who.get("admin"):
        return entry
    slug = _run_project(entry)
    if slug is None:
        raise ApiError(403, FORBIDDEN)
    require_project_access(home, who, slug)
    return entry


def require_brainstorming_access(home, who, record):
    """Authorize from the immutable service binding before session reads."""
    if who.get("admin"):
        return
    slug = record.get("project")
    if slug is None:
        raise ApiError(403, FORBIDDEN)
    require_brainstorming_project_access(home, who, slug)


def _brainstorming_task_attachment(home, record, allow_missing=False):
    """Find the one registered durable task that owns a task session."""
    caller = record.get("caller")
    identities = (
        (
            brainstorming_lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX,
            "current_profile",
        ),
        ("task:", "static"),
    )
    identity = next(
        (
            (caller[len(prefix):], authority)
            for prefix, authority in identities
            if isinstance(caller, str) and caller.startswith(prefix)
        ),
        None,
    )
    if identity is None:
        return None
    task_id, authority = identity
    if not task_id:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    context = record.get("execution_context")
    workspace = (
        context.get("workspace_path") if isinstance(context, dict) else None
    )
    matches = []
    try:
        direct = task_api.StandaloneTaskStore(home).records()
    except Exception:
        # A milestone attachment may still be authoritative.  If it is not,
        # the ordinary no-unique-match refusal below remains conservative.
        direct = []
    for task in direct:
        if (
            task.get("id") == task_id
            and (task.get("order") or {}).get("task_executor")
            == "brainstorming"
            and (task.get("resolved_staffing") or {}).get(
                "dispatch_authority"
            ) == authority
        ):
            try:
                task_workspace = task_api._workspace(task)
            except Exception:
                continue
            if (
                isinstance(workspace, str)
                and os.path.abspath(task_workspace)
                != os.path.abspath(workspace)
            ):
                continue
            matches.append({
                "standalone": True,
                "task_id": task_id,
                "dispatch_authority": authority,
                "terminal": task.get("result") is not None,
                "record": task,
            })
    try:
        entries = registry.load(home).get("runs") or []
    except Exception as exc:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE) from exc
    for entry in entries:
        if (
            isinstance(workspace, str)
            and os.path.abspath(entry.get("workspace") or "")
            != os.path.abspath(workspace)
        ):
            continue
        try:
            run_state = st.load(entry["state_path"])
        except Exception:
            continue
        owned = [
            task
            for task in run_state.get("tasks") or []
            if isinstance(task, dict)
            and task.get("id") == task_id
            and (task.get("order") or {}).get("task_executor")
            == "brainstorming"
            and (task.get("resolved_staffing") or {}).get(
                "dispatch_authority"
            ) == authority
        ]
        if len(owned) == 1:
            matches.append({
                "standalone": False,
                "state_path": os.path.abspath(entry["state_path"]),
                "task_id": task_id,
                "dispatch_authority": authority,
                "terminal": owned[0].get("result") is not None,
            })
        elif len(owned) > 1:
            raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    if not matches and allow_missing:
        return None
    if len(matches) != 1:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    return matches[0]


def _attached_brainstorming_staffing_session(
    home, session_id, record=None
):
    """Find the staffing session an ATTACHED discussion resolves through.

    A discussion created since the staffing cutover names its own session in
    its registry entry and never needs this. One created BEFORE it does not,
    and its entry is never rewritten to add one, so an explicit restart
    reattaches it to the run that owns it — through the session id held in
    ordinary milestone state, or the immutable task id held by an attached
    task session — and reads that run's one bound staffing session.
    Standalone sessions stay unattached and answer nothing.
    """
    if record is None:
        record = brainstorming_lifecycle._record_by_id(home, session_id)
    caller = record.get("caller")
    task_attachment = _brainstorming_task_attachment(home, record)
    if task_attachment is not None:
        if task_attachment["dispatch_authority"] != "current_profile":
            return None
        if task_attachment["terminal"]:
            raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
        return _run_staffing_session(task_attachment["state_path"])
    milestone_session = (
        isinstance(caller, str) and caller.startswith("milestone:")
    )
    if not milestone_session:
        return None
    context = record.get("execution_context")
    workspace = (
        context.get("workspace_path") if isinstance(context, dict) else None
    )
    matches = []
    try:
        entries = registry.load(home).get("runs") or []
    except Exception as exc:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE) from exc
    for entry in entries:
        if (
            isinstance(workspace, str)
            and os.path.abspath(entry.get("workspace") or "")
            != os.path.abspath(workspace)
        ):
            continue
        try:
            run_state = st.load(entry["state_path"])
        except Exception:
            # A registered state is only authoritative for this restart when
            # it actually exposes the session attachment.  Keep looking so
            # corruption in an unrelated run cannot mask a readable match;
            # if none is readable below, the ordinary unattached refusal
            # still prevents launch with the lifecycle roster.
            continue
        milestone_attached = milestone_session and any(
            ((unit.get("brainstorming_wait") or {}).get("session_id")
             == session_id)
            for unit in run_state.get("units") or []
            if isinstance(unit, dict)
        )
        if milestone_attached:
            matches.append(os.path.abspath(entry["state_path"]))
    if len(matches) > 1:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    if not matches:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    return _run_staffing_session(matches[0])


def _run_staffing_session(state_path):
    """The one staffing session a registered run binds, or None."""
    try:
        return st.staffing_session(st.load(state_path))
    except Exception as exc:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE) from exc


def _start_brainstorming_session(home, who, session_id, task_host=None):
    """Resume task-owned sessions through their durable adapter boundary."""
    record = brainstorming_lifecycle._record_by_id(home, session_id)
    require_brainstorming_access(home, who, record)
    projection = brainstorming_lifecycle.inspect_session(
        home,
        session_id,
        lambda current: require_brainstorming_access(home, who, current),
    )
    terminal = (
        projection["state"]["status"] in brainstorming.TERMINAL_STATUSES
    )
    attachment = _brainstorming_task_attachment(
        home, record, allow_missing=terminal
    )
    if terminal and attachment is None:
        return brainstorming_lifecycle.start_session(
            home,
            session_id,
            lambda current: require_brainstorming_access(home, who, current),
        )
    if attachment is None:
        return brainstorming_lifecycle.start_session(
            home,
            session_id,
            lambda current: require_brainstorming_access(home, who, current),
            resolve_staffing_session=(
                lambda current: (
                    _attached_brainstorming_staffing_session(
                        home,
                        session_id,
                        record=current,
                    )
                )
            ),
        )
    if attachment["terminal"]:
        projection = brainstorming_lifecycle.inspect_session(
            home,
            session_id,
            lambda current: require_brainstorming_access(home, who, current),
        )
        if projection["state"]["status"] in brainstorming.TERMINAL_STATUSES:
            return projection
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    if attachment["standalone"]:
        # This is the recovery half of create_task's sync exclusion. Hold
        # the same registry lock from lease inspection until the direct host
        # has claimed the workspace, so a sync cannot begin in between.
        with registry.locked(home):
            store = task_api.StandaloneTaskStore(home)
            state = {"tasks": store.records()}
            task = tasks.task_record(state, attachment["task_id"])
            if workspace_sync_in_flight(task_api._workspace(task)):
                raise ApiError(409, WORK_AREA_BUSY)
            try:
                projection = brainstorming_tasks.start_task(
                    state,
                    attachment["task_id"],
                    {},
                    home,
                    staffing_selection=(
                        brainstorming_tasks.standalone_staffing()
                    ),
                    session_id=session_id,
                )
            except brainstorming_lifecycle.PublicLifecycleError:
                raise
            except brainstorming_tasks.AdapterError as exc:
                raise ApiError(
                    503, brainstorming_lifecycle.UNAVAILABLE
                ) from exc
            task = tasks.task_record(state, attachment["task_id"])
            if task["result"] is not None:
                try:
                    store.record_result_locked(task["id"], task["result"])
                except tasks.TaskRecordError:
                    current = store.record(task["id"])
                    if current["result"] is None:
                        raise
                raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
            if task_host is not None:
                project = _task_project(task)
                task_host.start(
                    task,
                    lambda: _direct_task_config(home, project),
                )
        return projection
    staffing_selection = (
        {"session": _run_staffing_session(attachment["state_path"])}
        if attachment["dispatch_authority"] == "current_profile"
        else None
    )
    try:
        projection, task = brainstorming_tasks.start_persisted_task(
            attachment["state_path"],
            attachment["task_id"],
            {},
            home,
            staffing_selection=staffing_selection,
            session_id=session_id,
        )
    except st.ConcurrentStateMutation as exc:
        raise ApiError(409, WORK_AREA_BUSY) from exc
    except brainstorming_tasks.AdapterError as exc:
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE) from exc
    if task["result"] is not None:
        _evict_summary(attachment["state_path"])
        raise ApiError(503, brainstorming_lifecycle.UNAVAILABLE)
    return projection


def brainstorming_visibility(home, who):
    """A record-level predicate for the Brainstorming list route.

    Refusals filter (a session the caller may not see simply is not
    listed); a broken standing-access state still raises, exactly as it
    does on the single-session routes — a fault must never render as the
    healthy "no sessions" answer.
    """

    def visible(record):
        if who.get("admin"):
            return True
        slug = record.get("project")
        if slug is None:
            # A project-less session belongs to the administrator alone.
            return False
        try:
            require_brainstorming_project_access(home, who, slug)
        except ApiError as exc:
            if exc.status >= 500:
                raise
            return False
        return True

    return visible


def require_brainstorming_project_access(home, who, slug):
    """Keep Brainstorming refusals typed if standing access state is broken."""
    try:
        return require_project_access(home, who, slug)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            503, brainstorming_lifecycle.UNAVAILABLE
        ) from exc


def visible_runs(home, who):
    reap_exited_drivers(home)
    entries = registry.load(home)["runs"]
    if who.get("admin"):
        visible = entries
    else:
        rec = registry.load_projects_record(home)
        allowed = {
            project["slug"] for project in rec["projects"]
            if panel_access.can_access_project(who, project)
        }
        # Authorize before run_status reads or projects any state.  The API
        # and its running/total counters never process a foreign run.
        visible = [entry for entry in entries if _run_project(entry) in allowed]
    return [run_status(entry, home=home) for entry in visible]


# ---------------------------------------------------------------------------
# Standalone tasks


def _raise_task_request(exc):
    status = 503 if exc.code == tasks.TASK_UNAVAILABLE else 400
    raise ApiError(status, exc.code) from exc


def _direct_task_config(home, project=None):
    config = driver.load_config(None)
    if project is None:
        return config
    record = registry.load_projects_record(home)
    declared = registry.get_project(record, project)
    if declared is None:
        raise RuntimeError("project configuration is unavailable")
    if declared.get("defaults"):
        driver.merge_config(config, declared["defaults"])
    return config


def _projectless_task_work_area(who, value):
    if not who.get("admin"):
        raise ApiError(403, FORBIDDEN)
    if set(value) != {"workspace_path", "primary", "additional"}:
        raise tasks.TaskRequestError(
            tasks.INVALID_TASK_REQUEST, "invalid project-less work area"
        )
    workspace = value["workspace_path"]
    primary = value["primary"]
    additional = value["additional"]
    if (
        not isinstance(workspace, str)
        or not os.path.isabs(workspace)
        or workspace != primary
        or not os.path.isdir(workspace)
        or not isinstance(additional, list)
        or any(
            not isinstance(root, str)
            or not os.path.isabs(root)
            or not os.path.isdir(root)
            for root in additional
        )
    ):
        raise tasks.TaskRequestError(
            tasks.INVALID_TASK_REQUEST, "invalid project-less work area"
        )
    return copy.deepcopy(value)


def _task_roots(work_area):
    primary = work_area["primary"]
    primary = primary.get("path") if isinstance(primary, dict) else primary
    additional = []
    for root in work_area.get("additional") or []:
        additional.append(root.get("path") if isinstance(root, dict) else root)
    return primary, [primary] + additional


def _validate_task_references(order):
    request = order["request"]
    primary, roots = _task_roots(request["work_area"])
    roots = [os.path.realpath(root) for root in roots]
    for reference in request["reference_documents"]:
        candidate = reference if os.path.isabs(reference) else os.path.join(
            primary, reference
        )
        if not kvstore.path_is_inside_roots(os.path.realpath(candidate), roots):
            raise tasks.TaskRequestError(
                tasks.INVALID_TASK_REQUEST,
                "task reference_documents must stay inside readable roots",
            )
    return primary


def _resolve_direct_task_order(home, who, body):
    try:
        order = tasks.validate_order(body)
        selector = order["request"]["work_area"]
        if set(selector) == {"project", "work_area"}:
            project = require_project_access(home, who, selector["project"])
            binding = {
                "directory": registry.projects_base(home),
                "project": selector["project"],
                "work_area": selector["work_area"],
            }
            if project.get("defaults"):
                binding["defaults"] = project["defaults"]
            try:
                _workspace, work_area, config = driver._resolve_project_binding(
                    binding, None, None
                )
            except driver.ProjectResolutionError as exc:
                raise _work_area_error(exc.cause) from exc
            project_slug = work_area["project"]
        elif set(selector) == {"workspace_path", "primary", "additional"}:
            work_area = _projectless_task_work_area(who, selector)
            project_slug = None
            config = _direct_task_config(home)
        else:
            raise tasks.TaskRequestError(
                tasks.INVALID_TASK_REQUEST, "invalid task work area selector"
            )
        order["request"]["work_area"] = work_area
        primary = _validate_task_references(order)
        order = tasks._canonical_output_directory(order, primary)
        if order["task_executor"] == "agent_call":
            staffing = task_api.worker_staffing(config)
        else:
            staffing = brainstorming_tasks.resolve_staffing(
                config,
                os.path.realpath(primary),
                brainstorming_tasks.standalone_staffing(),
            )
        return order, staffing, primary, project_slug
    except tasks.TaskRequestError as exc:
        _raise_task_request(exc)


def create_task(home, who, body, host):
    order, staffing, primary, project = _resolve_direct_task_order(
        home, who, body
    )
    store = task_api.StandaloneTaskStore(home)
    resolver = lambda: _direct_task_config(home, project)
    with registry.locked(home):
        if workspace_sync_in_flight(primary):
            raise ApiError(409, WORK_AREA_BUSY)
        record = store.admit_locked(order, staffing, primary)
        try:
            host.start(record, resolver)
        except Exception:
            # Admission already succeeded. Preserve the acknowledged identity
            # and make the observed handoff failure terminal when writable.
            try:
                store.record_result_locked(record["id"], {
                    "status": "failure",
                    "reason": "Task execution handoff failed",
                    "duration_s": 0.0,
                    "token_usage": None,
                    "token_usage_partial": True,
                    "cost": None,
                    "cost_partial": True,
                    "native_result": None,
                })
            except Exception:
                pass
    return record


def _task_project(record):
    work_area = ((record.get("order") or {}).get("request") or {}).get(
        "work_area"
    ) or {}
    return work_area.get("project")


def _allowed_task_projects(home, who):
    if who.get("admin"):
        return None
    projects_record = registry.load_projects_record(home)
    return {
        project["slug"]
        for project in projects_record.get("projects", [])
        if panel_access.can_access_project(who, project)
    }


def _registered_task_records(home, allowed_projects=None):
    records = []
    for entry in registry.load(home)["runs"]:
        if (
            allowed_projects is not None
            and _run_project(entry) not in allowed_projects
        ):
            continue
        try:
            state = st.load(entry["state_path"])
            run_records = [
                record for record in tasks.task_records(state)
                if (
                    allowed_projects is None
                    or _task_project(record) in allowed_projects
                )
            ]
        except Exception:
            continue
        records.extend(run_records)
    return records


def visible_tasks(home, who):
    allowed = _allowed_task_projects(home, who)
    direct = task_api.StandaloneTaskStore(home).records()
    if allowed is not None:
        direct = [
            record for record in direct if _task_project(record) in allowed
        ]
    return [
        tasks.projected_task_record(record)
        for record in direct + _registered_task_records(home, allowed)
    ]


def _visible_run_task_state(home, who, run_id):
    entry = require_run_access(home, who, run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(500, "task storage unavailable") from exc
    return state, _allowed_task_projects(home, who)


def visible_run_tasks(home, who, run_id):
    """Return canonical records from one authorized milestone only."""
    state, allowed = _visible_run_task_state(home, who, run_id)
    try:
        records = tasks.task_records(state)
    except tasks.TaskRecordError as exc:
        raise ApiError(500, "task storage unavailable") from exc
    if allowed is not None:
        records = [
            record for record in records if _task_project(record) in allowed
        ]
    return [tasks.projected_task_record(record) for record in records]


def read_task(home, who, task_id, run_id=None):
    if run_id is not None:
        state, allowed = _visible_run_task_state(home, who, run_id)
        try:
            record = tasks.task_record(state, task_id)
        except tasks.TaskRecordError as exc:
            if str(exc).startswith("unknown task"):
                raise ApiError(404, "not found") from exc
            raise ApiError(500, "task storage unavailable") from exc
        if allowed is not None and _task_project(record) not in allowed:
            raise ApiError(403, FORBIDDEN)
        return tasks.projected_task_record(record)

    allowed = _allowed_task_projects(home, who)
    direct = task_api.StandaloneTaskStore(home).records()
    record = next(
        (record for record in direct if record.get("id") == task_id), None
    )
    if record is not None:
        if allowed is not None and _task_project(record) not in allowed:
            raise ApiError(403, FORBIDDEN)
        return tasks.projected_task_record(record)

    entries = registry.load(home)["runs"]
    if allowed is None:
        accessible = entries
        inaccessible = []
    else:
        accessible = [
            entry for entry in entries if _run_project(entry) in allowed
        ]
        inaccessible = [
            entry for entry in entries if _run_project(entry) not in allowed
        ]

    unreadable_accessible = False
    for entry in accessible:
        try:
            state = st.load(entry["state_path"])
            records = tasks.task_records(state)
        except Exception:
            unreadable_accessible = True
            continue
        record = next(
            (row for row in records if row.get("id") == task_id), None
        )
        if record is not None:
            if allowed is not None and _task_project(record) not in allowed:
                raise ApiError(403, FORBIDDEN)
            return tasks.projected_task_record(record)

    # Preserve the public foreign-record classification without letting an
    # unreadable, unauthorized run couple its faults to another inspection.
    for entry in inaccessible:
        try:
            state = st.load(entry["state_path"])
            records = tasks.task_records(state)
        except Exception:
            continue
        if any(row.get("id") == task_id for row in records):
            raise ApiError(403, FORBIDDEN)

    if unreadable_accessible:
        raise ApiError(500, "task storage unavailable")
    raise ApiError(404, "not found")


# ---------------------------------------------------------------------------
# HTTP layer


def make_handler(home, task_host=None):
    task_host = task_host or task_api.DirectTaskHost(home)

    class Handler(BaseHTTPRequestHandler):
        def _route(self):
            """Split the request target into (path, query dict)."""
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            return parsed.path, {k: v[-1] for k, v in query.items()}

        def _who(self):
            try:
                return panel_access.identity(self.headers)
            except panel_access.AccessDenied:
                raise ApiError(403, FORBIDDEN)

        def _require_admin(self, who):
            if not who.get("admin"):
                raise ApiError(403, FORBIDDEN)

        def _authorize_project_route(self, who, method, segments):
            if who.get("admin"):
                return
            if not segments:
                if method != "GET":
                    self._require_admin(who)
                return
            if len(segments) == 2 and segments[1] == "users":
                self._require_admin(who)
                return
            if len(segments) == 2 and segments[1] == "git-sync":
                # The privileged rung: it can rewrite the work area's
                # contents, so membership is not enough.
                require_project_admin(home, who, segments[0])
                return
            if method != "GET":
                self._require_admin(who)
                return
            require_project_access(home, who, segments[0])

        def do_GET(self):
            try:
                brainstorming_lifecycle.reap_children(home)
                route, query = self._route()
                who = self._who()
                if route in ("/", "/index.html"):
                    self._static("panel.html", "text/html; charset=utf-8")
                elif route == "/api/access":
                    self._json(200, {"ok": True, **access_view(who, home)})
                elif route == "/api/task-executors":
                    self._json(200, {
                        "ok": True,
                        "task_executors": tasks.task_executor_catalogue(),
                    })
                elif route == "/api/tasks":
                    run_id = query.get("run_id")
                    self._json(
                        200,
                        {
                            "ok": True,
                            "tasks": (
                                visible_run_tasks(home, who, run_id)
                                if run_id is not None
                                else visible_tasks(home, who)
                            ),
                        },
                    )
                elif route.startswith("/api/tasks/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) == 4 and parts[3]:
                        self._json(200, {
                            "ok": True,
                            "task": read_task(
                                home, who, parts[3],
                                run_id=query.get("run_id"),
                            ),
                        })
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                elif route == "/api/runs":
                    self._json(200, {"ok": True, "runs": visible_runs(home, who)})
                elif route == "/api/recents":
                    self._require_admin(who)
                    self._json(200, {"ok": True, **recent_paths(home)})
                elif route == "/api/ui-state":
                    self._json(200, {"ok": True, **registry.load_ui_state(home)})
                elif route == "/api/profiles":
                    self._json(200, {
                        "ok": True,
                        "profiles": profiles_list(home),
                        "decisions": profiles.decision_catalogue(),
                    })
                elif route == "/api/model-profiles":
                    self._json(
                        200,
                        {"ok": True, "profiles": model_profiles_list(home)},
                    )
                elif route == "/api/staffing/documents":
                    self._json(
                        200,
                        {
                            "ok": True,
                            "documents": staffing_documents_list(home),
                        },
                    )
                elif route.startswith("/api/staffing/sessions/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) == 5 and parts[4]:
                        record = read_staffing_session(home, who, parts[4])
                        self._json(200, {
                            "ok": True,
                            **staffing_session_view(home, record),
                        })
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                elif route == "/api/fs":
                    # Unscoped browsing spans the whole host and stays
                    # administrative. A project+work_area scope authorizes
                    # like every other project route and confines the
                    # listing to that area's roots, so a member can pick a
                    # target inside their own area without being handed
                    # the operator's machine.
                    roots = None
                    if query.get("project") or query.get("work_area"):
                        roots = work_area_roots(
                            home,
                            who,
                            query.get("project"),
                            query.get("work_area"),
                        )
                    else:
                        self._require_admin(who)
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
                        roots=roots,
                    )
                    self._json(200, {"ok": True, **listing})
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    segments = project_route_segments(route)
                    self._authorize_project_route(who, "GET", segments)
                    if not segments:
                        status, payload = 200, {
                            "ok": True, "projects": list_projects(home, who)
                        }
                    else:
                        status, payload = projects_api(
                            home, "GET", segments, None
                        )
                    self._json(status, payload)
                elif route == "/api/brainstorming/sessions":
                    self._json(
                        200,
                        {
                            "ok": True,
                            "sessions": brainstorming_lifecycle.list_sessions(
                                home, brainstorming_visibility(home, who)
                            ),
                        },
                    )
                elif route.startswith("/api/brainstorming/sessions/"):
                    parts = route.rstrip("/").split("/")
                    if (
                        len(parts) == 7
                        and parts[4]
                        and parts[5] == "activity"
                        and parts[6]
                    ):
                        activity = brainstorming_lifecycle.view_activity(
                            home,
                            parts[4],
                            parts[6],
                            lambda record: require_brainstorming_access(
                                home, who, record
                            ),
                            ARTIFACT_MAX,
                        )
                        self._json(200, {"ok": True, **activity})
                    elif (
                        len(parts) == 6
                        and parts[4]
                        and parts[5] == "intervention"
                    ):
                        intervention = (
                            brainstorming_lifecycle.view_external_intervention(
                                home,
                                parts[4],
                                lambda record: require_brainstorming_access(
                                    home, who, record
                                ),
                            )
                        )
                        self._json(
                            200,
                            {"ok": True, "intervention": intervention},
                        )
                    elif (
                        len(parts) == 6
                        and parts[4]
                        and parts[5] == "view"
                    ):
                        view = brainstorming_lifecycle.view_session(
                            home,
                            parts[4],
                            lambda record: require_brainstorming_access(
                                home, who, record
                            ),
                            ARTIFACT_MAX,
                            resolve_staffing_session=lambda record: (
                                _attached_brainstorming_staffing_session(
                                    home, record["id"], record=record
                                )
                            ),
                        )
                        self._json(200, {"ok": True, "view": view})
                    elif len(parts) == 5 and parts[4]:
                        session = brainstorming_lifecycle.inspect_session(
                            home,
                            parts[4],
                            lambda record: require_brainstorming_access(
                                home, who, record
                            ),
                        )
                        self._json(
                            200, {"ok": True, "session": session}
                        )
                    else:
                        self._json(
                            404, {"ok": False, "error": "not found"}
                        )
                elif route.startswith("/api/runs/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) >= 4:
                        require_run_access(home, who, parts[3])
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
                    elif len(parts) == 5 and parts[4] == "artifact":
                        self._json(200, {
                            "ok": True,
                            **run_artifact(home, parts[3],
                                           query.get("unit", "")),
                        })
                    elif len(parts) == 5 and parts[4] == "commit":
                        self._json(200, {
                            "ok": True,
                            **run_commit(home, parts[3],
                                         query.get("unit", "")),
                        })
                    elif len(parts) == 5 and parts[4] == "model-profile":
                        selection = read_model_profile_selection(
                            home, parts[3]
                        )
                        self._json(
                            200, {"ok": True, "selection": selection}
                        )
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except brainstorming_lifecycle.PublicLifecycleError as exc:
                self._json(
                    exc.status, {"ok": False, "error": exc.code}
                )
            except Exception as exc:  # panel must never crash the service
                self._json(500, {"ok": False, "error": str(exc)})

        def do_POST(self):
            try:
                brainstorming_lifecycle.reap_children(home)
                route, _query = self._route()
                who = self._who()
                if route == "/api/tasks":
                    task = create_task(home, who, self._task_body(), task_host)
                    self._json(201, {"ok": True, "task": task})
                elif route == "/api/brainstorming/sessions":
                    body = self._brainstorming_body()
                    checked = brainstorming_lifecycle.validate_create_body(
                        body
                    )
                    project = None
                    if checked["project"] is None:
                        self._require_admin(who)
                    else:
                        project = require_brainstorming_project_access(
                            home, who, checked["project"]
                        )
                    if checked["staffing_session"] is not None:
                        # A named session must be one this caller could
                        # already read: the same authorization the session's
                        # own route applies, so a discussion cannot become a
                        # side door onto another project's staffing. Unknown
                        # is 404 `unknown_staffing_session` and inaccessible
                        # is 403, exactly as `GET /api/staffing/sessions/<id>`
                        # answers them. Omitted names no session at all and
                        # asks nothing here: those calls take the default
                        # document, and their activity says so.
                        read_staffing_session(
                            home, who, checked["staffing_session"]
                        )
                    # A discussion started into a tree a sync is merging
                    # would fight it, the same way a run would — and the
                    # check must not straddle a sync beginning between it
                    # and the create, so both sit under the lock the lease
                    # is taken beneath. create_session takes only the
                    # BRAINSTORMING registry lock inside, so there is no
                    # cycle with this one.
                    with registry.locked(home):
                        if workspace_sync_in_flight(
                            (body.get("request") or {}).get("workspace_path")
                        ):
                            raise ApiError(409, WORK_AREA_BUSY)
                        # A discussion verifies the same roots a milestone
                        # does — and records the same finding. What it does
                        # NOT verify is the milestone's git repository
                        # root: brainstorming writes no gate ledger, so a
                        # work area is usable here the moment its roots
                        # exist, whether or not a milestone has ever run.
                        _record_launch_roots(
                            home, checked["project"], checked["work_area"]
                        )
                        session = brainstorming_lifecycle.create_session(
                            home,
                            body,
                            who["email"],
                            project_record=project,
                        )
                    self._json(
                        201, {"ok": True, "session": session}
                    )
                elif route.startswith("/api/brainstorming/sessions/"):
                    parts = route.rstrip("/").split("/")
                    if (
                        len(parts) == 6
                        and parts[4]
                        and parts[5] == "floor"
                    ):
                        body = self._brainstorming_body()
                        delivered = (
                            brainstorming_lifecycle.submit_floor_intervention(
                                home,
                                parts[4],
                                body,
                                lambda record: require_brainstorming_access(
                                    home, who, record
                                ),
                                who["email"],
                            )
                        )
                        self._json(200, {"ok": True, **delivered})
                    elif (
                        len(parts) == 6
                        and parts[4]
                        and parts[5] == "intervention"
                    ):
                        body = self._brainstorming_body()
                        intervention = (
                            brainstorming_lifecycle.submit_external_intervention(
                                home,
                                parts[4],
                                body,
                                lambda record: require_brainstorming_access(
                                    home, who, record
                                ),
                            )
                        )
                        self._json(
                            200,
                            {"ok": True, "intervention": intervention},
                        )
                    elif (
                        len(parts) == 6
                        and parts[4]
                        and parts[5] in ("stop", "start")
                    ):
                        body = self._brainstorming_body()
                        if body:
                            raise ApiError(
                                400,
                                brainstorming_lifecycle.INVALID_REQUEST,
                            )
                        if parts[5] == "stop":
                            session = brainstorming_lifecycle.stop_session(
                                home, parts[4],
                                lambda record: require_brainstorming_access(
                                    home, who, record
                                ),
                            )
                        else:
                            session = _start_brainstorming_session(
                                home, who, parts[4], task_host=task_host
                            )
                        self._json(
                            200, {"ok": True, "session": session}
                        )
                    else:
                        self._json(
                            404, {"ok": False, "error": "not found"}
                        )
                elif route == "/api/runs":
                    body = self._body()
                    if body.get("project") is None:
                        self._require_admin(who)
                    elif not who.get("admin"):
                        require_project_access(home, who, body.get("project"))
                    entry = create_run(home, body)
                    self._json(201, {"ok": True, "run": run_status(entry, home=home)})
                elif route == "/api/ui-state":
                    self._json(
                        200,
                        {"ok": True, **registry.save_ui_state(home, self._body())},
                    )
                elif route == "/api/profiles":
                    self._require_admin(who)
                    saved = save_profile(home, self._body())
                    self._json(200, {"ok": True, "profile": saved})
                elif route == "/api/model-profiles":
                    self._require_admin(who)
                    saved = save_model_profile(home, self._body())
                    self._json(200, {"ok": True, "profile": saved})
                elif route == "/api/staffing/documents":
                    self._require_admin(who)
                    saved = save_staffing_document(
                        home,
                        self._staffing_body(INVALID_STAFFING_DOCUMENT),
                    )
                    self._json(200, {"ok": True, "document": saved})
                elif route == "/api/staffing/sessions":
                    session = create_staffing_session(
                        home, who,
                        self._staffing_body(INVALID_STAFFING_SESSION),
                    )
                    self._json(201, {
                        "ok": True,
                        **staffing_session_view(home, session),
                    })
                elif route.startswith("/api/staffing/sessions/"):
                    parts = route.rstrip("/").split("/")
                    # Both session writes authorize from the STORED record
                    # before the body is read at all, so an unknown or
                    # foreign session is answered as such rather than as
                    # whatever the body got wrong.
                    if len(parts) == 5 and parts[4]:
                        record = read_staffing_session(home, who, parts[4])
                        edited = edit_staffing_session(
                            home, record["id"],
                            self._staffing_body(INVALID_STAFFING_SESSION),
                        )
                        self._json(200, {
                            "ok": True,
                            **staffing_session_view(home, edited),
                        })
                    elif (len(parts) == 6 and parts[4]
                            and parts[5] == "resolve"):
                        record = read_staffing_session(home, who, parts[4])
                        answer = resolve_staffing_request(
                            home, record,
                            self._staffing_body(INVALID_STAFFING_REQUEST),
                        )
                        self._json(200, {"ok": True, "staffing": answer})
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    segments = project_route_segments(route)
                    self._authorize_project_route(who, "POST", segments)
                    status, payload = projects_api(
                        home, "POST", segments,
                        self._body(),
                        task_host=task_host,
                    )
                    self._json(status, payload)
                elif route.startswith("/api/runs/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) >= 4:
                        require_run_access(home, who, parts[3])
                    if (
                        len(parts) == 7
                        and parts[4] == "slices"
                        and parts[6] == "producer"
                    ):
                        try:
                            slice_id = int(parts[5])
                        except (TypeError, ValueError):
                            raise ApiError(400, tasks.INVALID_TASK_REQUEST)
                        producer_map = set_slice_producer(
                            home, parts[3], slice_id, self._body()
                        )
                        self._json(
                            200,
                            {
                                "ok": True,
                                "producer_task_executor": producer_map,
                            },
                        )
                    elif len(parts) == 5 and parts[4] == "start":
                        entry = start_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry, home=home)})
                    elif len(parts) == 5 and parts[4] == "stop":
                        self._json(200, {"ok": True, **stop_run(home, parts[3])})
                    elif len(parts) == 5 and parts[4] == "name":
                        entry = rename_run(home, parts[3], self._body())
                        self._json(200, {"ok": True, "run": entry})
                    elif len(parts) == 5 and parts[4] == "resume":
                        entry = resume_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry, home=home)})
                    elif len(parts) == 5 and parts[4] == "pause-after-seal":
                        self._json(200, {
                            "ok": True,
                            **set_pause_after_seal(
                                home, parts[3], self._body()
                            ),
                        })
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
                    elif len(parts) == 5 and parts[4] == "model-profile":
                        selection = set_model_profile_selection(
                            home, parts[3], self._body()
                        )
                        self._json(
                            200, {"ok": True, "selection": selection}
                        )
                    elif len(parts) == 5 and parts[4] == "profile":
                        swap = set_profile_swap(home, parts[3], self._body())
                        self._json(200, {"ok": True, "profile_swap": swap})
                    else:
                        self._json(404, {"ok": False, "error": "not found"})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except brainstorming_lifecycle.PublicLifecycleError as exc:
                self._json(
                    exc.status, {"ok": False, "error": exc.code}
                )
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        def do_PATCH(self):
            try:
                brainstorming_lifecycle.reap_children(home)
                route, _query = self._route()
                who = self._who()
                parts = route.rstrip("/").split("/")
                if (len(parts) == 5 and route.startswith("/api/runs/")
                        and parts[4] == "acts"):
                    require_run_access(home, who, parts[3])
                    acts = patch_acts(home, parts[3], self._body())
                    self._json(200, {"ok": True, "acts": acts})
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})

        def do_DELETE(self):
            try:
                brainstorming_lifecycle.reap_children(home)
                route, query = self._route()
                who = self._who()
                parts = route.rstrip("/").split("/")
                if (len(parts) == 6 and route.startswith("/api/runs/")
                        and parts[4] == "amendments"):
                    require_run_access(home, who, parts[3])
                    amendments = delete_amendment(home, parts[3], parts[5])
                    self._json(200, {"ok": True, "amendments": amendments})
                elif len(parts) == 4 and route.startswith("/api/runs/"):
                    require_run_access(home, who, parts[3])
                    self._json(200, {"ok": True, **delete_run(
                        home, parts[3], purge=query.get("purge") == "1")})
                elif (
                    len(parts) == 5
                    and route.startswith("/api/brainstorming/sessions/")
                    and parts[4]
                ):
                    result = brainstorming_lifecycle.delete_session(
                        home,
                        parts[4],
                        lambda record: require_brainstorming_access(
                            home, who, record
                        ),
                        purge=query.get("purge") == "1",
                    )
                    self._json(200, {"ok": True, **result})
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    segments = project_route_segments(route)
                    self._authorize_project_route(who, "DELETE", segments)
                    status, payload = projects_api(
                        home, "DELETE", segments, None,
                        query=query,
                    )
                    self._json(status, payload)
                else:
                    self._json(404, {"ok": False, "error": "not found"})
            except ApiError as exc:
                self._json(exc.status, {"ok": False, "error": str(exc)})
            except brainstorming_lifecycle.PublicLifecycleError as exc:
                self._json(
                    exc.status, {"ok": False, "error": exc.code}
                )
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

        def _brainstorming_body(self):
            try:
                return self._body()
            except ApiError as exc:
                if exc.status in (400, 413):
                    raise ApiError(
                        400, brainstorming_lifecycle.INVALID_REQUEST
                    ) from exc
                raise

        def _task_body(self):
            try:
                return self._body()
            except ApiError as exc:
                if exc.status in (400, 413):
                    raise ApiError(400, tasks.INVALID_TASK_REQUEST) from exc
                raise

        def _staffing_body(self, token):
            """One staffing route's body under that route's fixed token.

            The `_task_body` pattern: a body the service could not read at
            all is that route's own invalid-input refusal, not a second
            vocabulary a caller would have to string-match.
            """
            try:
                return self._body()
            except ApiError as exc:
                if exc.status in (400, 413):
                    raise ApiError(400, token) from exc
                raise

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
# and waits for the operator. Sized so the probing window covers a full
# sleeping-operator night: with the linear 10min*n spacing, 12 attempts
# spread over ~13 cumulative hours — a sustained provider outage (the
# 2026-07-06 correlated capacity blackout classified `busy`) must not
# strand a run at 4 probes / ~100 minutes. Progress still resets the
# counter, so the cap only ever bites consecutive no-progress failures.
AUTO_RESUME_CAPS = {"quota": 12, "network": 12, "busy": 12, "timeout": 12}
# Emergency resume of an UNCLASSIFIED failure ("unknown"): the classifier
# could not type it (a novel banner, or a correlated outage that took the
# classifier down too). Retried forever, this far apart. No cap by
# deliberate operator choice: a stuck run should keep probing rather than
# sit dead — a transient clears, an irrecoverable one costs only a cheap
# periodic re-check, and the operator can always Stop it.
EMERGENCY_RESUME_MIN = 15
EMERGENCY_RESUME_S = EMERGENCY_RESUME_MIN * 60


def append_log(home, run_id, text):
    try:
        # The run's log may be written before any driver ever started
        # (e.g. a projection fault on a never-started run): the log is
        # such faults' only surface, so create the directory here rather
        # than silently dropping the line.
        os.makedirs(registry.logs_dir(home), exist_ok=True)
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
            summ = load_summary(
                entry["state_path"], model_profiles_home=home
            )
            if summ is None:
                continue
            # The guard's periodic scan is the projection's second
            # observation path (change-driven, contained): terminal
            # states reach the store even when no panel is polling.
            _pump_projection(home, entry, summ)
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
            if ftype == "unknown":
                # Emergency resume: a failure we could not classify is retried
                # FOREVER, EMERGENCY_RESUME_MIN apart, no cap. The run re-fails
                # with a fresh timestamp, so the cadence holds regardless of
                # the driver's replay events; the first probe waits a full
                # interval after the failure so we never retry straight into
                # an ongoing outage.
                failed_at = st._epoch(failure.get("at")) or 0
                last = max(entry.get("last_emergency_resume_at") or 0,
                           failed_at)
                if now - last < EMERGENCY_RESUME_S:
                    actions.append((run_id, "emergency-spaced"))
                    continue
                resume_run(home, run_id)
                registry.update(home, run_id, last_emergency_resume_at=now)
                append_log(
                    home, run_id,
                    "[guard] emergency resume of an unclassified failure; "
                    "retrying every %d min until it clears or you Stop it\n"
                    % EMERGENCY_RESUME_MIN,
                )
                actions.append((run_id, "emergency-resume"))
                continue
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


def make_server(home, port, task_host=None):
    # Seed the two starter strategy profiles (strict, light) when missing,
    # so the panel's new-run selector always has something to offer.
    # Idempotent and best-effort: a seed-write fault must never stop the
    # service from serving.
    try:
        profiles.ensure_seeds(home)
    except Exception:
        pass
    # The model-profile `default` seed is NOT best-effort: a successfully
    # initialized service must hold a valid `default` (missing-only — an
    # existing file, operator edits included, is validated but never
    # rewritten), so a seed or validation failure here stops startup
    # visibly instead of serving without the guaranteed catalogue entry.
    model_profiles.ensure_default(home)
    # The staffing catalogue initializes beside it, with the same posture:
    # every readable, valid profile gains a document of its own name once,
    # and a served home always holds a valid `default` document. Conversion
    # is missing-only, so an operator's edited document is never reverted.
    staffing.ensure_documents(home)
    if task_host is None:
        task_host = task_api.DirectTaskHost(home)
    return ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(home, task_host=task_host)
    )


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
    home = os.path.abspath(os.path.expanduser(args.home))
    os.makedirs(home, exist_ok=True)
    return serve(home, args.port, open_browser=args.open)


if __name__ == "__main__":
    sys.exit(main())
