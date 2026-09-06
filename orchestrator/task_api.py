"""Durable standalone task records and their immediate execution host."""

from __future__ import annotations

import copy
import datetime
import json
import math
import os
import shutil
import tempfile
import threading
import time
import uuid

from orchestrator import brainstorming, brainstorming_tasks, contracts, driver, gitsync
from orchestrator import brainstorming_coordination as coordination
from orchestrator import kvstore, pricing, profiles, prompt_sets
from orchestrator import registry, runners, session_repository, staffing, tasks
from orchestrator import state as st
from orchestrator.task_execution import ExecutionBusy, TaskExecutionLease


TASKS_DIRNAME = "tasks"
REVIEWED_DIRNAME = "reviewed"
_TASK_KEY_PREFIX = "tasks/task:"
_DOCUMENT_SCHEMA_VERSION = 1
RECOVERABLE_EXECUTORS = frozenset(("agent_call", "reviewed_task", "deep_task"))


class TaskControlConflict(RuntimeError):
    """The requested control no longer names a safe execution boundary."""


class _TaskPaused(Exception):
    """Unwind a coordinator without publishing a terminal task result."""


def state_directory(home):
    """Directory of the standalone task KV store, beside Brainstorming's."""
    return os.path.join(os.path.abspath(home), TASKS_DIRNAME, "state")


def records_path(home):
    """The KV file that holds every standalone task document."""
    return os.path.join(state_directory(home), kvstore.STORE_FILENAME)


def reviewed_state_directory(home, task_id):
    fragment = kvstore.validate_fragment(task_id, "task_id")
    return os.path.join(os.path.abspath(home), TASKS_DIRNAME, REVIEWED_DIRNAME, fragment)


def reviewed_state_path(home, task_id):
    return os.path.join(reviewed_state_directory(home, task_id), "state.json")


def task_key(task_id):
    """`tasks/task:<id>` — one namespace beside runs and Brainstorming."""
    return _TASK_KEY_PREFIX + kvstore.validate_fragment(task_id, "task_id")


def _admission_stamp():
    """Microsecond ISO stamp: second-resolution ties lose admission order."""
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f+0000"
    )


class StandaloneTaskStore:
    """One durable home for canonical records admitted outside a milestone.

    Records live in the shared KV model under their own namespace prefix, one
    document per task, exactly as Brainstorming keeps its sessions: the same
    layout a product datastore (Agent99) reads, listable by prefix and
    filterable by project. Locally the store is its own directory file, kept
    apart from the Brainstorming and service files on purpose (operator,
    2026-08-18). The document wraps the canonical record with the admission
    time so listings keep admission order without touching the exact record
    shape.
    """

    def __init__(self, home):
        self.home = os.path.abspath(home)
        self._store = kvstore.RevisionEnvelopeStore(
            kvstore.LocalKVClient(state_directory(self.home))
        )

    @staticmethod
    def _document(record, admitted_at, stop_reason=None, lifecycle=None):
        document = {
            "schema_version": _DOCUMENT_SCHEMA_VERSION,
            "admitted_at": admitted_at,
            "record": record,
        }
        if stop_reason is not None:
            document["stop_reason"] = stop_reason
        if lifecycle is not None:
            document["lifecycle"] = lifecycle
        return document

    @staticmethod
    def _validate_document(value, key):
        if (
            not isinstance(value, dict)
            or not {"schema_version", "admitted_at", "record"} <= set(value)
            or set(value) - {
                "schema_version", "admitted_at", "record", "stop_reason", "lifecycle"
            }
            or value["schema_version"] != _DOCUMENT_SCHEMA_VERSION
            or not isinstance(value["admitted_at"], str)
            or not isinstance(value["record"], dict)
            or (
                "stop_reason" in value
                and (
                    not isinstance(value["stop_reason"], str)
                    or not value["stop_reason"].strip()
                )
            )
        ):
            raise tasks.TaskRecordError(
                "standalone task document %s is malformed" % key
            )
        if "lifecycle" not in value:
            return value  # Pre-control documents deliberately remain readable.
        lifecycle = value["lifecycle"]
        required = {"status", "revision", "reason", "source", "history"}
        if (
            not isinstance(lifecycle, dict)
            or not required <= set(lifecycle)
            or set(lifecycle) - required - {"completed_result"}
            or lifecycle.get("status") not in ("running", "pausing", "paused")
            or type(lifecycle.get("revision")) is not int
            or lifecycle["revision"] < 0
            or not isinstance(lifecycle.get("history"), list)
        ):
            raise tasks.TaskRecordError("standalone task lifecycle is malformed")
        for name in ("reason", "source"):
            entry = lifecycle[name]
            if not (entry is None or isinstance(entry, str) and entry.strip()):
                raise tasks.TaskRecordError("standalone task lifecycle is malformed")
            if lifecycle["status"] != "running" and entry is None:
                raise tasks.TaskRecordError("paused task lifecycle requires a reason and source")
        for event in lifecycle["history"]:
            if (
                not isinstance(event, dict)
                or not {"status", "at"} <= set(event)
                or set(event) - {"status", "at", "reason", "source", "attempt", "call_id"}
                or event["status"] not in ("running", "pausing", "paused")
                or not isinstance(event["at"], str) or not event["at"].strip()
            ):
                raise tasks.TaskRecordError("standalone task lifecycle history is malformed")
            for name in ("reason", "source", "call_id"):
                entry = event.get(name)
                if name in event and not isinstance(entry, str):
                    raise tasks.TaskRecordError("standalone task lifecycle history is malformed")
                if name in event and not entry.strip():
                    raise tasks.TaskRecordError("standalone task lifecycle history is malformed")
                if name in ("reason", "source") and event["status"] != "running" and name not in event:
                    raise tasks.TaskRecordError("paused task history requires a reason and source")
            if "attempt" in event:
                try:
                    tasks.validate_result(event["attempt"])
                except (TypeError, ValueError) as exc:
                    raise tasks.TaskRecordError("task attempt result is malformed") from exc
        if "completed_result" in lifecycle:
            try:
                completed = tasks.validate_result(lifecycle["completed_result"])
                if completed["status"] != "success":
                    raise ValueError("retained completion must be successful")
            except (TypeError, ValueError) as exc:
                raise tasks.TaskRecordError("retained task completion is malformed") from exc
        return value

    def _read_document(self, task_id):
        key = task_key(task_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise tasks.TaskRecordError("unknown task %r" % task_id)
        return current, self._validate_document(current["value"], key)

    @staticmethod
    def _lifecycle(document):
        return copy.deepcopy(document.get("lifecycle") or {
            "status": "running", "revision": 0, "reason": None,
            "source": None, "history": [],
        })

    def lifecycle(self, task_id):
        _current, document = self._read_document(task_id)
        lifecycle = self._lifecycle(document)
        result = document["record"].get("result")
        if result is not None:
            lifecycle["status"] = result["status"]
        if tasks.stored_task_executor(
            document["record"]["order"]["task_executor"]
        ) == "agent_call":
            attempts = [event["attempt"] for event in lifecycle["history"]
                        if isinstance(event.get("attempt"), dict)]
            if attempts:
                aggregate = result or tasks.deep_task_result("success", attempts)
                lifecycle["accounting"] = {
                    key: aggregate[key] for key in (
                        "duration_s", "token_usage", "token_usage_partial", "cost", "cost_partial"
                    )
                }
        return lifecycle

    def _write_lifecycle_locked(self, task_id, current, document, lifecycle):
        updated = dict(document, lifecycle=lifecycle)
        if not self._store.cas(task_key(task_id), current["revision"], updated).ok:
            raise TaskControlConflict("task changed while applying control")
        return copy.deepcopy(lifecycle)

    def pause_locked(self, task_id, reason, source="operator", pending=False,
                     attempt=None, completed_result=None, attempt_id=None):
        current, document = self._read_document(task_id)
        if document["record"].get("result") is not None:
            raise TaskControlConflict("a terminal task cannot be paused")
        lifecycle = self._lifecycle(document)
        status = "pausing" if pending else "paused"
        if (lifecycle["status"] == "paused" and not pending and attempt is None
                and completed_result is None) or (
            lifecycle["status"] == "pausing" and pending and attempt is None
            and completed_result is None
        ):
            return lifecycle
        if lifecycle["status"] == "running":
            lifecycle.update(reason=str(reason), source=source)
        lifecycle.update(status=status, revision=lifecycle["revision"] + 1)
        event = {"status": status, "at": _admission_stamp(),
                 "reason": lifecycle["reason"], "source": lifecycle["source"]}
        if attempt is not None:
            event["attempt"] = copy.deepcopy(attempt)
        if attempt_id is not None:
            event["call_id"] = attempt_id
        if completed_result is not None:
            lifecycle["completed_result"] = copy.deepcopy(completed_result)
        lifecycle["history"].append(event)
        return self._write_lifecycle_locked(task_id, current, document, lifecycle)

    def resume_locked(self, task_id, revision):
        current, document = self._read_document(task_id)
        lifecycle = self._lifecycle(document)
        if (document["record"].get("result") is not None
                or document.get("stop_reason") is not None
                or lifecycle["status"] != "paused"
                or lifecycle["revision"] != revision):
            raise TaskControlConflict("task is not at the requested paused revision")
        lifecycle.update(status="running", revision=revision + 1,
                         reason=None, source=None)
        lifecycle["history"].append({"status": "running", "at": _admission_stamp()})
        return self._write_lifecycle_locked(task_id, current, document, lifecycle)

    def _documents(self):
        listing = self._store.list_entries(prefix=_TASK_KEY_PREFIX)
        documents = []
        for item in listing["items"]:
            key = item["key"]
            current = self._store.read(key)
            if not current["exists?"]:
                continue
            documents.append(self._validate_document(current["value"], key))
        documents.sort(key=lambda doc: (doc["admitted_at"], doc["record"]["id"]))
        return documents

    def _load(self):
        return tasks.task_records(
            {"tasks": [doc["record"] for doc in self._documents()]}
        )

    def records(self):
        return self._load()

    def documents(self):
        """Every stored document, oldest admission first: `admitted_at` beside
        the exact canonical `record`. Listing surfaces use this; the record
        shape itself stays untouched."""
        return [
            {"admitted_at": doc["admitted_at"], "record": doc["record"]}
            for doc in self._documents()
        ]

    def record(self, task_id):
        return tasks.task_record({"tasks": self._load()}, task_id)

    def owner_chain(self, task_id):
        """Return the task and its durable parents, nearest first."""
        records = self._load()
        by_id = {record["id"]: record for record in records}
        current = tasks.task_record({"tasks": records}, task_id)
        chain = []
        seen = set()
        while current["id"] not in seen:
            chain.append(current)
            seen.add(current["id"])
            parent_id = (current.get("parent") or {}).get("task_id")
            if not isinstance(parent_id, str) or parent_id not in by_id:
                break
            current = by_id[parent_id]
        return chain

    def owner_stop_reason(self, task_id):
        """Return the first accepted Stop on a task or its owner chain."""
        for record in self.owner_chain(task_id):
            reason = self.stop_reason(record["id"])
            if reason is not None:
                return reason
        return None

    def admit(self, order, resolved_staffing, primary_workspace):
        with registry.locked(self.home):
            return self.admit_locked(
                order, resolved_staffing, primary_workspace
            )

    def admit_locked(self, order, resolved_staffing, primary_workspace):
        """Admit while the caller holds the service registry lock."""
        state = {"tasks": self._load()}
        record = tasks.admit_task(
            state,
            order,
            resolved_staffing,
            primary_workspace=primary_workspace,
        )
        outcome = self._store.cas(
            task_key(record["id"]),
            None,
            self._document(record, _admission_stamp()),
        )
        if not outcome.ok:
            raise tasks.TaskRecordError(
                "standalone task %s already exists" % record["id"]
            )
        return record

    @staticmethod
    def _related(records, parent_task_id, phase, part):
        return tasks.related_task(
            {"tasks": records}, parent_task_id, phase, part
        )

    def related(self, parent_task_id, phase, part):
        """Return the child durably admitted for one parent phase and part."""
        return self._related(self._load(), parent_task_id, phase, part)

    def admit_related_locked(
        self,
        parent_task_id,
        phase,
        part,
        order,
        resolved_staffing,
        primary_workspace,
    ):
        """Admit or reuse one child while the registry lock serializes identity."""
        records = self._load()
        existing = self._related(records, parent_task_id, phase, part)
        if existing is not None:
            return existing
        state = {"tasks": records}
        record = tasks.admit_related_task(
            state,
            parent_task_id,
            phase,
            part,
            order,
            resolved_staffing,
            primary_workspace=primary_workspace,
        )
        outcome = self._store.cas(
            task_key(record["id"]),
            None,
            self._document(record, _admission_stamp()),
        )
        if not outcome.ok:
            raise tasks.TaskRecordError(
                "standalone task %s already exists" % record["id"]
            )
        return record

    def delete(self, task_id):
        """Forget one terminal task document. Returns the record removed, or
        None when no such document exists. Callers refuse running tasks
        before getting here."""
        with registry.locked(self.home):
            key = task_key(task_id)
            current = self._store.read(key)
            if not current["exists?"]:
                return None
            document = self._validate_document(current["value"], key)
            self._store.delete(key, expected_revision=current["revision"])
            return document["record"]

    def record_result(self, task_id, result):
        with registry.locked(self.home):
            return self.record_result_locked(task_id, result)

    def record_result_locked(self, task_id, result):
        """Record a result while the caller holds the service registry lock."""
        key = task_key(task_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise tasks.TaskRecordError("unknown task %r" % task_id)
        document = self._validate_document(current["value"], key)
        if tasks.stored_task_executor(
            document["record"]["order"]["task_executor"]
        ) == "agent_call":
            result = copy.deepcopy(result)
            for event in self._lifecycle(document)["history"]:
                attempt = event.get("attempt")
                if not isinstance(attempt, dict) or (
                    attempt.get("status") == "success" and result["status"] == "success"
                ):
                    continue
                result["duration_s"] += attempt["duration_s"]
                result["token_usage"] = st._add_token_usage(result["token_usage"], attempt["token_usage"])
                result["cost"] = st._add_cost(result["cost"], attempt["cost"])
                result["token_usage_partial"] |= attempt["token_usage_partial"]
                result["cost_partial"] |= attempt["cost_partial"]
        state = {"tasks": [document["record"]]}
        record = tasks.record_task_result(state, task_id, result)
        outcome = self._store.cas(
            key,
            current["revision"],
            self._document(
                state["tasks"][0],
                document["admitted_at"],
                document.get("stop_reason"),
                document.get("lifecycle"),
            ),
        )
        if not outcome.ok:
            raise tasks.TaskRecordError(
                "standalone task %s changed while recording its result"
                % task_id
            )
        return record

    def stop_reason(self, task_id):
        """Return one accepted internal Stop intent, if it was recorded."""
        key = task_key(task_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise tasks.TaskRecordError("unknown task %r" % task_id)
        document = self._validate_document(current["value"], key)
        return document.get("stop_reason")

    def record_stop_locked(self, task_id, reason):
        """Durably accept an owner-coupled Stop under the registry lock."""
        if not isinstance(reason, str) or not reason.strip():
            raise tasks.TaskRecordError("task Stop reason must be non-empty")
        key = task_key(task_id)
        current = self._store.read(key)
        if not current["exists?"]:
            raise tasks.TaskRecordError("unknown task %r" % task_id)
        document = self._validate_document(current["value"], key)
        record = document["record"]
        if record.get("result") is not None:
            raise tasks.TaskRecordError("task %s is already terminal" % task_id)
        existing = document.get("stop_reason")
        if existing is not None:
            return existing
        outcome = self._store.cas(
            key,
            current["revision"],
            self._document(record, document["admitted_at"], reason.strip(),
                           document.get("lifecycle")),
        )
        if not outcome.ok:
            raise tasks.TaskRecordError(
                "standalone task %s changed while recording its Stop" % task_id
            )
        return reason.strip()


def forget_task_evidence(home, record):
    """Best-effort removal of what a deleted task left beside its record:
    the per-call marker and, for Brainstorming, the private work area that
    held its discussion target. Repository files are never touched."""
    task_id = record["id"]
    try:
        os.unlink(_marker_path(home, task_id))
    except FileNotFoundError:
        pass
    except Exception:
        pass
    if (record.get("order") or {}).get("task_executor") == "reviewed_task":
        shutil.rmtree(
            reviewed_state_directory(home, task_id), ignore_errors=True
        )
    if (record.get("order") or {}).get("task_executor") == "brainstorming":
        try:
            work_area, _parent, _target = (
                brainstorming_tasks._private_target_paths(
                    _workspace(record), home, task_id
                )
            )
            shutil.rmtree(work_area, ignore_errors=True)
        except Exception:
            pass


def task_session_id(home, record, host=None):
    """The Brainstorming session a standalone task owns, or None.

    Running: the host knows it. Otherwise: the adapter's durable caller
    relation names a registered session, with its retained private target as
    the fallback after discard. Worker tasks own no session."""
    executor = (record.get("order") or {}).get("task_executor")
    if executor == "reviewed_task":
        try:
            lifecycle = st.load(reviewed_state_path(home, record["id"]))
            selected = next(
                unit for unit in lifecycle["units"]
                if st.unit_key(unit) == lifecycle["reviewed_task"]["unit"]
            )
            session_id = (selected.get("brainstorming_wait") or {}).get(
                "session_id"
            )
            return session_id if isinstance(session_id, str) else None
        except Exception:
            return None
    if executor != "brainstorming":
        return None
    lookup = getattr(host, "running_session_id", None)
    if callable(lookup):
        known = lookup(record["id"])
        if known:
            return known
    native = (record.get("result") or {}).get("native_result")
    if isinstance(native, dict) and isinstance(native.get("session_id"), str):
        return native["session_id"]
    try:
        _area, _parent, target = brainstorming_tasks._private_target_paths(
            _workspace(record), home, record["id"]
        )
        caller = brainstorming_tasks._task_caller(record, record["id"])
        owned = brainstorming_tasks._owned_projection(home, caller, target)
        if owned is not None:
            return owned[0]
        store = brainstorming.SessionStore(
            brainstorming_tasks.lifecycle.state_directory(home)
        )
        found = store.session_ids_for_target(target)
    except Exception:
        return None
    return found[0] if found else None


def worker_staffing(config):
    """The order's best-effort agent-call bookkeeping at admission.

    It DECIDES NOTHING. The call itself is staffed by the router,
    immediately before it is dispatched, from the session the order
    inherited; this snapshot is the ordinary configuration reading kept
    beside the order so a reader can see what the machine looked like when
    the work was admitted, and the marker remains the record of what ran.

    Best-effort accordingly: a configuration this cannot read yields no
    snapshot rather than a refusal. Refusing here would make order
    bookkeeping an availability gate over a call whose staffing it does
    not choose — and the gate would be the wrong one, since the family it
    checks is not the family the router will pick.
    """
    try:
        if not isinstance(config, dict):
            raise ValueError("config")
        families = config["families_order"]
        if not isinstance(families, list) or not families:
            raise ValueError("families_order")
        family = families[0]
        model_defaults = config.get("model_defaults") or {}
        if not isinstance(model_defaults, dict):
            raise ValueError("model_defaults")
        defaults = model_defaults.get(family) or {}
        if not isinstance(defaults, dict):
            raise ValueError("family model defaults")
        model = defaults.get("model")
        effort = defaults.get("effort")
        if not isinstance(family, str) or not family.strip():
            raise ValueError("family")
        for value in (model, effort):
            if value is not None and (
                not isinstance(value, str) or not value.strip()
            ):
                raise ValueError("model default")
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    return {
        "agent_call": {"agent": family, "model": model, "effort": effort}
    }


def _workspace(record, require_exists=True):
    work_area = record["order"]["request"]["work_area"]
    primary = work_area.get("primary")
    workspace = work_area.get("workspace_path")
    if isinstance(primary, dict):
        primary = primary.get("path")
    workspace = workspace or primary
    if not isinstance(workspace, str) or (require_exists and not os.path.isdir(workspace)):
        raise RuntimeError("the task workspace is unavailable")
    return workspace


def _marker_path(home, task_id):
    fragment = kvstore.validate_fragment(task_id, "task_id")
    return os.path.join(home, "task-runtime", "%s.json" % fragment)


def read_worker_marker(home, task_id):
    with open(_marker_path(home, task_id), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_worker_marker(home, task_id, marker):
    path = _marker_path(home, task_id)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=".worker-call-", suffix=".json", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(marker, handle, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


# The pre-provider staffing boundary of a directly ordered agent call.
#
# One router answer, read immediately before the one physical call, from
# the session the order inherited: an edit to that session or to the
# document it names reaches this call, and neither the admission snapshot
# beside the order nor the host's first configured family can select it.
#
# A record admitted BEFORE the cutover carries no `staffing_session` key at
# all, and that absence is the whole of compatibility: it runs the staffing
# frozen on it, under the current or the retired executor name, with no
# rewrite and no derived session.


def _frozen_dispatch(record):
    """(family, model, effort) frozen on one pre-cutover order."""
    staffed = record.get("resolved_staffing") or {}
    snapshot = staffed.get("agent_call")
    if snapshot is None:
        snapshot = staffed.get("worker")
    if not isinstance(snapshot, dict):
        raise RuntimeError(
            "the task carries no staffing and no session to resolve one"
        )
    return snapshot.get("agent"), snapshot.get("model"), snapshot.get("effort")


def _dispatch(home, record, config):
    """(family, model, effort, fallback) for this task's one call."""
    order = record["order"]
    supplied, session = tasks.order_staffing_session(order)
    if not supplied:
        return _frozen_dispatch(record) + (None,)
    resolution = staffing.resolve(
        home,
        session,
        # Always present: admission resolves the catalogue's own default
        # for an order that named none, so there is no second default here.
        (order.get("configuration") or {}).get("role"),
        index=1,
        round=1,
        # The order's own text, passed best-effort and read by no rule.
        brief=order["request"]["request"],
        # Only reachable when the session itself cannot be read, which is
        # also the one case where the machine's families cannot be.
        families=list((config or {}).get("families_order") or []),
    )
    answer = resolution.answer
    return (
        answer["agent"], answer["model"], answer["effort"],
        resolution.staffing_fallback,
    )


def _accounting(carrier, family, model, config, elapsed):
    duration = getattr(carrier, "duration_s", None)
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or duration < 0
    ):
        duration = elapsed
    usage = runners.normalize_token_usage(
        getattr(carrier, "token_usage", None)
    )
    configured_billing = config.get("billing")
    billing_authority_usable = (
        configured_billing is None or isinstance(configured_billing, dict)
    )
    billing = (
        configured_billing.get(family)
        if isinstance(configured_billing, dict)
        else None
    )
    quote = pricing.quote_many(
        family,
        model,
        getattr(carrier, "cost_payloads", None) or [],
        billing=billing,
    )
    cost = None
    if (
        billing_authority_usable
        and quote.api_usd is not None
        and quote.real_usd is not None
    ):
        cost = quote.as_dict()
    return {
        "duration_s": float(duration),
        "token_usage": usage,
        "token_usage_partial": bool(
            getattr(carrier, "token_usage_partial", False) or usage is None
        ),
        "cost": cost,
        "cost_partial": cost is None,
    }


def _native_failure(exc):
    raw = getattr(exc, "raw_texts", None)
    if isinstance(raw, list) and raw:
        return raw[-1]
    return getattr(exc, "raw_text", None)


def _reviewed_authority(record):
    request = record["order"]["request"]
    return (
        "# Standalone reviewed task authority\n\n"
        "## Request\n\n%s\n\n## Context\n\n```json\n%s\n```\n\n"
        "## Reference documents (caller order; no positional roles)\n\n%s\n"
        % (
            request["request"],
            json.dumps(
                request["context"], ensure_ascii=False, sort_keys=True, indent=2
            ),
            "\n".join(
                "- %s" % path for path in request["reference_documents"]
            ) or "- none",
        )
    )


def ensure_reviewed_state(home, record, config, implementation_scope=None):
    """Create the task-id-owned lifecycle state before its first call."""
    path = reviewed_state_path(home, record["id"])
    if os.path.exists(path):
        return path
    request = record["order"]["request"]
    workspace = _workspace(record)
    effective = copy.deepcopy(config)
    strategy_profile = record["order"].get("strategy_profile")
    if strategy_profile is not None:
        profiles.verify_retained(
            strategy_profile["ref"], strategy_profile["profile"]
        )
        effective["profile_ref"] = copy.deepcopy(strategy_profile["ref"])
        effective["profile"] = copy.deepcopy(strategy_profile["profile"])
    output = request.get("output_directory")
    if output is not None:
        relative = os.path.relpath(output, os.path.realpath(workspace))
        effective["docs_dir"] = relative if relative != "." else "."
    task_kind = record["order"]["configuration"]["task_kind"]
    project = request["work_area"]
    project = (
        copy.deepcopy(project)
        if set(("directory", "project", "work_area", "primary", "additional"))
        <= set(project)
        else None
    )
    state = st.new_state(
        request["request"],
        workspace,
        effective,
        name="reviewed task %s" % record["id"],
        slug="reviewed-task-%s" % record["id"][:8],
        project=project,
        prompt_set=record["order"].get(
            "prompt_set", prompt_sets.DEFAULT_SET_NAME
        ),
    )
    authority_path = os.path.join(
        reviewed_state_directory(home, record["id"]), "authority.md"
    )
    slice_info = {
        "id": 1,
        "title": request["request"].splitlines()[0][:120],
        "intent": request["request"],
    }
    if task_kind == contracts.KIND_DRAFT_SKELETON:
        target = state["units"][0]
    else:
        skeleton = state["units"][0]
        skeleton["status"] = st.U_SEALED
        skeleton["artifact"] = authority_path
        state["milestone"]["slices"] = [slice_info]
        note = st._new_unit(st.UNIT_SLICE_DOC, 1)
        if task_kind == contracts.KIND_DRAFT_SLICE_NOTE:
            target = note
            state["units"].append(note)
        else:
            note["status"] = st.U_SEALED
            note["artifact"] = authority_path
            target = st._new_unit(st.UNIT_SLICE_IMPL, 1)
            state["units"].extend((note, target))
    if task_kind == tasks.REVIEWED_COMPLETE_VERIFICATION:
        target["reviewed_task_kind"] = task_kind
    policy = copy.deepcopy(record["order"]["configuration"])
    policy.pop("task_kind")
    target["reviewed_policy"] = policy
    reviewed_task = {
        "task_id": record["id"],
        "unit": st.unit_key(target),
        "authority_path": authority_path,
    }
    if implementation_scope is not None:
        reviewed_task["implementation_scope"] = copy.deepcopy(
            implementation_scope
        )
    state["reviewed_task"] = reviewed_task
    session = record["order"].get("staffing_session")
    if session:
        st.bind_staffing_session(state, session)
    st.append_event(state, "initialized", goal=request["request"])
    st.append_event(
        state,
        "reviewed_policy_frozen",
        unit=st.unit_key(target),
        task_kind=task_kind,
        task_executor=policy["producer"]["task_executor"],
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(authority_path, "w", encoding="utf-8") as handle:
        handle.write(_reviewed_authority(record))
    driver._write_initial_amendments(path)
    st.save_new(path, state)
    return path


class DirectTaskHost:
    """Start one daemon execution per admitted order; retain no queue policy."""

    def __init__(self, home, store=None, runner_factory=None, poll_interval=None):
        self.home = os.path.abspath(home)
        self.store = store or StandaloneTaskStore(home)
        self.runner_factory = runner_factory or self._runner
        self.poll_interval = (
            driver.BRAINSTORMING_POLL_INTERVAL_S
            if poll_interval is None else poll_interval
        )
        self._active = {}
        # Per running task: the worker call control (to interrupt it) or the
        # Brainstorming session id (to stop it), and any operator stop.
        self._controls = {}
        self._sessions = {}
        self._stops = {}
        self._leases = {}
        self._lock = threading.Lock()

    def _family(self, task_id):
        root = self.store.owner_chain(task_id)[-1]
        family = [root]
        identities = {root["id"]}
        for record in self.store.records():
            if (record.get("parent") or {}).get("task_id") in identities:
                family.append(record)
                identities.add(record["id"])
        return family

    def _lease(self, task_id):
        lease = TaskExecutionLease(
            os.path.join(self.home, "task-runtime", kvstore.validate_fragment(task_id, "task_id")),
            on_pending=lambda: self._worker_quiescence_pending(task_id),
            poll_interval=self.poll_interval,
        )
        if not os.path.exists(lease.lock_path):
            # A pre-upgrade worker never inherited a lease or wrote its PGID.
            # Do not turn absence of NEW evidence into proof that it died.
            for path in (
                _marker_path(self.home, task_id),
                os.path.join(reviewed_state_directory(self.home, task_id), "current.json"),
            ):
                try:
                    with open(path, encoding="utf-8") as handle:
                        marker = json.load(handle)
                except FileNotFoundError:
                    continue
                except (OSError, ValueError) as exc:
                    raise ExecutionBusy("legacy execution marker is unreadable; recovery is blocked") from exc
                if (not isinstance(marker, dict)
                        or not isinstance(marker.get("pending_calls", []), list)
                        or any(not isinstance(call, dict)
                               for call in marker.get("pending_calls", []))):
                    raise ExecutionBusy("legacy execution marker is malformed; recovery is blocked")
                calls = [marker] + marker.get("pending_calls", [])
                if any(call.get("completed") is not True for call in calls):
                    raise ExecutionBusy(
                        "prior execution predates worker tracking; its quiescence "
                        "must be established before Resume"
                    )
        return lease

    def _worker_quiescence_pending(self, task_id):
        with registry.locked(self.home):
            if self.store.record(task_id)["result"] is None:
                self.store.pause_locked(
                    task_id, "Waiting for prior worker quiescence before continuing",
                    source="error", pending=True,
                )

    def _ensure_workers_quiescent(self, records, owner_ids=()):
        """Fence physical work, including immutable terminal family members.

        A coordinator checking its own safe boundary already holds the lease;
        inspect its journal without trying to flock a second descriptor. Other
        active coordinators must finish before their workspace can be reused.
        """
        for record in records:
            identity = record["id"]
            with self._lock:
                active = identity in self._active
                lease = self._leases.get(identity)
                if lease is not None:
                    if active and identity not in owner_ids:
                        raise ExecutionBusy("the previous execution is still stopping")
                    # Resume releases unused child reservations concurrently
                    # with the root's startup checks. Keep the owned descriptor
                    # alive for the entire journal inspection/clear operation.
                    lease.ensure_quiescent()
                    continue
            with self._lease(identity):
                pass
            if active and identity not in owner_ids:
                raise ExecutionBusy("the previous execution is still stopping")

    def _workers_quiescent(self, records, owner_ids=()):
        try:
            self._ensure_workers_quiescent(records, owner_ids)
            return True
        except (ExecutionBusy, OSError):
            return False

    def lifecycle(self, task_id):
        value = self.store.lifecycle(task_id)
        family = self._family(task_id)
        supported = tasks.stored_task_executor(
            self.store.record(task_id)["order"]["task_executor"]
        ) in RECOVERABLE_EXECUTORS
        value.update(root_task_id=family[0]["id"], can_pause=False,
                     can_resume=False, blocked_reason=None)
        if not supported or self.store.record(task_id)["result"] is not None:
            return value
        if self.store.owner_stop_reason(task_id) is not None:
            value["blocked_reason"] = "Cancellation is pending; this task cannot resume"
            return value
        value["can_pause"] = value["status"] == "running"
        if value["status"] in ("paused", "pausing"):
            try:
                if not self._discussions_quiescent(family):
                    raise TaskControlConflict("an owned discussion is still stopping or its quiescence is unknown")
                self._ensure_workers_quiescent(family)
                value["can_resume"] = value["status"] == "paused"
            except (ExecutionBusy, TaskControlConflict) as exc:
                value["blocked_reason"] = str(exc)
        return value

    def pause(self, task_id, reason="paused by operator"):
        with registry.locked(self.home):
            record = self.store.record(task_id)
            if (tasks.stored_task_executor(record["order"]["task_executor"])
                    not in RECOVERABLE_EXECUTORS or record["result"] is not None):
                raise TaskControlConflict("this task cannot be paused")
            family = self._family(task_id)
            pending = (not self._discussions_quiescent(family)
                       or not self._workers_quiescent(family))
            for member in family:
                if member["result"] is None:
                    self.store.pause_locked(
                        member["id"], reason,
                        pending=pending,
                    )
            if pending:
                self._start_pause_settlement(
                    [member for member in family if member["result"] is None], lambda: {})
        return self.lifecycle(task_id)

    def resume(self, task_id, config_resolver, revision):
        with registry.locked(self.home):
            return self.resume_locked(task_id, config_resolver, revision)

    def resume_locked(self, task_id, config_resolver, revision):
        if type(revision) is not int or revision < 0:
            raise ValueError("revision must be a non-negative integer")
        current = self.store.lifecycle(task_id)
        if current["status"] != "paused" or current["revision"] != revision:
            raise TaskControlConflict("task is not at the requested paused revision")
        family = self._family(task_id)
        open_members = [member for member in family if member["result"] is None]
        acquired = {}
        changing = False
        try:
            if not self._discussions_quiescent(family):
                raise TaskControlConflict("an owned discussion is still stopping or its quiescence is unknown")
            # Acquire the entire family BEFORE touching state or Git. A
            # surviving worker keeps this lease across a host-process crash.
            for member in family:
                identity = member["id"]
                if self.is_active(identity):
                    raise TaskControlConflict("the previous execution is still stopping")
                lifecycle = self.store.lifecycle(identity)
                if member["result"] is None and (
                        lifecycle["status"] != "paused" or self.store.stop_reason(identity)):
                    raise TaskControlConflict("the task family is not fully paused")
                acquired[identity] = self._lease(identity).acquire()
            changing = True
            for member in open_members:
                identity = member["id"]
                self._recover_worker_attempt_locked(identity)
                if tasks.stored_task_executor(member["order"]["task_executor"]) == "reviewed_task":
                    path = reviewed_state_path(self.home, identity)
                    if os.path.isfile(path):
                        with st.exclusive_mutation(path):
                            state = st.load(path)
                            if state.get("failure") is not None:
                                st.resume_run(state)
                                st.save(path, state)
                self.store.resume_locked(identity, self.store.lifecycle(identity)["revision"])
            with self._lock:
                self._leases.update(acquired)
            acquired = {}
            try:
                self.start(family[0], config_resolver)
            except Exception as exc:
                for member in open_members:
                    self.store.pause_locked(member["id"], str(exc), source="error")
                raise
        except ExecutionBusy as exc:
            raise TaskControlConflict(str(exc)) from exc
        except Exception as exc:
            if changing:
                for member in open_members:
                    if self.store.record(member["id"])["result"] is None:
                        self.store.pause_locked(
                            member["id"], "Resume could not start: %s" % exc,
                            source="error",
                        )
            raise
        finally:
            for lease in acquired.values():
                lease.close()
            # Reservations for children are released; start() reacquires
            # them before dispatch. Durable running state alone grants no
            # permission to execute without the lease.
            with self._lock:
                unused = [identity for identity in self._leases if identity not in self._active]
                for identity in unused:
                    self._leases.pop(identity).close()
        return self.store.lifecycle(task_id)

    @staticmethod
    def _reviewed_discussion_callers(state, unit):
        callers = {"milestone:%s:%s" % (state.get("name") or "run", st.unit_key(unit))}
        # A Brainstorming producer is itself a durable inner task, and uses
        # the adapter's task caller rather than the need_rethink caller.
        callers.update(
            brainstorming_tasks._task_caller(inner, inner["id"])
            for inner in state.get("tasks", [])
            if tasks.stored_task_executor(inner["order"]["task_executor"]) == "brainstorming"
        )
        return callers

    def _pause_discussion_ids(self, record):
        """Read ownership without constructing a Driver or recovering Git."""
        if tasks.stored_task_executor(record["order"]["task_executor"]) != "reviewed_task":
            return set()
        path = reviewed_state_path(self.home, record["id"])
        if not os.path.isfile(path):
            return set()
        state = st.load(path)
        unit = next(unit for unit in state["units"]
                    if st.unit_key(unit) == state["reviewed_task"]["unit"])
        session_id = (unit.get("brainstorming_wait") or {}).get("session_id")
        identities = {session_id} if isinstance(session_id, str) else set()
        callers = self._reviewed_discussion_callers(state, unit)
        # Include creation-before-attachment and still-exiting historical
        # sessions. Neither an absent attachment nor a terminal result proves
        # that an independently owned process has stopped.
        rows = brainstorming_tasks.lifecycle.list_sessions(
            self.home, lambda session: session.get("caller") in callers
        )
        if any(row.get("state_error") for row in rows):
            raise TaskControlConflict("owned discussion state is unavailable")
        identities.update(row["id"] for row in rows)
        if (record["result"] is not None and isinstance(session_id, str)
                and any(event.get("type") == "brainstorming_missing_detached"
                        and event.get("session_id") == session_id
                        for event in state.get("events", []))):
            # Older Cancel receipts kept the missing attachment. Honor the
            # durable detach without rewriting an immutable terminal child,
            # but never mistake a registered session or surviving attempt for
            # a completed discard.
            try:
                brainstorming_tasks.lifecycle._record_by_id(self.home, session_id)
            except brainstorming_tasks.lifecycle.PublicLifecycleError as exc:
                if exc.code != brainstorming_tasks.lifecycle.UNKNOWN_SESSION:
                    raise
                if self._discussion_attempts_quiescent(session_id):
                    identities.discard(session_id)
        return identities

    def _discussion_quiescent(self, session_id):
        projection = brainstorming_tasks.lifecycle.inspect_session(
            self.home, session_id, lambda _record: True
        )
        if projection.get("process") != "stopped":
            return False
        return self._discussion_attempts_quiescent(session_id)

    def _discussion_attempts_quiescent(self, session_id):
        sessions = brainstorming.SessionStore(
            brainstorming_tasks.lifecycle.state_directory(self.home)
        )
        attempt = sessions.read_turn_attempt(session_id)
        intervention = sessions.read_external_intervention(session_id)
        return bool(
            (attempt is None or attempt["quiescent"])
            and (intervention is None or intervention["provider_attempt"] == 0
                 or intervention["provider_quiescent"])
        )

    def _discussions_quiescent(self, records, stop=False):
        quiet = True
        for record in records:
            try:
                identities = self._pause_discussion_ids(record)
            except Exception:
                quiet = False
                continue
            for identity in identities:
                try:
                    if self._discussion_quiescent(identity):
                        continue
                    if stop:
                        brainstorming_tasks.lifecycle.stop_session(
                            self.home, identity, lambda _record: True
                        )
                    if not self._discussion_quiescent(identity):
                        quiet = False
                except Exception:
                    # Unknown is not stopped. Leave the durable pause pending
                    # and retry inspection/Stop, never the failed provider call.
                    quiet = False
        return quiet

    def _settle_pause(self, task_id, records=None, owner_ids=None):
        records = records or [self.store.record(task_id)]
        owner_ids = (task_id,) if owner_ids is None else owner_ids
        evidence = (self._family(task_id)
                    if tasks.stored_task_executor(self.store.record(task_id)["order"]["task_executor"])
                    == "deep_task" else records)
        while True:
            if self._stop_reason(task_id) is not None:
                # Leave descendant cancellation to the ordinary parent loop,
                # but never abandon this coordinator's surviving worker.
                if self._workers_quiescent([self.store.record(task_id)], owner_ids):
                    return
            elif (self._discussions_quiescent(evidence, stop=True)
                  and self._workers_quiescent(evidence, owner_ids)):
                with registry.locked(self.home):
                    if self._stop_reason(task_id) is not None:
                        return
                    for record in reversed(records):
                        identity = record["id"]
                        if self.store.record(identity)["result"] is not None:
                            continue
                        lifecycle = self.store.lifecycle(identity)
                        self.store.pause_locked(
                            identity, lifecycle.get("reason") or "paused by operator",
                            source=lifecycle.get("source") or "operator",
                        )
                return
            time.sleep(self.poll_interval)

    def _start_pause_settlement(self, records, config_resolver):
        """Control-only recovery; never restores Git or dispatches a worker.

        The caller holds the registry lock. Existing coordinators settle their
        own cooperative boundary; an interrupted family needs only this host
        thread to stop/inspect its independently running discussions.
        """
        with self._lock:
            if any(record["id"] in self._active for record in records):
                return
            for record in records:
                self._active[record["id"]] = _workspace(record, require_exists=False)

        def settle():
            root = records[0]
            try:
                self._settle_pause(root["id"], records,
                                   owner_ids={record["id"] for record in records})
            finally:
                with registry.locked(self.home):
                    with self._lock:
                        for record in records:
                            self._active.pop(record["id"], None)
                            self._stops.pop(record["id"], None)
                    if self.store.stop_reason(root["id"]) is not None:
                        try:
                            self.start(self.store.record(root["id"]), config_resolver)
                        except ExecutionBusy:
                            # The lease can become busy again between its
                            # quiet observation and this ownership handoff.
                            # Keep the durable Cancel supervised, not stranded
                            # until a second operator action or service restart.
                            self._start_pause_settlement(records, config_resolver)
                        except Exception:
                            pass  # Durable Cancel is retained for later adoption.

        thread = threading.Thread(target=settle, name="pause-%s" % records[0]["id"], daemon=True)
        try:
            thread.start()
        except Exception:
            with self._lock:
                for record in records:
                    self._active.pop(record["id"], None)
            raise

    def _pause_failure(self, task_id, reason, attempt=None):
        with registry.locked(self.home):
            self.store.pause_locked(task_id, reason, source="error",
                                    pending=True, attempt=attempt)
        self._settle_pause(task_id)

    def _pause_boundary(self, task_id, subject=None, unit=None):
        if self._stop_reason(task_id) is not None:
            return
        lifecycle = self.store.lifecycle(task_id)
        if lifecycle["status"] not in ("pausing", "paused"):
            record = self.store.record(task_id)
            deep = tasks.stored_task_executor(record["order"]["task_executor"]) == "deep_task"
            evidence = self._family(task_id) if deep else [record]
            # A reviewed coordinator may legitimately be awaiting its own
            # discussion. At a deep handoff, however, every prior child must
            # be physically quiet, including its independently owned sessions.
            if (self._workers_quiescent(evidence, (task_id,))
                    and (not deep or self._discussions_quiescent(evidence))):
                return
            with registry.locked(self.home):
                lifecycle = self.store.pause_locked(
                    task_id, "Waiting for prior execution quiescence before continuing",
                    source="error", pending=True,
                )
        with registry.locked(self.home):
            if self.store.stop_reason(task_id) is not None:
                return
            self.store.pause_locked(task_id, lifecycle["reason"],
                                    source=lifecycle["source"], pending=True)
        self._settle_pause(task_id)
        if self._stop_reason(task_id) is None:
            raise _TaskPaused()

    def stop(self, task_id, reason="stopped by operator", _member=False):
        """Stop one running standalone task. Returns True when a stop was
        delivered, False when the task is not running here (already
        terminal, or not this host's). The task closes as `failure` with
        this reason: a stop is an operator outcome, never a guessed
        success from whatever the interrupted worker last printed."""
        reason = str(reason or "stopped by operator").strip()
        record = self.store.record(task_id)
        if (not _member and tasks.stored_task_executor(
                record["order"]["task_executor"]) in RECOVERABLE_EXECUTORS):
            root_id = self._family(task_id)[0]["id"]
            if root_id != task_id:
                return self.stop(root_id, reason)
        if not self.is_active(task_id):
            with registry.locked(self.home):
                record = self.store.record(task_id)
                if (record["result"] is not None or tasks.stored_task_executor(
                        record["order"]["task_executor"]) not in RECOVERABLE_EXECUTORS):
                    return False
                if self.is_active(task_id):
                    raise TaskControlConflict("task execution changed; retry Cancel")
                reservations = {}
                try:
                    cancellation_family = [record] if _member else self._family(task_id)
                    for member in cancellation_family:
                        if self.is_active(member["id"]):
                            raise TaskControlConflict("a child is still stopping")
                        reservations[member["id"]] = self._lease(member["id"]).acquire()
                    for member in cancellation_family:
                        if member["result"] is None:
                            self.store.record_stop_locked(member["id"], reason)
                    root = cancellation_family[0]
                    with self._lock:
                        self._leases.update(reservations)
                    reservations = {}
                    self.start(root, lambda: {})
                except ExecutionBusy as exc:
                    raise TaskControlConflict(str(exc)) from exc
                finally:
                    for lease in reservations.values():
                        lease.close()
                    with self._lock:
                        unused = [identity for identity in self._leases
                                  if identity not in self._active]
                        for identity in unused:
                            self._leases.pop(identity).close()
            return True
        with registry.locked(self.home):
            with self._lock:
                if task_id not in self._active:
                    return False
                record = self.store.record(task_id)
                executor = tasks.stored_task_executor(
                    record["order"]["task_executor"]
                )
                if record["result"] is not None:
                    return False
                if executor in RECOVERABLE_EXECUTORS or executor == "brainstorming":
                    reason = self.store.record_stop_locked(task_id, reason)
                self._stops[task_id] = reason
                control = self._controls.get(task_id)
                session_id = self._sessions.get(task_id)
        if control is not None:
            # The transport binds interrupt only once the worker is spawned;
            # a stop landing in that window would otherwise be dropped.
            # Retry briefly; the stop flag closes the task either way.
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    if control.interrupt(reason) or control.closed:
                        break
                except Exception:
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.05)
        if session_id is not None:
            self._pause_session(session_id)
        return True

    def stop_inactive_brainstorming(
        self, task_id, reason, config_resolver
    ):
        """Accept and settle Stop after a direct Brainstorming host exited.

        A recoverable discussion outlives its task thread.  Its durable Stop
        therefore fences continuation first, then reuses normal host adoption
        to terminalize the same session and task.
        """
        reason = str(reason or "stopped by operator").strip()
        with registry.locked(self.home):
            record = self.store.record(task_id)
            if record["result"] is not None or tasks.stored_task_executor(
                record["order"]["task_executor"]
            ) != "brainstorming":
                return False
            session_id = task_session_id(self.home, record, self)
            if session_id is None:
                return False
            reason = self.store.record_stop_locked(task_id, reason)

        # Continuation may have re-adopted the task before the Stop fence won.
        # Deliver to that host when present; otherwise adopt the durable Stop.
        if not self.stop(task_id, reason):
            try:
                self.start(record, config_resolver)
            except Exception:
                # The Stop remains durable and blocks continuation. Ordinary
                # service adoption retries the same settlement after restart.
                pass
        return True

    def _pause_session(self, session_id):
        try:
            brainstorming_tasks.lifecycle.stop_session(
                self.home, session_id, lambda _record: True
            )
        except Exception:
            # Best-effort: the task still closes on the stop flag; the
            # session is left as it is for native recovery.
            pass

    def _stop_reason(self, task_id):
        with self._lock:
            reason = self._stops.get(task_id)
        if reason is not None:
            return reason
        return self.store.stop_reason(task_id)

    def running_session_id(self, task_id):
        """The Brainstorming session a running task owns, if known here."""
        with self._lock:
            return self._sessions.get(task_id)

    def is_active(self, task_id):
        """Whether this service currently owns the task's execution thread.

        This is presentation-only liveness.  Durable task/lifecycle state
        remains the execution authority; callers use this only to avoid
        animating a stale in-flight marker after a service restart.
        """
        with self._lock:
            return task_id in self._active

    @staticmethod
    def _runner(config, _workspace):
        return runners.SubprocessRunner(
            config["commands"],
            config.get("timeouts", {}),
            stall_window_s=config.get("worker_stall_window_s"),
            stall_min_cpu_s=config.get("worker_stall_min_cpu_s"),
        )

    def _recover_worker_attempt_locked(self, task_id):
        """Import a completed direct call once, without changing its control.

        The caller holds the registry lock. This accounting boundary is also
        valid after Cancel: importing evidence must not turn a durable Stop
        into a pause or require reopening the task's workspace.
        """
        current, document = self.store._read_document(task_id)
        if (document["record"]["result"] is not None or tasks.stored_task_executor(
                document["record"]["order"]["task_executor"]) != "agent_call"):
            return False
        try:
            marker = read_worker_marker(self.home, task_id)
        except (OSError, ValueError):
            return False
        if (not isinstance(marker, dict) or marker.get("completed") is not True
                or marker.get("task_id") != task_id
                or not isinstance(marker.get("call_id"), str)
                or not marker["call_id"].strip()):
            return False
        lifecycle = self.store._lifecycle(document)
        if any(event.get("call_id") == marker["call_id"]
               for event in lifecycle["history"]):
            return False
        try:
            if "result" in marker:
                attempt = tasks.validate_result(marker["result"])
            else:
                # Before resumable tasks, completed markers retained only
                # accounting, not the outcome or native answer. Preserve that
                # physical call's charge without inventing a reusable success.
                attempt = tasks.validate_result({
                    "status": "failure",
                    "reason": "Completed worker outcome was not retained by the earlier marker format",
                    "native_result": None,
                    **{field: marker[field] for field in (
                        "duration_s", "token_usage", "token_usage_partial",
                        "cost", "cost_partial",
                    )},
                })
        except (KeyError, TypeError, ValueError):
            return False
        event = {"status": lifecycle["status"], "at": _admission_stamp(),
                 "call_id": marker["call_id"], "attempt": copy.deepcopy(attempt)}
        if lifecycle["status"] != "running":
            event.update(reason=lifecycle["reason"], source=lifecycle["source"])
        lifecycle["history"].append(event)
        if attempt["status"] == "success":
            lifecycle["completed_result"] = copy.deepcopy(attempt)
        self.store._write_lifecycle_locked(task_id, current, document, lifecycle)
        return True

    def start(self, record, config_resolver, parent_task_id=None):
        task_id = record["id"]
        # Cancellation only settles retained evidence and owned discussions.
        # A missing/unmounted work area must not prevent that terminal action.
        workspace = _workspace(
            record, require_exists=self.store.stop_reason(task_id) is None
        )
        with self._lock:
            if (
                parent_task_id is not None
                and (
                    parent_task_id in self._stops
                    or self.store.stop_reason(parent_task_id) is not None
                )
            ):
                return None
            if task_id in self._active:
                return None
            executor = tasks.stored_task_executor(record["order"]["task_executor"])
            if (executor in RECOVERABLE_EXECUTORS
                    and self.store.lifecycle(task_id)["status"] != "running"
                    and self.store.stop_reason(task_id) is None):
                return None
            if executor in RECOVERABLE_EXECUTORS and task_id not in self._leases:
                self._leases[task_id] = self._lease(task_id).acquire()
            self._active[task_id] = workspace
            thread = threading.Thread(
                target=self._run,
                args=(task_id, config_resolver),
                name="task-%s" % task_id,
                daemon=True,
            )
            try:
                thread.start()
            except Exception:
                self._active.pop(task_id, None)
                lease = self._leases.pop(task_id, None)
                if lease is not None:
                    lease.close()
                raise
        return thread

    def adopt_open_tasks(self, config_resolver_for):
        """Readopt independent discussions; pause interrupted ordinary tasks.

        An explicit durable Cancel still settles after restart, but a service
        restart is never authorization to retry physical work.
        """
        adopted, closed = [], []
        try:
            records = self.store.records()
        except Exception:
            return {"adopted": adopted, "closed": closed}
        for record in records:
            if record.get("result") is not None:
                continue
            task_id = record["id"]
            executor = tasks.stored_task_executor(record["order"]["task_executor"])
            if executor in RECOVERABLE_EXECUTORS:
                if self.is_active(task_id):
                    continue
                with registry.locked(self.home):
                    if self.store.stop_reason(task_id) is not None:
                        try:
                            self.start(record, config_resolver_for(record))
                            adopted.append(task_id)
                        except ExecutionBusy as exc:
                            self.store.pause_locked(
                                task_id, str(exc), source="interrupted", pending=True,
                            )
                            self._start_pause_settlement([record], config_resolver_for(record))
                        except Exception as exc:
                            self.store.pause_locked(task_id, str(exc), source="interrupted")
                        continue
                    evidence = self._family(task_id)
                    family = [member for member in evidence
                              if member["result"] is None
                              and self.store.stop_reason(member["id"]) is None]
                    if any(self.is_active(member["id"]) for member in family):
                        continue
                    pending = (not self._discussions_quiescent(evidence)
                               or not self._workers_quiescent(evidence))
                    for member in family:
                        identity = member["id"]
                        previous = self.store.lifecycle(identity)
                        if previous["status"] == "paused" and not pending:
                            continue
                        attempt = completed = attempt_id = None
                        if tasks.stored_task_executor(member["order"]["task_executor"]) == "agent_call":
                            self._recover_worker_attempt_locked(identity)
                            try:
                                marker = read_worker_marker(self.home, identity)
                            except (OSError, ValueError):
                                marker = {}
                            if not isinstance(marker, dict):
                                marker = {}
                            attempt_id = marker.get("call_id")
                            if not isinstance(attempt_id, str):
                                attempt_id = None
                            known = any(
                                event.get("call_id") == attempt_id
                                for event in self.store.lifecycle(identity)["history"]
                            ) if attempt_id else False
                            if not known:
                                try:
                                    attempt = tasks.validate_result(
                                        marker.get("result") if marker.get("completed") is True else None
                                    )
                                except contracts.ContractError:
                                    attempt = self._deep_failure(
                                        "Worker result was not recorded before service restart"
                                    )
                                if attempt.get("status") == "success":
                                    completed = attempt
                        self.store.pause_locked(
                            identity, "Execution interrupted by service restart; Resume when ready",
                            source="interrupted", pending=pending,
                            attempt=attempt, completed_result=completed, attempt_id=attempt_id,
                        )
                    if pending:
                        self._start_pause_settlement(family, config_resolver_for(family[0]))
                continue
            if executor == "brainstorming":
                try:
                    relation = record.get("parent") or {}
                    parent_task_id = relation.get("task_id")
                    parent_argument = (
                        {"parent_task_id": parent_task_id}
                        if parent_task_id is not None else {}
                    )
                    if self.start(
                        record,
                        config_resolver_for(record),
                        **parent_argument,
                    ) is not None:
                        adopted.append(task_id)
                except Exception:
                    pass
                continue
            try:
                self.store.record_result(task_id, {
                    "status": "failure",
                    "reason": (
                        "the service restarted while this call was in "
                        "flight; the worker did not finish — re-order the "
                        "task if the work is still wanted"
                    ),
                    "duration_s": 0.0,
                    "token_usage": None,
                    "token_usage_partial": True,
                    "cost": None,
                    "cost_partial": True,
                    "native_result": None,
                })
                closed.append(task_id)
            except Exception:
                pass
        return {"adopted": adopted, "closed": closed}

    def owns_workspace(self, workspace):
        """Paused work retains its work area until completion or Cancel."""
        with self._lock:
            active = list(self._active.values())
        active.extend(_workspace(record, require_exists=False) for record in self._reserved_records())
        return any(gitsync.paths_overlap(path, workspace) for path in active)

    def _reserved_records(self):
        for record in self.store.records():
            if tasks.stored_task_executor(record["order"]["task_executor"]) not in RECOVERABLE_EXECUTORS:
                continue
            if record["result"] is None:
                yield record
                continue
            journal = os.path.join(self.home, "task-runtime", record["id"], "execution.json")
            lease_path = os.path.join(self.home, "task-runtime", record["id"], "execution.lock")
            legacy_evidence = not os.path.exists(lease_path) and any(os.path.isfile(path) for path in (
                _marker_path(self.home, record["id"]),
                os.path.join(reviewed_state_directory(self.home, record["id"]), "current.json"),
            ))
            if os.path.isfile(journal) or legacy_evidence:
                try:
                    with self._lease(record["id"]):
                        pass
                except ExecutionBusy:
                    # Even a terminal Cancel cannot make a surviving process
                    # safe for another task to overwrite.
                    yield record

    def owns_workspace_except(self, workspace, task_id):
        """Whether work outside one task's owner chain holds the tree."""
        try:
            excluded = {record["id"] for record in self._family(task_id)}
        except Exception:
            excluded = {task_id}
        with self._lock:
            active = [
                path for active_id, path in self._active.items()
                if active_id not in excluded
            ]
        active.extend(
            _workspace(record, require_exists=False) for record in self._reserved_records()
            if record["id"] not in excluded
        )
        return any(gitsync.paths_overlap(path, workspace) for path in active)

    def _run(self, task_id, config_resolver):
        unexpected_failure = False
        try:
            record = self.store.record(task_id)
            if record["result"] is not None:
                return
            executor = tasks.stored_task_executor(
                record["order"]["task_executor"]
            )
            if executor in RECOVERABLE_EXECUTORS:
                self._pause_boundary(task_id)
                if (self._stop_reason(task_id) is not None and
                        (executor == "agent_call" or (
                            executor == "reviewed_task" and not os.path.isfile(
                                reviewed_state_path(self.home, task_id))))):
                    with registry.locked(self.home):
                        self._recover_worker_attempt_locked(task_id)
                        self.store.record_result_locked(task_id, {
                            "status": "failure", "reason": self._stop_reason(task_id),
                            "native_result": None, **brainstorming_tasks._zero_accounting(),
                        })
                    return
            if executor == "reviewed_task":
                path = reviewed_state_path(self.home, task_id)
                if not os.path.exists(path):
                    ensure_reviewed_state(
                        self.home, record, config_resolver(),
                        implementation_scope=self._deep_implementation_scope(record),
                    )
            if executor == "agent_call":
                self._run_worker(record, config_resolver)
            elif executor == "brainstorming":
                self._run_brainstorming(record, config_resolver)
            elif executor == "deep_task":
                self._run_deep(record, config_resolver)
            else:
                self._run_reviewed(record)
        except _TaskPaused:
            self._settle_pause(task_id)
        except Exception as exc:
            unexpected_failure = True
            already_cancelling = self._stop_reason(task_id) is not None
            record = self.store.record(task_id)
            if (record["result"] is None and tasks.stored_task_executor(
                    record["order"]["task_executor"]) in RECOVERABLE_EXECUTORS):
                self._pause_failure(task_id, str(exc).strip() or type(exc).__name__)
                # A newly accepted Cancel can win while an error pause is
                # quiescing a discussion. Settle it after releasing this host.
                if not already_cancelling and self._stop_reason(task_id) is not None:
                    unexpected_failure = False
            else:
                raise
        finally:
            settle_stop = False
            with registry.locked(self.home):
                try:
                    current = self.store.record(task_id)
                    settle_stop = bool(
                        not unexpected_failure and current["result"] is None
                        and self.store.stop_reason(task_id) is not None
                        and tasks.stored_task_executor(current["order"]["task_executor"])
                        in RECOVERABLE_EXECUTORS
                    )
                finally:
                    with self._lock:
                        self._active.pop(task_id, None)
                        self._controls.pop(task_id, None)
                        self._sessions.pop(task_id, None)
                        self._stops.pop(task_id, None)
                        lease = self._leases.pop(task_id, None)
                        if lease is not None:
                            lease.close()
                if settle_stop:
                    # Cancel may win just as a paused coordinator exits.
                    # Re-enter ONLY its durable cancellation settlement; the
                    # stop fence prevents another production or review call.
                    try:
                        self.start(current, config_resolver)
                    except Exception:
                        pass  # Keep the durable Cancel for later settlement.

    @staticmethod
    def _deep_child_order(record):
        return tasks.deep_documentation_order(record)

    @staticmethod
    def _deep_implementation_order(record, documentation_reference):
        return tasks.deep_implementation_order(
            record, documentation_reference
        )

    def _deep_implementation_scope(self, record):
        relation = record.get("parent") or {}
        if relation.get("phase") != "implementation":
            return None
        part = relation["part"]
        if part == "a":
            # Part a is the whole admitted implementation request. It becomes
            # a size-cut scope only if its own eligible producer returns a cut.
            return None
        parent = self.store.record(relation["task_id"])
        predecessor = next(
            candidate for candidate in self.store.records()
            if (candidate.get("parent") or {}).get("task_id") == parent["id"]
            and (candidate.get("parent") or {}).get("phase") == "implementation"
            and st._next_part(candidate["parent"]["part"]) == part
        )
        scope = predecessor["result"]["native_result"]["production_result"][
            "implementation_cut"
        ]["remaining_scope"]
        return {
            "part": part,
            "scope": scope,
            "delegated_remaining": None,
            "source_unit": predecessor["id"],
        }

    @staticmethod
    def _deep_documentation_reference(record, child):
        workspace = os.path.realpath(_workspace(record))
        artifact = child["result"]["native_result"]["production_result"][
            "artifact"
        ]
        reference = os.path.realpath(
            artifact if os.path.isabs(artifact)
            else os.path.join(workspace, artifact)
        )
        reference = tasks.resolve_derived_path(workspace, reference)
        with open(reference, "rb") as handle:
            handle.read(1)
        return reference

    @staticmethod
    def _deep_implementation_cut(child):
        configuration = child["order"]["configuration"]
        if (
            configuration["producer"]["task_executor"] != "agent_call"
            or "implementation_size_control" not in configuration
        ):
            return None
        return child["result"]["native_result"]["production_result"].get(
            "implementation_cut"
        )

    @staticmethod
    def _deep_result(status, child_results, reason=None):
        return tasks.deep_task_result(status, child_results, reason)

    @classmethod
    def _deep_failure(cls, reason, child_result=None):
        return cls._deep_result(
            "failure", [] if child_result is None else [child_result], reason
        )

    def _record_deep_terminal(
        self, task_id, status, child_results, reason=None
    ):
        """Fence a deep terminal choice against concurrent operator Stop."""
        self._pause_boundary(task_id)
        if self._stop_reason(task_id) is not None:
            self._settle_deep_cancel_quiescence(task_id, self._family(task_id))
        with registry.locked(self.home):
            with self._lock:
                stop_reason = (
                    self._stops.get(task_id)
                    or self.store.stop_reason(task_id)
                )
                result = self._deep_result(
                    "failure" if stop_reason is not None else status,
                    child_results,
                    stop_reason or reason,
                )
                if stop_reason is None and status == "failure":
                    self.store.pause_locked(task_id, reason or "Deep task failed", source="error")
                    return result
                if (stop_reason is None and self.store.lifecycle(task_id)["status"]
                        in ("pausing", "paused")):
                    self.store.pause_locked(task_id, "paused by operator")
                    raise _TaskPaused()
                self.store.record_result_locked(task_id, result)
                # A Stop arriving after this point was not accepted: the
                # terminal record and work-area release become visible as one
                # host decision under the same control lock.
        return result

    def _settle_deep_cancel_quiescence(self, task_id, records):
        """Keep Cancel nonterminal until already-settled children are quiet.

        Open children receive their ordinary Cancel first. Never reopen a
        terminal child or import its discussion accounting a second time.
        """
        while not (self._discussions_quiescent(records, stop=True)
                   and self._workers_quiescent(records, (task_id,))):
            with registry.locked(self.home):
                self.store.pause_locked(
                    task_id, self._stop_reason(task_id) or "Waiting for cancellation quiescence",
                    source="operator", pending=True,
                )
            time.sleep(self.poll_interval)

    def _await_deep_child(self, task_id, child, config_resolver):
        if child["result"] is None and self._stop_reason(task_id) is None:
            self.start(child, config_resolver, parent_task_id=task_id)
        while True:
            child = self.store.record(child["id"])
            stop_reason = self._stop_reason(task_id)
            if stop_reason is None:
                child_lifecycle = self.store.lifecycle(child["id"])
                if (child["result"] is None and child_lifecycle["status"] == "paused"
                        and not self.is_active(child["id"])):
                    with registry.locked(self.home):
                        self.store.pause_locked(
                            task_id, child_lifecycle["reason"] or "Child task paused",
                            source="child",
                        )
                    raise _TaskPaused()
                if not self.is_active(child["id"]):
                    self._pause_boundary(task_id)
            if stop_reason is not None and child["result"] is None:
                try:
                    delivered = self.stop(child["id"], stop_reason, _member=True)
                except TaskControlConflict as exc:
                    # A surviving worker or concurrent child adoption can
                    # temporarily refuse delivery. Cancel is already durable
                    # on the parent: wait here and retry control, never work.
                    with registry.locked(self.home):
                        self.store.pause_locked(task_id, str(exc), source="operator", pending=True)
                    time.sleep(self.poll_interval)
                    continue
                if not delivered:
                    if tasks.stored_task_executor(
                        child["order"]["task_executor"]
                    ) == "reviewed_task":
                        try:
                            with registry.locked(self.home):
                                current = self.store.record(child["id"])
                                if current["result"] is None:
                                    self.store.record_stop_locked(
                                        child["id"], stop_reason
                                    )
                        except tasks.TaskRecordError:
                            pass
                        child = self.store.record(child["id"])
                        if child["result"] is None:
                            # Parent Stop normally reaches an already-running
                            # child.  After restart it instead adopts that
                            # child's durable Stop without the stopped-parent
                            # admission fence, so the reviewed lifecycle can
                            # settle any attached discussion before closing.
                            try:
                                self.start(child, config_resolver)
                            except ExecutionBusy as exc:
                                with registry.locked(self.home):
                                    self.store.pause_locked(
                                        task_id, str(exc), source="operator", pending=True,
                                    )
                                time.sleep(self.poll_interval)
                                continue
                    else:
                        try:
                            child = self.store.record_result(
                                child["id"], self._deep_failure(stop_reason)
                            )
                        except tasks.TaskRecordError:
                            child = self.store.record(child["id"])
            if child["result"] is not None and not self.is_active(child["id"]):
                if stop_reason is not None:
                    self._settle_deep_cancel_quiescence(task_id, [child])
                self._pause_boundary(task_id)
                return child, self._stop_reason(task_id)
            time.sleep(self.poll_interval)

    def _admit_deep_child(
        self, task_id, phase, part, order, workspace
    ):
        with registry.locked(self.home):
            with self._lock:
                if (self.store.lifecycle(task_id)["status"] != "running"
                        and self.store.stop_reason(task_id) is None):
                    raise _TaskPaused()
                stop_reason = (
                    self._stops.get(task_id)
                    or self.store.stop_reason(task_id)
                )
                child = (
                    self.store.admit_related_locked(
                        task_id, phase, part, order, {}, workspace
                    )
                    if stop_reason is None else None
                )
        return child, stop_reason

    def _settle_stopped_deep(self, record, config_resolver, stop_reason):
        """Settle every already-admitted child before a stopped parent."""
        task_id = record["id"]
        children = []
        documentation = self.store.related(task_id, "documentation", None)
        if documentation is not None:
            children.append(documentation)
        part = "a"
        while True:
            child = self.store.related(task_id, "implementation", part)
            if child is None:
                break
            children.append(child)
            part = st._next_part(part)

        results = []
        for child in children:
            child, _current_reason = self._await_deep_child(
                task_id, child, config_resolver
            )
            results.append(child["result"])
        self._record_deep_terminal(
            task_id, "failure", results, stop_reason
        )

    def _run_deep(self, record, config_resolver):
        """Deliver documentation, then sequential reviewed implementation."""
        task_id = record["id"]
        stop_reason = self._stop_reason(task_id)
        if stop_reason is not None:
            self._settle_stopped_deep(record, config_resolver, stop_reason)
            return
        workspace = _workspace(record)
        results = []
        child, stop_reason = self._admit_deep_child(
            task_id, "documentation", None,
            self._deep_child_order(record), workspace,
        )
        if child is None:
            self._record_deep_terminal(
                task_id, "failure", results, stop_reason
            )
            return
        child, stop_reason = self._await_deep_child(
            task_id, child, config_resolver
        )
        result = child["result"]
        results.append(result)
        if stop_reason is not None or result["status"] == "failure":
            self._record_deep_terminal(
                task_id, "failure", results,
                stop_reason or result.get("reason"),
            )
            return
        try:
            documentation_reference = self._deep_documentation_reference(
                record, child
            )
        except (OSError, tasks.TaskRequestError) as exc:
            self._record_deep_terminal(
                task_id,
                "failure",
                results,
                "Deep task documentation artifact is unavailable: %s" % exc,
            )
            return

        part = "a"
        implementation_order = self._deep_implementation_order(
            record, documentation_reference
        )
        while True:
            child, stop_reason = self._admit_deep_child(
                task_id, "implementation", part,
                implementation_order, workspace,
            )
            if child is None:
                self._record_deep_terminal(
                    task_id, "failure", results, stop_reason
                )
                return
            child, stop_reason = self._await_deep_child(
                task_id, child, config_resolver
            )
            result = child["result"]
            results.append(result)
            if stop_reason is not None or result["status"] == "failure":
                self._record_deep_terminal(
                    task_id, "failure", results,
                    stop_reason or result.get("reason"),
                )
                return
            cut = self._deep_implementation_cut(child)
            if cut is None:
                self._record_deep_terminal(
                    task_id, "success", results
                )
                return
            part = st._next_part(part)

    def _reviewed_failure(self, subject, unit, reason):
        return {
            "status": "failure",
            "reason": str(reason or "Reviewed task failed"),
            **st.reviewed_work_accounting(subject.state, unit),
            "native_result": None,
        }

    def _record_reviewed_terminal(
        self, task_id, result, stopped_session_settled=False
    ):
        """Choose the terminal result at the Stop-delivery boundary.

        Return a Stop that won before publication so its owned discussion can
        be settled first.  The settlement path opts into the final write only
        after that discussion is terminal or durably detached.
        """
        with registry.locked(self.home):
            with self._lock:
                stop_reason = (
                    self._stops.get(task_id)
                    or self.store.stop_reason(task_id)
                )
                if stop_reason is not None and not stopped_session_settled:
                    return stop_reason
                if stop_reason is not None:
                    result = dict(
                        result,
                        status="failure",
                        reason=stop_reason,
                        native_result=None,
                    )
                if (stop_reason is None and self.store.lifecycle(task_id)["status"]
                        in ("pausing", "paused")):
                    raise _TaskPaused()
                # Keep the task active until its chosen result is durable.
                # A concurrent parent then either delivers Stop before this
                # write or observes the already-terminal child; it can never
                # mistake an in-progress settlement for abandoned work.
                self.store.record_result_locked(task_id, result)
        return None

    def _unattached_reviewed_session_id(self, subject, unit):
        """Recover the one session created before its attachment was saved."""
        callers = self._reviewed_discussion_callers(subject.state, unit)
        rows = brainstorming_tasks.lifecycle.list_sessions(
            self.home, lambda record: record.get("caller") in callers
        )
        if any(row.get("state_error") for row in rows):
            raise brainstorming_tasks.AdapterError(
                "owned Brainstorming session state is unavailable"
            )
        represented = {
            event.get("session_id")
            for event in subject.state.get("events", [])
            if isinstance(event, dict)
            and isinstance(event.get("session_id"), str)
        }
        unattached = [
            row for row in rows
            if row.get("id") not in represented
        ]
        if len(unattached) > 1:
            raise brainstorming_tasks.AdapterError(
                "one reviewed task owns multiple unattached sessions"
            )
        return unattached[0]["id"] if unattached else None

    def _settle_stopped_reviewed(self, task_id, subject, unit, reason):
        """Close an owned discussion before publishing task failure."""
        session_id = (unit.get("brainstorming_wait") or {}).get("session_id")
        if not isinstance(session_id, str):
            try:
                session_id = self._unattached_reviewed_session_id(
                    subject, unit
                )
            except Exception:
                return False
        if isinstance(session_id, str):
            projection = None
            outcome_event = None
            try:
                record = brainstorming_tasks.lifecycle._record_by_id(
                    self.home, session_id
                )
                if not self._discussion_quiescent(session_id):
                    brainstorming_tasks.lifecycle.stop_session(
                        self.home, session_id,
                        brainstorming_tasks._authorize_caller(record.get("caller")),
                    )
                    if not self._discussion_quiescent(session_id):
                        return False
                projection = brainstorming_tasks.lifecycle.abandon_session(
                    self.home,
                    session_id,
                    brainstorming_tasks._authorize_caller(record.get("caller")),
                    reason,
                )
                outcome_event = (
                    "brainstorming_failure_routed"
                    if projection["state"]["status"] == "failure"
                    else "brainstorming_owner_stop_detached"
                )
            except brainstorming_tasks.lifecycle.PublicLifecycleError as exc:
                if exc.code != brainstorming_tasks.lifecycle.UNKNOWN_SESSION:
                    # Store and lifecycle unavailability is retryable.  A
                    # missing service record is not: Discard has already made
                    # this discussion permanently non-actionable.
                    return False
                outcome_event = "brainstorming_missing_detached"
                try:
                    # Discard removes the coordinator record, but retained
                    # turn evidence can still describe a surviving provider.
                    if not self._discussion_attempts_quiescent(session_id):
                        return False
                    store = brainstorming.SessionStore(
                        brainstorming_tasks.lifecycle.state_directory(
                            self.home
                        )
                    )
                    snapshot = store.read(session_id)
                    if snapshot is not None:
                        target_path = (
                            None if brainstorming.repository_session(snapshot.state)
                            else coordination.resolve_target_path(snapshot.state["request"])
                        )
                        projection = brainstorming_tasks._retained_projection(
                            self.home,
                            session_id,
                            "discarded:%s" % session_id,
                            target_path,
                        )
                except Exception:
                    # A retained state that exists but cannot be read may hold
                    # accounting that Stop must preserve; retry that case.
                    return False
            except Exception:
                # Retain the durable Stop and owner until the session can be
                # terminalized and its accepted accounting can be imported;
                # adoption retries this same idempotent settlement.
                return False

            try:
                wait = unit.get("brainstorming_wait") or {}
                if not any(
                    event.get("type") == "brainstorming_wait_started"
                    and event.get("session_id") == session_id
                    for event in subject.state.get("events", [])
                ):
                    # Session creation wins before the reviewed attachment is
                    # saved.  Recover that missing ledger opening before its
                    # accounting and terminal outcome so the ordinary summary
                    # can represent the accepted discussion in event order.
                    st.append_event(
                        subject.state,
                        "brainstorming_wait_started",
                        unit=st.unit_key(unit),
                        kind=(wait.get("origin") or {}).get("kind"),
                        session_id=session_id,
                    )
                if projection is not None:
                    subject._record_brainstorming_work(
                        unit,
                        session_id,
                        projection.get("work_duration_s"),
                        projection.get("work_token_usage"),
                        projection.get("work_token_usage_partial", False),
                        cost=projection.get("work_cost"),
                        cost_partial=projection.get(
                            "work_cost_partial", False
                        ),
                        task_id=subject._reviewed_call_task_id(unit),
                    )
                if not any(
                    event.get("session_id") == session_id
                    and event.get("type") in st._BRAINSTORMING_OUTCOMES
                    for event in subject.state.get("events", [])
                ):
                    st.append_event(
                        subject.state,
                        outcome_event,
                        unit=st.unit_key(unit),
                        kind=(wait.get("origin") or {}).get("kind"),
                        session_id=session_id,
                    )
                if outcome_event == "brainstorming_missing_detached":
                    # Match the ordinary missing-session settlement: retain
                    # its ledger, not an attachment that can never be stopped.
                    unit.pop("brainstorming_wait", None)
                subject._save()
            except Exception:
                return False
        self._record_reviewed_terminal(
            task_id,
            self._reviewed_failure(subject, unit, reason),
            stopped_session_settled=True,
        )
        return True

    def _publish_reviewed_terminal(self, task_id, subject, unit, result):
        """Publish normally, or finish a Stop that won the result fence."""
        if result["status"] == "failure" and self._stop_reason(task_id) is None:
            self._pause_failure(task_id, result.get("reason") or "Reviewed task failed")
            return
        self._pause_boundary(task_id, subject, unit)
        stop_reason = self._record_reviewed_terminal(task_id, result)
        if stop_reason is None:
            return
        while not self._settle_stopped_reviewed(
            task_id, subject, unit, stop_reason
        ):
            time.sleep(self.poll_interval)

    def _run_reviewed(self, record):
        task_id = record["id"]
        path = reviewed_state_path(self.home, task_id)
        cancelling = self._stop_reason(task_id) is not None
        runner = None
        if not cancelling:
            lifecycle_state = st.load(path)
            runner = self.runner_factory(lifecycle_state["config"], _workspace(record))
            runner.execution_lease = self._leases.get(task_id)
        subject = driver.Driver(
            path, runner=runner, model_profiles_home=self.home,
            pause_on_call_failure=True,
            cancellation_only=cancelling,
        )
        unit_key = subject.state["reviewed_task"]["unit"]
        resume_discussion = any(
            event["status"] == "running"
            for event in self.store.lifecycle(task_id)["history"]
        )
        try:
            steps = 0
            while steps < 10000:
                unit = subject._unit_by_key(unit_key)
                stop_reason = self._stop_reason(task_id)
                if stop_reason is not None:
                    if self._settle_stopped_reviewed(
                        task_id, subject, unit, stop_reason
                    ):
                        return
                    time.sleep(self.poll_interval)
                    continue
                self._pause_boundary(task_id, subject, unit)
                if subject.state.get("failure") is not None:
                    failure = subject.state["failure"]
                    self._publish_reviewed_terminal(
                        task_id,
                        subject,
                        unit,
                        self._reviewed_failure(
                            subject, unit, failure.get("reason")
                        ),
                    )
                    return
                if resume_discussion:
                    resume_discussion = False
                    session_id = (unit.get("brainstorming_wait") or {}).get("session_id")
                    if isinstance(session_id, str):
                        try:
                            brainstorming_tasks.lifecycle.start_session(
                                self.home, session_id, lambda _record: True,
                                resolve_staffing_session=lambda _record: st.staffing_session(subject.state),
                            )
                        except brainstorming_tasks.lifecycle.PublicLifecycleError as exc:
                            if exc.code != brainstorming_tasks.lifecycle.UNKNOWN_SESSION:
                                raise
                            # Let the existing missing-discussion recovery
                            # decide the next lawful action; do not invent one.
                completed = subject.reviewed_work.result(unit)
                if completed is not None:
                    self._publish_reviewed_terminal(task_id, subject, unit, completed)
                    return
                with subject._exclusive():
                    subject._assert_not_stale()
                    recovered = subject.reviewed_work.recover_pending_gate()
                    if recovered is None:
                        action = subject.reviewed_work.next_action(unit)
                        # An operator may leave a discussion waiting for any
                        # duration. Polling it is not an execution step.
                        if action.type != driver.A_BRAINSTORM_WAIT:
                            steps += 1
                        subject.reviewed_work.execute(
                            action,
                            call_preparation=(
                                driver.StandaloneReviewedWorkCallPreparation(
                                    subject
                                )
                            ),
                        )
                    else:
                        steps += 1
                    subject._save()
                    subject._clear_busy()
                unit = subject._unit_by_key(unit_key)
                wait = unit.get("brainstorming_wait") or {}
                session_id = wait.get("session_id")
                with self._lock:
                    if isinstance(session_id, str):
                        self._sessions[task_id] = session_id
                    else:
                        self._sessions.pop(task_id, None)
                result = subject.reviewed_work.result(unit)
                if result is not None:
                    stop_reason = self._stop_reason(task_id)
                    if stop_reason is not None:
                        if not self._settle_stopped_reviewed(
                            task_id, subject, unit, stop_reason
                        ):
                            time.sleep(self.poll_interval)
                            continue
                    else:
                        self._publish_reviewed_terminal(
                            task_id, subject, unit, result
                        )
                    return
                if session_id:
                    time.sleep(self.poll_interval)
            raise RuntimeError("reviewed task exceeded its lifecycle step bound")
        except _TaskPaused:
            raise
        except driver.StopStep as exc:
            unit = subject._unit_by_key(unit_key)
            reason = (
                (subject.state.get("failure") or {}).get("reason") or str(exc)
            )
            stop_reason = self._stop_reason(task_id)
            if stop_reason is not None:
                while not self._settle_stopped_reviewed(
                    task_id, subject, unit, stop_reason
                ):
                    time.sleep(self.poll_interval)
                return
            self._publish_reviewed_terminal(
                task_id,
                subject,
                unit,
                self._reviewed_failure(subject, unit, reason),
            )
        except Exception as exc:
            unit = subject._unit_by_key(unit_key)
            stop_reason = self._stop_reason(task_id)
            if stop_reason is not None:
                while not self._settle_stopped_reviewed(
                    task_id, subject, unit, stop_reason
                ):
                    time.sleep(self.poll_interval)
                return
            self._publish_reviewed_terminal(
                task_id,
                subject,
                unit,
                self._reviewed_failure(
                    subject,
                    unit,
                    "Reviewed task execution failed: %s"
                    % (str(exc).strip() or type(exc).__name__),
                ),
            )

    def _run_worker(self, record, config_resolver):
        task_id = record["id"]
        completed = self.store.lifecycle(task_id).get("completed_result")
        if completed is not None and self._stop_reason(task_id) is None:
            with registry.locked(self.home):
                lifecycle = self.store.lifecycle(task_id)
                if lifecycle["status"] != "running":
                    self.store.pause_locked(task_id, lifecycle["reason"])
                    raise _TaskPaused()
                stop_reason = self._stop_reason(task_id)
                self.store.record_result_locked(
                    task_id, {"status": "failure", "reason": stop_reason,
                              "native_result": None, **brainstorming_tasks._zero_accounting()}
                    if stop_reason else completed,
                )
            return
        started = time.time()
        marker = None
        carrier = None
        native = None
        reason = None
        try:
            config = config_resolver()
            family, model, effort, fallback = _dispatch(
                self.home, record, config
            )
            marker = {
                "task_id": task_id,
                "call_id": str(uuid.uuid4()),
                "family": family,
                "model": model,
                "effort": effort,
                "started_at": started,
            }
            if fallback is not None:
                # The call was staffed by the default document because an
                # input could not be read. It ran; the marker says so.
                marker["staffing_fallback"] = fallback
            try:
                _write_worker_marker(self.home, task_id, marker)
            except Exception:
                # Evidence, not a gate. This write is attempted before the
                # provider call only so a call in flight is visible; losing
                # it must not refuse a call the router already staffed.
                pass
            runner = self.runner_factory(config, _workspace(record))
            runner.execution_lease = self._leases.get(task_id)
            control = runners.ActiveCallControl()
            with self._lock:
                self._controls[task_id] = control
                early_stop = self._stops.get(task_id)
            if early_stop is not None:
                raise RuntimeError(early_stop)
            carrier = tasks.execute_worker(
                record,
                lambda request: runner.call(
                    family,
                    request["request"],
                    _workspace(record),
                    model=model,
                    effort=effort,
                    active_control=control,
                    keep_template=True,
                ),
            )
            native = carrier.text
            status = "success"
        except staffing.StaffingConditionError as exc:
            # One of the router's two surfaced conditions. The task is
            # terminal under that token, and no provider was called: the
            # marker is written only once a call is actually staffed, so
            # there is none to correct.
            config = locals().get("config", {})
            family = model = effort = None
            carrier = exc
            reason = "staffing refused this call (%s): %s" % (exc.code, exc)
            status = "failure"
        except Exception as exc:
            config = locals().get("config", {})
            family = locals().get("family")
            model = locals().get("model")
            effort = locals().get("effort")
            carrier = exc
            native = _native_failure(exc)
            reason = "Worker execution failed: %s" % (
                str(exc).strip() or type(exc).__name__
            )
            status = "failure"
        accounting = _accounting(
            carrier, family, model, config, max(0.0, time.time() - started)
        )
        if marker is not None:
            marker.update({
                "family": family,
                "model": model,
                "effort": effort,
                "completed": True,
                "result": {"status": status, "native_result": native,
                           **copy.deepcopy(accounting),
                           **({"reason": reason} if status == "failure" else {})},
                **copy.deepcopy(accounting),
            })
            try:
                _write_worker_marker(self.home, task_id, marker)
            except Exception:
                # The terminal marker is auxiliary accounting evidence.  Once
                # execution has produced a native outcome, losing this
                # best-effort write cannot replace that outcome.
                pass
        stop_reason = self._stop_reason(task_id)
        if stop_reason is not None:
            # An interrupted worker may exit cleanly and print something;
            # that is not a success. The operator's stop is the outcome.
            status = "failure"
            reason = stop_reason
        result = {"status": status, **accounting, "native_result": native}
        if status == "failure":
            result["reason"] = reason or "Worker execution failed"
        pending = not self._workers_quiescent([record], (task_id,))
        with registry.locked(self.home):
            stop_reason = self._stop_reason(task_id)
            if pending:
                self.store.pause_locked(
                    task_id, result.get("reason") or "Waiting for prior worker quiescence",
                    source="error", pending=True, attempt=result,
                    completed_result=result if status == "success" else None,
                    attempt_id=marker.get("call_id") if marker else None,
                )
            elif stop_reason is not None:
                result.update(status="failure", reason=stop_reason)
                self.store.record_result_locked(task_id, result)
            elif status == "failure" or self.store.lifecycle(task_id)["status"] != "running":
                self.store.pause_locked(
                    task_id, result.get("reason") or "paused by operator",
                    source="error" if status == "failure" else "operator",
                    attempt=result,
                    completed_result=result if status == "success" else None,
                    attempt_id=marker.get("call_id") if marker else None,
                )
            else:
                self.store.record_result_locked(task_id, result)
        if pending:
            self._settle_pause(task_id)

    def _persist_adapter_result(self, state, task_id):
        record = tasks.task_record(state, task_id)
        if record["result"] is None:
            return None
        with registry.locked(self.home):
            stop_reason = self.store.stop_reason(task_id)
            result = record["result"]
            if stop_reason is not None:
                result = dict(
                    result,
                    status="failure",
                    reason=stop_reason,
                )
            return self.store.record_result_locked(task_id, result)

    def _record_brainstorming_terminal(self, state, task_id):
        """Order terminal result against a concurrently accepted task Stop."""
        with registry.locked(self.home):
            stop_reason = self.store.stop_reason(task_id)
            if stop_reason is not None:
                return stop_reason
            record = tasks.task_record(state, task_id)
            self.store.record_result_locked(task_id, record["result"])
            return None

    def _run_brainstorming(self, record, config_resolver):
        task_id = record["id"]
        caller = brainstorming_tasks._task_caller(record, task_id)
        _area, _parent, private_target = (
            brainstorming_tasks._private_target_paths(
                _workspace(record), self.home, task_id
            )
        )
        session_id = None

        def stopped(reason):
            nonlocal session_id
            # Recovery may inherit a durable Stop before this host has learned
            # the task's session id.  Discover the existing owner relation
            # without starting it; if no session was ever admitted, close the
            # stopped task without manufacturing one.
            if session_id is None:
                owned = brainstorming_tasks._owned_projection(
                    self.home, caller, private_target
                )
                if owned is None:
                    retained = brainstorming_tasks._retained_owned_projection(
                        self.home, caller, private_target
                    )
                    if retained is None:
                        self.store.record_result(task_id, {
                            "status": "failure",
                            "reason": reason,
                            **brainstorming_tasks._zero_accounting(),
                            "native_result": None,
                        })
                        return
                    session_id = retained[0]
                else:
                    session_id = owned[0]
                with self._lock:
                    self._sessions[task_id] = session_id
            # The stop may have landed before the session id was known
            # (start() registers the task before this thread runs), or
            # while the lead was applying agreed effects. Choose against
            # any terminal session outcome, then close the task only after
            # the owned session is terminal too.
            try:
                projection = brainstorming_tasks.lifecycle.abandon_session(
                    self.home,
                    session_id,
                    brainstorming_tasks._authorize_caller(caller),
                    reason,
                )
            except brainstorming_tasks.lifecycle.PublicLifecycleError as exc:
                if exc.code != brainstorming_tasks.lifecycle.UNKNOWN_SESSION:
                    raise
                retained = brainstorming_tasks._retained_projection(
                    self.home, session_id, caller, private_target
                )
                state = {"tasks": self.store.records()}
                lost = brainstorming_tasks._fail_lost_session(
                    state, task_id, retained
                )
                self.store.record_result(
                    task_id, dict(lost["result"], reason=reason)
                )
                return
            accounting = brainstorming_tasks._projection_accounting(
                projection
            )
            native_result = copy.deepcopy(projection["state"]["result"])
            native_result["session_id"] = session_id
            self.store.record_result(task_id, {
                "status": "failure",
                "reason": reason,
                **accounting,
                "native_result": native_result,
            })

        def settle_stopped(reason):
            # Stop is already durable.  Keep this task owned by the host
            # until its same-session terminal settlement can be retried.
            while True:
                try:
                    stopped(reason)
                    return
                except Exception:
                    time.sleep(self.poll_interval)

        # Avoid even configuration recovery when startup already inherited an
        # accepted Stop.  Recheck below in case Stop arrived while resolving.
        with registry.locked(self.home):
            stop_reason = self._stop_reason(task_id)
        if stop_reason is not None:
            settle_stopped(stop_reason)
            return

        # A directly ordered task carries its owner's session on the order
        # itself — an id, or an explicit null choosing the default document
        # — and every automatic call of its discussion resolves through
        # that. A pre-cutover static record has no such key and keeps its
        # pins; `standalone_staffing` reads the absence as no session.
        _supplied, session = tasks.order_staffing_session(record["order"])
        start_options = {
            "staffing_selection": brainstorming_tasks.standalone_staffing(
                session
            ),
        }
        try:
            config = config_resolver()
        except Exception as exc:
            config = {}
            start_options["pre_session_failure_reason"] = (
                "Brainstorming execution unavailable: %s" % exc
            )
        state = {"tasks": self.store.records()}
        try:
            stop_reason = self._stop_reason(task_id)
            if stop_reason is not None:
                settle_stopped(stop_reason)
                return
            projection = brainstorming_tasks.start_task(
                state, task_id, config, self.home, **start_options
            )
            if self._persist_adapter_result(state, task_id) is not None:
                return
            if projection is None:
                return
            session_id = projection["id"]
            repository_backed = session_repository.context_from_state(
                projection["state"]
            ) is not None
            with self._lock:
                self._sessions[task_id] = session_id
            authority = record["resolved_staffing"]["dispatch_authority"]
            while True:
                stop_reason = self._stop_reason(task_id)
                if stop_reason is not None:
                    settle_stopped(stop_reason)
                    return
                state = {"tasks": self.store.records()}
                effect = (
                    None
                    if repository_backed else
                    lambda effect_request: (
                        brainstorming_tasks.apply_agreed_effects(
                            self.home,
                            session_id,
                            task_id,
                            effect_request,
                            dispatch_authority=authority,
                            staffing_selection=(
                                brainstorming_tasks.standalone_staffing(
                                    session
                                )
                            ),
                        )
                    )
                )
                terminal = brainstorming_tasks.finish_task(
                    state,
                    task_id,
                    self.home,
                    session_id,
                    effect,
                )
                if terminal is not None:
                    stop_reason = self._stop_reason(task_id)
                    if stop_reason is not None:
                        settle_stopped(stop_reason)
                        return
                    stop_reason = self._record_brainstorming_terminal(
                        state, task_id
                    )
                    if stop_reason is not None:
                        settle_stopped(stop_reason)
                    return
                time.sleep(self.poll_interval)
        except Exception:
            # Inspection and process loss are not a new abandonment judgment.
            # Order recovery failure against Stop acceptance: if Stop won,
            # settle it; otherwise retire this host before a later Stop can be
            # reported as accepted and lose its terminal settlement.
            with registry.locked(self.home):
                with self._lock:
                    stop_reason = self._stops.get(task_id)
                    if stop_reason is None:
                        stop_reason = self.store.stop_reason(task_id)
                    if stop_reason is None:
                        self._active.pop(task_id, None)
            if stop_reason is not None:
                settle_stopped(stop_reason)
            return
