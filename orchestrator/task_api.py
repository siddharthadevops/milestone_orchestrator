"""Durable standalone task records and their immediate execution host."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import threading
import time
import uuid

from orchestrator import brainstorming_tasks, driver, gitsync, kvstore, pricing
from orchestrator import registry, runners, tasks


def records_path(home):
    return os.path.join(home, "tasks.json")


class StandaloneTaskStore:
    """One atomic home for canonical records admitted outside a milestone."""

    def __init__(self, home):
        self.home = os.path.abspath(home)

    def _load(self):
        path = records_path(self.home)
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise tasks.TaskRecordError("standalone task history must be a list")
        return tasks.task_records({"tasks": records})

    def _save(self, records):
        os.makedirs(self.home, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".tasks-", suffix=".json", dir=self.home
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    records,
                    handle,
                    indent=2,
                    ensure_ascii=False,
                    allow_nan=False,
                )
                handle.write("\n")
            os.replace(temporary, records_path(self.home))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def records(self):
        return self._load()

    def record(self, task_id):
        return tasks.task_record({"tasks": self._load()}, task_id)

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
        self._save(state["tasks"])
        return record

    def record_result(self, task_id, result):
        with registry.locked(self.home):
            return self.record_result_locked(task_id, result)

    def record_result_locked(self, task_id, result):
        """Record a result while the caller holds the service registry lock."""
        state = {"tasks": self._load()}
        record = tasks.record_task_result(state, task_id, result)
        self._save(state["tasks"])
        return record


def worker_staffing(config):
    """Resolve the profile-less agent-call snapshot used at direct admission."""
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
        commands = config.get("commands")
        if not isinstance(commands, dict) or family not in commands:
            raise ValueError("family command")
        runners.apply_model_effort(commands[family], model, effort)
    except (KeyError, IndexError, TypeError, ValueError, runners.RunnerError) as exc:
        raise tasks.TaskRequestError(
            tasks.TASK_UNAVAILABLE, "Worker staffing is unavailable"
        ) from exc
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


def _dispatch(config):
    snapshot = worker_staffing(config)["agent_call"]
    return snapshot["agent"], snapshot["model"], snapshot["effort"]


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
        self._lock = threading.Lock()

    @staticmethod
    def _runner(config, _workspace):
        return runners.SubprocessRunner(
            config["commands"],
            config.get("timeouts", {}),
            stall_window_s=config.get("worker_stall_window_s"),
            stall_min_cpu_s=config.get("worker_stall_min_cpu_s"),
        )

    def start(self, record, config_resolver):
        task_id = record["id"]
        workspace = _workspace(record)
        with self._lock:
            if task_id in self._active:
                return None
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
            with self._lock:
                self._active.pop(task_id, None)
            raise
        return thread

    def owns_workspace(self, workspace):
        """Whether an execution thread currently owns an overlapping tree."""
        with self._lock:
            active = list(self._active.values())
        return any(gitsync.paths_overlap(path, workspace) for path in active)

    def _run(self, task_id, config_resolver):
        try:
            record = self.store.record(task_id)
            if record["result"] is not None:
                return
            if tasks.stored_task_executor(
                record["order"]["task_executor"]
            ) == "agent_call":
                self._run_worker(record, config_resolver)
            else:
                self._run_brainstorming(record, config_resolver)
        finally:
            with self._lock:
                self._active.pop(task_id, None)

    def _run_worker(self, record, config_resolver):
        task_id = record["id"]
        started = time.time()
        marker = None
        carrier = None
        native = None
        reason = None
        try:
            config = config_resolver()
            family, model, effort = _dispatch(config)
            marker = {
                "task_id": task_id,
                "call_id": str(uuid.uuid4()),
                "family": family,
                "model": model,
                "effort": effort,
                "started_at": started,
            }
            _write_worker_marker(self.home, task_id, marker)
            runner = self.runner_factory(config, _workspace(record))
            carrier = tasks.execute_worker(
                record,
                lambda request: runner.call(
                    family,
                    request["request"],
                    _workspace(record),
                    model=model,
                    effort=effort,
                ),
            )
            native = carrier.text
            status = "success"
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
        result = {"status": status, **accounting, "native_result": native}
        if status == "failure":
            result["reason"] = reason or "Worker execution failed"
        self.store.record_result(task_id, result)

    def _persist_adapter_result(self, state, task_id):
        record = tasks.task_record(state, task_id)
        if record["result"] is None:
            return None
        return self.store.record_result(task_id, record["result"])

    def _run_brainstorming(self, record, config_resolver):
        task_id = record["id"]
        # A directly ordered task has no owner run: its discussion resolves
        # every automatic call through the router holding no session of its
        # own. A pre-cutover static record ignores this and keeps its pins.
        start_options = {
            "staffing_selection": brainstorming_tasks.standalone_staffing(),
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
            projection = brainstorming_tasks.start_task(
                state, task_id, config, self.home, **start_options
            )
            if self._persist_adapter_result(state, task_id) is not None:
                return
            if projection is None:
                return
            session_id = projection["id"]
            authority = record["resolved_staffing"]["dispatch_authority"]
            while True:
                state = {"tasks": self.store.records()}
                terminal = brainstorming_tasks.finish_task(
                    state,
                    task_id,
                    self.home,
                    session_id,
                    lambda effect_request: (
                        brainstorming_tasks.apply_agreed_effects(
                            self.home,
                            session_id,
                            task_id,
                            effect_request,
                            dispatch_authority=authority,
                            staffing_selection=(
                                brainstorming_tasks.standalone_staffing()
                            ),
                        )
                    ),
                )
                if terminal is not None:
                    self._persist_adapter_result(state, task_id)
                    return
                time.sleep(self.poll_interval)
        except Exception:
            # Inspection and process loss are not a new abandonment judgment.
            # The durable task/session remain open for native recovery.
            return
