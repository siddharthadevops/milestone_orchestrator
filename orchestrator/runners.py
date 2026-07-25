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
import json
import math
import os
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


class WorkerProtocolError(RuntimeError):
    """The CLI ran but its output violates the JSON contract even after the
    repair retry. Carries the raw output texts of both attempts so the
    driver can persist them for the operator."""

    def __init__(self, message, raw_texts=None):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])


class RunnerResult(object):
    def __init__(self, text, exit_code, duration_s, transport_text=None):
        self.text = text
        self.exit_code = exit_code
        self.duration_s = duration_s
        # stdout before {output_file} selection. Session-capable Codex calls
        # emit their explicit thread id here while keeping the final answer in
        # the historical last-message file.
        self.transport_text = text if transport_text is None else transport_text


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
RECOVERABLE_KINDS = frozenset({contracts.KIND_REVIEW_ROUND,
                               contracts.KIND_SEAL_HALF})


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
                 participant_process_factory=None):
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
             timeout_override=None):
        if family not in self.commands:
            raise RunnerError("no command configured for family %r" % family)
        template = apply_model_effort(self.commands[family], model, effort)
        return self._call_template(
            family,
            prompt,
            workspace,
            template,
            timeout_override=timeout_override,
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
            if family == "codex":
                if "--json" not in template:
                    template = list(template) + ["--json"]
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
        if family == "codex":
            result = self._call_template(
                family,
                prompt,
                workspace,
                template,
                timeout_override=timeout_override,
                execution_context=execution_context,
            )
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
            return result

        result = self._call_template(
            family,
            prompt,
            workspace,
            template,
            timeout_override=timeout_override,
            execution_context=execution_context,
        )
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
                if "--json" not in template:
                    template.append("--json")
                # `-` makes stdin the prompt explicitly; omitting it would
                # leave room for CLI recency/picker behavior in future versions.
                template.extend([session_ref, "-"])
            else:
                template = list(template) + ["--resume", session_ref]
        except BaseException as exc:
            # Validation and argv construction above occur before any worker
            # process can exist.
            try:
                exc.worker_quiescent = True
            except (AttributeError, TypeError):
                pass
            raise
        result = self._call_template(
            family,
            prompt,
            workspace,
            template,
            timeout_override=timeout_override,
            execution_context=execution_context,
        )
        result.session_ref = session_ref
        return result

    def _call_template(
        self,
        family,
        prompt,
        workspace,
        template,
        timeout_override=None,
        execution_context=_AMBIENT_EXECUTION,
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
            )
            # Ordered Brainstorming coordination consumes this positive
            # evidence before accepting a turn. Plain participant exchanges
            # retain the existing fail-open delivery posture when process
            # inspection is unavailable.
            if worker_quiescent:
                result.worker_quiescent = True
            return result
        except BaseException as exc:
            failure = exc
            raise
        finally:
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
             timeout_override=None):
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
    ):
        self._session_seq += 1
        session_ref = "mock-session-%d" % self._session_seq
        self.session_calls.append(("start", family, session_ref))
        result = self.call(
            family,
            prompt,
            workspace,
            model=model,
            effort=effort,
            timeout_override=timeout_override,
        )
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
    ):
        if not isinstance(session_ref, str) or not session_ref.strip():
            raise RunnerError("session_ref must be a non-empty string")
        self.session_calls.append(("continue", family, session_ref))
        result = self.call(
            family,
            prompt,
            workspace,
            model=model,
            effort=effort,
            timeout_override=timeout_override,
        )
        result.session_ref = session_ref
        return result


def prompt_kind(prompt):
    for line in prompt.splitlines():
        if line.startswith("KIND:"):
            return line.split(":", 1)[1].strip()
    return None


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


def call_worker(runner, family, prompt, kind, workspace,
                model=None, effort=None, extensions=None, roots=None,
                validate_opts=None, start_session=False, session_ref=None,
                execution_context=_AMBIENT_EXECUTION):
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

    def invoke(call_prompt, continuation_ref=None):
        if continuation_ref is not None:
            continuation = getattr(runner, "continue_session", None)
            if not callable(continuation):
                raise RunnerError(
                    "the runner cannot continue an explicit provider session"
                )
            return continuation(
                family,
                continuation_ref,
                call_prompt,
                workspace,
                execution_context,
                model=model,
                effort=effort,
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
                    return runner.call(
                        family,
                        call_prompt,
                        workspace,
                        model=model,
                        effort=effort,
                    )
            if callable(starter):
                return starter(
                    family,
                    call_prompt,
                    workspace,
                    execution_context,
                    model=model,
                    effort=effort,
                )
        return runner.call(
            family, call_prompt, workspace, model=model, effort=effort
        )

    result = invoke(prompt, continuation_ref=session_ref)
    try:
        validated, closers = _extract_contract_output(
            result.text, _validate, kind
        )
        _note_recovery(result, closers)
        return validated, result
    except (ValueError, contracts.ContractError) as exc:
        first_error = str(exc)
    repair_prompt = prompt + (REPAIR_SUFFIX % first_error)
    repair_ref = getattr(result, "session_ref", None) or session_ref
    result2 = invoke(repair_prompt, continuation_ref=repair_ref)
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
            "raw_text": result.text,
            "duration_s": result.duration_s,
        }
        return validated, result2
    except (ValueError, contracts.ContractError) as exc:
        raise WorkerProtocolError(
            "family %s produced contract-violating output twice for kind %s: "
            "first error: %s; second error: %s"
            % (family, kind, first_error, exc),
            raw_texts=[result.text, result2.text],
        )


# ---------------------------------------------------------------------------
# Workspace snapshot (structural "unchanged artifact" enforcement)

# Runtime/bookkeeping dirs plus well-known Python tool caches: read-only
# seal halves are instructed to base claims on tests/command output, and
# those legitimately write tool caches. Entries are directory names or
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

    Used to enforce, mechanically, that report-only workers edit nothing
    and that both seal halves reviewed the same artifact. Snapshots
    compare with ==; snapshot_changes() names the paths that differ.

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
