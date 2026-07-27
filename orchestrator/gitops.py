"""Git choreography for the driver.

Two jobs, both structural:

1. Gate commits — the canon's "commit the sealed unit" rule, executed by
   code: every sealed unit becomes a commit with a canonical message, and
   closing the milestone commits the final generated ledgers.

2. The amend discipline that powers the review/fix loop: each unit opens
   with a wip commit of its draft; every green fix episode AMENDS that
   commit (one clean commit per unit, no patch stacking). Any changed bytes
   restart whole-artifact review from the first family. Once every family is
   clean or debt-clean on those same bytes and verification passes, the
   deterministic seal result finalizes the commit with the canonical gate
   message. HEAD is therefore always "the last accepted state", and the
   pending fix delta is exactly `git diff HEAD` (with intent-to-add so new
   files show). Report-only phases run on a clean worktree, so a tampering
   reviewer is both detectable AND revertible (restore_clean).

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
            # `-c core.hooksPath=/dev/null` disables ALL repo hooks for every
            # orchestrator git command: a command-line -c outranks any config
            # or env, so a builder that installs .git/hooks/pre-commit or sets
            # core.hooksPath cannot make the orchestrator's own commits (wip,
            # amend, gate) execute its code. The orchestrator never has a
            # legitimate use for a repo hook.
            ("git", "-c", "core.hooksPath=/dev/null") + args,
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


def ratify_note_correction(workspace, artifact, base, message):
    """Insert a note-only ratification commit beneath the implementation WIP.

    The pending tree contains both the corrected note and implementation
    fixes.  The note needs its own clean gate so a later implementation unwind
    keeps the correction without keeping unfinished code.
    """
    _assert_workspace_root(workspace)
    _assert_no_embedded_repos(workspace)
    original = head_full_sha(workspace)
    original_index = snapshot_index_tree(workspace)
    full_tree = None
    try:
        parent = _run(workspace, "rev-parse", "HEAD^").stdout.strip()
        expected = _run(
            workspace, "rev-parse", "%s^{commit}" % base
        ).stdout.strip()
        if parent != expected:
            raise GitError(
                "the implementation WIP is not based on the note gate"
            )
        _run(workspace, "add", "-A")
        full_tree = _run(workspace, "write-tree").stdout.strip()
        _run(workspace, "reset", "--hard", parent)
        _run(workspace, "checkout", full_tree, "--", artifact)
        _run(workspace, "commit", "-q", "-m", message)
        note_sha = head_sha(workspace)
        _run(workspace, "read-tree", "-u", "--reset", full_tree)
        _run(workspace, "commit", "-q", "--allow-empty", "-C", original)
        return note_sha, head_sha(workspace)
    except GitError:
        try:
            if full_tree is not None:
                _run(workspace, "reset", "--hard", original, check=False)
                _run(
                    workspace, "read-tree", "-u", "--reset", full_tree,
                    check=False,
                )
            _run(workspace, "read-tree", original_index, check=False)
        except GitError:
            pass
        raise


def finalize_gate(workspace, message):
    """Seal predicate satisfied: fold the generated ledgers into the unit's
    commit and retitle it with the canonical gate message. Returns the short
    sha."""
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


def has_builder_edits(workspace):
    """True when the worktree diverges from the INDEX — unstaged edits to
    tracked files or untracked (non-ignored) files. This is exactly a
    worker's scratch work: the staged reviewed baseline (index) is excluded,
    so an adopted repo's pre-run edits do not read as builder edits. Unlike
    worktree_diff / has_pending_delta it does NOT stage anything (no
    intent-to-add). Staged-only changes are invisible here — pair it with a
    snapshot_index_tree comparison to catch a worker that `git add`ed."""
    _assert_workspace_root(workspace)
    if _run(workspace, "diff", "--quiet", check=False).returncode != 0:
        return True
    others = _run(
        workspace, "ls-files", "--others", "--exclude-standard", "-z"
    ).stdout
    return bool(others.replace("\0", "").strip())


def head_symbolic_ref(workspace):
    """The branch HEAD points at, e.g. "refs/heads/main", or "" when HEAD is
    detached. Part of the pre-call snapshot: a worker that switches branches
    must be put back on its original one, not have whatever branch it left us
    on reset to the saved sha."""
    _assert_workspace_root(workspace)
    proc = _run(workspace, "symbolic-ref", "-q", "HEAD", check=False)
    return proc.stdout.strip()


def snapshot_refs(workspace):
    """A {refname: sha} map of EVERY ref under refs/ — branches, tags, the
    stash, notes, anything a worker could move, delete, or create — the
    pre-call ref map. Capturing ALL of them (not just heads/tags) means
    restore_to_snapshot fully undoes a worker's ref surgery: moved or deleted
    refs (e.g. a popped/cleared stash) are put back, worker-created refs are
    removed. HEAD is not under refs/ and is snapshotted separately."""
    _assert_workspace_root(workspace)
    proc = _run(
        workspace, "for-each-ref", "--format=%(objectname) %(refname)",
    )
    refs = {}
    for line in proc.stdout.splitlines():
        sha, _, refname = line.strip().partition(" ")
        if refname:
            refs[refname] = sha
    return refs


def head_full_sha(workspace):
    """The FULL (unabbreviated) sha HEAD points at — the pre-call commit tip.
    Distinct from head_sha (which returns a short sha for display): the
    snapshot needs a full sha so restore_to_snapshot's update-ref is never
    ambiguous. Pair with head_symbolic_ref, snapshot_index_tree and
    restore_to_snapshot to undo everything a worker did, including commits or
    ref moves it made itself."""
    _assert_workspace_root(workspace)
    return _run(workspace, "rev-parse", "HEAD").stdout.strip()


def snapshot_index_tree(workspace):
    """The tree sha of the current index — a cheap handle on the reviewed
    baseline BEFORE a worker runs (index == HEAD, or an adopted repo's staged
    pre-run edits). Pair with head_sha + restore_to_snapshot to undo a
    worker's changes even if it staged them."""
    _assert_workspace_root(workspace)
    return _run(workspace, "write-tree").stdout.strip()


def snapshot_worktree_tree(workspace):
    """Tree object for the current worktree without advancing the index."""
    original_index = snapshot_index_tree(workspace)
    try:
        _run(workspace, "add", "-A")
        return _run(workspace, "write-tree").stdout.strip()
    finally:
        _run(workspace, "read-tree", original_index, check=False)


def restore_index_tree(workspace, tree):
    """Restore only the index; leave the worktree bytes untouched."""
    _assert_workspace_root(workspace)
    _run(workspace, "read-tree", tree)


def snapshot_stash(workspace):
    """The stash STACK as a list of [sha, message] entries (newest first),
    read from the refs/stash reflog. The stash is a reflog-backed stack, so
    its ref tip alone (snapshot_refs) does not capture the older entries a
    `git stash clear` or repeated `git stash pop` would drop. Best-effort:
    an empty list when there is no stash."""
    _assert_workspace_root(workspace)
    proc = _run(
        workspace, "reflog", "refs/stash", "--format=%H%x09%gs", check=False
    )
    entries = []
    for line in proc.stdout.splitlines():
        sha, _, msg = line.partition("\t")
        if sha.strip():
            entries.append([sha.strip(), msg])
    return entries


def _restore_stash(workspace, stash):
    """Rebuild the stash stack to `stash` (from snapshot_stash) when it
    diverged — clear the reflog and replay oldest-first via `git stash store`,
    so a worker's `git stash clear`/pop is undone and its new stashes removed.
    Compares by sha, so identical stacks are a no-op."""
    current = [e[0] for e in snapshot_stash(workspace)]
    if current == [e[0] for e in stash]:
        return
    _run(workspace, "stash", "clear", check=False)
    for sha, msg in reversed(stash):
        _run(workspace, "stash", "store", "-m", msg or "restored", sha,
             check=False)


def restore_to_snapshot(workspace, refs, sym, head, tree, stash=None):
    """Restore the repo to a pre-call snapshot, undoing EVERYTHING a worker
    could have touched locally:
      - the ref map (`refs`): moved or deleted branches/tags are put back to
        their recorded shas, and any ref the worker created is deleted;
      - HEAD's IDENTITY (`sym`: the original branch, or detached when "");
      - the index AND worktree (`tree`: the reviewed baseline, staged but
        uncommitted on the first unit), then untracked files are removed.
    So staged, committed, ref-moved, branch-switched, branch-deleted, or
    new-branch junk is all discarded, while an adopted repo's staged pre-run
    edits (captured in `tree`) survive. `stash` (from snapshot_stash) rebuilds
    the full stash STACK — the ref map only carries its tip, so without this a
    worker's `git stash clear`/pop would drop older entries. `clean -ffd` also
    removes a builder-created NESTED repo (plain -fd refuses one); it honors
    .gitignore, so .orchestrator/ survives."""
    _assert_workspace_root(workspace)
    now = snapshot_refs(workspace)
    # Restore moved/deleted refs to their recorded shas (update-ref creates a
    # missing ref), then delete refs the worker created.
    for refname, sha in refs.items():
        if now.get(refname) != sha:
            _run(workspace, "update-ref", refname, sha)
    for refname in now:
        if refname not in refs:
            _run(workspace, "update-ref", "-d", refname)
    if sym:
        # Re-point HEAD at the original branch (its sha was restored above).
        _run(workspace, "symbolic-ref", "HEAD", sym)
    else:
        # HEAD was detached: set HEAD itself back to `head` (re-detaching if
        # the worker had checked out a branch).
        _run(workspace, "update-ref", "--no-deref", "HEAD", head)
    _run(workspace, "read-tree", "-u", "--reset", tree)
    _run(workspace, "clean", "-ffdq")
    # The stash reflog stack (its tip was handled by the ref map above, but the
    # older entries live only in the reflog); rebuild it last.
    if stash is not None:
        _restore_stash(workspace, stash)


def newest_commit(workspace, shas):
    """The descendant-most commit among `shas` (short sha), or None when
    none can be resolved. The driver's history is linear (single branch,
    amend discipline), so rev-list order is containment order: the first
    commit listed from the given tips is the one every other given sha
    is an ancestor of. Used by the sealed-artifact guard to pick the
    run's LAST gate commit as its canonical baseline."""
    shas = [s for s in shas if s]
    if not shas:
        return None
    _assert_workspace_root(workspace)
    try:
        proc = subprocess.run(
            # --topo-order: children strictly before parents. Plain
            # rev-list sorts by commit timestamp, and gates created
            # within the same second would tie-break arbitrarily.
            ("git", "rev-list", "--max-count=1", "--topo-order",
             "--abbrev-commit") + tuple(shas),
            cwd=workspace,
            capture_output=True,
            timeout=GIT_TIMEOUT,
            env=_scrubbed_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.decode("ascii", "replace").strip()
    return out or None


def reset_hard(workspace, revspec):
    """Hard-reset the current branch to `revspec` (a commit sha), discarding
    every commit and working-tree change after it. Used to unwind a fixer-gap
    reporter's abandoned slice (its draft wip + uncommitted fix edits) back to
    the last sealed baseline before a re-documentation wave commits, so the
    abandoned work never becomes the wave's parent. Raises GitError on
    failure — the caller fails the run rather than proceed on a dirty tree."""
    _assert_workspace_root(workspace)
    _run(workspace, "reset", "--hard", revspec)
    return head_full_sha(workspace)


def show_file(workspace, rev, relpath):
    """The file's BYTES at `rev` (e.g. a unit's gate commit), or None
    when the rev or path cannot be read. Byte-exact on purpose: the
    sealed-artifact guard compares a sealed unit's artifact against its
    own gate commit, and a text/encoding round-trip could mask (or
    invent) a violation."""
    _assert_workspace_root(workspace)
    try:
        proc = subprocess.run(
            ("git", "show", "%s:%s" % (rev, relpath)),
            cwd=workspace,
            capture_output=True,
            timeout=GIT_TIMEOUT,
            env=_scrubbed_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def head_sha(workspace):
    if not _has_head(workspace):
        return None
    return _run(workspace, "rev-parse", "--short", "HEAD").stdout.strip()
