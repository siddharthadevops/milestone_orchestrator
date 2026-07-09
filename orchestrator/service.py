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
    GET    /api/runs/<id>          entry + full state summary + log tail +
                                   commit_web_base (workspace origin as an
                                   https web URL, for gate-commit links)
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
    GET    /api/runs/<id>/log      {"lines": [...]} tail of driver output
    DELETE /api/runs/<id>          forget the run (workspace files untouched;
                                   ?purge=1 also removes the run's state file
                                   + lock so the workspace can launch fresh)

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
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import driver, errclass, gitops, kvstore, profiles, projects, registry
from . import reuse_audit
from . import state as st
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
MISSING_ADDITIONAL_ROOT = "missing_additional_root"

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


def list_projects(home):
    rec = registry.load_projects_record(home)
    return [_project_entry(home, p) for p in rec["projects"]]


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
        project = {"slug": slug, "defaults": defaults}
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


def projects_api(home, method, segments, body, query=None):
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
            summ.get("name"), "run", known_paths=known_paths
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
        "current_unit_status": None,
        "current_family": None,
        "failure_reason": None,
        "events_total": 0,
        "state_error": None,
    }
    try:
        summ = load_summary(entry["state_path"])
        info["project"] = summ.get("project")
        info["work_area"] = summ.get("work_area")
        info["milestone_status"] = summ["milestone_status"]
        info["current_unit"] = summ["current_unit"]
        info["current_unit_status"] = summ["current_unit_status"]
        info["current_family"] = summ.get("current_family")
        info["failure_reason"] = (summ["failure"] or {}).get("reason")
        info["events_total"] = summ["events_total"]
        if home is not None:
            _pump_projection(home, entry, summ)
    except Exception as exc:
        info["state_error"] = str(exc)
    return info


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


def _create_bound_run(home, payload, workspace):
    """POST /api/runs {project, work_area}: launch against a declared
    project instead of a bare path. Observable order: (1) addressing —
    declared project, live stored record; (2) validation of the STORED
    descriptor's roots against the real filesystem (the
    executor-reconcile role — never roots taken from the request);
    (3) the sealed pending->ready confirm; (4) Slice 5's project-bound
    init. Refusal tokens ride verbatim; every refusal creates no state
    file, no registry entry, and no projection entry (a refusal after
    step 3 may truthfully leave the work area ready — readiness
    describes the descriptor, not this launch).

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

    # Launch-time standing defaults: the SAME trio the project-less path
    # forces (found live 2026-07-09: the first project-bound run sealed
    # sequentially because this dict only carried git) merged BENEATH the
    # persisted project defaults — standing operator law beats a service
    # convention, and the explicit launch config beats both.
    binding_defaults = {
        "git": {"enabled": True},
        "seal_concurrent": True,
        "single_seal_first_attempt": True,
    }
    if project.get("defaults"):
        driver.merge_config(binding_defaults, project["defaults"])

    # Validation is the reconcile's real-filesystem half, under the
    # launch's effective config (the same order init will apply). A
    # failure refuses 400 with a machine-readable reason, leaves the
    # record's status UNCHANGED, and creates nothing.
    effective = driver.load_config(None)
    driver.merge_config(effective, binding_defaults)
    if user_cfg:
        driver.merge_config(effective, user_cfg)
    if not os.path.isdir(primary["path"]):
        raise ApiError(400, driver.MISSING_PRIMARY_PATH)
    if gitops.enabled(effective) and not gitops.is_repo_root(primary["path"]):
        # Same predicate as the project-less gate below: the gate ledger
        # must land in a repo the operator created on purpose.
        raise ApiError(400, PRIMARY_NOT_REPO_ROOT)
    for root in additional:
        if not os.path.isdir(root["path"]):
            raise ApiError(400, MISSING_ADDITIONAL_ROOT)

    # Reconcile -> ready through the sealed transition: the first confirm
    # takes pending v1 to ready v2 (the agent_99-pinned bump); re-confirms
    # with the service's stable identity are version-silent.
    try:
        confirmed = store.confirm(area, primary, additional, _executor_id(home))
    except (RuntimeError, OSError) as exc:
        _raise_store_error(exc)
    if not confirmed.ok:
        raise _work_area_error(confirmed.reason)

    resolved_workspace = primary["path"] if workspace is None else workspace
    if resolved_workspace == primary["path"]:
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
        )
    except driver.ProjectResolutionError as exc:
        # The sealed seam built cause for exactly this consumer: the
        # token rides verbatim, no per-cause status remapping.
        raise ApiError(400, exc.cause)
    except FileExistsError as exc:
        raise ApiError(409, str(exc) + ' (use "attach": true to adopt it)')
    return primary["path"], state_path, goal_doc


def _snapshot_profile(state_path, ref, content):
    """Write the run's profile snapshot into its config: the identity
    (`profile_ref` = {name, version, hash}) AND the sealed semantic content
    (`profile`), so the driver can interpret the run's stages and dials
    self-containedly — no service home needed at run time, and the run
    carries its exact governing profile for provenance. Append-only-safe:
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

    # Per-run strategy profile (build-driven review reform, phase 1b). When
    # supplied, the run stores a {name, version, hash} snapshot of the
    # chosen profile in its config and the profile SEALS (first production
    # use). It is OPTIONAL during the reform build-out: a run with no
    # profile is profile-less and behaves exactly as today — the driver
    # does not read profiles yet (that lands with the stage interpreter),
    # so a profiled run is likewise bit-identical for now; only the stored
    # snapshot differs. Validated for existence here so a typo fails fast
    # before any state is created; sealed and snapshotted only once the
    # state exists (below).
    profile_name = payload.get("profile")
    if profile_name is not None:
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ApiError(400, "profile must be a non-empty profile name")
        profile_name = profile_name.strip()
        try:
            profiles.load(home, profile_name)  # existence/validity, no seal
        except profiles.ProfileError as exc:
            raise ApiError(400, str(exc))

    goal_doc = None
    if attach:
        # Attach adopts the on-disk state exactly as it is; a supplied
        # goal/goal_doc/config — or a project binding, which would
        # re-resolve what the state already records — would be silently
        # ignored: reject instead of pretending it was honored. Adopts the
        # legacy workspace-root state, or an explicit `state_path` for a
        # per-milestone run.
        for key in ("goal", "goal_doc", "config", "project", "work_area",
                    "profile"):
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
        # discipline, delta reviews of every fix, and revertible tamper
        # recovery all require git (README, "Git gates and the amend
        # discipline"), so service launches enable it by default — same as
        # the demo config, and matching driver.DEFAULT_CONFIG's own note.
        # An explicit {"git": {"enabled": false}} in the advanced config
        # still wins (merged below), for deliberate pure-state runs.
        # Live runs also seal concurrently (the two double-seal halves run in
        # parallel) and run a single half on the first attempt (a1's last
        # reviewer is byte-redundant; any finding reopens to the full double
        # seal). Both are overridable in the advanced config, merged below.
        driver.merge_config(config, {
            "git": {"enabled": True},
            "seal_concurrent": True,
            "single_seal_first_attempt": True,
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
            state_path = driver.init_run(
                goal.strip(), workspace, config=config, name=name_for_init
            )
        except FileExistsError as exc:
            raise ApiError(409, str(exc) + ' (use "attach": true to adopt it)')

    if profile_name is not None:
        # The state exists now: seal the profile (first production
        # reference) and snapshot its identity AND content into the config.
        try:
            profile_ref = profiles.reference(home, profile_name)
            profile_doc = profiles.load(home, profile_name)
        except profiles.ProfileError as exc:
            raise ApiError(400, str(exc))
        _snapshot_profile(state_path, profile_ref, profile_doc["profile"])

    name = payload.get("name") or os.path.basename(workspace.rstrip("/")) or "run"
    run_id = registry.make_run_id()
    entry_summ = None
    entry_project = None
    entry_work_area = None
    try:
        entry_summ = load_summary(state_path)
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
            summ = load_summary(entry["state_path"])
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


ACT_KEYS = ("drafter", "implementer", "fixer", "delta_review",
            "consultation", "reclassifier")


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


def _profile_overlay_path(entry):
    # Beside the state file (the run's runtime dir), matching acts.json and
    # amendments.json.
    return os.path.join(os.path.dirname(entry["state_path"]),
                        "profile_swap.json")


def read_profile_overlay(entry):
    """The operator's current runtime repoint for this run, or None. An
    operator-owned, lock-free file beside the state (the amendments/acts
    pattern): the operator writes it, and the driver will re-read it at
    stage boundaries and record the profile_changed ledger event when the
    repoint actually takes effect — that driver-side pickup lands with the
    stage interpreter. Tolerant of a mid-write race (returns None)."""
    try:
        with open(_profile_overlay_path(entry), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    ref = data.get("ref")
    if not isinstance(ref, dict) or "name" not in ref:
        return None
    return {"ref": ref, "at": data.get("at")}


def read_profile(entry):
    """The run's governing strategy profile for the panel, or None for a
    profile-less, never-swapped run. Read straight from state (like
    read_acts) and tolerant of a transiently unreadable state. `base` is
    the snapshot stored in the run config at creation; `swap` is the
    operator's runtime repoint (present only after a swap); `governing` is
    the profile that rules the run right now — the swap when present, else
    the base. The swap takes effect on run BEHAVIOR only once the driver
    honors it at a stage boundary (the stage interpreter, a later phase);
    the displayed governing profile reflects the operator's intent now."""
    try:
        state = st.load(entry["state_path"])
        base = (state.get("config") or {}).get("profile_ref")
    except Exception:
        base = None
    overlay = read_profile_overlay(entry)
    if not base and not overlay:
        return None
    swap = overlay["ref"] if overlay else None
    out = {"base": base, "governing": swap or base}
    if overlay:
        out["swap"] = overlay
    return out


def _profile_view(doc):
    """The panel-facing shape of one profile document (identity hash
    exposed, semantic content included for the decomposition view)."""
    return {
        "name": doc["name"],
        "version": doc["version"],
        "sealed": doc["sealed"],
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
    """Create or update a strategy profile from the panel. The save API
    NEVER seals — a profile seals only on its first production reference by
    a run (profiles.reference), so an operator can keep refining an unused
    profile in place. An already-sealed profile's seal and its immutable
    semantic content are preserved by profiles.save (a metadata-only edit,
    e.g. the description, still lands; a content change is refused)."""
    if not isinstance(body, dict):
        raise ApiError(400, "profile document must be an object")
    doc = dict(body)
    doc["sealed"] = False
    try:
        saved = profiles.save(home, doc)
    except profiles.ProfileError as exc:
        raise ApiError(400, str(exc))
    return _profile_view(saved)


def set_profile_swap(home, run_id, body):
    """Repoint a run at another strategy profile at RUNTIME. Swap != edit:
    the profile is never mutated in place; the run points elsewhere. Seals
    the target (a referenced profile is in production) and writes the
    operator-owned overlay (profile_swap.json) beside the state — the same
    lock-free pattern as acts/amendments, so a hot repoint never collides
    with the driver's lock. The repoint takes effect on run behavior at the
    next stage boundary, where the driver records the profile_changed
    ledger event and marks the run profile_mixed; that driver-side pickup
    lands with the stage interpreter. Here we record the operator's intent
    and the panel reflects the new governing profile immediately."""
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
        ref = profiles.reference(home, name.strip())
    except profiles.ProfileError as exc:
        raise ApiError(400, str(exc))
    overlay = {"ref": ref, "at": registry.now_iso()}
    path = _profile_overlay_path(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(overlay, fh, indent=1)
    os.replace(tmp, path)
    return overlay


MALFORMED_RAW_CLIP = 20000


def run_story(home, run_id, item):
    """The full record behind one pipeline chip — fetched on click, so
    the 2s-poll summary stays lean. item forms: round:<round_id>,
    seal:<unit>:<attempt>, draft:<unit>, malformed:<event seq>."""
    reg = registry.load(home)
    entry = registry.get(reg, run_id)
    if entry is None:
        raise ApiError(404, "unknown run %r" % run_id)
    try:
        state = st.load(entry["state_path"])
    except Exception as exc:
        raise ApiError(409, "state unreadable: %s" % exc)
    kind, _, ref = (item or "").partition(":")
    if kind == "malformed":
        # The repaired-first-strike viewer: the raw path comes from the
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
                "error": e.get("error"),
                "fatal": bool(e.get("fatal")),
                "raw_path": e.get("raw_path"),
                "raw_text": _read_raw(e.get("raw_path")),
                # A FATAL strike has a second attempt: the repair's text.
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
    if kind == "debt":
        for unit in state["units"]:
            if st.unit_key(unit) != ref:
                continue
            reclassify = [
                {
                    "finding_id": e.get("finding_id"),
                    "reclassifier": e.get("reclassifier"),
                    "drift_risk": e.get("drift_risk"),
                    "threshold": e.get("threshold"),
                    "defer_ok": e.get("defer_ok"),
                    "reason": e.get("reason"),
                    "at": e.get("at"),
                }
                for e in state["events"]
                if e.get("type") == "reclassify_recorded"
                and e.get("unit") == ref
            ]
            return {
                "story": "debt",
                "unit": ref,
                "debt": unit.get("debt", []),
                "reclassify": reclassify,
            }
        raise ApiError(404, "unknown unit %r" % ref)
    raise ApiError(400, "item must be round:/seal:/draft:/debt:")


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
        detail["summary"] = load_summary(entry["state_path"])
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
                elif route == "/api/ui-state":
                    self._json(200, {"ok": True, **registry.load_ui_state(home)})
                elif route == "/api/profiles":
                    self._json(200, {"ok": True, "profiles": profiles_list(home)})
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
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    status, payload = projects_api(
                        home, "GET", project_route_segments(route), None
                    )
                    self._json(status, payload)
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
                    self._json(201, {"ok": True, "run": run_status(entry, home=home)})
                elif route == "/api/ui-state":
                    self._json(
                        200,
                        {"ok": True, **registry.save_ui_state(home, self._body())},
                    )
                elif route == "/api/profiles":
                    saved = save_profile(home, self._body())
                    self._json(200, {"ok": True, "profile": saved})
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    status, payload = projects_api(
                        home, "POST", project_route_segments(route),
                        self._body(),
                    )
                    self._json(status, payload)
                elif route.startswith("/api/runs/"):
                    parts = route.rstrip("/").split("/")
                    if len(parts) == 5 and parts[4] == "start":
                        entry = start_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry, home=home)})
                    elif len(parts) == 5 and parts[4] == "stop":
                        self._json(200, {"ok": True, **stop_run(home, parts[3])})
                    elif len(parts) == 5 and parts[4] == "resume":
                        entry = resume_run(home, parts[3])
                        self._json(200, {"ok": True, "run": run_status(entry, home=home)})
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
                    elif len(parts) == 5 and parts[4] == "profile":
                        swap = set_profile_swap(home, parts[3], self._body())
                        self._json(200, {"ok": True, "profile_swap": swap})
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
                elif route == "/api/projects" or route.startswith("/api/projects/"):
                    status, payload = projects_api(
                        home, "DELETE", project_route_segments(route), None,
                        query=query,
                    )
                    self._json(status, payload)
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
            summ = load_summary(entry["state_path"])
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


def make_server(home, port):
    # Seed the two starter strategy profiles (strict, light) when missing,
    # so the panel's new-run selector always has something to offer.
    # Idempotent and best-effort: a seed-write fault must never stop the
    # service from serving.
    try:
        profiles.ensure_seeds(home)
    except Exception:
        pass
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
