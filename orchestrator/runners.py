"""CLI runners: how the deterministic driver talks to LLM workers.

Two implementations of the same tiny interface:

- SubprocessRunner: builds the configured command line for a family
  (codex / claude / fake test CLIs), feeds the prompt on stdin, captures the
  last message, enforces a timeout by killing the whole process group.
- MockRunner: scripted responses for deterministic lifecycle tests.

On top of the raw call, `call_worker()` extracts the JSON object, validates
it against orchestrator.contracts, and performs exactly one repair retry
when the output is not valid JSON / not contract-conformant. After that the
caller receives WorkerProtocolError and the driver fails the run with the
explanation in the log — no prose parsing, ever.
"""

import fnmatch
import hashlib
import inspect
import json
import math
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time
import uuid

from . import contracts

# In-flight worker CLI processes. Workers run in their OWN sessions
# (start_new_session=True below) so a timeout can SIGKILL the whole worker
# tree without touching the driver — which also means a SIGTERM to the
# driver's group does NOT reach them. The driver's stop handler uses this
# set to forward a stop to every active worker's process group instead of
# orphaning full-permission CLIs mid-edit.
_ACTIVE_WORKERS = set()
_ACTIVE_WORKERS_LOCK = threading.Lock()


def _track_worker(proc):
    with _ACTIVE_WORKERS_LOCK:
        _ACTIVE_WORKERS.add(proc)


def _untrack_worker(proc):
    with _ACTIVE_WORKERS_LOCK:
        _ACTIVE_WORKERS.discard(proc)


def kill_active_worker_groups():
    """SIGKILL the process groups of all in-flight worker CLIs (same signal
    the timeout path uses). Called from the driver's SIGTERM handler so a
    service-initiated stop cannot leave an orphaned worker editing the
    workspace and burning quota."""
    with _ACTIVE_WORKERS_LOCK:
        procs = list(_ACTIVE_WORKERS)
    for proc in procs:
        _kill_group(proc)


class RunnerError(RuntimeError):
    """The CLI process itself failed (spawn error, timeout, nonzero exit
    with no usable output)."""


class ProviderResponseError(RunnerError):
    """The CLI returned a structured provider failure, not an answer."""

    def __init__(self, message, raw_texts=None, token_usage=None):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])
        self.token_usage = normalize_token_usage(token_usage)
        self.token_usage_partial = self.token_usage is None


class WorkerStalled(RunnerError):
    """A liveness watchdog killed the worker: its whole process tree burned
    less than the configured CPU floor over a full sampling window, i.e. it
    was frozen (no local compute, so no bytes flowing from the provider and
    no local work either) — the dead-CLI-spawn / provider-side-hang that has
    no timeout to catch it. Typed like a timeout: recoverable, auto-resumed,
    and a fresh call re-issues the same work."""


def _parse_ps_time(text):
    """Cumulative CPU seconds from a `ps -o time=` field. Formats seen:
    `MM:SS`, `M:SS.ss`, `HH:MM:SS`, `DD-HH:MM:SS`. Returns None on garbage."""
    text = (text or "").strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        d, _, text = text.partition("-")
        try:
            days = int(d)
        except ValueError:
            return None
    parts = text.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    secs = 0.0
    for n in nums:
        secs = secs * 60 + n
    return days * 86400 + secs


def group_cpu_by_pid(pgid):
    """{pid: cumulative_cpu_seconds} for every process in process GROUP
    `pgid`, or None when it cannot be measured (a ps failure, an unreadable
    member) so the caller fails open — never kills on a blind spot.

    Keyed on the process GROUP, not a ppid tree, because a worker is spawned
    as its own session/group leader (pgid == pid) and its descendants inherit
    that pgid: they stay in the group even after the leader exits and they
    reparent to init. A ppid walk would LOSE those reparented children —
    reading them as gone (miss a real hang) or, worse, seeing only the frozen
    leader and killing a child that is still working."""
    try:
        proc = subprocess.run(
            ["ps", "-Ao", "pid=,pgid=,time="],
            capture_output=True, text=True, timeout=PS_SAMPLE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = {}
    for line in proc.stdout.splitlines():
        f = line.split(None, 2)
        if len(f) < 3:
            continue
        try:
            pid = int(f[0])
            this_pgid = int(f[1])
        except ValueError:
            continue
        if this_pgid != pgid:
            continue
        secs = _parse_ps_time(f[2])
        if secs is None:
            # A group member whose CPU we could not read: fail open.
            return None
        out[pid] = secs
    return out or None


def tree_cpu_seconds(root_pid):
    """Sum of group_cpu_by_pid, or None. NOT monotonic across child churn —
    for one-shot measurement/tests only, never for stall deltas."""
    m = group_cpu_by_pid(root_pid)
    return None if m is None else sum(m.values())


# ps sampling is cheap but bounded so a wedged ps can never hang the watchdog.
PS_SAMPLE_TIMEOUT = 10


def _process_group_exists(pgid):
    """Return whether ``pgid`` still exists, or None when that is unknown."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


def _process_group_quiescent(pgid):
    """Return whether a worker group has no process capable of more work."""
    exists = _process_group_exists(pgid)
    if exists is not True:
        return None if exists is None else True
    try:
        observed = subprocess.run(
            ["ps", "-Ao", "pgid=,stat="],
            capture_output=True,
            text=True,
            timeout=PS_SAMPLE_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if observed.returncode != 0:
        return None
    for line in observed.stdout.splitlines():
        fields = line.split(None, 1)
        if not fields:
            continue
        try:
            member_pgid = int(fields[0])
        except ValueError:
            continue
        if member_pgid != pgid:
            continue
        if len(fields) < 2:
            return None
        # A zombie has exited and cannot mutate the target; it may remain in
        # the process table briefly until its new parent reaps it.
        if not fields[1].startswith("Z"):
            return False
    return True


def _wait_for_process_group_quiescence(pgid, timeout=PS_SAMPLE_TIMEOUT):
    """Confirm that every member of a signalled worker group is quiet."""
    deadline = time.monotonic() + timeout
    while True:
        quiescent = _process_group_quiescent(pgid)
        if quiescent is True:
            return True
        if quiescent is None or time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def _positive_float(value):
    """Coerce a config knob to a positive FINITE float, or None. A malformed
    value (string, negative, zero, inf/nan) disables the feature instead of
    raising later on the hot call path (inf window overflows the wait; inf
    floor kills every worker) or leaking a spawned worker."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0:
        return None
    return f


_TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _token_count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(float(value)) or value < 0:
        return 0
    return int(value)


def normalize_token_usage(usage, family=None):
    """Normalize Codex and Claude usage into one additive shape.

    Codex reports cached input as a subset of ``input_tokens``. Claude
    reports ordinary, cache-write, and cache-read input separately, so its
    normalized input is their sum. Reasoning is a breakdown of output and is
    therefore never added again to the total.
    """
    if not isinstance(usage, dict):
        return None
    canonical = "total_tokens" in usage

    def value(snake, camel=None):
        if snake in usage:
            return _token_count(usage.get(snake))
        return _token_count(usage.get(camel)) if camel else 0

    base_input = value("input_tokens", "inputTokens")
    cached_input = value("cached_input_tokens", "cachedInputTokens")
    output = value("output_tokens", "outputTokens")
    reasoning = value("reasoning_output_tokens", "reasoningOutputTokens")
    if family == "claude" and not canonical:
        cache_write = value(
            "cache_creation_input_tokens", "cacheCreationInputTokens"
        )
        cache_read = value("cache_read_input_tokens", "cacheReadInputTokens")
        base_input += cache_write + cache_read
        cached_input = cache_read
        details = usage.get("output_tokens_details") or {}
        if not reasoning and isinstance(details, dict):
            reasoning = _token_count(details.get("thinking_tokens"))
    recognized = any(
        key in usage
        for key in (
            "input_tokens", "inputTokens", "output_tokens", "outputTokens",
            "total_tokens", "totalTokens", "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    )
    if not recognized:
        return None
    return {
        "input_tokens": base_input,
        "cached_input_tokens": cached_input,
        "output_tokens": output,
        "reasoning_output_tokens": reasoning,
        "total_tokens": base_input + output,
    }


def add_token_usage(*items):
    normalized = [normalize_token_usage(item) for item in items]
    normalized = [item for item in normalized if item is not None]
    if not normalized:
        return None
    return {
        field: sum(item[field] for item in normalized)
        for field in _TOKEN_USAGE_FIELDS
    }


def subtract_token_usage(current, previous):
    """Return a cumulative provider counter's non-negative turn delta."""
    current = normalize_token_usage(current)
    previous = normalize_token_usage(previous)
    if current is None or previous is None:
        return None
    delta = {
        field: current[field] - previous[field]
        for field in _TOKEN_USAGE_FIELDS
    }
    if any(value < 0 for value in delta.values()):
        return None
    return delta


def _provider_transport_result(family, transport_text):
    """Return (final_text, normalized usage) from provider JSON output."""
    events = []
    for line in (transport_text or "").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(event, dict):
            events.append(event)
    if not events:
        try:
            event = json.loads((transport_text or "").strip())
        except (TypeError, json.JSONDecodeError):
            event = None
        if isinstance(event, dict):
            events.append(event)
    final_text = None
    token_usage = None
    provider_error = None
    for event in events:
        if family == "claude" and event.get("type") == "result":
            if event.get("is_error"):
                provider_error = (
                    event.get("result") or event.get("subtype")
                    or "unknown provider error"
                )
            elif isinstance(event.get("result"), str):
                final_text = event["result"]
            token_usage = normalize_token_usage(event.get("usage"), "claude")
        elif family == "codex" and event.get("type") in (
            "error", "turn.failed"
        ):
            error = event.get("error")
            if isinstance(error, dict):
                provider_error = error.get("message") or json.dumps(error)
            else:
                provider_error = error or event.get("message") or event.get(
                    "detail"
                ) or "unknown provider error"
        elif family == "codex" and event.get("type") == "item.completed":
            item = event.get("item") or {}
            if (
                isinstance(item, dict)
                and item.get("type") == "agent_message"
                and isinstance(item.get("text"), str)
            ):
                final_text = item["text"]
        elif family == "codex" and event.get("type") == "turn.completed":
            token_usage = normalize_token_usage(event.get("usage"), "codex")
        elif family == "codex" \
                and event.get("method") == "thread/tokenUsage/updated":
            usage = ((event.get("params") or {}).get("tokenUsage") or {})
            token_usage = normalize_token_usage(usage.get("last"), "codex")
    if provider_error is not None:
        raise ProviderResponseError(
            "family %s reported a provider failure: %s"
            % (family, str(provider_error)[:500]),
            raw_texts=[transport_text],
            token_usage=token_usage,
        )
    return final_text, token_usage


class WorkerProtocolError(RuntimeError):
    """The CLI ran but its output violates the JSON contract even after the
    repair retry. Carries the raw output texts of both attempts so the
    driver can persist them for the operator."""

    def __init__(self, message, raw_texts=None, duration_s=None,
                 token_usage=None, token_usage_partial=False):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])
        self.duration_s = duration_s
        self.token_usage = normalize_token_usage(token_usage)
        self.token_usage_partial = bool(token_usage_partial)


class RunnerResult(object):
    def __init__(self, text, exit_code, duration_s, transport_text=None,
                 token_usage=None):
        self.text = text
        self.exit_code = exit_code
        self.duration_s = duration_s
        # stdout before {output_file} selection. Session-capable Codex calls
        # emit their explicit thread id here while keeping the final answer in
        # the historical last-message file.
        self.transport_text = text if transport_text is None else transport_text
        self.token_usage = normalize_token_usage(token_usage)


class ControlledInterruptionResult(RunnerResult):
    def __init__(self, text, exit_code, duration_s, reason,
                 transport_text=None, token_usage=None):
        RunnerResult.__init__(
            self, text, exit_code, duration_s,
            transport_text=transport_text,
            token_usage=token_usage,
        )
        self.controlled_interruption = True
        self.interrupt_reason = str(reason or "controlled interruption")


class ActiveCallControl(object):
    def __init__(self, observer=None, on_interrupt=None,
                 _interrupt_state=None, _confirmation_state=None,
                 on_interrupt_rejected=None):
        if observer is not None and not callable(observer):
            raise RunnerError("active-call observer must be callable")
        if on_interrupt is not None and not callable(on_interrupt):
            raise RunnerError("active-call interrupt callback must be callable")
        if (on_interrupt_rejected is not None
                and not callable(on_interrupt_rejected)):
            raise RunnerError(
                "active-call interrupt rejection callback must be callable"
            )
        self._observer = observer
        self._on_interrupt = on_interrupt
        self._on_interrupt_rejected = on_interrupt_rejected
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._functions = {}
        self._thread = None
        self._steers, self._error = [], None
        self._confirmation_state = _confirmation_state or {
            "lock": threading.Lock(),
            "token": None,
            "at": None,
        }
        self._interrupt_state = _interrupt_state or {
            "lock": threading.Lock(),
            "reason": None,
        }

    @property
    def closed(self):
        return self._closed.is_set()

    @property
    def steers(self):
        return list(self._steers)

    @property
    def interrupt_reason(self):
        with self._interrupt_state["lock"]:
            return self._interrupt_state["reason"]

    @property
    def interrupted(self):
        return self.interrupt_reason is not None

    @property
    def error(self):
        return self._error

    @property
    def model_confirmation_at(self):
        with self._confirmation_state["lock"]:
            return self._confirmation_state["at"]

    def expect_model_confirmation(self, token):
        """Arm one exact model-authored acknowledgement before steering."""
        token = str(token or "").strip()
        if not token:
            raise ValueError("model confirmation token must be non-empty")
        with self._lock:
            if self.closed:
                return False
        with self._confirmation_state["lock"]:
            # A repair is another physical call in the same logical episode.
            # Re-arming the same token must not erase an ACK already observed
            # by either physical call; a different token starts a new proof.
            if self._confirmation_state["token"] != token:
                self._confirmation_state["token"] = token
                self._confirmation_state["at"] = None
        return True

    def observe_model_message(self, text):
        """Accept only the exact armed message; transports select its role."""
        if not isinstance(text, str):
            return False
        with self._confirmation_state["lock"]:
            if self._confirmation_state["at"] is not None:
                return False
            if text.strip() != self._confirmation_state["token"]:
                return False
            self._confirmation_state["at"] = time.monotonic()
        return True

    def wait_closed(self, timeout=None):
        return self._closed.wait(timeout)

    def renew(self):
        """Return a fresh physical-call control with the same observer.

        A provider call closes its controller. Contract repair is a second
        physical call and must not silently reuse that closed instance.
        """
        return ActiveCallControl(
            observer=self._observer,
            on_interrupt=self._on_interrupt,
            _interrupt_state=self._interrupt_state,
            _confirmation_state=self._confirmation_state,
            on_interrupt_rejected=self._on_interrupt_rejected,
        )

    def steer(self, text):
        text = str(text or "").strip()
        if not text:
            raise ValueError("steer text must be non-empty")
        return self._request("steer", text)

    def interrupt(self, reason="controlled interruption"):
        reason = str(reason or "controlled interruption").strip()
        return self._request("interrupt", reason)

    def _request(self, kind, value):
        with self._lock:
            if self.closed:
                return False
            fn = self._functions.get(kind)
        if fn is None:
            return False
        if kind == "interrupt" and self._on_interrupt is not None:
            # Write the durable cutoff intent before the transport can observe
            # the interrupt. If persistence fails, do not send a stop that a
            # restarted driver would be unable to distinguish from a crash in
            # the ordinary draft.
            try:
                self._on_interrupt(value)
            except Exception as exc:
                self._error = str(exc)
                return False
        try:
            accepted = fn(value) is not False
        except Exception as exc:
            self._reject_persisted_interrupt(kind, value, exc)
            return False
        if not accepted:
            self._reject_persisted_interrupt(kind, value)
            return False
        if kind == "steer":
            self._steers.append(value)
        else:
            # Renewed physical calls share the same state, so a transport
            # error from a contract-repair call remains visible to the outer
            # driver as the accepted interruption it is.
            with self._interrupt_state["lock"]:
                self._interrupt_state["reason"] = value
        return True

    def _reject_persisted_interrupt(self, kind, value, transport_error=None):
        """Undo write-ahead intent after an explicit transport rejection."""
        rollback_error = None
        if kind == "interrupt" and self._on_interrupt_rejected is not None:
            try:
                self._on_interrupt_rejected(value)
            except Exception as exc:
                rollback_error = exc
        if transport_error is not None and rollback_error is not None:
            self._error = "%s; interrupt rollback failed: %s" % (
                transport_error, rollback_error
            )
        elif transport_error is not None:
            self._error = str(transport_error)
        elif rollback_error is not None:
            self._error = "interrupt rollback failed: %s" % rollback_error

    def _bind(self, steer_fn, interrupt_fn):
        with self._lock:
            if self.closed:
                return
            self._functions = {"steer": steer_fn, "interrupt": interrupt_fn}
        if self._observer is None:
            return
        self._thread = threading.Thread(
            target=self._run_observer, name="worker-control-observer",
            daemon=True,
        )
        try:
            self._thread.start()
        except RuntimeError as exc:
            self._error = str(exc)

    def _run_observer(self):
        try:
            self._observer(self)
        except Exception as exc:
            self._error = str(exc)

    def _close(self):
        with self._lock:
            self._functions = {}
            self._closed.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=PS_SAMPLE_TIMEOUT)


# ---------------------------------------------------------------------------
# JSON extraction


def extract_json_objects(text):
    """Return every independent complete JSON object found in text."""
    if text is None:
        raise ValueError("no output text")
    stripped = text.strip()
    if not stripped:
        raise ValueError("no valid JSON object found in worker output")
    try:
        bare = json.loads(stripped)
        if isinstance(bare, dict):
            return [bare]
    except json.JSONDecodeError:
        pass

    valid = []
    start = stripped.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = stripped[start : i + 1]
                        try:
                            obj = json.loads(candidate)
                            if isinstance(obj, dict):
                                valid.append(obj)
                            start = stripped.find("{", i + 1)
                        except json.JSONDecodeError:
                            start = stripped.find("{", start + 1)
                        break
        else:
            start = stripped.find("{", start + 1)
    if not valid:
        raise ValueError("no valid JSON object found in worker output")
    return valid


def extract_json(text):
    """Extract one complete JSON object for schema-less callers.

    Accepts: a bare JSON object; an object wrapped in ```json fences; an
    object surrounded by stray prose. Raises ValueError when no valid object
    can be found. Worker protocol calls do not use this positional fallback:
    they select the sole object satisfying the expected contract. Never uses
    regex heuristics over findings prose — this is the structural replacement
    for the old VERDICT-line parser.
    """
    return extract_json_objects(text)[-1]


def _closers_from(stripped, start):
    """The closing delimiters the object opening at `start` still needs, or
    None when the text cannot be completed by punctuation alone.

    None means: an unterminated string, mismatched nesting, or an object
    that already closed. Only a value cut exactly at a structural boundary
    is completable — anything else would require inventing content."""
    stack = []
    in_str = False
    esc = False
    for ch in stripped[start:]:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return None
            stack.pop()
            if not stack:
                return None
    if in_str or not stack:
        return None
    return "".join(reversed(stack))


# The only characters a recoverable text may end on. Each one PROVES the
# preceding token finished: a closing quote ends a string, `}`/`]` end a
# container. Anything else may be a token cut mid-way — and a bare token
# is the dangerous case, because it can still parse after closing while
# meaning something different: `"id": 1` truncated from `10` would
# silently validate as 1. Refusing here is what keeps "append only
# grammar-determined punctuation" an honest claim rather than a guess.
_COMPLETE_TOKEN_TAIL = ('"', "}", "]")


# Kinds whose output only REPORTS. Their optional keys are descriptive,
# so an envelope recovered by its closing brace cannot have lost anything
# that changes what the machine does.
#
# Every other kind DIRECTS the machine through optional keys — implement
# and fix_findings carry `suite_command`, which retargets the verification
# gate; drafts carry `slices`. For those, "the required keys are present"
# does NOT mean the object was finished: a truncation just before
# `,"suite_command": ...` would validate and silently seal against the
# wrong suite. They keep the repair retry, whose cost is honest.
RECOVERABLE_KINDS = frozenset({contracts.KIND_REVIEW_ROUND})


def _prefix_opens_nothing(stripped, start):
    """No unmatched opener sits before `start` (outside strings).

    A prefix that still has one open means the object is an ELEMENT of a
    larger unterminated structure (`[{...`), not a top-level object that
    lost its brace. Closing the element alone would silently promote it to
    the whole answer and drop whatever the container had yet to emit.

    Delimiter TYPES are matched, not merely counted: a bare depth counter
    reads `[}` as balanced and would let exactly that promotion through."""
    stack = []
    in_str = False
    esc = False
    for ch in stripped[:start]:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if not stack or stack.pop() != ch:
                return False
    return not stack and not in_str


def _reject_duplicate_keys(pairs):
    """json object hook that refuses any object with a repeated key.

    json.loads keeps the LAST of duplicate keys, so without this a
    recovered `{"status":"ok",...,"status":"blocked"}` (or a duplicated
    project-extension field) would silently collapse to one value and the
    "the object is complete and valid" proof would not hold. A duplicate
    is never legitimate worker output, so rejecting is free of false
    negatives."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError("duplicate key %r" % key)
        seen[key] = value
    return seen


def _repair_unterminated(text):
    """Recover a top-level object whose CLOSING DELIMITERS are missing.

    Workers occasionally stop one token early: the last value's string is
    closed, a newline follows, and generation ends without the object's
    final `}`. Observed live across three claude review rounds, each
    otherwise complete and contract-valid — a finished review was being
    thrown away, and its replacement re-review reached a different verdict
    (one dropped two findings and the unit sealed clean).

    Returns (object, closers) or None. Five independent conditions must
    all hold, because "append only punctuation" is a claim that has to be
    earned: the text must end on a character proving its last token
    finished, nothing may be left open before the object starts, the ONLY
    missing delimiter must be the top-level object's own brace, it must
    parse, and it must carry no duplicate key. The caller then requires
    the worker contract on top.

    The single-brace rule is what keeps this honest. A deeper truncation
    ends inside a COLLECTION, and no amount of punctuation can tell us
    whether that collection had more elements coming: closing
    `"findings": [F1` yields a valid object reporting one finding when the
    worker may have been writing five. Losing a finding that way is the
    exact damage this whole change exists to prevent, so anything deeper
    than the outermost brace is refused and pays the re-review instead.

    Residual limit, stated honestly: a truncation that dropped a LATER
    re-emission of an already-present key (e.g. a second `status`) cannot
    be detected from the text alone. It is mitigated structurally — status
    is required and emitted first, so a recovered object already carries
    its verdict — and by the report-only kind gate the caller applies; a
    duplicate that IS present in the recovered text is rejected here."""
    stripped = (text or "").strip()
    if stripped[-1:] not in _COMPLETE_TOKEN_TAIL:
        return None
    if _prefix_opens_nothing(stripped, len(stripped)):
        return None  # nothing is left open; there is nothing to recover
    start = stripped.find("{")
    while start != -1:
        if _prefix_opens_nothing(stripped, start):
            if _closers_from(stripped, start) == "}":
                try:
                    obj = json.loads(stripped[start:] + "}",
                                     object_pairs_hook=_reject_duplicate_keys)
                except ValueError:
                    obj = None
                if isinstance(obj, dict):
                    return obj, "}"
        start = stripped.find("{", start + 1)
    return None


def _extract_contract_output(text, validate, kind=None):
    """Select by contract validity, never by an object's text position.

    Returns (validated_output, closers) — `closers` is None normally, or
    the delimiter run that recovered an unterminated envelope. Recovery is
    attempted only for RECOVERABLE_KINDS; every other kind behaves exactly
    as before."""
    matches = []
    errors = []
    unparseable = None
    try:
        candidates = extract_json_objects(text)
    except ValueError as exc:
        candidates = []
        unparseable = exc
    for obj in candidates:
        try:
            matches.append(validate(obj))
        except contracts.ContractError as exc:
            errors.append(str(exc))
    # The recovery candidate is weighed ALONGSIDE the complete ones, never
    # only after they fail: a worker that echoes a contract-shaped example
    # and then truncates its real answer would otherwise have the example
    # silently chosen over the answer. Two viable readings is exactly the
    # ambiguity the caller already refuses.
    recovered = None
    repaired = (
        _repair_unterminated(text) if kind in RECOVERABLE_KINDS else None
    )
    if repaired is not None:
        try:
            recovered = (validate(repaired[0]), repaired[1])
        except contracts.ContractError as exc:
            errors.append(str(exc))
    if len(matches) + (1 if recovered else 0) > 1:
        raise ValueError(
            "multiple JSON objects satisfy the worker contract; response is ambiguous"
        )
    if matches:
        return matches[0], None
    if recovered:
        return recovered
    if unparseable is not None and not errors:
        raise unparseable
    detail = "; ".join(errors) if errors else "no object candidate"
    raise contracts.ContractError("no JSON object satisfies the worker contract: " + detail)


# ---------------------------------------------------------------------------
# Subprocess runner

# Families whose CLI can spawn background, multi-turn "workflow"
# orchestration. That model is fundamentally incompatible with the
# orchestrator's one-shot contract: the worker fires an async workflow and
# returns an interim "I'll continue next turn" message — but a `-p` call
# has no next turn, so the process exits without the required JSON and the
# call fails as contract-violating. We force the feature OFF in the worker
# environment (claude reads CLAUDE_CODE_DISABLE_WORKFLOWS), so a claude
# worker CANNOT defer and must produce its result in the single call.
# Central and unbypassable: it does not depend on any config command,
# survives every stop/start/resume/relaunch, and applies to every claude
# call regardless of model or effort.
WORKFLOW_DISABLED_ENV = {"claude": {"CLAUDE_CODE_DISABLE_WORKFLOWS": "1"}}
_AMBIENT_EXECUTION = object()


def _worker_env(base_env, family):
    """Environment for a worker subprocess: the driver's environment plus
    any family-specific hardening (workflow disable). Returns None when
    there is nothing to add and no base override, so the child simply
    inherits — the historical behaviour for families with no override."""
    overrides = WORKFLOW_DISABLED_ENV.get(family)
    if not overrides:
        return base_env
    env = dict(base_env if base_env is not None else os.environ)
    env.update(overrides)
    return env


def _codex_session_ref(transport_text):
    """Read the explicit thread id from Codex's documented JSONL stream."""
    refs = []
    for line in (transport_text or "").splitlines():
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "thread.started":
            continue
        ref = event.get("thread_id")
        if isinstance(ref, str) and ref.strip() and ref not in refs:
            refs.append(ref)
    if len(refs) != 1:
        raise RunnerError(
            "codex session start did not expose exactly one thread id"
        )
    return refs[0]


def apply_model_effort(argv, model, effort):
    """Apply per-act model/effort to a command template.

    Preferred: {model}/{effort} placeholders in the template. Fallback for
    templates frozen before placeholders existed: replace the value right
    after a --model/--effort flag. Templates with neither (e.g. codex,
    whose model/effort live in its own config) ignore the overrides. A
    placeholder left without a value is a config error — passing the
    literal brace-string to a CLI would fail cryptically."""
    out = list(argv)
    for name, value in (("{model}", model), ("{effort}", effort)):
        if any(name in a for a in out):
            if not value:
                raise RunnerError(
                    "command template uses %s but no value was resolved "
                    "(set model_defaults for the family or the act)" % name
                )
            out = [a.replace(name, value) for a in out]
        elif value:
            flag = "--model" if name == "{model}" else "--effort"
            for i, a in enumerate(out[:-1]):
                if a == flag:
                    out[i + 1] = value
                    break
    return out


def _with_usage_output(family, template):
    """Ask supported CLIs for machine-readable usage metadata."""
    out = list(template)
    if family == "codex" and len(out) >= 2 and out[1] == "exec":
        if "--json" not in out:
            out.append("--json")
        return out
    if family != "claude" or not ("-p" in out or "--print" in out):
        return out
    for index, arg in enumerate(out):
        if (
            arg == "--output-format"
            and index + 1 < len(out)
            and out[index + 1] == "stream-json"
        ) or arg == "--output-format=stream-json":
            # stream-json already exposes the final result usage and may
            # carry stream-only flags used by the live/stall machinery.
            return out
    cleaned = []
    skip_value = False
    for arg in out:
        if skip_value:
            skip_value = False
            continue
        if arg == "--output-format":
            skip_value = True
            continue
        if arg.startswith("--output-format="):
            continue
        cleaned.append(arg)
    cleaned.extend(["--output-format", "json"])
    return cleaned


class SubprocessRunner(object):
    """Runs a family's configured command with the prompt on stdin.

    Command templates come from config["commands"][family] as an argv list.
    Supported placeholders in arguments:
      {workspace}    absolute workspace path
      {output_file}  a temp file; when present in the template, the runner
                     reads the last message from this file instead of stdout
                     (codex's --output-last-message pattern).
    """

    def __init__(self, commands, timeouts, cwd=None, env=None,
                 stall_window_s=None, stall_min_cpu_s=None,
                 participant_process_factory=None, prompt_recorder=None):
        self.commands = commands
        self.timeouts = timeouts or {}
        self.cwd = cwd
        self.env = env
        # Participant execution must apply the caller-resolved capability
        # bundle, not silently inherit this service process's authority.
        # The factory is the caller-owned pass-through seam: it receives the
        # exact opaque bundle plus the prepared argv/Popen kwargs and returns
        # the supervised process. Ordinary one-shot calls keep using Popen
        # directly and therefore remain byte-for-byte compatible.
        self.participant_process_factory = participant_process_factory
        if prompt_recorder is not None and not callable(prompt_recorder):
            raise RunnerError("prompt_recorder must be callable")
        # Optional caller-owned durable sink. It receives the exact stdin
        # prompt for EVERY physical CLI invocation (ordinary calls, explicit
        # session starts/continuations, repair retries, infrastructure retries,
        # reclassification, and error classification). The sink runs before a
        # worker is spawned: an unrecordable prompt is never sent to an LLM.
        self.prompt_recorder = prompt_recorder
        # Liveness watchdog: kill a worker whose whole process tree burns
        # less than stall_min_cpu_s of CPU over a stall_window_s window
        # (a frozen call — no local compute at all). Disabled when either
        # is unset/<=0, so MockRunner-based tests and unconfigured runs keep
        # exactly their current behavior. There is deliberately no hard wall
        # clock timeout: a legitimate multi-hour test suite keeps burning
        # CPU and is never touched; only a truly idle process is.
        # Coerced to float here so a malformed config value disables the
        # watchdog rather than raising mid-call and leaking the worker.
        self.stall_window_s = _positive_float(stall_window_s)
        self.stall_min_cpu_s = _positive_float(stall_min_cpu_s)
        # `codex exec resume --json` reports the thread's cumulative usage.
        # Keep its last total so continued calls expose only their delta.
        self._codex_session_usage = {}

    def _start_stall_watchdog(self, proc, family, done, state, kill_lock,
                              output_paths=()):
        """Watch the worker for a FROZEN window and SIGKILL it. Returns the
        watchdog thread, or None when the watchdog is disabled or its thread
        cannot start.

        `done` (an Event), `state` (a dict carrying "stalled"), and
        `kill_lock` are OWNED by the caller and created BEFORE this call: a
        caller interrupted after the thread starts can still set `done` and
        stop it, so the thread is never left armed with handles the caller
        cannot reach. The kill and the caller's reap both run under
        `kill_lock` with a `done` recheck, so they can never both signal the
        group — no join-timeout window in which the watchdog resumes and
        SIGKILLs a pgid the caller already reaped and let be recycled.

        Fail-open by construction: a window where a signal cannot be measured
        is treated as alive, never as a stall."""
        window = self.stall_window_s
        floor = self.stall_min_cpu_s
        if not window or not floor:
            return None
        output_paths = tuple(output_paths)

        def out_bytes():
            total = 0
            for p in output_paths:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
            return total

        def watch():
            # THREE liveness signals, because none alone is a reliable proxy
            # for "the worker is doing its job":
            #  (1) the tree's CPU sum grew by at least the floor this window;
            #  (2) the tree's PROCESS SET changed — a child appeared or exited
            #      (activity even when the live-process CPU sum FELL, e.g. an
            #      exited child whose CPU left the sum);
            #  (3) the worker produced OUTPUT (stdout / last-message file grew)
            #      — a slow token streamer burns little CPU but is working.
            # A stall is ONLY a stable process set AND sub-floor CPU AND no
            # new output. Residual, stated honestly: a worker fully idle while
            # a helper both spawns AND exits, producing nothing, inside one
            # window — negligible at the real 15-minute window.
            tree = group_cpu_by_pid(proc.pid)
            last_total = None if tree is None else sum(tree.values())
            last_pids = None if tree is None else frozenset(tree)
            last_out = out_bytes()
            while not done.wait(window):
                tree = group_cpu_by_pid(proc.pid)
                # `done` is set in the caller's finally AFTER communicate()
                # returns — which, with stderr piped, waits for the whole
                # group (not just the leader). So the watchdog covers the
                # ENTIRE call and never stops early on a bare leader exit.
                if done.is_set():
                    return
                cur_out = out_bytes()
                grew = cur_out > last_out
                last_out = cur_out
                if tree is None or last_total is None:
                    last_total = None if tree is None else sum(tree.values())
                    last_pids = None if tree is None else frozenset(tree)
                    continue  # can't measure CPU this window -> assume alive
                pids = frozenset(tree)
                cur_total = sum(tree.values())
                stalled = (
                    pids == last_pids
                    and (cur_total - last_total) < floor
                    and not grew
                )
                last_total = cur_total
                last_pids = pids
                if stalled:
                    # Recheck `done` and kill UNDER the lock: if the caller has
                    # begun its reap (set done, then sweeps under the same
                    # lock), we see done and skip — never SIGKILLing a pgid it
                    # already reaped and may have let be recycled. done unset
                    # here means the caller has not reached its finally, so the
                    # leader is still alive and its pgid is ours.
                    with kill_lock:
                        if done.is_set():
                            return
                        state["stalled"] = True
                        _kill_group(proc)
                    return

        t = threading.Thread(target=watch, name="stall-watchdog", daemon=True)
        try:
            t.start()
        except RuntimeError:
            # Thread creation failed (resource exhaustion): run WITHOUT a
            # watchdog rather than abort the call and orphan the worker.
            return None
        return t

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        if family not in self.commands:
            raise RunnerError("no command configured for family %r" % family)
        template = _with_usage_output(
            family,
            apply_model_effort(self.commands[family], model, effort),
        )
        return self._call_prepared(
            family, prompt, workspace, template, model, effort,
            timeout_override, _AMBIENT_EXECUTION, active_control,
        )

    def supports_session_continuation(self, family, ambient=False):
        """Whether the configured family has an explicit-reference CLI seam."""
        template = self.commands.get(family)
        if (
            not isinstance(template, list)
            or not template
            or (
                not ambient
                and not callable(self.participant_process_factory)
            )
        ):
            return False
        if family == "codex":
            return (
                len(template) >= 2
                and template[1] == "exec"
                and "--ephemeral" not in template
                and any(
                    arg == "--output-last-message"
                    and index + 1 < len(template)
                    and "{output_file}" in template[index + 1]
                    for index, arg in enumerate(template)
                )
            )
        if family == "claude":
            return (
                ("-p" in template or "--print" in template)
                and "--no-session-persistence" not in template
                and "--session-id" not in template
                and "--resume" not in template
                and "--continue" not in template
                and "-c" not in template
                and "-r" not in template
            )
        return False

    def start_session(
        self,
        family,
        prompt,
        workspace,
        execution_context=_AMBIENT_EXECUTION,
        model=None,
        effort=None,
        timeout_override=None,
        active_control=None,
    ):
        """Start one provider conversation and return its explicit reference."""
        try:
            if not self.supports_session_continuation(
                family, ambient=execution_context is _AMBIENT_EXECUTION
            ):
                raise RunnerError(
                    "family %r has no explicit session continuation support"
                    % family
                )
            template = apply_model_effort(
                self.commands[family], model, effort
            )
            template = _with_usage_output(family, template)
            if family == "codex":
                session_ref = None
            else:
                session_ref = str(uuid.uuid4())
                template = list(template) + ["--session-id", session_ref]
        except BaseException as exc:
            # No process factory has been called, so participant coordination
            # can safely reject and clear its exclusive attempt.
            try:
                exc.worker_quiescent = True
            except (AttributeError, TypeError):
                pass
            raise
        result = self._call_prepared(
            family, prompt, workspace, template, model, effort,
            timeout_override, execution_context, active_control,
            session_ref=session_ref, persist_session=True,
        )
        if isinstance(result, ControlledInterruptionResult):
            return result
        if family == "codex" and not getattr(result, "session_ref", None):
            try:
                result.session_ref = _codex_session_ref(
                    result.transport_text
                )
            except BaseException as exc:
                if getattr(result, "worker_quiescent", None) is True:
                    try:
                        exc.worker_quiescent = True
                    except (AttributeError, TypeError):
                        pass
                raise
        elif not getattr(result, "session_ref", None):
            result.session_ref = session_ref
        if family == "codex":
            usage = normalize_token_usage(
                getattr(result, "session_token_usage", None)
                or result.token_usage
            )
            if usage is not None:
                self._codex_session_usage[result.session_ref] = usage
        return result

    def continue_session(
        self,
        family,
        session_ref,
        prompt,
        workspace,
        execution_context=_AMBIENT_EXECUTION,
        model=None,
        effort=None,
        timeout_override=None,
        active_control=None,
    ):
        """Continue exactly ``session_ref``; there is no recency fallback."""
        try:
            if not isinstance(session_ref, str) or not session_ref.strip():
                raise RunnerError("session_ref must be a non-empty string")
            if not self.supports_session_continuation(
                family, ambient=execution_context is _AMBIENT_EXECUTION
            ):
                raise RunnerError(
                    "family %r has no explicit session continuation support"
                    % family
                )
            template = apply_model_effort(
                self.commands[family], model, effort
            )
            if family == "codex":
                template = list(template[:2]) + ["resume"] + list(template[2:])
                template = _with_usage_output(family, template)
                # `-` makes stdin the prompt explicitly; omitting it would
                # leave room for CLI recency/picker behavior in future versions.
                template.extend([session_ref, "-"])
            else:
                template = list(template) + ["--resume", session_ref]
                template = _with_usage_output(family, template)
        except BaseException as exc:
            # Validation and argv construction above occur before any worker
            # process can exist.
            try:
                exc.worker_quiescent = True
            except (AttributeError, TypeError):
                pass
            raise
        try:
            result = self._call_prepared(
                family, prompt, workspace, template, model, effort,
                timeout_override, execution_context, active_control,
                session_ref=session_ref, persist_session=True,
            )
        except ProviderResponseError as exc:
            if family == "codex":
                if getattr(exc, "token_usage_is_delta", False):
                    self._remember_codex_session_delta(session_ref, exc)
                else:
                    self._apply_codex_session_delta(session_ref, exc)
            raise
        if family == "codex":
            if getattr(result, "token_usage_is_delta", False):
                self._remember_codex_session_delta(session_ref, result)
            else:
                self._apply_codex_session_delta(session_ref, result)
        result.session_ref = session_ref
        return result

    def _apply_codex_session_delta(self, session_ref, outcome):
        cumulative = normalize_token_usage(
            getattr(outcome, "token_usage", None)
        )
        previous = self._codex_session_usage.get(session_ref)
        if cumulative is not None:
            self._codex_session_usage[session_ref] = cumulative
        outcome.session_token_usage = cumulative
        outcome.token_usage = subtract_token_usage(cumulative, previous)
        outcome.token_usage_partial = outcome.token_usage is None

    def _remember_codex_session_delta(self, session_ref, outcome):
        session_total = normalize_token_usage(
            getattr(outcome, "session_token_usage", None)
        )
        if session_total is not None:
            self._codex_session_usage[session_ref] = session_total
            return
        prior = self._codex_session_usage.get(session_ref)
        delta = normalize_token_usage(getattr(outcome, "token_usage", None))
        if prior is not None and delta is not None:
            self._codex_session_usage[session_ref] = add_token_usage(
                prior, delta
            )

    def seed_codex_session_usage(self, session_ref, cumulative):
        """Restore one durable Codex thread counter before a continuation."""
        usage = normalize_token_usage(cumulative)
        if isinstance(session_ref, str) and session_ref.strip() and usage:
            self._codex_session_usage[session_ref] = usage

    def _call_prepared(
        self, family, prompt, workspace, template, model, effort, timeout,
        execution_context, control, session_ref=None, persist_session=False,
    ):
        live_argv = (
            self._live_argv(family, template, session_ref=session_ref)
            if control else None
        )
        if live_argv:
            live_argv = [
                arg.replace("{workspace}", workspace) for arg in live_argv
            ]
            return self._call_live_transport(
                family, prompt, workspace, live_argv, template,
                model=model, effort=effort,
                timeout_override=timeout, execution_context=execution_context,
                active_control=control, session_ref=session_ref,
                persist_session=persist_session,
            )
        return self._call_template(
            family, prompt, workspace, template, timeout_override=timeout,
            execution_context=execution_context, active_control=control,
        )

    @staticmethod
    def _live_argv(family, template, session_ref=None):
        if not isinstance(template, list) or not template:
            return None
        if family == "codex" and len(template) >= 2 and template[1] == "exec":
            # app-server receives policy/cwd through its request schema, not
            # through `codex exec` flags. Use it only when every semantic
            # option is represented below; otherwise keep the configured CLI
            # command intact and retain hard-interrupt control without steer.
            if "--dangerously-bypass-approvals-and-sandbox" not in template:
                return None
            argv = [template[0], "app-server", "--stdio"]
            index = 2
            while index < len(template):
                arg = template[index]
                if arg in ("-c", "--config", "--enable", "--disable") \
                        and index + 1 < len(template):
                    argv.extend([arg, template[index + 1]])
                    index += 2
                    continue
                if arg == "--strict-config" or arg.startswith(
                    ("--config=", "--enable=", "--disable=")
                ):
                    argv.append(arg)
                    index += 1
                    continue
                if arg in ("-m", "--model", "--output-last-message") \
                        and index + 1 < len(template):
                    index += 2
                    continue
                if arg.startswith(("--model=", "--output-last-message=")) \
                        or arg in (
                            "--dangerously-bypass-approvals-and-sandbox",
                            "--json",
                            "resume",
                            "-",
                        ) \
                        or (session_ref is not None and arg == session_ref):
                    index += 1
                    continue
                return None
            return argv
        if family == "claude" and ("-p" in template or "--print" in template):
            argv = []
            skip_value = False
            for arg in template:
                if skip_value:
                    skip_value = False
                    continue
                if arg in ("--input-format", "--output-format"):
                    skip_value = True
                    continue
                if arg.startswith(("--input-format=", "--output-format=")) \
                        or arg == "--verbose":
                    continue
                argv.append(arg)
            argv.extend(["--input-format", "stream-json",
                         "--output-format", "stream-json", "--verbose"])
            return argv
        return None

    @staticmethod
    def _option_value(argv, *flags):
        for index, arg in enumerate(argv[:-1]):
            if arg in flags:
                return argv[index + 1]
        return None

    def _call_live_transport(
        self,
        family,
        prompt,
        workspace,
        argv,
        original_template,
        model=None,
        effort=None,
        timeout_override=None,
        execution_context=_AMBIENT_EXECUTION,
        active_control=None,
        session_ref=None,
        persist_session=False,
    ):
        timeout = timeout_override or self.timeouts.get(family)
        started = time.time()
        deadline = started + timeout if timeout else None
        proc = reader = watchdog = None
        tracked = cleaned = False
        quiescent = True
        raw, steer_paths = [], []
        events, eof, idle = queue.Queue(), object(), object()
        done, stalled, kill_lock, write_lock = (
            threading.Event(), {"stalled": False}, threading.Lock(),
            threading.Lock(),
        )
        out = err = None

        def record(text, steer=False):
            if self.prompt_recorder is None:
                return None
            try:
                path = self.prompt_recorder(family, text)
            except Exception as exc:
                label = " steer" if steer else ""
                raise RunnerError(
                    "could not persist the exact %s%s prompt: %s"
                    % (family, label, exc)
                )
            if steer:
                steer_paths.append(path)
            return path

        def send(message):
            line = json.dumps(message, separators=(",", ":")) + "\n"
            with write_lock:
                try:
                    if proc.poll() is not None:
                        return False
                    proc.stdin.write(line)
                    proc.stdin.flush()
                    return True
                except (BrokenPipeError, OSError, ValueError):
                    return False

        def receive():
            if deadline is not None and time.time() >= deadline:
                raise RunnerError(
                    "family %s timed out after %ss" % (family, timeout)
                )
            wait = min(0.2, max(0, deadline - time.time())) if deadline else 0.2
            try:
                item = events.get(timeout=wait)
                return None if item is eof else item
            except queue.Empty:
                # The process can exit a few microseconds before the reader
                # drains its last JSONL records.  Do not turn that ordinary
                # race into an incomplete provider result.
                if proc.poll() is not None \
                        and (reader is None or not reader.is_alive()):
                    return None
                return idle

        def read_stdout():
            try:
                for line in proc.stdout:
                    raw.append(line)
                    out.write(line)
                    out.flush()
                    try:
                        item = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        item = idle
                    events.put(item if isinstance(item, dict) else idle)
            finally:
                events.put(eof)

        def cleanup():
            nonlocal tracked, cleaned, quiescent
            if cleaned:
                return
            cleaned = True
            active_control._close()
            done.set()
            if proc is not None:
                try:
                    proc.stdin.close()
                except (OSError, ValueError):
                    pass
                with kill_lock:
                    _kill_group(proc)
                    try:
                        proc.wait(timeout=PS_SAMPLE_TIMEOUT)
                    except Exception:
                        pass
                    if tracked:
                        _untrack_worker(proc)
                        tracked = False
                    quiescent = _wait_for_process_group_quiescence(proc.pid)
                if reader is not None:
                    reader.join(timeout=PS_SAMPLE_TIMEOUT)
                if proc.stdout is not None:
                    try:
                        proc.stdout.close()
                    except (OSError, ValueError):
                        pass
            if watchdog is not None:
                watchdog.join(timeout=PS_SAMPLE_TIMEOUT)

        prompt_path = None
        try:
            prompt_path = record(prompt)
            out = tempfile.NamedTemporaryFile(
                mode="w+", encoding="utf-8", prefix="orch-live-", delete=False
            )
            err = tempfile.NamedTemporaryFile(
                mode="w+", encoding="utf-8", prefix="orch-live-err-",
                delete=False,
            )
            kwargs = dict(
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                cwd=self.cwd or workspace, env=_worker_env(self.env, family),
                start_new_session=True, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
            )
            quiescent = False
            try:
                proc = (
                    subprocess.Popen(argv, **kwargs)
                    if execution_context is _AMBIENT_EXECUTION
                    else self.participant_process_factory(
                        execution_context, argv, kwargs
                    )
                )
            except Exception as exc:
                raise RunnerError("failed to spawn %r: %s" % (argv[0], exc))
            _track_worker(proc)
            tracked = True
            reader = threading.Thread(
                target=read_stdout, name="worker-live-stdout", daemon=True
            )
            reader.start()
            watchdog = self._start_stall_watchdog(
                proc, family, done, stalled, kill_lock,
                output_paths=(out.name, err.name),
            )
            driver = (
                self._drive_codex_app_server
                if family == "codex" else self._drive_claude_stream
            )
            common = (active_control, proc, send,
                      lambda text: record(text, steer=True), receive, idle)
            args = (
                (prompt, workspace, original_template, model, effort,
                 session_ref, persist_session) + common
                if family == "codex" else (prompt, session_ref) + common
            )
            outcome = driver(*args)
            cleanup()
            err.flush()
            err.seek(0)
            diagnostics = err.read()
            text = outcome.get("text") or ""
            exit_code = 0 if outcome.get("ok", True) else 1
            provider_completed_ok = bool(
                outcome.get("complete") and outcome.get("ok")
            )
            if active_control.interrupted and not provider_completed_ok:
                result = ControlledInterruptionResult(
                    text, exit_code, time.time() - started,
                    active_control.interrupt_reason,
                    transport_text="".join(raw),
                    token_usage=outcome.get("token_usage"),
                )
                result.token_usage_partial = bool(
                    outcome.get(
                        "token_usage_partial",
                        outcome.get("token_usage") is None,
                    )
                )
            else:
                detail = outcome.get("error") or diagnostics[-500:]
                usage = normalize_token_usage(outcome.get("token_usage"))

                def with_usage(error):
                    error.token_usage = usage
                    error.token_usage_partial = bool(
                        outcome.get("token_usage_partial", usage is None)
                    )
                    error.session_token_usage = normalize_token_usage(
                        outcome.get("session_token_usage")
                    )
                    error.duration_s = time.time() - started
                    if family == "codex":
                        error.token_usage_is_delta = True
                    return error

                if stalled["stalled"] and not text.strip():
                    raise with_usage(
                        WorkerStalled("family %s stalled" % family)
                    )
                if not outcome.get("complete"):
                    raise with_usage(RunnerError(
                        "family %s live transport ended before a result: %s"
                        % (family, detail or "no provider result")
                    ))
                if exit_code:
                    raise with_usage(ProviderResponseError(
                        "family %s reported a provider failure: %s"
                        % (family, detail or "provider turn failed"),
                        raw_texts=["".join(raw) or text],
                        token_usage=usage,
                    ))
                result = RunnerResult(
                    text, exit_code, time.time() - started,
                    transport_text="".join(raw),
                    token_usage=outcome.get("token_usage"),
                )
                result.token_usage_partial = bool(
                    outcome.get(
                        "token_usage_partial",
                        outcome.get("token_usage") is None,
                    )
                )
            if family == "codex":
                result.token_usage_is_delta = True
                result.session_token_usage = normalize_token_usage(
                    outcome.get("session_token_usage")
                )
            result.prompt_path = prompt_path
            result.session_ref = None
            if persist_session or session_ref is not None:
                result.session_ref = outcome.get("session_ref") or session_ref
            result.steers = active_control.steers
            result.steer_prompt_paths = steer_paths
            if quiescent:
                result.worker_quiescent = True
            return result
        except BaseException as exc:
            cleanup()
            if proc is not None and getattr(exc, "duration_s", None) is None:
                try:
                    exc.duration_s = max(0.0, time.time() - started)
                except (AttributeError, TypeError):
                    pass
            if family in ("codex", "claude") \
                    and isinstance(exc, RunnerError):
                transport = "".join(raw)
                if transport:
                    exc.transport_text = transport
                    existing = getattr(exc, "raw_texts", None)
                    if isinstance(existing, (list, tuple)):
                        raw_texts = list(existing)
                    elif isinstance(existing, str) and existing:
                        raw_texts = [existing]
                    else:
                        raw_texts = []
                    if transport not in raw_texts:
                        raw_texts.append(transport)
                    exc.raw_texts = raw_texts
            if quiescent:
                try:
                    exc.worker_quiescent = True
                except (AttributeError, TypeError):
                    pass
            raise
        finally:
            cleanup()
            for handle in (out, err):
                if handle is not None:
                    path = handle.name
                    handle.close()
                    _unlink_quiet(path)

    @staticmethod
    def _drive_codex_app_server(
        prompt,
        workspace,
        template,
        model,
        effort,
        session_ref,
        persist_session,
        active_control,
        proc,
        send,
        record_steer,
        read_event,
        no_event,
    ):
        deferred_events = []

        def next_id():
            return str(uuid.uuid4())

        def request(method, params):
            ident = next_id()
            if not send({"id": ident, "method": method, "params": params}):
                raise RunnerError("codex app-server closed during %s" % method)
            while True:
                event = read_event()
                if event is no_event:
                    continue
                if event is None:
                    raise RunnerError(
                        "codex app-server exited during %s" % method
                    )
                if event.get("id") != ident:
                    deferred_events.append(event)
                    continue
                if "error" in event:
                    raise RunnerError(
                        "codex app-server %s failed: %s" % (method, event["error"])
                    )
                return event.get("result") or {}

        request(
            "initialize",
            {"clientInfo": {"name": "milestone-orchestrator", "version": "1"}},
        )
        send({"method": "initialized", "params": {}})
        requested_model = model or SubprocessRunner._option_value(
            template, "-m", "--model"
        )
        requested_effort = effort or SubprocessRunner._option_value(
            template, "--effort"
        )
        if requested_effort is None:
            requested_effort = next(
                (template[i + 1].split("=", 1)[1]
                 for i, arg in enumerate(template[:-1])
                 if arg in ("-c", "--config")
                 and template[i + 1].startswith("model_reasoning_effort=")),
                None,
            )
        common = dict(cwd=workspace, approvalPolicy="never",
                      sandbox="danger-full-access")
        if requested_model:
            common["model"] = requested_model
        method = "thread/resume" if session_ref else "thread/start"
        params = dict(common, **(
            {"threadId": session_ref} if session_ref
            else {"ephemeral": not persist_session}
        ))
        thread_id = (request(method, params).get("thread") or {}).get("id")
        thread_id = thread_id or session_ref
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise RunnerError("codex app-server did not expose a thread id")
        input_items = lambda text: [{"type": "text", "text": text}]
        turn_params = {
            "threadId": thread_id,
            "input": input_items(prompt),
            "cwd": workspace,
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "dangerFullAccess"},
        }
        if requested_model:
            turn_params["model"] = requested_model
        if requested_effort:
            turn_params["effort"] = requested_effort
        turn_id = (request("turn/start", turn_params).get("turn") or {}).get("id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            raise RunnerError("codex app-server did not expose a turn id")

        def steer(text):
            record_steer(text)
            ident = next_id()
            reply = queue.Queue(maxsize=1)
            with response_lock:
                pending_responses[ident] = reply
            params = dict(threadId=thread_id, expectedTurnId=turn_id,
                          input=input_items(text))
            if not send({"id": ident, "method": "turn/steer",
                         "params": params}):
                with response_lock:
                    pending_responses.pop(ident, None)
                return False
            deadline = time.monotonic() + 2
            while not active_control.closed and time.monotonic() < deadline:
                try:
                    response = reply.get(timeout=0.1)
                except queue.Empty:
                    continue
                return "error" not in response
            with response_lock:
                pending_responses.pop(ident, None)
            return False

        def interrupt(_reason):
            if not send({
                "id": next_id(), "method": "turn/interrupt",
                "params": {"threadId": thread_id, "turnId": turn_id},
            }):
                _kill_group(proc)
            return True

        pending_responses = {}
        response_lock = threading.Lock()
        active_control._bind(steer, interrupt)
        completed = None
        completed_final_messages = []
        completed_unphased_messages = []
        completed_commentary_messages = []
        token_usage = None
        snapshot_token_usage = None
        raw_response_seen = False
        raw_response_missing_usage = False
        session_token_usage = None
        stop_deadline = None
        while True:
            if active_control.interrupted:
                stop_deadline = stop_deadline or time.monotonic() + 3
                if time.monotonic() >= stop_deadline:
                    _kill_group(proc)
                    break
            event = deferred_events.pop(0) if deferred_events else read_event()
            if event is no_event:
                continue
            if event is None:
                break
            ident = event.get("id")
            if ident is not None:
                with response_lock:
                    reply = pending_responses.pop(ident, None)
                if reply is not None:
                    reply.put(event)
                    continue
            if event.get("method") == "item/completed":
                params = event.get("params") or {}
                if params.get("threadId") != thread_id \
                        or params.get("turnId") != turn_id:
                    continue
                item = params.get("item") or {}
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if item.get("type") == "agentMessage" \
                        and isinstance(text, str):
                    phase = item.get("phase")
                    if phase == "final_answer":
                        completed_final_messages.append(text)
                    elif phase == "commentary":
                        completed_commentary_messages.append(text)
                        active_control.observe_model_message(text)
                    else:
                        completed_unphased_messages.append(text)
                continue
            if event.get("method") == "thread/tokenUsage/updated":
                params = event.get("params") or {}
                if params.get("threadId") == thread_id:
                    provider_usage = params.get("tokenUsage") or {}
                    session_token_usage = normalize_token_usage(
                        provider_usage.get("total"), "codex"
                    )
                if params.get("threadId") == thread_id \
                        and params.get("turnId") == turn_id:
                    snapshot_token_usage = normalize_token_usage(
                        provider_usage.get("last"), "codex"
                    )
                continue
            if event.get("method") == "rawResponse/completed":
                params = event.get("params") or {}
                if params.get("threadId") == thread_id \
                        and params.get("turnId") == turn_id:
                    raw_response_seen = True
                    response_usage = normalize_token_usage(
                        params.get("usage"), "codex"
                    )
                    if response_usage is None:
                        raw_response_missing_usage = True
                    else:
                        token_usage = add_token_usage(
                            token_usage, response_usage
                        )
                continue
            if event.get("method") == "turn/completed":
                params = event.get("params") or {}
                candidate = params.get("turn") or {}
                if params.get("threadId") == thread_id \
                        and candidate.get("id") == turn_id:
                    completed = candidate
                    break
        turn = completed or {}
        fallback_items = turn.get("items") or []
        fallback_final = [
            item.get("text") for item in fallback_items
            if isinstance(item, dict) and item.get("type") == "agentMessage"
            and item.get("phase") == "final_answer"
            and isinstance(item.get("text"), str)
        ]
        fallback_unphased = [
            item.get("text") for item in fallback_items
            if isinstance(item, dict) and item.get("type") == "agentMessage"
            and item.get("phase") not in ("final_answer", "commentary")
            and isinstance(item.get("text"), str)
        ]
        fallback_commentary = [
            item.get("text") for item in fallback_items
            if isinstance(item, dict) and item.get("type") == "agentMessage"
            and item.get("phase") == "commentary"
            and isinstance(item.get("text"), str)
        ]
        texts = (
            completed_final_messages or fallback_final
            or completed_unphased_messages or fallback_unphased
            or completed_commentary_messages or fallback_commentary
        )
        if not raw_response_seen:
            token_usage = snapshot_token_usage
        return {
            "text": texts[-1] if texts else "",
            "session_ref": thread_id,
            "complete": completed is not None,
            "ok": turn.get("status") == "completed",
            "error": turn.get("error"),
            "token_usage": token_usage,
            "token_usage_partial": (
                raw_response_missing_usage
                if raw_response_seen else token_usage is None
            ),
            "session_token_usage": session_token_usage,
        }

    @staticmethod
    def _drive_claude_stream(
        prompt,
        session_ref,
        active_control,
        proc,
        send,
        record_steer,
        read_event,
        no_event,
    ):
        def user_message(text):
            content = [{"type": "text", "text": text}]
            return {"type": "user",
                    "message": {"role": "user", "content": content}}

        if not send(user_message(prompt)):
            raise RunnerError("claude stream closed before the initial prompt")

        def steer(text):
            record_steer(text)
            return send(user_message(text))

        active_control._bind(
            steer, lambda _reason: (_kill_group(proc) or True)
        )
        observed_session = session_ref
        while True:
            event = read_event()
            if event is no_event:
                continue
            if event is None:
                break
            if isinstance(event.get("session_id"), str):
                observed_session = event["session_id"]
            if event.get("type") == "assistant":
                message = event.get("message") or {}
                content = message.get("content") or []
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict) \
                                or block.get("type") != "text":
                            continue
                        active_control.observe_model_message(block.get("text"))
            if event.get("type") == "result":
                return {
                    "text": event.get("result") or "",
                    "session_ref": observed_session,
                    "complete": True,
                    "ok": not bool(event.get("is_error")),
                    "error": event.get("subtype"),
                    "token_usage": normalize_token_usage(
                        event.get("usage"), "claude"
                    ),
                }
        return {
            "text": "",
            "session_ref": observed_session,
            "complete": False,
            "ok": False,
            "error": None,
            "token_usage": None,
        }

    def _call_template(
        self,
        family,
        prompt,
        workspace,
        template,
        timeout_override=None,
        execution_context=_AMBIENT_EXECUTION,
        active_control=None,
    ):
        """Run one prepared argv through the shared supervised call path."""
        timeout = timeout_override or self.timeouts.get(family)
        started = time.time()

        output_file = None
        of_fd = None
        so_fd = stdout_path = None
        proc = None
        reaped = False
        worker_quiescent = True
        failure = None
        watchdog = None
        duration = None
        # OWNED here, before any thread starts, so an interrupt that lands
        # after the watchdog thread starts can still stop it (the finally sets
        # wd_done) — the thread is never left armed with unreachable handles.
        wd_done = threading.Event()
        wd_state = {"stalled": False}
        # Serializes the watchdog's kill with this call's reap so they can
        # never both signal the group. The caller sets wd_done, then sweeps
        # under this lock; the watchdog rechecks wd_done under it before
        # killing. A join-timeout can no longer let the watchdog resume and
        # kill a pgid the caller already reaped.
        kill_lock = threading.Lock()

        def _cleanup_files():
            if stdout_path:
                _unlink_quiet(stdout_path)
            if output_file:
                _unlink_quiet(output_file)

        def _reap(p):
            # SIGKILL the whole GROUP so no descendant is orphaned — including
            # an in-group helper that closed/redirected stderr and outlived the
            # leader (communicate() only waits on stderr-holding children) —
            # then WAIT (only if not already reaped) so the leader is not left
            # a zombie, and confirm that no group member can do more work
            # before exposing quiescence evidence. killpg targets the leader's
            # original pgid; while ANY member is alive it reserves that pgid,
            # so the signal reaches our group and only our group. Once every
            # member has exited the pgid is free and killpg returns ESRCH, a
            # no-op. The residual — the OS
            # having RECYCLED that freed pgid to an unrelated group in the
            # window before this killpg — cannot occur here: Linux and macOS
            # allocate pids from a rotating counter, so a just-freed pid is not
            # reissued until ~pid_max further spawns, never within the µs of a
            # reap. Orphaning a full-permission worker is the strictly worse
            # outcome, so we always sweep. Idempotent: a second _reap (an
            # interrupt between the call and reaped=True) re-kills a gone group
            # (ESRCH no-op), skips the already-done wait, and re-discards.
            # Best-effort: a cleanup path never re-raises. The kill+wait run
            # under kill_lock (paired with the watchdog's own kill); callers
            # MUST set wd_done before calling so a watchdog that takes the lock
            # after us observes done and skips its kill.
            with kill_lock:
                _kill_group(p)
                if p.returncode is None:
                    try:
                        p.communicate(timeout=PS_SAMPLE_TIMEOUT)
                    except Exception:
                        pass
                # This registry forwards a stop only to workers whose call is
                # still in flight. Once the final kill and leader wait have
                # run, retire the numeric pgid before the potentially slow
                # confirmation: retaining it could let a later stop signal an
                # unrelated group after identifier reuse.
                _untrack_worker(p)
                quiescent = _wait_for_process_group_quiescence(p.pid)
            return quiescent

        # ONE guard around the whole lifecycle. Any failure OR a
        # KeyboardInterrupt at ANY point — building argv (which may create
        # {output_file}), allocating the stdout temp, spawning, tracking, or
        # the gaps between — reaps a spawned worker (proc is not None) and,
        # in the finally, closes each parent temp FD (of_fd, so_fd) EXACTLY
        # once and deletes every temp file. The FDs are deliberately NOT
        # closed inline: a close-then-null is not atomic, so an interrupt in
        # that gap would leave the finally to close an FD number the OS may
        # have already recycled. Holding both (regular-file) FDs open for the
        # call's lifetime is harmless — the child holds its own dup of stdout,
        # and the worker opens {output_file} by path — so the finally is the
        # single close site. `reaped` skips a redundant second reap.
        # RESIDUAL, stated honestly: if an async exception lands INSIDE
        # subprocess.Popen after the child has exec'd but before __init__
        # returns, `proc` never binds and CPython neither kills nor returns
        # that child — it is orphaned to init. The only close for that window
        # is blocking signals across the fork, which is rejected: the child
        # inherits the blocked mask (verified), corrupting the worker's own
        # signal handling for a microsecond-wide, shutdown-only window.
        try:
            argv = []
            for arg in template:
                if "{output_file}" in arg:
                    if output_file is None:
                        # Held open until the outer finally closes it once;
                        # the worker opens {output_file} by path, not this fd.
                        of_fd, output_file = tempfile.mkstemp(
                            prefix="orch-last-", suffix=".txt"
                        )
                    arg = arg.replace("{output_file}", output_file)
                arg = arg.replace("{workspace}", workspace)
                argv.append(arg)

            prompt_path = None
            if self.prompt_recorder is not None:
                try:
                    prompt_path = self.prompt_recorder(family, prompt)
                except Exception as exc:
                    raise RunnerError(
                        "could not persist the exact %s prompt: %s"
                        % (family, exc)
                    )

            # stdout goes to a FILE, not a pipe, so the watchdog can watch it
            # grow as a liveness signal: a slow token streamer burns little
            # CPU but is working, and its bytes land here as they arrive. The
            # child dup's this fd; the parent's copy is closed once, in the
            # finally (harmless to hold open meanwhile — it is a regular file).
            so_fd, stdout_path = tempfile.mkstemp(
                prefix="orch-stdout-", suffix=".txt"
            )
            try:
                popen_kwargs = {
                    "stdin": subprocess.PIPE,
                    "stdout": so_fd,
                    "stderr": subprocess.PIPE,
                    "cwd": self.cwd or workspace,
                    "env": _worker_env(self.env, family),
                    "start_new_session": True,
                    "text": True,
                    "encoding": "utf-8",
                    "errors": "replace",
                }
                # Crossing either launch boundary means a worker may exist.
                # In particular, an opaque participant factory can spawn and
                # then raise without returning the process handle, so no
                # exception after entry may certify worker quiescence.
                worker_quiescent = False
                if execution_context is _AMBIENT_EXECUTION:
                    proc = subprocess.Popen(argv, **popen_kwargs)
                else:
                    proc = self.participant_process_factory(
                        execution_context, argv, popen_kwargs
                    )
            except Exception as exc:
                raise RunnerError("failed to spawn %r: %s" % (argv[0], exc))

            _track_worker(proc)
            if active_control is not None:
                active_control._bind(
                    lambda _text: False,
                    lambda _reason: (_kill_group(proc) or True),
                )
            try:
                # Start the watchdog INSIDE the try so a Thread.start()
                # failure cannot leak the tracked worker. wd_done/wd_state
                # are owned by call() (created above), so even if this
                # assignment is interrupted after the thread starts, the
                # finally still sets wd_done and stops it.
                watchdog = self._start_stall_watchdog(
                    proc, family, wd_done, wd_state, kill_lock,
                    output_paths=(
                        [stdout_path] + ([output_file] if output_file else [])
                    ),
                )
                try:
                    _, stderr = proc.communicate(input=prompt, timeout=timeout)
                except subprocess.TimeoutExpired:
                    _kill_group(proc)
                    proc.communicate()
                    raise RunnerError(
                        "family %s timed out after %ss" % (family, timeout)
                    )
            finally:
                # Order matters: set wd_done, THEN reap under kill_lock, THEN
                # join. Because the watchdog rechecks wd_done under the same
                # lock, a watchdog still past its own done check cannot kill
                # the group after we sweep it — the lock, not the (timed) join,
                # is what serializes them, so a slow-`ps` watchdog can no
                # longer resume and SIGKILL a reaped, recyclable pgid. The
                # sweep reaps any descendant the worker left running (holding
                # stdout, or having closed stderr); join then confirms the
                # daemon has exited.
                wd_done.set()
                worker_quiescent = _reap(proc)
                reaped = True
                if watchdog is not None:
                    watchdog.join(timeout=PS_SAMPLE_TIMEOUT)

            duration = time.time() - started
            try:
                with open(stdout_path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    stdout_text = fh.read()
            except OSError:
                stdout_text = ""
            text = stdout_text
            if output_file:
                try:
                    with open(output_file, "r", encoding="utf-8") as fh:
                        file_text = fh.read()
                    if file_text.strip():
                        text = file_text
                except OSError:
                    pass
            provider_text, token_usage = _provider_transport_result(
                family, stdout_text
            )
            if output_file is None and provider_text is not None:
                text = provider_text
            if active_control is not None and active_control.interrupted:
                result = ControlledInterruptionResult(
                    text,
                    proc.returncode,
                    duration,
                    active_control.interrupt_reason,
                    transport_text=stdout_text,
                    token_usage=token_usage,
                )
                if family == "codex":
                    result.session_token_usage = token_usage
                result.prompt_path = prompt_path
                result.steers = active_control.steers
                if worker_quiescent:
                    result.worker_quiescent = True
                return result
            # The watchdog sets "stalled" only after a full flat window, then
            # kills the group. Classify that as an auto-resumable stall
            # whenever the kill defined the outcome: the leader died by our
            # signal (returncode < 0), OR it had already exited (0 or an error
            # code) yet left no usable output — e.g. it exited early while a
            # frozen child held the stderr pipe open for a whole window, so
            # communicate() blocked and the watchdog killed the child while the
            # leader's returncode stayed 0. Only a stall that STILL produced
            # real output (the worker finished in the race between the last
            # sample and the SIGKILL) is honored rather than discarded.
            if (wd_state["stalled"]
                    and ((proc.returncode or 0) < 0
                         or not (text or "").strip())):
                raise WorkerStalled(
                    "family %s stalled: its process tree burned under %ss of "
                    "CPU over a %ss window (frozen worker)"
                    % (family, self.stall_min_cpu_s, self.stall_window_s)
                )
            if proc.returncode != 0 and not (text or "").strip():
                # Lead with the provider's own ERROR lines: codex buries
                # them under plugin WARN noise, which misled the operator
                # ("doesn't look like quota") and starved parse_resume_at
                # of a front-position window time (found live 2026-07-10).
                # The raw tail stays for forensics and pattern matching.
                stderr_text = stderr or ""
                errors = []
                for line in stderr_text.splitlines():
                    line = line.strip()
                    if line.upper().startswith("ERROR") and line not in errors:
                        errors.append(line)
                lead = ("; ".join(errors)[:400] + " | ") if errors else ""
                raise RunnerError(
                    "family %s exited %d with no output; %sstderr tail: %s"
                    % (family, proc.returncode, lead, stderr_text[-500:])
                )
            result = RunnerResult(
                text,
                proc.returncode,
                duration,
                transport_text=stdout_text,
                token_usage=token_usage,
            )
            if family == "codex":
                result.session_token_usage = token_usage
            result.prompt_path = prompt_path
            if active_control is not None:
                result.steers = active_control.steers
            # Ordered Brainstorming coordination consumes this positive
            # evidence before accepting a turn. Plain participant exchanges
            # retain the existing fail-open delivery posture when process
            # inspection is unavailable.
            if worker_quiescent:
                result.worker_quiescent = True
            return result
        except BaseException as exc:
            failure = exc
            if proc is not None and getattr(exc, "duration_s", None) is None:
                try:
                    exc.duration_s = (
                        duration if duration is not None
                        else max(0.0, time.time() - started)
                    )
                except (AttributeError, TypeError):
                    pass
            raise
        finally:
            if active_control is not None:
                active_control._close()
            # Single cleanup site, reached on EVERY exit. Set wd_done, then
            # reap a spawned-but-not-yet-reaped worker under kill_lock (so the
            # watchdog rechecking wd_done under the same lock never kills after
            # us), then join the daemon. `reaped` skips the redundant second
            # reap after the inner finally. Close each parent temp FD EXACTLY
            # once (never closed inline, so there is no close-then-null gap for
            # an interrupt to turn into a double-close of a recycled
            # descriptor); then delete the temp files.
            wd_done.set()
            if proc is not None and not reaped:
                worker_quiescent = _reap(proc)
            if watchdog is not None:
                watchdog.join(timeout=PS_SAMPLE_TIMEOUT)
            if failure is not None and worker_quiescent:
                # The exception is visible only after the same supervised
                # cleanup path has confirmed every admitted process quiet.
                # Pre-spawn failures also carry this evidence because no
                # worker process could exist.
                try:
                    failure.worker_quiescent = True
                except (AttributeError, TypeError):
                    pass
            for fd in (of_fd, so_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            _cleanup_files()


def _kill_group(proc):
    # Every worker is spawned with start_new_session=True, so its pgid ==
    # its pid. Kill by proc.pid DIRECTLY, not via os.getpgid(proc.pid):
    # getpgid raises once the leader is reaped, but the group lives on while
    # a lingering child holds it, and killpg still reaches that child.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Mock runner (tests)


class MockRunner(object):
    """Deterministic scripted runner.

    script: list of steps, each a dict:
      {"expect_kind": "<kind>",          # asserted against the prompt header
       "expect_family": "<family>",      # optional assertion
       "response": <dict or raw string>, # dict is json.dumps'ed
       "side_effect": callable(workspace) or None}
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = []  # (family, kind, prompt)
        self.call_meta = []  # {"family","kind","model","effort"} per call
        self.session_calls = []
        self._session_seq = 0

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None, active_control=None):
        kind = prompt_kind(prompt)
        self.calls.append((family, kind, prompt))
        self.call_meta.append(
            {"family": family, "kind": kind, "model": model,
             "effort": effort}
        )
        if not self.script:
            raise AssertionError(
                "MockRunner script exhausted; unexpected call family=%s kind=%s"
                % (family, kind)
            )
        step = self.script.pop(0)
        expect_kind = step.get("expect_kind")
        if expect_kind is not None and expect_kind != kind:
            raise AssertionError(
                "MockRunner expected kind %r, driver asked for %r"
                % (expect_kind, kind)
            )
        expect_family = step.get("expect_family")
        if expect_family is not None and expect_family != family:
            raise AssertionError(
                "MockRunner expected family %r, driver asked for %r"
                % (expect_family, family)
            )
        side_effect = step.get("side_effect")
        if side_effect is not None:
            side_effect(workspace)
        response = step["response"]
        if isinstance(response, dict):
            text = json.dumps(response)
        else:
            text = response
        return RunnerResult(text, 0, 0.01)

    def start_session(
        self,
        family,
        prompt,
        workspace,
        execution_context=_AMBIENT_EXECUTION,
        model=None,
        effort=None,
        timeout_override=None,
        active_control=None,
    ):
        self._session_seq += 1
        session_ref = "mock-session-%d" % self._session_seq
        self.session_calls.append(("start", family, session_ref))
        call_kwargs = {
            "model": model,
            "effort": effort,
            "timeout_override": timeout_override,
        }
        if active_control is not None:
            call_kwargs["active_control"] = active_control
        result = self.call(family, prompt, workspace, **call_kwargs)
        result.session_ref = session_ref
        return result

    def continue_session(
        self,
        family,
        session_ref,
        prompt,
        workspace,
        execution_context=_AMBIENT_EXECUTION,
        model=None,
        effort=None,
        timeout_override=None,
        active_control=None,
    ):
        if not isinstance(session_ref, str) or not session_ref.strip():
            raise RunnerError("session_ref must be a non-empty string")
        self.session_calls.append(("continue", family, session_ref))
        call_kwargs = {
            "model": model,
            "effort": effort,
            "timeout_override": timeout_override,
        }
        if active_control is not None:
            call_kwargs["active_control"] = active_control
        result = self.call(family, prompt, workspace, **call_kwargs)
        result.session_ref = session_ref
        return result


def prompt_kind(prompt):
    for line in prompt.splitlines():
        if line.startswith("KIND:"):
            return line.split(":", 1)[1].strip()
    return None


def save_prompt_trace(directory, family, prompt, label=None):
    """Persist one exact LLM stdin prompt as an immutable runtime artifact.

    The caller chooses an already-ignored runtime directory. A readable label
    is useful for pairing the prompt with milestone activity, but uniqueness
    never depends on it: O_EXCL plus a numeric suffix preserves every retry,
    repair, resume, and repeated label without overwriting history.
    """
    if not isinstance(prompt, str):
        raise RunnerError("prompt trace requires text")

    def safe(value, fallback):
        rendered = "".join(
            char
            if (char.isascii() and (char.isalnum() or char in "._-"))
            else "_"
            for char in str(value or "")
        ).strip("._-")
        return (rendered[:96] or fallback)

    os.makedirs(directory, exist_ok=True)
    family_part = safe(family, "family")
    kind_part = safe(prompt_kind(prompt), "prompt")
    label_part = safe(label, str(time.time_ns()))
    stem = "%s-%s-%s" % (label_part, family_part, kind_part)
    candidate = stem
    counter = 1
    while True:
        path = os.path.join(directory, candidate + ".txt")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            break
        except FileExistsError:
            counter += 1
            candidate = "%s-%d" % (stem, counter)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(prompt.encode("utf-8"))
    except BaseException:
        _unlink_quiet(path)
        raise
    return path


# ---------------------------------------------------------------------------
# Validated worker call with one repair retry


REPAIR_SUFFIX = (
    "\n\nREPAIR: your previous output was not a valid JSON object satisfying "
    "the OUTPUT CONTRACT (error: %s). Respond again with EXACTLY ONE valid "
    "JSON object and nothing else."
)


def _note_recovery(result, closers):
    """Record a delimiter recovery on the result so it cannot pass silently.

    The output WAS malformed and the operator must keep seeing that — the
    model dropping its closing brace is a real defect worth tracking. What
    changes is only the price: no retry is spent and no completed review is
    discarded."""
    if not closers:
        return
    result.recovered = {
        "error": "unterminated JSON object: recovered by appending %r "
                 "(no repair retry spent)" % closers,
        "raw_text": result.text,
        "closers": closers,
    }


def _attach_call_accounting(exc, *results):
    """Keep completed provider cost on a post-call validation failure."""
    usages = [getattr(result, "token_usage", None) for result in results]
    durations = [
        result.duration_s for result in results
        if isinstance(getattr(result, "duration_s", None), (int, float))
        and not isinstance(result.duration_s, bool)
    ]
    exc.token_usage = add_token_usage(*usages)
    exc.token_usage_partial = any(
        getattr(result, "token_usage_partial", False) or usage is None
        for result, usage in zip(results, usages)
    )
    if durations:
        exc.duration_s = sum(durations)


def call_worker(runner, family, prompt, kind, workspace,
                model=None, effort=None, extensions=None, roots=None,
                validate_opts=None, start_session=False, session_ref=None,
                execution_context=_AMBIENT_EXECUTION,
                active_control=None):
    """Run the CLI and return (validated_output, RunnerResult).

    Exactly one repair retry on contract violation; then
    WorkerProtocolError. RunnerError passes through untouched.

    extensions/roots (optional): the in-scope compiled project contract
    extensions (verifiers.CompiledExtension) and the granted work-area
    roots. Absent or empty, validation is exactly the base kind contract —
    unchanged behavior. Supplied, the merged validation runs at the same
    point and raises the same ContractError family, so a failed extension
    check is repaired (once) exactly like a malformed base contract; the
    extension layer's policy-config and operational faults are NOT part of
    the repairable exception family and propagate without a retry (they
    are never the worker's fault).

    validate_opts (optional): extra validation kwargs threaded into both
    validation paths (require_plain, battery_questions — the reform's
    plain/example hard-require and question battery). A battery/plain
    violation is worker-repairable and costs the single repair retry,
    exactly like a malformed base contract.
    """
    opts = dict(validate_opts or {})
    if start_session and session_ref is not None:
        raise RunnerError(
            "a worker call cannot both start and continue a session"
        )
    if extensions:
        from . import verifiers

        def _validate(obj):
            return verifiers.validate_merged_output(
                obj, kind, extensions, roots, **opts
            )
    else:
        def _validate(obj):
            return contracts.validate_worker_output(obj, kind, **opts)

    def diagnostic_text(result):
        """Keep app-server evidence when the selected final text is empty."""
        text = result.text
        if isinstance(text, str) and text.strip():
            return text
        transport = getattr(result, "transport_text", None)
        return transport if isinstance(transport, str) and transport else text

    def invoke(call_prompt, continuation_ref=None,
               call_control=active_control):
        def compatible_call(method, *args):
            kwargs = {"model": model, "effort": effort}
            accepts_control = False
            if call_control is not None:
                try:
                    signature = inspect.signature(method)
                    parameters = signature.parameters.values()
                    accepts_control = (
                        "active_control" in signature.parameters
                        or any(
                            parameter.kind == inspect.Parameter.VAR_KEYWORD
                            for parameter in parameters
                        )
                    )
                except (TypeError, ValueError):
                    accepts_control = False
                if accepts_control:
                    kwargs["active_control"] = call_control
            try:
                return method(*args, **kwargs)
            finally:
                if call_control is not None and not accepts_control:
                    # Historical injected runners remain valid. They cannot
                    # be steered live, but the driver's post-call hard-size
                    # check still enforces the boundary.
                    call_control._close()
        if continuation_ref is not None:
            continuation = getattr(runner, "continue_session", None)
            if not callable(continuation):
                raise RunnerError(
                    "the runner cannot continue an explicit provider session"
                )
            return compatible_call(
                continuation,
                family,
                continuation_ref,
                call_prompt,
                workspace,
                execution_context,
            )
        if start_session:
            starter = getattr(runner, "start_session", None)
            support = getattr(runner, "supports_session_continuation", None)
            if callable(support):
                try:
                    supported = support(family, ambient=True)
                except TypeError:
                    supported = support(family)
                if not supported:
                    return compatible_call(
                        runner.call,
                        family,
                        call_prompt,
                        workspace,
                    )
            if callable(starter):
                return compatible_call(
                    starter,
                    family,
                    call_prompt,
                    workspace,
                    execution_context,
                )
        return compatible_call(
            runner.call, family, call_prompt, workspace
        )

    result = invoke(prompt, continuation_ref=session_ref)
    if isinstance(result, ControlledInterruptionResult):
        return None, result
    try:
        validated, closers = _extract_contract_output(
            result.text, _validate, kind
        )
        _note_recovery(result, closers)
        return validated, result
    except (ValueError, contracts.ContractError) as exc:
        first_error = str(exc)
    except BaseException as exc:
        if extensions and isinstance(exc, verifiers.VerifierError):
            _attach_call_accounting(exc, result)
        raise
    repair_prompt = prompt + (REPAIR_SUFFIX % first_error)
    repair_ref = getattr(result, "session_ref", None) or session_ref
    repair_control = (
        active_control.renew() if active_control is not None else None
    )
    try:
        result2 = invoke(
            repair_prompt,
            continuation_ref=repair_ref,
            call_control=repair_control,
        )
    except RunnerError as exc:
        raw_texts = [diagnostic_text(result)]
        existing = getattr(exc, "raw_texts", None)
        if isinstance(existing, (list, tuple)):
            raw_texts.extend(existing)
        elif isinstance(existing, str) and existing:
            raw_texts.append(existing)
        else:
            second = getattr(exc, "transport_text", None)
            if not isinstance(second, str) or not second:
                second = getattr(exc, "raw_text", None)
            if isinstance(second, str) and second:
                raw_texts.append(second)
        exc.raw_texts = raw_texts
        first_usage = normalize_token_usage(result.token_usage)
        repair_usage = normalize_token_usage(
            getattr(exc, "token_usage", None)
        )
        exc.token_usage = add_token_usage(first_usage, repair_usage)
        first_duration = getattr(result, "duration_s", None)
        repair_duration = getattr(exc, "duration_s", None)
        if isinstance(first_duration, (int, float)) \
                and not isinstance(first_duration, bool):
            exc.duration_s = first_duration + (
                repair_duration
                if isinstance(repair_duration, (int, float))
                and not isinstance(repair_duration, bool)
                else 0
            )
        exc.token_usage_partial = bool(
            getattr(exc, "token_usage_partial", False)
            or first_usage is None
            or repair_usage is None
        )
        raise
    if isinstance(result2, ControlledInterruptionResult):
        result2.repair = {
            "error": first_error,
            "raw_text": diagnostic_text(result),
            "duration_s": result.duration_s,
            "token_usage": result.token_usage,
            "token_usage_partial": bool(
                getattr(result, "token_usage_partial", False)
                or result.token_usage is None
            ),
        }
        return None, result2
    try:
        validated, closers = _extract_contract_output(
            result2.text, _validate, kind
        )
        _note_recovery(result2, closers)
        # A repaired first strike must not stay invisible: hand the caller
        # what the worker actually returned (prompt/contract tuning needs
        # the malformed text and its cost, not just the happy ending).
        result2.repair = {
            "error": first_error,
            "raw_text": diagnostic_text(result),
            "duration_s": result.duration_s,
            "token_usage": result.token_usage,
            "token_usage_partial": bool(
                getattr(result, "token_usage_partial", False)
                or result.token_usage is None
            ),
        }
        return validated, result2
    except (ValueError, contracts.ContractError) as exc:
        token_usage = add_token_usage(result.token_usage, result2.token_usage)
        raise WorkerProtocolError(
            "family %s produced contract-violating output twice for kind %s: "
            "first error: %s; second error: %s"
            % (family, kind, first_error, exc),
            raw_texts=[diagnostic_text(result), diagnostic_text(result2)],
            duration_s=result.duration_s + result2.duration_s,
            token_usage=token_usage,
            token_usage_partial=(
                result.token_usage is None or result2.token_usage is None
            ),
        )
    except BaseException as exc:
        if extensions and isinstance(exc, verifiers.VerifierError):
            _attach_call_accounting(exc, result, result2)
        raise


# ---------------------------------------------------------------------------
# Workspace snapshot (structural "unchanged artifact" enforcement)

# Runtime/bookkeeping dirs plus well-known Python tool caches: report-only
# reviewers may base claims on tests/command output, and those legitimately
# write tool caches. Entries are directory names or
# fnmatch patterns. Operators can extend the set per run via the
# "snapshot_exclude_dirs" config key (driver plumbs it here).
SNAPSHOT_EXCLUDE_DIRS = {
    ".git",
    ".orchestrator",
    ".run",  # per-milestone runtime dir (state, raw, operator files)
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".hypothesis",
    ".tox",
    "*.egg-info",
}


def _dir_excluded(name, patterns):
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def _readlink_quiet(path):
    try:
        return os.readlink(path)
    except OSError:
        return "?"


def _hash_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return "unreadable"
    return "file %s" % h.hexdigest()


def _walk_entries(workspace, root, exclude, entries):
    """Fold a filesystem walk of `root` into `entries`, keyed by paths
    relative to `workspace` (walk-mode coverage: files, dirs, symlinks)."""
    for r, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not _dir_excluded(d, exclude))
        for name in dirs:
            path = os.path.join(r, name)
            rel = os.path.relpath(path, workspace)
            if os.path.islink(path):
                entries[rel] = "link -> %s" % _readlink_quiet(path)
            else:
                entries[rel] = "dir"
        for name in sorted(files):
            path = os.path.join(r, name)
            rel = os.path.relpath(path, workspace)
            if os.path.islink(path):
                entries[rel] = "link -> %s" % _readlink_quiet(path)
            else:
                entries[rel] = _hash_file(path)


def snapshot_workspace(workspace, extra_exclude=None, paths=None):
    """Map of workspace entries -> content descriptors (the tamper check).

    Used to enforce mechanically that report-only workers edit nothing.
    Snapshots compare with ==; snapshot_changes() names the paths that differ.

    Two universes:
    - paths=None (git-disabled runs): raw filesystem walk. Every entry
      contributes: file contents, directories (a new empty directory is
      detected), symlink targets (a new or retargeted symlink, broken or
      not, is detected), and unreadable files (recorded as existing even
      though their content cannot be hashed).
    - paths=<relative paths> (git-enabled runs; gitops.snapshot_paths):
      only those paths are hashed — tracked plus untracked-non-ignored —
      so build artifacts and caches that .gitignore excludes cannot
      invalidate a report-only call that ran the project's own tooling.
      A listed path missing from disk is recorded as such, so deletions
      of tracked files are still detected.
    """
    exclude = set(SNAPSHOT_EXCLUDE_DIRS)
    if extra_exclude:
        exclude.update(extra_exclude)
    entries = {}
    if paths is not None:
        for rel in paths:
            rel = rel.rstrip("/")
            parts = rel.split("/")
            # Exclusion patterns are DIRECTORY patterns (walk-mode
            # semantics): they never drop a plain file by its basename —
            # a tracked file named like a cache dir (x.egg-info) stays in
            # the universe.
            if any(_dir_excluded(part, exclude) for part in parts[:-1]):
                continue
            path = os.path.join(workspace, rel)
            if os.path.islink(path):
                entries[rel] = "link -> %s" % _readlink_quiet(path)
            elif os.path.isdir(path):
                # A directory entry (submodule gitlink or an untracked
                # nested repository, which ls-files reports as one bare
                # path). A constant marker would blind the tamper check
                # to everything inside it, so fold a full walk of the
                # subtree into the snapshot — same coverage the legacy
                # walk had.
                if _dir_excluded(parts[-1], exclude):
                    continue
                entries[rel] = "dir"
                _walk_entries(workspace, path, exclude, entries)
            elif os.path.exists(path):
                entries[rel] = _hash_file(path)
            else:
                entries[rel] = "missing"
        # The ignore surface git consults is part of the universe too:
        # otherwise a report-only worker could append a rule to
        # .git/info/exclude and plant files the after-listing omits.
        # (Residual, accepted: a NEW nested .gitignore containing '*'
        # cloaks itself and its directory; such plants stay git-invisible
        # everywhere — they can never reach a diff, commit, or seal.)
        info_exclude = os.path.join(workspace, ".git", "info", "exclude")
        if os.path.isfile(info_exclude):
            entries[".git/info/exclude"] = _hash_file(info_exclude)
        return entries
    _walk_entries(workspace, workspace, exclude, entries)
    return entries


def snapshot_changes(before, after):
    """Sorted relative paths whose snapshot entries differ (added, removed,
    or content-changed)."""
    keys = set(before) | set(after)
    return sorted(k for k in keys if before.get(k) != after.get(k))


def format_changes(changed, limit=8):
    """Human-readable summary of a snapshot diff for failure/invalidation
    records — the exact paths are what turns a tamper verdict from a
    mystery into a diagnosis."""
    if not changed:
        return "no visible changes"
    if len(changed) == 1 and changed[0].startswith("("):
        # Sentinel evidence (e.g. a mid-call snapshot-mode flip), not a
        # path: render it verbatim instead of dressing it as a file.
        return changed[0]
    head = ", ".join(changed[:limit])
    more = len(changed) - limit
    return "files: %s%s" % (head, " (+%d more)" % more if more > 0 else "")
