"""Standalone service lifecycle for product-neutral Brainstorming sessions.

This module deliberately owns no milestone state.  It binds an authenticated
caller to one Brainstorming SessionStore record, launches one independent
lifecycle process, projects durable progress for polling, and composes a
target-safe terminal failure for an explicit caller stop.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from dataclasses import dataclass

from orchestrator import brainstorming
from orchestrator import brainstorming_coordination as coordination
from orchestrator import brainstorming_execution as execution
from orchestrator import driver, kvstore, registry, runners

try:
    import fcntl
except ImportError:  # pragma: no cover - the production service is POSIX
    fcntl = None


SCHEMA_VERSION = 1
SERVICE_DIRNAME = "brainstorming"
REGISTRY_FILENAME = "sessions.json"
STATE_DIRNAME = "state"
LOGS_DIRNAME = "logs"
STOP_WAIT_S = 5.0

INVALID_REQUEST = "invalid_brainstorming_request"
UNKNOWN_SESSION = "unknown_brainstorming_session"
TARGET_IN_USE = "brainstorming_target_in_use"
STOP_INCOMPLETE = "brainstorming_stop_incomplete"
SESSION_RUNNING = "brainstorming_session_running"
UNAVAILABLE = "brainstorming_unavailable"
_PROJECT_REQUEST_ERRORS = {
    "invalid_project",
    "invalid_name",
    "unknown_work_area",
    "malformed_work_area",
    "work_area_not_ready",
    "workspace_mismatch",
    "missing_primary_path",
}

_REGISTRY_LOCKS = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()
_CHILDREN = {}  # pid -> (home, session_id, Popen-compatible process)
_CHILDREN_LOCK = threading.Lock()


class PublicLifecycleError(RuntimeError):
    """One intentionally small, non-diagnostic public lifecycle refusal."""

    def __init__(self, status, code):
        RuntimeError.__init__(self, code)
        self.status = status
        self.code = code


class LifecycleStop(BaseException):
    """Internal asynchronous stop delivered to the lifecycle process."""


@dataclass
class GatedLaunch:
    process: object
    release: object
    abort: object


def service_directory(home):
    return os.path.join(os.path.abspath(home), SERVICE_DIRNAME)


def state_directory(home):
    return os.path.join(service_directory(home), STATE_DIRNAME)


def registry_path(home):
    return os.path.join(service_directory(home), REGISTRY_FILENAME)


def _registry_lock_path(home):
    return registry_path(home) + ".lock"


def _registry_thread_lock(path):
    with _REGISTRY_LOCKS_GUARD:
        lock = _REGISTRY_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _REGISTRY_LOCKS[path] = lock
        return lock


@contextlib.contextmanager
def _locked_registry(home):
    path = _registry_lock_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _registry_thread_lock(path):
        handle = open(path, "a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            handle.close()


def _new_registry():
    return {"schema_version": SCHEMA_VERSION, "sessions": []}


def _validate_target_identity(identity):
    brainstorming._exact_keys(
        identity, ("device", "inode", "tail"), (), "target_identity"
    )
    if (
        type(identity["device"]) is not int
        or identity["device"] < 0
        or type(identity["inode"]) is not int
        or identity["inode"] < 0
        or not isinstance(identity["tail"], list)
        or any(not isinstance(item, str) for item in identity["tail"])
    ):
        raise RuntimeError("invalid Brainstorming service registry")
    return copy.deepcopy(identity)


def _validate_record(record):
    brainstorming._exact_keys(
        record,
        (
            "id",
            "caller",
            "project",
            "work_area",
            "target_path",
            "target_identity",
            "pid",
            "created_at",
            "runtime",
            "execution_context",
        ),
        (),
        "service_record",
    )
    try:
        kvstore.validate_fragment(record["id"], "session_id")
        brainstorming._text(record["caller"], "service_record.caller")
        brainstorming._text(
            record["target_path"], "service_record.target_path"
        )
        brainstorming._text(
            record["created_at"], "service_record.created_at"
        )
    except (ValueError, brainstorming.ContractError) as exc:
        raise RuntimeError("invalid Brainstorming service registry") from exc
    project = record["project"]
    work_area = record["work_area"]
    if (project is None) != (work_area is None):
        raise RuntimeError("invalid Brainstorming service registry")
    if project is not None:
        try:
            brainstorming._text(project, "service_record.project")
            brainstorming._text(work_area, "service_record.work_area")
        except brainstorming.ContractError as exc:
            raise RuntimeError(
                "invalid Brainstorming service registry"
            ) from exc
    pid = record["pid"]
    if pid is not None and (type(pid) is not int or pid <= 0):
        raise RuntimeError("invalid Brainstorming service registry")
    _validate_target_identity(record["target_identity"])
    try:
        brainstorming._json_copy(record["runtime"], "service_record.runtime")
        brainstorming._json_copy(
            record["execution_context"],
            "service_record.execution_context",
        )
    except brainstorming.ContractError as exc:
        raise RuntimeError("invalid Brainstorming service registry") from exc
    return copy.deepcopy(record)


def _load_registry(home):
    path = registry_path(home)
    if not os.path.exists(path):
        return _new_registry()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RuntimeError("invalid Brainstorming service registry") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "sessions"}
        or document["schema_version"] != SCHEMA_VERSION
        or not isinstance(document["sessions"], list)
    ):
        raise RuntimeError("invalid Brainstorming service registry")
    seen = set()
    sessions = []
    for record in document["sessions"]:
        checked = _validate_record(record)
        if checked["id"] in seen:
            raise RuntimeError("invalid Brainstorming service registry")
        seen.add(checked["id"])
        sessions.append(checked)
    return {"schema_version": SCHEMA_VERSION, "sessions": sessions}


def _save_registry(home, document):
    checked = _new_registry()
    seen = set()
    for record in document.get("sessions", []):
        record = _validate_record(record)
        if record["id"] in seen:
            raise RuntimeError("invalid Brainstorming service registry")
        seen.add(record["id"])
        checked["sessions"].append(record)
    directory = service_directory(home)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".brainstorming-sessions-", suffix=".json", dir=directory
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                checked,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            handle.write("\n")
        os.replace(temporary, registry_path(home))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _find_record(document, session_id):
    for record in document["sessions"]:
        if record["id"] == session_id:
            return record
    return None


def _new_session_id():
    return "bs-" + secrets.token_hex(16)


def validate_create_body(body):
    """Validate the exact caller-owned creation shape."""
    try:
        brainstorming._exact_keys(
            body,
            ("request", "participants", "closure_policy"),
            ("project", "work_area", "create_target_parents"),
            "brainstorming create body",
        )
        request = brainstorming.validate_request(body["request"])
        for field in ("workspace_path", "target_path"):
            if "\x00" in request[field]:
                raise brainstorming.ContractError(
                    "request.%s is not a valid filesystem path" % field
                )
        raw_participants = body["participants"]
        if not isinstance(raw_participants, list):
            raise brainstorming.ContractError(
                "participants must be an ordered list"
            )
        participants = []
        ids = set()
        lead_count = 0
        interlocutor_count = 0
        for index, participant in enumerate(raw_participants):
            context = "participants[%d]" % index
            # A caller may pin what a seat is staffed with — its model
            # family, and the model/effort that seat runs at. All three
            # stay OPTIONAL: omitted, the service resolves the family by
            # rotation and the family's own defaults, exactly as before.
            brainstorming._exact_keys(
                participant,
                ("id", "role"),
                ("model_family", "model", "effort"),
                context,
            )
            participant_id = brainstorming._text(
                participant["id"], "%s.id" % context
            )
            if participant_id in ids:
                raise brainstorming.ContractError(
                    "participant ids must be unique"
                )
            if participant["role"] not in brainstorming.ROLES:
                raise brainstorming.ContractError(
                    "%s.role is invalid" % context
                )
            ids.add(participant_id)
            lead_count += participant["role"] == "lead"
            interlocutor_count += participant["role"] == "interlocutor"
            checked_participant = {
                "id": participant_id, "role": participant["role"]
            }
            for field in ("model_family", "model", "effort"):
                if field in participant:
                    checked_participant[field] = brainstorming._text(
                        participant[field], "%s.%s" % (context, field)
                    )
            participants.append(checked_participant)
        if lead_count != 1 or interlocutor_count < 1:
            raise brainstorming.ContractError(
                "participants require exactly one lead and an interlocutor"
            )
        policy = body["closure_policy"]
        if policy not in brainstorming.CLOSURE_POLICIES:
            raise brainstorming.ContractError("closure_policy is invalid")
        has_project = "project" in body
        has_work_area = "work_area" in body
        if has_project != has_work_area:
            raise brainstorming.ContractError(
                "project and work_area must be supplied together"
            )
        project = work_area = None
        if has_project:
            project = brainstorming._text(body["project"], "project")
            work_area = brainstorming._text(body["work_area"], "work_area")
        # Opt-in mkdir of the target's missing parent folders at creation
        # (the panel's "New" flow: a fresh session folder under an existing
        # directory). Absent or false keeps the historical refusal: a
        # target whose parent does not exist is an invalid request.
        create_parents = body.get("create_target_parents", False)
        if type(create_parents) is not bool:
            raise brainstorming.ContractError(
                "create_target_parents must be a boolean"
            )
        return {
            "request": request,
            "participants": participants,
            "closure_policy": policy,
            "project": project,
            "work_area": work_area,
            "create_target_parents": create_parents,
        }
    except (TypeError, ValueError, brainstorming.ContractError) as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc


def _resolve_creation_context(home, checked, project_record):
    request = checked["request"]
    if checked["project"] is None:
        workspace = os.path.abspath(request["workspace_path"])
        if not os.path.isdir(workspace):
            raise PublicLifecycleError(400, INVALID_REQUEST)
        context = {
            "workspace_path": workspace,
            "project": None,
            "work_area": None,
            "primary": None,
            "additional": [],
        }
        return context, driver.load_config(None)

    if (
        not isinstance(project_record, dict)
        or project_record.get("slug") != checked["project"]
    ):
        raise PublicLifecycleError(404, "unknown_project")
    binding = {
        "directory": registry.projects_base(home),
        "project": checked["project"],
        "work_area": checked["work_area"],
    }
    if project_record.get("defaults") is not None:
        binding["defaults"] = project_record["defaults"]
    try:
        workspace, project_block, config = driver._resolve_project_binding(
            binding,
            request["workspace_path"],
            None,
        )
    except driver.ProjectResolutionError as exc:
        if exc.cause in _PROJECT_REQUEST_ERRORS:
            raise PublicLifecycleError(400, exc.cause) from exc
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    except (TypeError, ValueError) as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc
    context = {
        "workspace_path": workspace,
        "project": project_block["project"],
        "work_area": project_block["work_area"],
        "primary": project_block["primary"],
        "additional": project_block["additional"],
    }
    return context, config


def _executable_available(argv, workspace):
    if not argv or not isinstance(argv[0], str) or not argv[0].strip():
        return False
    executable = argv[0].replace("{workspace}", workspace)
    if os.path.sep in executable:
        candidate = executable
        if not os.path.isabs(candidate):
            candidate = os.path.join(workspace, candidate)
        return os.path.isfile(candidate) and os.access(candidate, os.X_OK)
    search_path = os.environ.get("PATH")
    if search_path is not None:
        search_path = os.pathsep.join(
            item if os.path.isabs(item) else os.path.join(workspace, item)
            for item in search_path.split(os.pathsep)
        )
    return shutil.which(executable, path=search_path) is not None


def _runtime_and_roster(config, participants, closure_policy, workspace):
    commands = config.get("commands")
    order = config.get("families_order")
    if not isinstance(commands, dict) or not isinstance(order, list):
        raise PublicLifecycleError(503, UNAVAILABLE)
    model_defaults = config.get("model_defaults") or {}
    timeouts = config.get("timeouts") or {}
    probe = runners.SubprocessRunner(
        commands,
        timeouts,
        participant_process_factory=_spawn_participant,
    )
    families = []
    for family in order:
        if (
            not isinstance(family, str)
            or family in families
            or not probe.supports_session_continuation(family)
        ):
            continue
        defaults = model_defaults.get(family) or {}
        model = defaults.get("model")
        effort = defaults.get("effort")
        try:
            argv = runners.apply_model_effort(
                commands[family], model, effort
            )
        except (TypeError, ValueError, runners.RunnerError):
            continue
        if _executable_available(argv, workspace):
            families.append(family)
    if not families:
        raise PublicLifecycleError(503, UNAVAILABLE)

    # One executor binding per SEAT, not per family: two seats on the same
    # family may legitimately run different models, and the roster's
    # executor_ref is the only key the sealed execution seam looks a
    # binding up by.
    def seat_ref(family, participant_id):
        return "brainstorming-%s-%s" % (family, participant_id)

    # Eligibility is what the caller ALLOWS a seat to be staffed with: an
    # unpinned seat may take any available family, a pinned seat only its
    # pin. The sealed cross-family rule then judges the roster against the
    # caller's real degrees of freedom — an all-one-family roster the
    # operator pinned on purpose is legitimate, not a fallback.
    eligible = []
    for participant in participants:
        seat_families = (
            [participant["model_family"]]
            if participant.get("model_family") is not None
            else families
        )
        for family in seat_families:
            if family not in families:
                raise PublicLifecycleError(400, INVALID_REQUEST)
            eligible.append(
                {
                    "id": participant["id"],
                    "role": participant["role"],
                    "executor_ref": seat_ref(family, participant["id"]),
                    "model_family": family,
                }
            )
    selected = []
    rotation = 0
    for participant in participants:
        pinned = participant.get("model_family")
        if pinned is None:
            # Unpinned seats keep the historical rotation over available
            # families; a roster with no pins resolves exactly as before.
            family = families[rotation % len(families)]
            rotation += 1
        elif pinned in families:
            family = pinned
        else:
            # The caller asked for a family this host cannot staff. That
            # is a request fault, not a service fault.
            raise PublicLifecycleError(400, INVALID_REQUEST)
        selected.append(
            {
                "id": participant["id"],
                "role": participant["role"],
                "executor_ref": seat_ref(family, participant["id"]),
                "model_family": family,
            }
        )
    # The rotation is pin-blind, so pins can herd every seat onto one
    # family (lead pinned codex + a default seat: rotation hands the
    # default seat codex too) — a shape the sealed cross-family rule then
    # rightly refuses, blaming the caller for the service's own choice.
    # While an unpinned seat can still diversify, flip the last one to
    # the first other available family; a roster with no pins is never
    # herded (indexes 0 and 1 already differ), so this changes nothing
    # for the historical path.
    if len(families) > 1 and len(
        {entry["model_family"] for entry in selected}
    ) == 1:
        mono = selected[0]["model_family"]
        for participant, entry in zip(
            reversed(participants), reversed(selected)
        ):
            if participant.get("model_family") is None:
                family = next(f for f in families if f != mono)
                entry["model_family"] = family
                entry["executor_ref"] = seat_ref(family, entry["id"])
                break
    try:
        run_config = brainstorming.resolve_run_config(
            selected, closure_policy, eligible
        )
    except brainstorming.ContractError as exc:
        # A roster the caller pinned into a shape the sealed rules refuse
        # (notably same-family while a cross-family one is eligible) is a
        # bad request; only an unpinned roster failing here is a fault of
        # the service's own rotation.
        if any(
            participant.get("model_family") is not None
            for participant in participants
        ):
            raise PublicLifecycleError(400, INVALID_REQUEST) from exc
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    # Each seat's resolved model/effort, recorded once so the lifecycle
    # child rebuilds the exact same bindings without re-deriving them.
    executors = {}
    for participant, entry in zip(participants, selected):
        defaults = model_defaults.get(entry["model_family"]) or {}
        executors[entry["executor_ref"]] = {
            "model_family": entry["model_family"],
            "model": participant.get("model") or defaults.get("model"),
            "effort": participant.get("effort") or defaults.get("effort"),
        }
    runtime = {
        "families_order": families,
        "commands": {
            family: copy.deepcopy(commands[family]) for family in families
        },
        "timeouts": {
            family: copy.deepcopy(timeouts.get(family))
            for family in families
            if family in timeouts
        },
        "model_defaults": {
            family: copy.deepcopy(model_defaults.get(family) or {})
            for family in families
        },
        "executors": executors,
        "worker_stall_window_s": config.get("worker_stall_window_s"),
        "worker_stall_min_cpu_s": config.get("worker_stall_min_cpu_s"),
    }
    try:
        runtime = brainstorming._json_copy(runtime, "runtime")
    except brainstorming.ContractError as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    return runtime, run_config, eligible


def _resolved_target_path(request, execution_context, owned_target_path=None):
    """Resolve and contain the target path without touching the filesystem."""
    path = coordination.resolve_target_path(request)
    primary = execution_context.get("primary")
    if primary is not None:
        primary_path = primary.get("path") if isinstance(primary, dict) else None
        if (
            not isinstance(primary_path, str)
            or not kvstore.path_is_inside_roots(path, [primary_path])
        ):
            if (
                owned_target_path is None
                or os.path.abspath(owned_target_path) != path
            ):
                raise PublicLifecycleError(400, INVALID_REQUEST)
    return path


def _require_capturable(path):
    """Fail fast on a target the coordination layer would refuse."""
    try:
        coordination.capture_target(path)
    except coordination.CoordinationRejected as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc


def _ensure_target_parents(path):
    """Create the target's missing parent folders; return what was created.

    Runs only after containment and authority-overlap validation, under
    the registry lock. The returned list (deepest first) is exactly the
    set of directories this call brought into existence, so a failed
    create can remove them — and nothing else — on the way out.
    """
    parent = os.path.dirname(os.path.abspath(path))
    missing = []
    probe = parent
    while not os.path.lexists(probe):
        missing.append(probe)
        upper = os.path.dirname(probe)
        if upper == probe:
            break
        probe = upper
    if not missing:
        return []
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        _remove_created_dirs(missing)
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc
    return missing


def _remove_created_dirs(created):
    """Best-effort compensation: remove only empty, still-ours folders."""
    for directory in created:
        try:
            os.rmdir(directory)
        except FileNotFoundError:
            continue
        except OSError:
            # Non-empty or otherwise busy: someone already relies on it —
            # never force anything beyond what this create added.
            return


def _discard_created_dirs(home, target_path, created):
    """Compensate a failed create's mkdir, never a sibling's adoption.

    Runs outside the registry lock (the create's with-block has exited by
    the time its except paths run), so a concurrent create may have found
    these folders existing and registered its own session INSIDE them —
    on the same target or on any other artifact under the same fresh
    folders (its target file may legitimately not exist yet, so the
    empty-folder rmdir guard alone cannot protect it). Re-checking under
    the lock — for any registered target that equals ours or lives under
    any folder this create added, in raw or realpath form — makes removal
    and adoption mutually exclusive; compensation stays best-effort.
    """
    if not created:
        return
    try:
        with _locked_registry(home):
            document = _load_registry(home)
            guarded = set()
            for directory in created:
                guarded.add(os.path.abspath(directory))
                guarded.add(os.path.realpath(directory))
            for record in document["sessions"]:
                for recorded in (
                    os.path.abspath(record["target_path"]),
                    os.path.realpath(record["target_path"]),
                ):
                    if recorded == target_path or any(
                        recorded == directory
                        or recorded.startswith(directory + os.sep)
                        for directory in guarded
                    ):
                        return
            _remove_created_dirs(created)
    except Exception:
        pass


def _target_identity(path):
    chain = brainstorming._existing_ancestor_chain(path)
    if not chain:
        raise PublicLifecycleError(400, INVALID_REQUEST)
    ancestor, tail = chain[0]
    try:
        observed = os.stat(ancestor)
    except OSError as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc
    normalized = [
        unicodedata.normalize("NFC", component) for component in tail
    ]
    if brainstorming._filesystem_ignores_case(ancestor):
        normalized = [component.casefold() for component in normalized]
    return {
        "device": observed.st_dev,
        "inode": observed.st_ino,
        "tail": normalized,
    }


def _target_overlaps_service_directory(authority_path, target_path):
    """Protect the service tree without inventing a sibling lock authority."""
    authority_path = os.path.abspath(authority_path)
    target_path = os.path.abspath(target_path)
    authority_real = os.path.realpath(authority_path)
    target_real = os.path.realpath(target_path)
    try:
        common = os.path.commonpath((authority_real, target_real))
    except ValueError:
        common = None
    if common in (authority_real, target_real):
        return True
    return brainstorming._paths_overlap_from_existing_ancestor(
        authority_path, target_path
    )


def _reject_authority_overlap(home, store, target_path):
    try:
        if _target_overlaps_service_directory(
            service_directory(home), target_path
        ):
            raise coordination.CoordinationRejected(
                "target overlaps Brainstorming service authority"
            )
        for authority in (registry_path(home), store.path):
            if brainstorming._target_overlaps_state_storage(
                authority, target_path
            ):
                raise coordination.CoordinationRejected(
                    "target overlaps Brainstorming service authority"
                )
        coordination._reject_store_target_alias(store.path, target_path)
    except coordination.CoordinationRejected as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc


def _same_target(record, target_path, identity):
    recorded_path = record["target_path"]
    if (
        recorded_path == target_path
        or os.path.realpath(recorded_path) == os.path.realpath(target_path)
    ):
        return True
    try:
        if os.path.samefile(recorded_path, target_path):
            return True
    except (FileNotFoundError, OSError):
        pass
    # A completed lead turn may replace the artifact and therefore change its
    # inode.  Compare only the live name identity: the admission-time inode can
    # later belong to an unrelated artifact and is no longer target authority.
    try:
        current_identity = _target_identity(recorded_path)
    except PublicLifecycleError:
        return False
    return brainstorming._same_json_value(current_identity, identity)


def _target_is_active(store, record):
    try:
        snapshot = store.read(record["id"])
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    return (
        snapshot is None
        or snapshot.state["status"] not in brainstorming.TERMINAL_STATUSES
    )


def _spawn_participant(execution_context, argv, popen_kwargs):
    """Use the caller-resolved context without narrowing inherited authority."""
    if not isinstance(execution_context, dict):
        raise RuntimeError("execution context is unavailable")
    return subprocess.Popen(argv, **popen_kwargs)


def _launch_lifecycle_process(home, session_id):
    """Spawn one child blocked until its binding and session are durable."""
    logs = os.path.join(service_directory(home), LOGS_DIRNAME)
    os.makedirs(logs, exist_ok=True)
    log_path = os.path.join(logs, "%s.log" % session_id)
    read_fd, write_fd = os.pipe()
    log_handle = open(log_path, "a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "orchestrator.brainstorming_lifecycle",
                "run",
                "--home",
                os.path.abspath(home),
                "--session",
                session_id,
                "--start-fd",
                str(read_fd),
            ],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(read_fd,),
        )
    except BaseException:
        os.close(read_fd)
        os.close(write_fd)
        log_handle.close()
        try:
            os.unlink(log_path)
        except OSError:
            pass
        raise
    finally:
        if not log_handle.closed:
            log_handle.close()
    os.close(read_fd)

    released = {"done": False}

    def release():
        if released["done"]:
            return
        released["done"] = True
        try:
            os.write(write_fd, b"1")
        except OSError:
            pass
        finally:
            os.close(write_fd)

    def abort():
        if not released["done"]:
            released["done"] = True
            try:
                os.close(write_fd)
            except OSError:
                pass
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except OSError:
                try:
                    process.terminate()
                except OSError:
                    pass
            try:
                process.wait(timeout=STOP_WAIT_S)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    pass
                try:
                    process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    return GatedLaunch(process, release, abort)


def _track_child(home, session_id, process):
    with _CHILDREN_LOCK:
        _CHILDREN[process.pid] = (
            os.path.abspath(home),
            session_id,
            process,
        )


def _tracked_child(pid):
    with _CHILDREN_LOCK:
        return _CHILDREN.get(pid)


def _clear_pid(home, session_id, pid):
    try:
        with _locked_registry(home):
            document = _load_registry(home)
            record = _find_record(document, session_id)
            if record is not None and record["pid"] == pid:
                record["pid"] = None
                _save_registry(home, document)
    except Exception:
        pass


def reap_children(home):
    home = os.path.abspath(home)
    exited = []
    with _CHILDREN_LOCK:
        for pid, (child_home, session_id, process) in list(
            _CHILDREN.items()
        ):
            if child_home == home and process.poll() is not None:
                exited.append((pid, session_id))
                del _CHILDREN[pid]
    for pid, session_id in exited:
        _clear_pid(home, session_id, pid)


def _process_alive(record):
    pid = record.get("pid")
    if not pid:
        return False
    tracked = _tracked_child(pid)
    if tracked is not None:
        return tracked[2].poll() is None
    return registry.session_leader_alive(pid)


def _record_by_id(home, session_id):
    try:
        kvstore.validate_fragment(session_id, "session_id")
    except ValueError as exc:
        raise PublicLifecycleError(404, UNKNOWN_SESSION) from exc
    reap_children(home)
    try:
        with _locked_registry(home):
            record = _find_record(_load_registry(home), session_id)
            if record is None:
                raise PublicLifecycleError(404, UNKNOWN_SESSION)
            return copy.deepcopy(record)
    except PublicLifecycleError:
        raise
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc


def _authorize_record(record, authorize):
    if not callable(authorize):
        raise PublicLifecycleError(503, UNAVAILABLE)
    authorize(copy.deepcopy(record))


def _projection(home, record):
    store = brainstorming.SessionStore(state_directory(home))
    try:
        snapshot = store.read(record["id"])
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    if snapshot is None:
        raise PublicLifecycleError(503, UNAVAILABLE)
    return {
        "id": record["id"],
        "caller": record["caller"],
        "project": record["project"],
        "work_area": record["work_area"],
        "process": "running" if _process_alive(record) else "stopped",
        "revision": snapshot.revision,
        "state": snapshot.state,
    }


def _rollback_unreleased_creation(
    home, store, session_id, recovery_revision=None
):
    """Compensate a create fault while the lifecycle child is still gated."""
    with _locked_registry(home):
        document = _load_registry(home)
        record = _find_record(document, session_id)
        if record is not None:
            document["sessions"].remove(record)
            _save_registry(home, document)
        store.discard_unlaunched(session_id, recovery_revision)


def create_session(
    home,
    body,
    caller,
    project_record=None,
    launcher=None,
):
    """Expose only the sealed lifecycle vocabulary for every create fault."""
    try:
        return _create_session(
            home,
            body,
            caller,
            project_record=project_record,
            launcher=launcher,
        )
    except PublicLifecycleError:
        raise
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc


def _create_session(
    home,
    body,
    caller,
    project_record=None,
    launcher=None,
):
    """Validate, bind, durably create, and launch one standalone session."""
    checked = validate_create_body(body)
    try:
        caller = brainstorming._text(caller, "caller")
    except brainstorming.ContractError as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    context, config = _resolve_creation_context(
        home, checked, project_record
    )
    checked["request"]["workspace_path"] = context["workspace_path"]
    return _create_session_with_context(
        home, checked, caller, context, config, launcher
    )


def create_resolved_session(
    home,
    body,
    caller,
    execution_context,
    config,
    launcher=None,
    owned_target_path=None,
):
    """Create for an already-resolved milestone without resolving roots again."""
    try:
        checked = validate_create_body(body)
        caller = brainstorming._text(caller, "caller")
        context = brainstorming._json_copy(
            execution_context, "execution_context"
        )
        brainstorming._exact_keys(
            context,
            (
                "workspace_path",
                "project",
                "work_area",
                "primary",
                "additional",
            ),
            (),
            "execution_context",
        )
        workspace = brainstorming._text(
            context["workspace_path"], "execution_context.workspace_path"
        )
        if os.path.abspath(workspace) != workspace or not os.path.isdir(
            workspace
        ):
            raise brainstorming.ContractError(
                "execution_context.workspace_path must be an existing "
                "absolute directory"
            )
        if checked["request"]["workspace_path"] != workspace:
            raise brainstorming.ContractError(
                "request workspace does not match resolved execution context"
            )
        if (
            checked["project"] != context["project"]
            or checked["work_area"] != context["work_area"]
        ):
            raise brainstorming.ContractError(
                "request binding does not match resolved execution context"
            )
        if not isinstance(config, dict):
            raise brainstorming.ContractError(
                "resolved config must be an object"
            )
        if owned_target_path is not None:
            owned_target_path = brainstorming._text(
                owned_target_path, "owned_target_path"
            )
            if os.path.abspath(owned_target_path) != owned_target_path:
                raise brainstorming.ContractError(
                    "owned_target_path must be absolute"
                )
        return _create_session_with_context(
            home,
            checked,
            caller,
            context,
            config,
            launcher,
            owned_target_path=owned_target_path,
        )
    except PublicLifecycleError:
        raise
    except (TypeError, ValueError, brainstorming.ContractError) as exc:
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc


def _create_session_with_context(
    home,
    checked,
    caller,
    context,
    config,
    launcher,
    owned_target_path=None,
):
    runtime, run_config, eligible = _runtime_and_roster(
        config,
        checked["participants"],
        checked["closure_policy"],
        context["workspace_path"],
    )
    store = brainstorming.SessionStore(state_directory(home))
    target_path = _resolved_target_path(
        checked["request"], context, owned_target_path=owned_target_path
    )
    _reject_authority_overlap(home, store, target_path)
    if not checked["create_target_parents"]:
        # Historical fail-fast: without the opt-in, a target whose parent
        # is missing (or otherwise uncapturable) refuses before anything
        # is spawned or written.
        _require_capturable(target_path)
    launcher = launcher or _launch_lifecycle_process
    launch = None
    session_id = None
    session_creation_attempted = False
    recovery_baseline = None
    created_dirs = []

    try:
        reap_children(home)
        with _locked_registry(home):
            document = _load_registry(home)
            if checked["create_target_parents"]:
                # Under the registry lock, after every pure validation: a
                # concurrent create of the same fresh folder serializes
                # here, so cleanup can never remove a sibling's folder.
                created_dirs = _ensure_target_parents(target_path)
            identity = _target_identity(target_path)
            for record in document["sessions"]:
                if (
                    _same_target(record, target_path, identity)
                    and _target_is_active(store, record)
                ):
                    raise PublicLifecycleError(409, TARGET_IN_USE)
            session_id = _new_session_id()
            while (
                _find_record(document, session_id) is not None
                or store.read(session_id) is not None
            ):
                session_id = _new_session_id()
            try:
                launch = launcher(home, session_id)
            except Exception as exc:
                raise PublicLifecycleError(503, UNAVAILABLE) from exc
            if (
                launch is None
                or not hasattr(launch, "process")
                or type(getattr(launch.process, "pid", None)) is not int
                or launch.process.pid <= 0
            ):
                raise PublicLifecycleError(503, UNAVAILABLE)
            session_creation_attempted = True
            recovery_baseline = coordination.capture_target(target_path)
            created = store.create(
                session_id,
                checked["request"],
                run_config,
                eligible,
            )
            running = store.transition(
                session_id, created.revision, "running"
            )
            store.initialize_coordination(
                session_id,
                running.revision,
                recovery_baseline,
            )
            record = {
                "id": session_id,
                "caller": caller,
                "project": checked["project"],
                "work_area": checked["work_area"],
                "target_path": target_path,
                "target_identity": identity,
                "pid": launch.process.pid,
                "created_at": registry.now_iso(),
                "runtime": runtime,
                "execution_context": context,
            }
            document["sessions"].append(record)
            _save_registry(home, document)
        projected = _projection(home, record)
        _track_child(home, session_id, launch.process)
        launch.release()
        return projected
    except PublicLifecycleError:
        if launch is not None:
            launch.abort()
        if session_creation_attempted:
            _rollback_unreleased_creation(
                home,
                store,
                session_id,
                (
                    None
                    if recovery_baseline is None
                    else recovery_baseline["revision"]
                ),
            )
        _discard_created_dirs(home, target_path, created_dirs)
        raise
    except (brainstorming.ContractError, coordination.CoordinationRejected) as exc:
        if launch is not None:
            launch.abort()
        if session_creation_attempted:
            _rollback_unreleased_creation(
                home,
                store,
                session_id,
                (
                    None
                    if recovery_baseline is None
                    else recovery_baseline["revision"]
                ),
            )
        _discard_created_dirs(home, target_path, created_dirs)
        raise PublicLifecycleError(400, INVALID_REQUEST) from exc
    except Exception as exc:
        if launch is not None:
            launch.abort()
        if session_creation_attempted:
            try:
                _rollback_unreleased_creation(
                    home,
                    store,
                    session_id,
                    (
                        None
                        if recovery_baseline is None
                        else recovery_baseline["revision"]
                    ),
                )
            except Exception as rollback_error:
                raise PublicLifecycleError(503, UNAVAILABLE) from rollback_error
        _discard_created_dirs(home, target_path, created_dirs)
        raise PublicLifecycleError(503, UNAVAILABLE) from exc


def inspect_session(home, session_id, authorize):
    """Authorize from immutable service metadata, then read durable state."""
    record = _record_by_id(home, session_id)
    _authorize_record(record, authorize)
    return _projection(home, record)


def _list_projection(store, record):
    """One cheap list row: immutable service metadata first, then state.

    A session whose durable state is unreadable still lists — with its
    state-derived fields null and the fault named — because one broken
    session must never hide every other session from the operator.
    """
    row = {
        "id": record["id"],
        "caller": record["caller"],
        "project": record["project"],
        "work_area": record["work_area"],
        "target_path": record["target_path"],
        "created_at": record["created_at"],
        "process": "running" if _process_alive(record) else "stopped",
        "status": None,
        "question": None,
        "revision": None,
        "rounds_used": None,
        "max_rounds": None,
        "state_error": None,
    }
    try:
        snapshot = store.read(record["id"])
        if snapshot is None:
            raise RuntimeError("Brainstorming session state is unavailable")
        state = snapshot.state
        progress = brainstorming.coordination_projection(state)
        row.update(
            {
                "status": state["status"],
                "question": state["request"]["question"],
                "revision": snapshot.revision,
                "rounds_used": (
                    0 if progress is None else progress["rounds_used"]
                ),
                "max_rounds": state["request"]["max_rounds"],
            }
        )
    except Exception as exc:  # one row's fault is not the list's fault
        row["state_error"] = str(exc)
    return row


def list_sessions(home, visible):
    """Project every session the caller may see, newest creation first.

    `visible` is a predicate over the immutable service record, so the
    authorization decision is taken before any durable state is read —
    the same ordering the single-session routes use.
    """
    if not callable(visible):
        raise PublicLifecycleError(503, UNAVAILABLE)
    reap_children(home)
    try:
        with _locked_registry(home):
            records = _load_registry(home)["sessions"]
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    store = brainstorming.SessionStore(state_directory(home))
    rows = [
        _list_projection(store, record)
        for record in records
        if visible(copy.deepcopy(record))
    ]
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    return rows


def delete_session(home, session_id, authorize, purge=False):
    """Forget one stopped session; with purge, drop its durable state too.

    A running session refuses (stop it first) — deletion never signals a
    process. Without purge only the service record is removed: the panel
    forgets the session, its target is freed for a new discussion, and
    the durable state stays on disk as evidence (a milestone replaying a
    retained revision keeps working). With purge the session's keys and
    transcript are removed FIRST — a purge fault leaves the record in
    place so the operator can simply retry. The target artifact is never
    touched either way.
    """
    record = _record_by_id(home, session_id)
    _authorize_record(record, authorize)
    try:
        with _locked_registry(home):
            document = _load_registry(home)
            record = _find_record(document, session_id)
            if record is None:
                raise PublicLifecycleError(404, UNKNOWN_SESSION)
            with _STOPS_GUARD:
                stopping = (
                    os.path.abspath(home), session_id
                ) in _STOPS_IN_FLIGHT
            if stopping or _process_alive(record):
                # A stop mid-reconcile still owns the target's recovery;
                # freeing the target under it would let the stale
                # reconcile rewrite a successor session's document.
                raise PublicLifecycleError(409, SESSION_RUNNING)
            if purge:
                store = brainstorming.SessionStore(state_directory(home))
                store.discard_session(session_id)
            document["sessions"] = [
                item
                for item in document["sessions"]
                if item["id"] != session_id
            ]
            _save_registry(home, document)
    except PublicLifecycleError:
        raise
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    return {"deleted": session_id, "purged": bool(purge)}


def view_session(home, session_id, authorize, preview_limit):
    """Project one authorized durable revision for the dedicated view."""
    record = _record_by_id(home, session_id)
    _authorize_record(record, authorize)
    try:
        store = brainstorming.SessionStore(state_directory(home))
        snapshot = store.read(record["id"])
        if snapshot is None:
            raise RuntimeError("Brainstorming session state is unavailable")
        state = snapshot.state
        progress = brainstorming.coordination_projection(state)
        target = {
            "ref": state["request"]["target_path"],
            "revision": None,
            "exists": None,
            "content": None,
            "truncated": False,
        }
        if (
            progress is not None
            and progress["accepted_target_revision"] is not None
        ):
            accepted = store.read_target_revision(
                record["id"], progress["accepted_target_revision"]
            )
            exists, content = brainstorming.target_revision_content(accepted)
            target.update(
                {"revision": accepted["revision"], "exists": exists}
            )
            if exists:
                try:
                    text = content.decode("utf-8")
                except UnicodeDecodeError:
                    pass
                else:
                    target["content"] = text[:preview_limit]
                    target["truncated"] = len(text) > preview_limit
        turns = [] if progress is None else progress["completed_turns"]
        return {
            "id": record["id"],
            "caller": record["caller"],
            "status": state["status"],
            "question": state["request"]["question"],
            "process": "running" if _process_alive(record) else "stopped",
            "revision": snapshot.revision,
            "target": target,
            "participants": copy.deepcopy(
                state["run_config"]["participants"]
            ),
            "same_family_fallback": state["run_config"][
                "same_family_fallback"
            ],
            "closure_policy": state["run_config"]["closure_policy"],
            "closure_ballots": [
                copy.deepcopy(event["fact"])
                for event in state["transcript_events"]
                if event["kind"] == "closure_ballot"
            ],
            "round": {
                "current": turns[-1]["round"] if turns else 0,
                "completed": 0 if progress is None else progress["rounds_used"],
                "maximum": state["request"]["max_rounds"],
            },
            "transcript_markdown": brainstorming.render_transcript(state),
            "result": copy.deepcopy(state.get("result")),
        }
    except PublicLifecycleError:
        raise
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc


def _signal_lifecycle(record):
    pid = record.get("pid")
    if not pid or not _process_alive(record):
        return True
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return not _process_alive(record)
    deadline = time.monotonic() + STOP_WAIT_S
    while time.monotonic() < deadline:
        if not _process_alive(record):
            return True
        time.sleep(0.05)
    return not _process_alive(record)


def _failure_result(state, reason):
    projection = brainstorming.coordination_projection(state)
    return {
        "outcome": "failure",
        "target_ref": state["request"]["target_path"],
        "transcript_ref": state["transcript_ref"],
        "rounds_used": 0 if projection is None else projection["rounds_used"],
        "reason": reason,
    }


def _closing_summary(state, reason, proportionality):
    projection = brainstorming.coordination_projection(state)
    accepted_record_exists = bool(
        projection
        and (
            projection["completed_turns"]
            or state.get("transcript_events")
        )
    )
    unresolved = []
    if accepted_record_exists:
        unresolved.append(
            "The lifecycle ended before accepted discussion turns and ballots "
            "were classified into a terminal objection account; consult those "
            "records above."
        )
    return {
        "reason": reason,
        "unresolved_objections": unresolved,
        "affected_parties": (
            "No participant-authored terminal account established the affected "
            "parties before the lifecycle ended."
        ),
        "damage_altitude": (
            "No participant-authored terminal account established the realistic "
            "damage altitude before the lifecycle ended."
        ),
        "proportionality": proportionality,
        "escalation_evidence": (
            "The lifecycle did not classify whether accepted discussion records "
            "contain concrete escalation evidence; consult those records above."
            if accepted_record_exists
            else None
        ),
    }


def _reconcile_for_terminal(store, session_id):
    coordinator = coordination.BrainstormingCoordinator(store, None)
    for _attempt in range(8):
        snapshot = store.read(session_id)
        if snapshot is None:
            raise PublicLifecycleError(503, UNAVAILABLE)
        if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
            return snapshot
        try:
            return coordinator.prepare(session_id)
        except brainstorming.RevisionConflict:
            continue
        except coordination.CoordinationRejected as exc:
            current = store.read(session_id)
            if current is None:
                raise PublicLifecycleError(503, UNAVAILABLE) from exc
            if current.state["status"] in brainstorming.TERMINAL_STATUSES:
                return current
            raise PublicLifecycleError(409, STOP_INCOMPLETE) from exc
        except brainstorming.HistoryRewriteError as exc:
            raise PublicLifecycleError(409, STOP_INCOMPLETE) from exc
    raise PublicLifecycleError(409, STOP_INCOMPLETE)


# Stops currently reconciling, announced so deletion can refuse them: a
# stop's reconcile-and-close phase runs for seconds without the registry
# lock, and a delete that freed the target meanwhile would let the stale
# reconcile rewrite a successor session's document. In-process like
# _CHILDREN — one service instance owns a home.
_STOPS_IN_FLIGHT = set()
_STOPS_GUARD = threading.Lock()


def stop_session(home, session_id, authorize):
    """Stop worker activity, reconcile only the target, and fail atomically."""
    record = _record_by_id(home, session_id)
    _authorize_record(record, authorize)
    token = (os.path.abspath(home), session_id)
    with _STOPS_GUARD:
        _STOPS_IN_FLIGHT.add(token)
    try:
        # Re-read AFTER announcing the stop; _record_by_id serializes on
        # the registry lock, so a delete lands strictly before this
        # re-read (the record is gone: typed 404, nothing to reconcile)
        # or strictly after the announcement (the delete refuses).
        record = _record_by_id(home, session_id)
        return _stop_authorized(home, session_id, record)
    except PublicLifecycleError:
        raise
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    finally:
        with _STOPS_GUARD:
            _STOPS_IN_FLIGHT.discard(token)


def _stop_authorized(home, session_id, record):
    store = brainstorming.SessionStore(state_directory(home))
    try:
        snapshot = store.read(session_id)
    except Exception as exc:
        raise PublicLifecycleError(503, UNAVAILABLE) from exc
    if snapshot is None:
        raise PublicLifecycleError(503, UNAVAILABLE)
    if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
        return _projection(home, record)

    if not _signal_lifecycle(record):
        raise PublicLifecycleError(409, STOP_INCOMPLETE)
    if record.get("pid"):
        _clear_pid(home, session_id, record["pid"])
        record["pid"] = None

    reason = "The caller stopped the discussion."
    for _attempt in range(8):
        snapshot = _reconcile_for_terminal(store, session_id)
        if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
            return _projection(home, record)
        projection = brainstorming.coordination_projection(snapshot.state)
        if projection is None:
            raise PublicLifecycleError(409, STOP_INCOMPLETE)
        interruption = {
            "after_completed_turns": len(projection["completed_turns"]),
            "plain": reason,
        }
        result = _failure_result(snapshot.state, reason)
        summary = _closing_summary(
            snapshot.state,
            reason,
            "Stopping follows the caller's explicit request.",
        )
        try:
            store.close_with_interruption(
                session_id,
                snapshot.revision,
                interruption,
                result,
                summary,
            )
            current = _record_by_id(home, session_id)
            return _projection(home, current)
        except brainstorming.RevisionConflict as conflict:
            if (
                conflict.current.state["status"]
                in brainstorming.TERMINAL_STATUSES
            ):
                current = _record_by_id(home, session_id)
                return _projection(home, current)
            continue
        except (
            brainstorming.ContractError,
            brainstorming.HistoryRewriteError,
            coordination.CoordinationRejected,
        ) as exc:
            raise PublicLifecycleError(409, STOP_INCOMPLETE) from exc
    raise PublicLifecycleError(409, STOP_INCOMPLETE)


def _participant_execution(store, record, participant_process_factory):
    runtime = record["runtime"]
    provider = runners.SubprocessRunner(
        runtime["commands"],
        runtime.get("timeouts") or {},
        stall_window_s=runtime.get("worker_stall_window_s"),
        stall_min_cpu_s=runtime.get("worker_stall_min_cpu_s"),
        participant_process_factory=participant_process_factory,
    )
    snapshot = store.read(record["id"])
    if snapshot is None:
        raise brainstorming.SessionNotFound(record["id"])
    bindings = {}
    for participant in snapshot.state["run_config"]["participants"]:
        family = participant["model_family"]
        # Per-seat resolution recorded at creation; records written before
        # seats carried their own model/effort fall back to the family
        # defaults, which is byte-identical to their original behavior.
        seat = (runtime.get("executors") or {}).get(
            participant["executor_ref"]
        )
        if seat is None:
            seat = runtime.get("model_defaults", {}).get(family) or {}
        bindings[participant["executor_ref"]] = (
            execution.RunnerParticipantExecutor(
                family,
                provider,
                model=seat.get("model"),
                effort=seat.get("effort"),
            )
        )
    return execution.ParticipantExecution(store, bindings)


def _safe_operational_failure(store, coordinator, session_id):
    """Record the stopped discussion and fail after exact target recovery."""
    reason = "The discussion stopped because participant execution failed."
    try:
        for _attempt in range(8):
            snapshot = store.read(session_id)
            if snapshot is None:
                return False
            if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
                return True
            try:
                snapshot = coordinator.prepare(session_id)
            except brainstorming.RevisionConflict:
                continue
            result = _failure_result(snapshot.state, reason)
            summary = _closing_summary(
                snapshot.state,
                reason,
                "Ending the failed discussion preserves its last accepted work.",
            )
            projection = brainstorming.coordination_projection(snapshot.state)
            if projection is None:
                return False
            interruption = {
                "after_completed_turns": len(projection["completed_turns"]),
                "plain": reason,
            }
            try:
                store.close_with_interruption(
                    session_id,
                    snapshot.revision,
                    interruption,
                    result,
                    summary,
                    failure_origin="operational",
                )
                return True
            except brainstorming.RevisionConflict:
                continue
        return False
    except Exception:
        return False


def run_lifecycle(
    home,
    session_id,
    participant_process_factory=None,
    require_pid_claim=True,
):
    """Drive complete ordered rounds and closure until one terminal result."""
    try:
        with _locked_registry(home):
            record = _find_record(_load_registry(home), session_id)
            if record is None:
                return 2
            record = copy.deepcopy(record)
        if require_pid_claim and record["pid"] != os.getpid():
            return 2
        store = brainstorming.SessionStore(state_directory(home))
        participant_execution = _participant_execution(
            store,
            record,
            participant_process_factory or _spawn_participant,
        )
        coordinator = coordination.BrainstormingCoordinator(
            store, participant_execution
        )
        prepared = coordinator.prepare(session_id)
        if prepared.state["status"] in brainstorming.TERMINAL_STATUSES:
            return 0
        execution_context = record["execution_context"]

        while True:
            snapshot = store.read(session_id)
            if snapshot is None:
                return 2
            if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
                return 0
            pending_attempt = store.read_turn_attempt(session_id)
            if (
                pending_attempt is not None
                and pending_attempt.get("kind", "discussion_turn")
                == "closure"
            ):
                snapshot = coordinator.run_closure(
                    session_id, execution_context
                )
                if snapshot.state["status"] in brainstorming.TERMINAL_STATUSES:
                    return 0
                continue
            starting_round = snapshot.state["rounds_used"]
            while snapshot.state["rounds_used"] == starting_round:
                try:
                    snapshot = coordinator.run_next_turn(
                        session_id, execution_context
                    )
                except brainstorming.RevisionConflict:
                    snapshot = store.read(session_id)
                    if (
                        snapshot is not None
                        and snapshot.state["status"]
                        in brainstorming.TERMINAL_STATUSES
                    ):
                        return 0
                if (
                    snapshot is not None
                    and snapshot.state["status"]
                    in brainstorming.TERMINAL_STATUSES
                ):
                    return 0
            try:
                snapshot = coordinator.run_closure(
                    session_id, execution_context
                )
            except brainstorming.RevisionConflict:
                continue
            if (
                snapshot is not None
                and snapshot.state["status"]
                in brainstorming.TERMINAL_STATUSES
            ):
                return 0
    except LifecycleStop:
        return 3
    except Exception:
        traceback.print_exc(file=sys.stderr)
        try:
            store
            coordinator
        except UnboundLocalError:
            return 3
        return 4 if _safe_operational_failure(
            store, coordinator, session_id
        ) else 3


def _install_stop_handler():
    def stop(_signum, _frame):
        runners.kill_active_worker_groups()
        raise LifecycleStop()

    signal.signal(signal.SIGTERM, stop)


def _wait_for_start(fd):
    try:
        return os.read(fd, 1) == b"1"
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--home", required=True)
    run.add_argument("--session", required=True)
    run.add_argument("--start-fd", required=True, type=int)
    args = parser.parse_args(argv)
    if args.command != "run" or not _wait_for_start(args.start_fd):
        return 2
    _install_stop_handler()
    return run_lifecycle(args.home, args.session)


if __name__ == "__main__":
    raise SystemExit(main())
