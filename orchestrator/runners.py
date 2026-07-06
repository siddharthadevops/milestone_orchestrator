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
import os
import signal
import subprocess
import tempfile
import threading
import time

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


class WorkerProtocolError(RuntimeError):
    """The CLI ran but its output violates the JSON contract even after the
    repair retry. Carries the raw output texts of both attempts so the
    driver can persist them for the operator."""

    def __init__(self, message, raw_texts=None):
        RuntimeError.__init__(self, message)
        self.raw_texts = list(raw_texts or [])


class RunnerResult(object):
    def __init__(self, text, exit_code, duration_s):
        self.text = text
        self.exit_code = exit_code
        self.duration_s = duration_s


# ---------------------------------------------------------------------------
# JSON extraction


def extract_json(text):
    """Extract the first complete JSON object from text.

    Accepts: a bare JSON object; an object wrapped in ```json fences; an
    object surrounded by stray prose. Raises ValueError when no valid object
    can be found. Never uses regex heuristics over findings prose — this is
    the structural replacement for the old VERDICT-line parser.
    """
    if text is None:
        raise ValueError("no output text")
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    # Fenced block
    if "```" in stripped:
        parts = stripped.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    # Balanced-brace scan from each '{'
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
                            return json.loads(candidate)
                        except json.JSONDecodeError:
                            break
        start = stripped.find("{", start + 1)
    raise ValueError("no valid JSON object found in worker output")


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

    def __init__(self, commands, timeouts, cwd=None, env=None):
        self.commands = commands
        self.timeouts = timeouts or {}
        self.cwd = cwd
        self.env = env

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None):
        if family not in self.commands:
            raise RunnerError("no command configured for family %r" % family)
        template = apply_model_effort(self.commands[family], model, effort)
        output_file = None
        argv = []
        for arg in template:
            if "{output_file}" in arg:
                if output_file is None:
                    fd, output_file = tempfile.mkstemp(
                        prefix="orch-last-", suffix=".txt"
                    )
                    os.close(fd)
                arg = arg.replace("{output_file}", output_file)
            arg = arg.replace("{workspace}", workspace)
            argv.append(arg)

        timeout = timeout_override or self.timeouts.get(family)
        started = time.time()
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd or workspace,
                env=_worker_env(self.env, family),
                start_new_session=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            if output_file:
                _unlink_quiet(output_file)
            raise RunnerError("failed to spawn %r: %s" % (argv[0], exc))
        _track_worker(proc)
        try:
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                stdout, stderr = proc.communicate()
                if output_file:
                    _unlink_quiet(output_file)
                raise RunnerError(
                    "family %s timed out after %ss" % (family, timeout)
                )
        finally:
            _untrack_worker(proc)
        duration = time.time() - started
        text = stdout
        if output_file:
            try:
                with open(output_file, "r", encoding="utf-8") as fh:
                    file_text = fh.read()
                if file_text.strip():
                    text = file_text
            finally:
                _unlink_quiet(output_file)
        if proc.returncode != 0 and not (text or "").strip():
            raise RunnerError(
                "family %s exited %d with no output; stderr tail: %s"
                % (family, proc.returncode, (stderr or "")[-500:])
            )
        return RunnerResult(text, proc.returncode, duration)


def _kill_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
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


def call_worker(runner, family, prompt, kind, workspace,
                model=None, effort=None, extensions=None, roots=None):
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
    """
    if extensions:
        from . import verifiers

        def _validate(obj):
            return verifiers.validate_merged_output(
                obj, kind, extensions, roots
            )
    else:
        def _validate(obj):
            return contracts.validate_worker_output(obj, kind)

    result = runner.call(family, prompt, workspace, model=model, effort=effort)
    try:
        obj = extract_json(result.text)
        return _validate(obj), result
    except (ValueError, contracts.ContractError) as exc:
        first_error = str(exc)
    repair_prompt = prompt + (REPAIR_SUFFIX % first_error)
    result2 = runner.call(family, repair_prompt, workspace, model=model, effort=effort)
    try:
        obj = extract_json(result2.text)
        return _validate(obj), result2
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
