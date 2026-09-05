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
from orchestrator import kvstore, pricing, profiles, prompt_sets
from orchestrator import registry, runners, session_repository, staffing, tasks
from orchestrator import state as st


TASKS_DIRNAME = "tasks"
REVIEWED_DIRNAME = "reviewed"
_TASK_KEY_PREFIX = "tasks/task:"
_DOCUMENT_SCHEMA_VERSION = 1


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
    def _document(record, admitted_at, stop_reason=None):
        document = {
            "schema_version": _DOCUMENT_SCHEMA_VERSION,
            "admitted_at": admitted_at,
            "record": record,
        }
        if stop_reason is not None:
            document["stop_reason"] = stop_reason
        return document

    @staticmethod
    def _validate_document(value, key):
        if (
            not isinstance(value, dict)
            or set(value) not in (
                {"schema_version", "admitted_at", "record"},
                {"schema_version", "admitted_at", "record", "stop_reason"},
            )
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
        return value

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
        state = {"tasks": [document["record"]]}
        record = tasks.record_task_result(state, task_id, result)
        outcome = self._store.cas(
            key,
            current["revision"],
            self._document(
                state["tasks"][0],
                document["admitted_at"],
                document.get("stop_reason"),
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
            self._document(record, document["admitted_at"], reason.strip()),
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


def _workspace(record):
    work_area = record["order"]["request"]["work_area"]
    primary = work_area.get("primary")
    workspace = work_area.get("workspace_path")
    if isinstance(primary, dict):
        primary = primary.get("path")
    workspace = workspace or primary
    if not isinstance(workspace, str) or not os.path.isdir(workspace):
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
        self._lock = threading.Lock()

    def stop(self, task_id, reason="stopped by operator"):
        """Stop one running standalone task. Returns True when a stop was
        delivered, False when the task is not running here (already
        terminal, or not this host's). The task closes as `failure` with
        this reason: a stop is an operator outcome, never a guessed
        success from whatever the interrupted worker last printed."""
        reason = str(reason or "stopped by operator").strip()
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
                if executor in (
                    "brainstorming", "reviewed_task", "deep_task"
                ):
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

    def start(self, record, config_resolver, parent_task_id=None):
        task_id = record["id"]
        workspace = _workspace(record)
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
            if tasks.stored_task_executor(
                record["order"]["task_executor"]
            ) == "reviewed_task":
                path = reviewed_state_path(self.home, task_id)
                if not os.path.exists(path):
                    ensure_reviewed_state(
                        self.home,
                        record,
                        config_resolver(),
                        implementation_scope=(
                            self._deep_implementation_scope(record)
                        ),
                    )
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
                raise
        return thread

    def adopt_open_tasks(self, config_resolver_for):
        """Re-attach the standalone tasks left open by a previous service.

        The host's execution threads die with the process; the records do
        not. A Brainstorming task owns an independent session that may have
        gone on (or finished) meanwhile, and the adapter already knows how
        to recover it from the task's private target — so it is restarted
        here and runs to its result. A Worker task's call died with the
        service and cannot be resumed without redoing the work blind, so it
        is closed honestly and the operator re-orders if still wanted.
        `config_resolver_for(record)` returns the zero-arg config resolver
        to use for that record. Returns {adopted: [...], closed: [...]}."""
        adopted, closed = [], []
        try:
            records = self.store.records()
        except Exception:
            return {"adopted": adopted, "closed": closed}
        for record in records:
            if record.get("result") is not None:
                continue
            task_id = record["id"]
            executor = (record.get("order") or {}).get("task_executor")
            if executor in ("brainstorming", "reviewed_task", "deep_task"):
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
        """Whether an execution thread currently owns an overlapping tree."""
        with self._lock:
            active = list(self._active.values())
        return any(gitsync.paths_overlap(path, workspace) for path in active)

    def owns_workspace_except(self, workspace, task_id):
        """Whether work outside one task's owner chain holds the tree."""
        try:
            excluded = {
                record["id"] for record in self.store.owner_chain(task_id)
            }
        except Exception:
            excluded = {task_id}
        with self._lock:
            active = [
                path for active_id, path in self._active.items()
                if active_id not in excluded
            ]
        return any(gitsync.paths_overlap(path, workspace) for path in active)

    def _run(self, task_id, config_resolver):
        try:
            record = self.store.record(task_id)
            if record["result"] is not None:
                return
            executor = tasks.stored_task_executor(
                record["order"]["task_executor"]
            )
            if executor == "agent_call":
                self._run_worker(record, config_resolver)
            elif executor == "brainstorming":
                self._run_brainstorming(record, config_resolver)
            elif executor == "deep_task":
                self._run_deep(record, config_resolver)
            else:
                self._run_reviewed(record)
        finally:
            with self._lock:
                self._active.pop(task_id, None)
                self._controls.pop(task_id, None)
                self._sessions.pop(task_id, None)
                self._stops.pop(task_id, None)

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
                self.store.record_result_locked(task_id, result)
                # A Stop arriving after this point was not accepted: the
                # terminal record and work-area release become visible as one
                # host decision under the same control lock.
                self._active.pop(task_id, None)
        return result

    def _await_deep_child(self, task_id, child, config_resolver):
        if child["result"] is None and self._stop_reason(task_id) is None:
            self.start(child, config_resolver, parent_task_id=task_id)
        while True:
            child = self.store.record(child["id"])
            stop_reason = self._stop_reason(task_id)
            if stop_reason is not None and child["result"] is None:
                delivered = self.stop(child["id"], stop_reason)
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
                            self.start(child, config_resolver)
                    else:
                        try:
                            child = self.store.record_result(
                                child["id"], self._deep_failure(stop_reason)
                            )
                        except tasks.TaskRecordError:
                            child = self.store.record(child["id"])
            if child["result"] is not None:
                return child, stop_reason
            time.sleep(self.poll_interval)

    def _admit_deep_child(
        self, task_id, phase, part, order, workspace
    ):
        with registry.locked(self.home):
            with self._lock:
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
            if child["result"] is None:
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
                # Keep the task active until its chosen result is durable.
                # A concurrent parent then either delivers Stop before this
                # write or observes the already-terminal child; it can never
                # mistake an in-progress settlement for abandoned work.
                self.store.record_result_locked(task_id, result)
                self._active.pop(task_id, None)
        return None

    def _unattached_reviewed_session_id(self, subject, unit):
        """Recover the one session created before its attachment was saved."""
        caller = "milestone:%s:%s" % (
            subject.state.get("name") or "run", st.unit_key(unit)
        )
        rows = brainstorming_tasks.lifecycle.list_sessions(
            self.home, lambda record: record.get("caller") == caller
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
                    store = brainstorming.SessionStore(
                        brainstorming_tasks.lifecycle.state_directory(
                            self.home
                        )
                    )
                    snapshot = store.read(session_id)
                    if snapshot is not None:
                        projection = brainstorming_tasks._retained_projection(
                            self.home,
                            session_id,
                            "discarded:%s" % session_id,
                            snapshot.state["request"].get("target_path"),
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
        lifecycle_state = st.load(path)
        runner = self.runner_factory(lifecycle_state["config"], _workspace(record))
        subject = driver.Driver(
            path, runner=runner, model_profiles_home=self.home
        )
        unit_key = subject.state["reviewed_task"]["unit"]
        try:
            for _ in range(10000):
                unit = subject._unit_by_key(unit_key)
                stop_reason = self._stop_reason(task_id)
                if stop_reason is not None:
                    if self._settle_stopped_reviewed(
                        task_id, subject, unit, stop_reason
                    ):
                        return
                    time.sleep(self.poll_interval)
                    continue
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
                with subject._exclusive():
                    subject._assert_not_stale()
                    recovered = subject.reviewed_work.recover_pending_gate()
                    if recovered is None:
                        action = subject.reviewed_work.next_action(unit)
                        subject.reviewed_work.execute(
                            action,
                            call_preparation=(
                                driver.StandaloneReviewedWorkCallPreparation(
                                    subject
                                )
                            ),
                        )
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
        self.store.record_result(task_id, result)

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
