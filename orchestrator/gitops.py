"""Git choreography for the driver.

Two jobs, both structural:

1. Gate commits — the canon's "commit the sealed unit" rule, executed by
   code: every sealed unit becomes a commit with a canonical message, and
   closing the milestone commits the final generated ledgers.

2. The amend discipline that powers the review/fix loop: each unit opens
   with a wip commit of its draft; every green fix episode AMENDS that
   commit (one clean commit per unit, no patch stacking); the seal reviews
   that amended commit and a passing seal finalizes it with the canonical
   gate message. HEAD is therefore always "the last accepted state", and
   the pending fix delta is exactly `git diff HEAD` (with intent-to-add so
   new files show). Report-only phases run on a clean worktree, so a
   tampering reviewer is both detectable AND revertible (restore_clean).

`.orchestrator/` is force-ignored so runtime bookkeeping (state, raw worker
outputs, fake counters) never pollutes diffs or gate commits.
"""

import os
import subprocess

from . import runners

GIT_TIMEOUT = 60
IGNORE_LINE = ".orchestrator/"
DIFF_MAX_CHARS = 24000
TRUNCATION_MARKER = "\n[... diff truncated by the driver: review the files directly ...]\n"

# Local-config marker: the index baseline has been seeded for this repo.
# ensure_repo() must stage the "everything present = reviewed" baseline
# exactly ONCE; re-staging on a later Driver construction (a `step`-driven
# run, a service stop/start, crash resume) would silently advance the
# reviewed-point index past a pending un-micro-reviewed delta.
BASELINE_MARK = "orchestrator.baselined"

# Environment overrides that redirect git to ANOTHER repository. A leaked
# GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE would make every command here
# read and write a FOREIGN repo while the workspace-root ownership check
# still passes — the exact enclosing-repo pollution _assert_workspace_root
# exists to prevent. Every git subprocess runs with these scrubbed.
_FOREIGN_REPO_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)


class GitError(RuntimeError):
    """A git invocation failed; the driver fails the run with this text."""


def enabled(config):
    return bool((config.get("git") or {}).get("enabled"))


def _scrubbed_env():
    env = dict(os.environ)
    for var in _FOREIGN_REPO_ENV:
        env.pop(var, None)
    return env


def _run(workspace, *args, check=True):
    try:
        proc = subprocess.run(
            ("git",) + args,
            cwd=workspace,
            capture_output=True,
            text=True,
            errors="surrogateescape",
            timeout=GIT_TIMEOUT,
            env=_scrubbed_env(),
        )
    except OSError as exc:
        raise GitError("git not runnable: %s" % exc)
    except subprocess.TimeoutExpired:
        raise GitError("git %s timed out after %ss" % (" ".join(args), GIT_TIMEOUT))
    if check and proc.returncode != 0:
        raise GitError(
            "git %s failed (%d): %s"
            % (" ".join(args), proc.returncode, (proc.stderr or proc.stdout)[-800:])
        )
    return proc


def _has_head(workspace):
    return _run(workspace, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


def _toplevel(workspace):
    proc = _run(workspace, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        return None
    return os.path.realpath(proc.stdout.strip())


def _git_dir(workspace):
    proc = _run(workspace, "rev-parse", "--absolute-git-dir", check=False)
    if proc.returncode != 0:
        return None
    return os.path.realpath(proc.stdout.strip())


def _is_own_repo(workspace):
    """The workspace is the root of its OWN repository: the worktree
    toplevel is the workspace AND the git directory actually lives inside
    it as `<workspace>/.git`. The second half matters: a `.git` gitdir-link
    file (the layout `git worktree add` produces, which a full-permission
    worker could create) satisfies the toplevel check alone while every
    staged file and gate commit would land in the LINKED foreign repo."""
    real_ws = os.path.realpath(workspace)
    top = _toplevel(workspace)
    if top is None or top != real_ws:
        return False
    return _git_dir(workspace) == os.path.join(real_ws, ".git")


def is_repo_root(workspace):
    """Public check: is this directory the root of its own git repo?"""
    return _is_own_repo(workspace)


def _assert_workspace_root(workspace):
    """Refuse to mutate unless the workspace is the root of its OWN repo.

    Without this, a workspace nested inside another repository (a project
    subdirectory, a monorepo, this very canon repo during its own demo)
    would silently adopt the PARENT repo: `git add -A` stages the whole
    enclosing tree and a gate commit swallows foreign files. That must be
    a hard failure, never a foreign commit."""
    if not _is_own_repo(workspace):
        raise GitError(
            "workspace %s is not the root of its own git repository "
            "(toplevel: %s); refusing to stage or commit into an enclosing "
            "repo" % (workspace, _toplevel(workspace) or "none")
        )


def _declared_submodule_paths(workspace):
    """Submodule paths declared in .gitmodules (an intentional gitlink is
    a correct representation; an undeclared nested repo is content loss)."""
    modfile = os.path.join(workspace, ".gitmodules")
    if not os.path.exists(modfile):
        return set()
    proc = _run(
        workspace,
        "config",
        "--file",
        modfile,
        "--get-regexp",
        r"submodule\..*\.path",
        check=False,
    )
    paths = set()
    for line in proc.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip():
            paths.add(os.path.normpath(parts[1].strip()))
    return paths


def _embedded_repo_paths(workspace):
    """Relative paths of nested git repos below the workspace root that are
    not declared submodules. `git add -A` records such a repo as a bare
    gitlink pointer (mode 160000) — or, before its first commit, not at
    all — so its actual content would be silently absent from micro-review
    diffs and gate commits: the gate would "seal" content that is neither
    committed nor reviewable from the sealed history."""
    declared = _declared_submodule_paths(workspace)
    hits = []
    for root, dirs, files in os.walk(workspace):
        rel = os.path.relpath(root, workspace)
        if rel == ".":
            # The workspace's own repo and runtime bookkeeping are fine.
            dirs[:] = [d for d in dirs if d not in (".git", ".orchestrator")]
            continue
        if ".git" in dirs or ".git" in files:
            dirs[:] = []  # never descend into a nested repo
            if os.path.normpath(rel) in declared:
                continue
            # A gitignored nested repo (e.g. a tool cache that pulled
            # sources from VCS inside .tox/) can never be staged; only
            # repos `add -A` would actually swallow as a pointer count.
            ignored = _run(workspace, "check-ignore", "-q", rel, check=False)
            if ignored.returncode == 0:
                continue
            hits.append(rel)
    return sorted(hits)


def _assert_no_embedded_repos(workspace):
    hits = _embedded_repo_paths(workspace)
    if hits:
        raise GitError(
            "nested git repository inside the workspace: %s; staging would "
            "record only a bare submodule pointer (mode 160000) and the "
            "actual content would be silently absent from gate commits; "
            "remove the nested .git or declare a proper submodule"
            % ", ".join(hits)
        )


def ignore_lines(extra_dirs=None):
    """The workspace .gitignore entries: runtime bookkeeping plus the same
    tool-cache set workspace snapshots exclude (SNAPSHOT_EXCLUDE_DIRS and
    the operator's snapshot_exclude_dirs config), so cache files written by
    verification runs and workers neither enter micro-review diffs as
    un-reviewable binary noise nor get committed into gate commits."""
    lines = [IGNORE_LINE]
    cache_dirs = sorted(runners.SNAPSHOT_EXCLUDE_DIRS - {".git", ".orchestrator"})
    for name in cache_dirs + sorted(set(extra_dirs or [])):
        line = name if name.endswith("/") else name + "/"
        if line not in lines:
            lines.append(line)
    return lines


def ensure_repo(workspace, extra_ignore_dirs=None):
    """Idempotently make the workspace a usable gate repo.

    - REQUIRES the workspace to already be the ROOT of its own git
      repository — no auto-init, no adopting an enclosing repo: the
      operator creates the ledger repo deliberately (git init). A `.git`
      entry that does not resolve to the workspace's own repository (a
      gitdir link into a foreign repo, a corrupt repo) is likewise a hard
      failure.
    - A local committer identity when none is configured (gate commits must
      never fail over a missing global git config).
    - `.orchestrator/` and the tool-cache set in .gitignore (created or
      appended); see ignore_lines().
    - ONCE per repo (marked in local git config), the index baseline:
      everything currently present is staged as the initial reviewed
      point; a fresh repo also gets its baseline commit so HEAD exists
      before the first gate. A pre-existing own-root repo (even dirty) is
      adopted as-is: its worktree becomes the reviewed baseline, nothing
      is committed until the first gate. Later constructions (a
      `step`-driven run, a service stop/start, crash resume) must NOT
      re-stage: the index is the last REVIEWED point, and re-baselining
      would silently mark a pending un-micro-reviewed delta as reviewed.
    """
    if not _is_own_repo(workspace):
        dot_git = os.path.join(workspace, ".git")
        if os.path.lexists(dot_git):
            raise GitError(
                "workspace %s has a .git entry that does not resolve to its "
                "own repository (git dir: %s); refusing to initialize or "
                "operate through it" % (workspace, _git_dir(workspace) or "none")
            )
        # Deliberately NO auto `git init`: the gate ledger must land in a
        # repository the operator created on purpose. Auto-initializing is
        # how run history ends up in the wrong place when a path is
        # mistyped or a parent directory gets picked by accident.
        raise GitError(
            "workspace %s is not the root of a git repository; create the "
            "ledger repo deliberately first (git -C %s init) or pick the "
            "right directory" % (workspace, workspace)
        )
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    for key, value in (
        ("user.name", "impl-roadmap-orchestrator"),
        ("user.email", "orchestrator@impl-roadmap.local"),
    ):
        probe = _run(workspace, "config", "--get", key, check=False)
        if probe.returncode != 0 or not probe.stdout.strip():
            _run(workspace, "config", key, value)
    gitignore = os.path.join(workspace, ".gitignore")
    try:
        with open(gitignore, "r", encoding="utf-8") as fh:
            lines = [l.strip() for l in fh.read().splitlines()]
    except OSError:
        lines = []
    present = {l.rstrip("/") for l in lines if l}
    missing = [
        l for l in ignore_lines(extra_ignore_dirs) if l.rstrip("/") not in present
    ]
    if missing:
        with open(gitignore, "a", encoding="utf-8") as fh:
            if lines and lines[-1] != "":
                fh.write("\n")
            fh.write("\n".join(missing) + "\n")
    baselined = _run(
        workspace, "config", "--local", "--get", BASELINE_MARK, check=False
    )
    if baselined.returncode != 0:
        _run(workspace, "add", "-A")
        if not _has_head(workspace):
            if _run(workspace, "diff", "--cached", "--quiet", check=False).returncode != 0:
                _run(workspace, "commit", "-q", "-m", "Initialize milestone workspace")
            else:
                _run(
                    workspace,
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "Initialize milestone workspace",
                )
        _run(workspace, "config", "--local", BASELINE_MARK, "true")


def snapshot_paths(workspace):
    """Relative paths of everything the repository can see: tracked files
    plus untracked files that are NOT ignored. This is the tamper-check
    universe when git is enabled — build artifacts and caches excluded by
    .gitignore never enter it, so a report-only worker that runs the
    project's build or test commands is not invalidated by artifact churn.
    Deleted tracked files stay in the list (the snapshot records them as
    missing, so deletions are still detected)."""
    _assert_workspace_root(workspace)
    proc = _run(
        workspace, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
    )
    return sorted({rel for rel in proc.stdout.split("\0") if rel})


def worktree_diff(workspace, max_chars=DIFF_MAX_CHARS):
    """The pending (not yet amended) delta: worktree vs HEAD, including new
    files.

    `git add -N` (intent-to-add, honors .gitignore) makes untracked files
    appear in `git diff` without treating them as reviewed.
    `--ignore-removal` is essential: a bare `add -N .` follows Git 2.0
    "add = add -A" pathspec semantics for removed paths and would STAGE
    the removal of a deleted tracked file outright — the deletion would
    vanish from the unreviewed delta and the reviewed-point index would
    silently advance without any micro-review pass. With it, deletions
    stay worktree-only and show up in the diff like every other change."""
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    _run(workspace, "add", "-N", "--ignore-removal", ".", check=False)
    proc = _run(workspace, "diff", "--no-ext-diff", "--no-color", "HEAD")
    text = proc.stdout
    if len(text) > max_chars:
        return text[:max_chars] + TRUNCATION_MARKER
    return text


def has_pending_delta(workspace):
    _assert_workspace_root(workspace)
    _run(workspace, "add", "-N", "--ignore-removal", ".", check=False)
    return _run(workspace, "diff", "--quiet", "HEAD", check=False).returncode != 0


def commit_wip(workspace, message):
    """Open a unit's working commit (its draft). Returns the short sha."""
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    _run(workspace, "add", "-A")
    _run(workspace, "commit", "-q", "--allow-empty", "-m", message)
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()


def amend(workspace):
    """Fold the current worktree into the unit's working commit (a green
    fix episode). Keeps the message. Returns the short sha."""
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    _run(workspace, "add", "-A")
    _run(workspace, "commit", "-q", "--amend", "--no-edit", "--allow-empty")
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()


def finalize_gate(workspace, message):
    """Seal passed: fold the generated ledgers into the unit's commit and
    retitle it with the canonical gate message. Returns the short sha."""
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    _run(workspace, "add", "-A")
    _run(workspace, "commit", "-q", "--amend", "--allow-empty", "-m", message)
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()


def commit_plain(workspace, message):
    """A plain commit (milestone close). Returns short sha, or None when
    there is nothing to commit."""
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    _run(workspace, "add", "-A")
    if _run(workspace, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    _run(workspace, "commit", "-q", "-m", message)
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()


def restore_clean(workspace):
    """Revert the worktree to HEAD (the last accepted state): the recovery
    path when a report-only reviewer tampered with a clean worktree.
    `git clean -fd` honors .gitignore, so .orchestrator/ survives."""
    _assert_workspace_root(workspace)
    _run(workspace, "reset", "-q", "--hard", "HEAD")
    _run(workspace, "clean", "-fdq")


def head_sha(workspace):
    if not _has_head(workspace):
        return None
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()
