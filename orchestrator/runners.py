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
import time

from . import contracts


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

    def call(self, family, prompt, workspace):
        if family not in self.commands:
            raise RunnerError("no command configured for family %r" % family)
        template = self.commands[family]
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

        timeout = self.timeouts.get(family)
        started = time.time()
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd or workspace,
                env=self.env,
                start_new_session=True,
                text=True,
            )
        except OSError as exc:
            if output_file:
                _unlink_quiet(output_file)
            raise RunnerError("failed to spawn %r: %s" % (argv[0], exc))
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

    def call(self, family, prompt, workspace):
        kind = prompt_kind(prompt)
        self.calls.append((family, kind, prompt))
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


def call_worker(runner, family, prompt, kind, workspace):
    """Run the CLI and return (validated_output, RunnerResult).

    Exactly one repair retry on contract violation; then
    WorkerProtocolError. RunnerError passes through untouched.
    """
    result = runner.call(family, prompt, workspace)
    try:
        obj = extract_json(result.text)
        return contracts.validate_worker_output(obj, kind), result
    except (ValueError, contracts.ContractError) as exc:
        first_error = str(exc)
    repair_prompt = prompt + (REPAIR_SUFFIX % first_error)
    result2 = runner.call(family, repair_prompt, workspace)
    try:
        obj = extract_json(result2.text)
        return contracts.validate_worker_output(obj, kind), result2
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


def snapshot_workspace(workspace, extra_exclude=None):
    """Content digest of the workspace tree (excluding runtime dirs).

    Used to enforce, mechanically, that seal halves do not edit anything and
    that both halves reviewed the same artifact. Every filesystem entry
    contributes to the digest: file contents, directories (so a new empty
    directory is detected), symlink targets (so a new or retargeted symlink,
    broken or not, is detected), and unreadable files (recorded as existing
    even though their content cannot be hashed).
    """
    exclude = set(SNAPSHOT_EXCLUDE_DIRS)
    if extra_exclude:
        exclude.update(extra_exclude)
    entries = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if not _dir_excluded(d, exclude))
        for name in dirs:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, workspace)
            if os.path.islink(path):
                entries.append("link %s -> %s" % (rel, _readlink_quiet(path)))
            else:
                entries.append("dir %s" % rel)
        for name in sorted(files):
            path = os.path.join(root, name)
            rel = os.path.relpath(path, workspace)
            if os.path.islink(path):
                entries.append("link %s -> %s" % (rel, _readlink_quiet(path)))
                continue
            h = hashlib.sha256()
            try:
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
            except OSError:
                entries.append("unreadable %s" % rel)
                continue
            entries.append("file %s %s" % (h.hexdigest(), rel))
    entries.sort()
    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return digest
