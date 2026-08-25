"""Tests for gitops.py: the wip/amend/gate discipline and repo protections.

The centerpiece is the nesting-incident regression: ensure_repo no longer
auto-inits, so a workspace that is not already the root of its own repo is
refused outright (the operator creates the ledger repo deliberately), and
every mutating op must hard-fail (GitError) rather than stage or commit
into the enclosing project. The first demo run polluted the enclosing
canon repo exactly this way; these tests keep that impossible.

The amend discipline under test: each unit opens with a wip commit
(commit_wip), every green fix episode folds the worktree into that commit
(amend, message kept), a passing seal retitles it with the canonical gate
message (finalize_gate), and the milestone close is a plain commit
(commit_plain). HEAD is always "the last accepted state", so the pending
fix delta is exactly worktree_diff (vs HEAD, intent-to-add for new files)
and a tampering report-only reviewer is revertible with restore_clean.

All git activity happens inside tempfile.TemporaryDirectory(); nothing
here touches the canon repo. Global/system git config is masked per test
so identity defaults are deterministic on any machine.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import gitops, runners


def _write(path, content):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class GitopsTestCase(unittest.TestCase):
    """Temp dirs + masked global/system git config for every test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # realpath: on macOS the temp root is behind a symlink; gitops
        # compares realpaths, so the tests should hand it real paths too.
        self.tmp = os.path.realpath(tmp.name)
        self._saved_env = {}
        for key, value in (
            ("GIT_CONFIG_GLOBAL", os.devnull),
            ("GIT_CONFIG_SYSTEM", os.devnull),
            ("GIT_DIR", None),
            ("GIT_WORK_TREE", None),
            ("GIT_INDEX_FILE", None),
        ):
            self._saved_env[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    # -- plain-git helpers (independent of the module under test) --------

    def git(self, cwd, *args):
        proc = subprocess.run(
            ("git",) + args, cwd=cwd, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            raise AssertionError(
                "test git %s failed in %s: %s"
                % (" ".join(args), cwd, proc.stderr or proc.stdout)
            )
        return proc.stdout

    def git_rc(self, cwd, *args):
        return subprocess.run(
            ("git",) + args, cwd=cwd, capture_output=True, text=True, timeout=60
        ).returncode

    def status(self, cwd):
        return self.git(cwd, "status", "--porcelain")

    def commit_count(self, cwd):
        return int(self.git(cwd, "rev-list", "--count", "HEAD").strip())

    def subject(self, cwd):
        return self.git(cwd, "log", "-1", "--format=%s").strip()

    def make_workspace(self, name="ws", files=None):
        ws = os.path.join(self.tmp, name)
        os.makedirs(ws)
        for rel, content in (files or {}).items():
            _write(os.path.join(ws, rel), content)
        return ws

    def make_repo(self, name="ws", files=None):
        """A workspace the operator deliberately made a git repo. Since
        ensure_repo no longer auto-inits, every test that wants a usable
        gate repo owes the workspace this `git init` first."""
        ws = self.make_workspace(name, files)
        self.git(ws, "init", "-q")
        return ws

    def make_outer_repo(self, name="outer"):
        """A committed repo standing in for the polluted canon repo."""
        outer = os.path.join(self.tmp, name)
        os.makedirs(outer)
        self.git(outer, "init", "-q")
        self.git(outer, "config", "user.name", "Outer Owner")
        self.git(outer, "config", "user.email", "outer@example.test")
        _write(os.path.join(outer, "project.txt"), "outer project file\n")
        self.git(outer, "add", "-A")
        self.git(outer, "commit", "-q", "-m", "outer baseline")
        return outer

    def outer_fingerprint(self, outer):
        """Everything a leak would change: log, index, tracked set, status."""
        return (
            self.git(outer, "rev-list", "HEAD"),
            self.git(outer, "ls-files"),
            self.git(outer, "diff", "--cached", "--name-only"),
            self.status(outer),
        )


class EnsureRepoTests(GitopsTestCase):
    def test_non_repo_dir_is_refused_no_auto_init(self):
        # ensure_repo no longer auto-inits: a plain directory is refused
        # with the explanation that the operator must create the ledger
        # repo deliberately — and the refusal leaves the directory intact.
        ws = self.make_workspace()
        with self.assertRaises(gitops.GitError) as ctx:
            gitops.ensure_repo(ws)
        msg = str(ctx.exception)
        self.assertIn("is not the root of a git repository", msg)
        self.assertIn("create the ledger repo deliberately", msg)
        self.assertFalse(os.path.lexists(os.path.join(ws, ".git")))
        self.assertEqual(os.listdir(ws), [])  # no .gitignore either

    def test_fresh_empty_deliberate_repo_gets_baseline_commit(self):
        # On a freshly `git init`ed EMPTY repo, ensure_repo still seeds
        # identity, .gitignore and the baseline commit.
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".git")))
        top = os.path.realpath(self.git(ws, "rev-parse", "--show-toplevel").strip())
        self.assertEqual(top, ws)
        self.assertEqual(self.commit_count(ws), 1)
        self.assertEqual(self.subject(ws), "Initialize milestone workspace")
        self.assertIn(
            gitops.IGNORE_LINE,
            _read(os.path.join(ws, ".gitignore")).splitlines(),
        )

    def test_sets_local_identity_when_none_configured(self):
        # Global/system config is masked in setUp, so the defaults MUST be
        # written locally or the baseline commit could not even succeed.
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        self.assertEqual(
            self.git(ws, "config", "--get", "user.name").strip(),
            "impl-roadmap-orchestrator",
        )
        self.assertEqual(
            self.git(ws, "config", "--get", "user.email").strip(),
            "orchestrator@impl-roadmap.local",
        )

    def test_second_call_is_idempotent(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        first_head = self.git(ws, "rev-parse", "HEAD").strip()
        first_ignore = _read(os.path.join(ws, ".gitignore"))
        gitops.ensure_repo(ws)
        self.assertEqual(self.git(ws, "rev-parse", "HEAD").strip(), first_head)
        self.assertEqual(self.commit_count(ws), 1)
        self.assertEqual(_read(os.path.join(ws, ".gitignore")), first_ignore)
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_adopts_dirty_own_root_repo_without_committing(self):
        ws = self.make_workspace()
        self.git(ws, "init", "-q")
        self.git(ws, "config", "user.name", "Custom Committer")
        self.git(ws, "config", "user.email", "custom@example.test")
        _write(os.path.join(ws, "tracked.txt"), "original\n")
        self.git(ws, "add", "-A")
        self.git(ws, "commit", "-q", "-m", "pre-existing work")
        head_before = self.git(ws, "rev-parse", "HEAD").strip()
        # Dirty it: a modification and an untracked file.
        _write(os.path.join(ws, "tracked.txt"), "modified\n")
        _write(os.path.join(ws, "untracked.txt"), "new\n")
        gitops.ensure_repo(ws)
        # Adopted as-is: nothing committed, HEAD untouched. The dirty state
        # remains a pending delta vs HEAD until the first wip commit folds
        # it in (the delta is worktree-vs-HEAD in the amend discipline).
        self.assertEqual(self.git(ws, "rev-parse", "HEAD").strip(), head_before)
        self.assertEqual(self.commit_count(ws), 1)
        self.assertTrue(gitops.has_pending_delta(ws))
        delta = gitops.worktree_diff(ws)
        self.assertIn("tracked.txt", delta)
        self.assertIn("+modified", delta)
        self.assertIn("untracked.txt", delta)
        gitops.commit_wip(ws, "wip: skeleton")
        self.assertEqual(gitops.worktree_diff(ws), "")
        self.assertFalse(gitops.has_pending_delta(ws))

    def test_rerun_keeps_the_pending_delta_intact(self):
        # A fresh Driver construction mid-run (a `step`-driven run, a
        # service stop/start, crash resume) re-calls ensure_repo. It must
        # neither commit nor otherwise disturb the pending worktree delta:
        # HEAD is the last accepted state and only commit_wip/amend may
        # advance it.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "draft.py"), "pending unreviewed delta\n")
        delta_before = gitops.worktree_diff(ws)
        self.assertIn("pending unreviewed delta", delta_before)
        gitops.ensure_repo(ws)  # a fresh Driver construction mid-run
        self.assertEqual(self.commit_count(ws), 1)
        delta_after = gitops.worktree_diff(ws)
        self.assertEqual(delta_before, delta_after)
        self.assertTrue(gitops.has_pending_delta(ws))
        # Only a commit closes the delta.
        gitops.commit_wip(ws, "wip: skeleton")
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_extra_ignore_dirs_are_written_to_gitignore(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws, extra_ignore_dirs=["opcache", "buildcache/"])
        lines = _read(os.path.join(ws, ".gitignore")).splitlines()
        self.assertIn("opcache/", lines)
        self.assertIn("buildcache/", lines)
        # And they behave as ignores: contents never enter diffs.
        _write(os.path.join(ws, "opcache", "blob.bin"), "x" * 32)
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_respects_existing_identity(self):
        ws = self.make_workspace()
        self.git(ws, "init", "-q")
        self.git(ws, "config", "user.name", "Custom Committer")
        self.git(ws, "config", "user.email", "custom@example.test")
        gitops.ensure_repo(ws)
        self.assertEqual(
            self.git(ws, "config", "--get", "user.name").strip(),
            "Custom Committer",
        )
        self.assertEqual(
            self.git(ws, "config", "--get", "user.email").strip(),
            "custom@example.test",
        )


class NestingRegressionTests(GitopsTestCase):
    """The incident: a workspace nested inside another repo must never
    stage into or commit to the enclosing repository. ensure_repo no
    longer auto-inits an independent nested repo — a nested non-repo
    workspace is refused outright; only a nested repo the operator
    created deliberately is accepted."""

    def test_nested_non_repo_workspace_is_refused_no_auto_init(self):
        # Flip of the old auto-init expectation: a workspace nested inside
        # another repository (and NOT itself a repo) raises GitError AND
        # leaves the outer repo completely untouched (status+log identical).
        outer = self.make_outer_repo()
        ws = os.path.join(outer, "workspace")
        os.makedirs(ws)
        _write(os.path.join(ws, "seed.txt"), "seed\n")
        before = self.outer_fingerprint(outer)
        with self.assertRaises(gitops.GitError) as ctx:
            gitops.ensure_repo(ws)
        msg = str(ctx.exception)
        self.assertIn("is not the root of a git repository", msg)
        self.assertIn("create the ledger repo deliberately", msg)
        # No nested repo materialized, no adoption of the enclosing repo.
        self.assertFalse(os.path.lexists(os.path.join(ws, ".git")))
        self.assertEqual(self.outer_fingerprint(outer), before)
        self.assertEqual(self.git_rc(outer, "diff", "--cached", "--quiet"), 0)
        self.assertEqual(self.git(outer, "ls-files").strip(), "project.txt")
        # The refusal repeats deterministically (nothing half-initialized).
        with self.assertRaises(gitops.GitError):
            gitops.ensure_repo(ws)
        self.assertEqual(self.outer_fingerprint(outer), before)

    def test_deliberately_inited_nested_workspace_stays_isolated(self):
        # Still supported and still crucial: a nested dir the operator
        # deliberately `git init`ed IS accepted, and every mutation stays
        # inside it — the enclosing repo sees nothing.
        outer = self.make_outer_repo()
        ws = os.path.join(outer, "workspace")
        os.makedirs(ws)
        _write(os.path.join(ws, "seed.txt"), "seed\n")
        before = self.outer_fingerprint(outer)
        self.git(ws, "init", "-q")  # the deliberate operator act
        gitops.ensure_repo(ws)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".git")))
        top = os.path.realpath(self.git(ws, "rev-parse", "--show-toplevel").strip())
        self.assertEqual(top, os.path.realpath(ws))
        self.assertEqual(self.commit_count(ws), 1)  # own baseline only
        # A full unit cycle: draft -> wip commit -> fix -> amend -> gate.
        _write(os.path.join(ws, "src.py"), "def add(a, b):\n    return a + b\n")
        delta = gitops.worktree_diff(ws)
        self.assertIn("return a + b", delta)
        wip = gitops.commit_wip(ws, "wip: slice_doc-01")
        self.assertIsNotNone(wip)
        _write(os.path.join(ws, "src.py"), "def add(a, b):\n    return a + b\n# doc\n")
        gitops.amend(ws)
        sha = gitops.finalize_gate(ws, "Seal slice 01 note")
        self.assertIsNotNone(sha)
        self.assertEqual(self.commit_count(ws), 2)
        self.assertEqual(self.subject(ws), "Seal slice 01 note")
        # The regression assertion: the outer repo saw NOTHING.
        self.assertEqual(self.outer_fingerprint(outer), before)
        self.assertEqual(self.git_rc(outer, "diff", "--cached", "--quiet"), 0)
        self.assertEqual(self.git(outer, "ls-files").strip(), "project.txt")

    def test_mutating_ops_hard_fail_when_workspace_not_own_root(self):
        # Simulate losing the nested repo: after deleting the workspace's
        # own .git, git commands in it resolve to the ENCLOSING repo, and
        # every mutating op must refuse before touching anything.
        outer = self.make_outer_repo()
        ws = os.path.join(outer, "workspace")
        os.makedirs(ws)
        _write(os.path.join(ws, "seed.txt"), "seed\n")
        self.git(ws, "init", "-q")  # the deliberate operator act
        gitops.ensure_repo(ws)
        before = self.outer_fingerprint(outer)
        shutil.rmtree(os.path.join(ws, ".git"))
        _write(os.path.join(ws, "leak.txt"), "must never be staged outside\n")
        for op in (
            lambda: gitops.worktree_diff(ws),
            lambda: gitops.has_pending_delta(ws),
            lambda: gitops.commit_wip(ws, "wip: skeleton"),
            lambda: gitops.amend(ws),
            lambda: gitops.finalize_gate(ws, "Seal slice 01 note"),
            lambda: gitops.commit_plain(ws, "Close milestone"),
            lambda: gitops.restore_clean(ws),
        ):
            with self.assertRaises(gitops.GitError):
                op()
        self.assertEqual(self.outer_fingerprint(outer), before)
        self.assertEqual(self.git_rc(outer, "diff", "--cached", "--quiet"), 0)
        self.assertNotIn("leak.txt", self.git(outer, "ls-files"))
        # restore_clean refused too: the leak file is still in the worktree
        # (it belongs to no repo, so "restoring" would have meant deleting
        # data through the ENCLOSING repo's view).
        self.assertTrue(os.path.exists(os.path.join(ws, "leak.txt")))


class GitEnvLeakRegressionTests(GitopsTestCase):
    """A leaked GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE in the driver's
    environment used to redirect every gitops subprocess to a FOREIGN
    repository while _assert_workspace_root still passed — the same
    enclosing-repo pollution the guard exists to prevent. gitops now runs
    every git subprocess with those variables scrubbed."""

    def leak(self, key, value):
        os.environ[key] = value  # setUp's cleanup restores/pops it

    def test_leaked_git_dir_cannot_redirect_gate_commits(self):
        outer = self.make_outer_repo()
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "payload.py"), "x = 1\n")
        before = self.outer_fingerprint(outer)
        self.leak("GIT_DIR", os.path.join(outer, ".git"))
        self.assertTrue(gitops._is_own_repo(ws))
        gitops.commit_wip(ws, "wip: skeleton")
        sha = gitops.finalize_gate(ws, "Seal milestone skeleton")
        self.assertIsNotNone(sha)
        # The gate landed in the WORKSPACE repo, not the outer one.
        del os.environ["GIT_DIR"]
        self.assertEqual(self.subject(ws), "Seal milestone skeleton")
        self.assertEqual(self.outer_fingerprint(outer), before)
        self.assertNotIn("payload.py", self.git(outer, "ls-files"))

    def test_leaked_git_dir_does_not_hijack_ensure_repo(self):
        outer = self.make_outer_repo()
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        before = self.outer_fingerprint(outer)
        self.leak("GIT_DIR", os.path.join(outer, ".git"))
        gitops.ensure_repo(ws)
        self.assertTrue(os.path.isdir(os.path.join(ws, ".git")))
        del os.environ["GIT_DIR"]
        self.assertEqual(self.commit_count(ws), 1)
        self.assertEqual(self.outer_fingerprint(outer), before)

    def test_leaked_index_and_worktree_do_not_touch_outer_repo(self):
        outer = self.make_outer_repo()
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "payload.py"), "x = 1\n")
        before = self.outer_fingerprint(outer)
        self.leak("GIT_INDEX_FILE", os.path.join(outer, ".git", "index"))
        self.leak("GIT_WORK_TREE", outer)
        self.assertIn("payload.py", gitops.worktree_diff(ws))
        gitops.commit_wip(ws, "wip: skeleton")
        del os.environ["GIT_INDEX_FILE"]
        del os.environ["GIT_WORK_TREE"]
        # The wip commit landed in the workspace repo; the outer repo saw
        # nothing.
        self.assertIn("payload.py", self.git(ws, "ls-files"))
        self.assertEqual(self.subject(ws), "wip: skeleton")
        self.assertEqual(self.outer_fingerprint(outer), before)


class GitdirLinkRegressionTests(GitopsTestCase):
    """A `.git` gitdir-link FILE (worktree/submodule-style, creatable by a
    full-permission worker) used to pass _is_own_repo — the toplevel check
    alone was satisfied — and gate commits landed in the LINKED foreign
    repository. Ownership now also requires the resolved git directory to
    be <workspace>/.git itself."""

    def make_linked_workspace(self):
        real = self.make_outer_repo("realrepo")
        ws = self.make_workspace()
        _write(os.path.join(ws, ".git"), "gitdir: %s/.git\n" % real)
        _write(os.path.join(ws, "payload.py"), "x = 1\n")
        return real, ws

    def test_gitdir_link_fails_ownership_and_all_mutating_ops(self):
        real, ws = self.make_linked_workspace()
        before = self.outer_fingerprint(real)
        self.assertFalse(gitops._is_own_repo(ws))
        for op in (
            lambda: gitops.worktree_diff(ws),
            lambda: gitops.has_pending_delta(ws),
            lambda: gitops.commit_wip(ws, "wip: skeleton"),
            lambda: gitops.amend(ws),
            lambda: gitops.finalize_gate(ws, "Seal milestone skeleton"),
            lambda: gitops.commit_plain(ws, "Close milestone"),
            lambda: gitops.restore_clean(ws),
        ):
            with self.assertRaises(gitops.GitError):
                op()
        self.assertEqual(self.outer_fingerprint(real), before)

    def test_ensure_repo_refuses_to_init_through_the_link(self):
        real, ws = self.make_linked_workspace()
        before = self.outer_fingerprint(real)
        with self.assertRaises(gitops.GitError):
            gitops.ensure_repo(ws)
        self.assertEqual(self.outer_fingerprint(real), before)
        self.assertNotIn(
            "Seal", self.git(real, "log", "--format=%s")
        )

    def test_dot_git_symlink_to_foreign_repo_is_refused(self):
        real = self.make_outer_repo("realrepo")
        ws = self.make_workspace()
        os.symlink(os.path.join(real, ".git"), os.path.join(ws, ".git"))
        _write(os.path.join(ws, "payload.py"), "x = 1\n")
        before = self.outer_fingerprint(real)
        self.assertFalse(gitops._is_own_repo(ws))
        with self.assertRaises(gitops.GitError):
            gitops.commit_wip(ws, "wip: skeleton")
        with self.assertRaises(gitops.GitError):
            gitops.ensure_repo(ws)
        self.assertEqual(self.outer_fingerprint(real), before)


class EmbeddedRepoTests(GitopsTestCase):
    """A worker-created nested repo would be staged by `git add -A` as a
    bare gitlink pointer (mode 160000): the gate would "seal" content that
    is absent from the workspace repository. Every staging/diff op now
    hard-fails instead of silently losing the content."""

    def make_nested(self, ws, rel="vendor/dep", commit=True):
        dep = os.path.join(ws, rel)
        os.makedirs(dep)
        self.git(dep, "init", "-q")
        self.git(dep, "config", "user.name", "V")
        self.git(dep, "config", "user.email", "v@example.test")
        _write(os.path.join(dep, "lib.py"), "def f():\n    return 1\n")
        if commit:
            self.git(dep, "add", "-A")
            self.git(dep, "commit", "-q", "-m", "dep content")
        return dep

    def test_committed_nested_repo_fails_diff_wip_and_gate(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.make_nested(ws)
        for op in (
            lambda: gitops.worktree_diff(ws),
            lambda: gitops.commit_wip(ws, "wip: skeleton"),
            lambda: gitops.amend(ws),
            lambda: gitops.finalize_gate(ws, "Seal milestone skeleton"),
            lambda: gitops.commit_plain(ws, "Close milestone"),
        ):
            with self.assertRaises(gitops.GitError) as ctx:
                op()
            self.assertIn("vendor/dep", str(ctx.exception))
        # Nothing was committed; no gitlink pointer entered the history.
        self.assertEqual(self.commit_count(ws), 1)
        self.assertNotIn("vendor/dep", self.git(ws, "ls-files"))

    def test_commitless_nested_repo_is_also_detected(self):
        # Without a HEAD the nested repo cannot even be represented as a
        # gitlink: add -A simply skips it and the content vanishes with
        # no trace at all. Detection must not depend on the index.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.make_nested(ws, rel="vendor2/dep", commit=False)
        with self.assertRaises(gitops.GitError):
            gitops.commit_wip(ws, "wip: skeleton")

    def test_declared_submodule_is_allowed(self):
        # An intentional submodule (gitlink + .gitmodules entry) is a
        # correct representation, not content loss: adoption must work.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.make_nested(ws, rel="libs/sub")
        _write(
            os.path.join(ws, ".gitmodules"),
            '[submodule "sub"]\n\tpath = libs/sub\n\turl = ./libs/sub\n',
        )
        self.assertNotEqual(gitops.worktree_diff(ws), "")
        sha = gitops.commit_wip(ws, "wip: skeleton")
        self.assertIsNotNone(sha)
        self.assertIn("libs/sub", self.git(ws, "ls-files"))

    def test_gitignored_nested_repo_is_not_flagged(self):
        # A nested repo inside an ignored cache dir (e.g. a tox env that
        # pulled sources from VCS) can never be staged — it must not
        # hard-fail the run.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.make_nested(ws, rel=os.path.join(".tox", "dep"))
        self.assertEqual(gitops.worktree_diff(ws), "")
        self.assertIsNone(gitops.commit_plain(ws, "Close milestone"))


class CacheNoiseTests(GitopsTestCase):
    """Python tool caches written by verification runs used to enter
    review diffs as binary noise and get committed into gate commits; the
    workspace .gitignore now covers the same cache set that workspace
    snapshots exclude (runners.SNAPSHOT_EXCLUDE_DIRS)."""

    def test_pycache_never_enters_diffs_or_gate_commits(self):
        ws = self.make_repo(files={"mod.py": "x = 1\n"})
        gitops.ensure_repo(ws)
        _write(
            os.path.join(ws, "__pycache__", "mod.cpython-311.pyc"),
            "\x00fake bytecode\x00",
        )
        _write(os.path.join(ws, ".pytest_cache", "v", "cache", "lastfailed"), "{}")
        self.assertEqual(gitops.worktree_diff(ws), "")
        self.assertFalse(gitops.has_pending_delta(ws))
        self.assertIsNone(gitops.commit_plain(ws, "Close milestone"))
        _write(os.path.join(ws, "real.py"), "y = 2\n")
        gitops.commit_wip(ws, "wip: skeleton")
        gitops.finalize_gate(ws, "Seal milestone skeleton")
        tracked = self.git(ws, "ls-files")
        self.assertNotIn("__pycache__", tracked)
        self.assertNotIn(".pytest_cache", tracked)
        self.assertIn("real.py", tracked)

    def test_ignore_lines_cover_the_snapshot_exclude_set(self):
        from orchestrator import runners

        lines = {l.rstrip("/") for l in gitops.ignore_lines()}
        for name in runners.SNAPSHOT_EXCLUDE_DIRS - {".git", ".orchestrator"}:
            self.assertIn(name, lines)
        self.assertIn(gitops.IGNORE_LINE.rstrip("/"), lines)


class SnapshotUniverseTests(GitopsTestCase):
    """The tamper universe tolerates a nested repository's OWN ignored
    artifacts while keeping every detection the raw walk had.

    The rule under test: an ignored region is outside the universe, so
    CHANGING what a repo ignores must never be free — the files deciding
    that are hashed, wherever they live.
    """

    def _commit_all(self, repo, message):
        self.git(repo, "add", "-A")
        self.git(
            repo,
            "-c", "user.name=Snapshot Tester",
            "-c", "user.email=snapshot@example.test",
            "commit", "-q", "-m", message,
        )

    def _vendored(self):
        """A committed workspace embedding a committed vendored repo whose
        own .gitignore excludes its _build artifacts."""
        ws = self.make_repo("ws", {"app.py": "print(1)\n"})
        self._commit_all(ws, "baseline")
        sub = os.path.join(ws, "vendor", "lib")
        os.makedirs(sub)
        self.git(sub, "init", "-q")
        _write(os.path.join(sub, ".gitignore"), "_build/\n")
        _write(os.path.join(sub, "src.ex"), "defmodule X do end\n")
        self._commit_all(sub, "vendored baseline")
        _write(os.path.join(sub, "_build", "test", "a.beam"), "artifact v1\n")
        _write(os.path.join(sub, "notes.txt"), "untracked but visible\n")
        return ws, sub

    def _snapshot(self, ws):
        universe = gitops.snapshot_universe(ws)
        return runners.snapshot_workspace(
            ws,
            paths=universe["paths"],
            walk_skip=universe["walk_skip"],
            ignore_surfaces=universe["ignore_surfaces"],
        )

    def _changes(self, ws, before):
        return runners.snapshot_changes(before, self._snapshot(ws))

    def test_universe_skips_only_what_the_nested_repo_ignores(self):
        ws, _sub = self._vendored()
        universe = gitops.snapshot_universe(ws)
        # The parent still sees the nested repo as one bare directory; the
        # subtree is covered by the walk, not by a second listing.
        self.assertIn("app.py", universe["paths"])
        self.assertIn("vendor/lib", universe["paths"])
        self.assertIn("vendor/lib/_build", universe["walk_skip"])
        snapshot = self._snapshot(ws)
        self.assertIn(os.path.join("vendor", "lib", "src.ex"), snapshot)
        self.assertIn(os.path.join("vendor", "lib", "notes.txt"), snapshot)
        # No CONTENT under the pruned region is hashed. Its own rule file
        # is named as a surface: pruning it is the thing that must not be
        # silently widenable.
        self.assertEqual(
            [
                key for key in snapshot
                if "_build" in key and not key.startswith("(ignore surface)")
            ],
            [],
        )
        self.assertIn("(ignore surface) vendor/lib/.git/config", snapshot)
        self.assertIn(
            "(ignore surface) vendor/lib/.git/info/exclude", snapshot
        )

    def test_vendored_artifact_churn_is_invisible_but_edits_are_named(self):
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        # Build churn inside the vendored repo (a reviewer running the
        # project's tests) must not read as tampering. This is the live
        # incident: mix wrote .mix_test_failures under _build.
        _write(os.path.join(sub, "_build", "test", "a.beam"), "artifact v2\n")
        _write(
            os.path.join(sub, "_build", "test", "lib", ".mix_test_failures"),
            "failures\n",
        )
        self.assertEqual(self._changes(ws, before), [])
        # A real edit inside the vendored repo is still named.
        before = self._snapshot(ws)
        _write(os.path.join(sub, "src.ex"), "defmodule X do :changed end\n")
        self.assertEqual(
            self._changes(ws, before),
            [os.path.join("vendor", "lib", "src.ex")],
        )
        # So is a deletion, and an untracked-but-visible plant.
        before = self._snapshot(ws)
        os.remove(os.path.join(sub, "src.ex"))
        _write(os.path.join(sub, "planted.ex"), "plant\n")
        self.assertEqual(
            self._changes(ws, before),
            [
                os.path.join("vendor", "lib", "planted.ex"),
                os.path.join("vendor", "lib", "src.ex"),
            ],
        )

    def test_nested_empty_directory_outside_ignored_regions_is_detected(self):
        # Git lists no directories, so an expansion-by-listing universe
        # would go blind here; the subtree walk must keep this.
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        os.makedirs(os.path.join(sub, "enable_feature"))
        self.assertEqual(
            self._changes(ws, before),
            [os.path.join("vendor", "lib", "enable_feature")],
        )

    def test_ignored_regions_are_out_of_the_universe_at_every_depth(self):
        """The deliberate boundary, pinned so it cannot drift unnoticed.

        What a repo ignores is outside the tamper universe — that is the
        whole point, and it is exactly the posture the workspace repo has
        always had for its own ignored regions. Extending it to a nested
        repo therefore adds no NEW class of blind spot, and this test
        states both halves so a future reader sees the trade rather than
        discovering it.
        """
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        # Inside the nested repo's ignored region: not covered.
        os.makedirs(os.path.join(sub, "_build", "enable_feature"))
        os.symlink(
            "/etc/passwd", os.path.join(sub, "_build", "link_to_secret")
        )
        self.assertEqual(self._changes(ws, before), [])
        # Inside the WORKSPACE repo's own ignored region: equally not
        # covered, and that was true long before nested repos were.
        _write(os.path.join(ws, ".gitignore"), "artifacts/\n")
        before = self._snapshot(ws)
        os.makedirs(os.path.join(ws, "artifacts", "enable_feature"))
        _write(os.path.join(ws, "artifacts", "plant.py"), "plant\n")
        self.assertEqual(self._changes(ws, before), [])

    def test_cloaking_via_a_self_ignoring_gitignore_is_visible(self):
        # cloak/.gitignore holding "*" hides itself and its directory from
        # every listing. The plant stays git-invisible, but the act of
        # cloaking is hashed, so the call is invalidated.
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        _write(os.path.join(sub, "cloak", ".gitignore"), "*\n")
        _write(os.path.join(sub, "cloak", "payload.ex"), "malicious\n")
        changed = self._changes(ws, before)
        self.assertTrue(changed, "a cloaked plant must not be free")
        self.assertTrue(
            any("cloak" in name and ".gitignore" in name for name in changed),
            changed,
        )

    def test_cloaking_via_core_excludesfile_is_visible(self):
        # core.excludesFile can point anywhere, including inside the git
        # dir the walk excludes. Both the config and its target are hashed.
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        secret = os.path.join(sub, ".git", "private-ignore")
        _write(secret, "payload.ex\n")
        self.git(sub, "config", "core.excludesFile", secret)
        _write(os.path.join(sub, "payload.ex"), "malicious\n")
        changed = self._changes(ws, before)
        self.assertTrue(changed, "an excludesFile cloak must not be free")
        self.assertTrue(
            any("config" in name for name in changed), changed
        )
        # Editing the pointed-at rule file later is visible on its own.
        before = self._snapshot(ws)
        _write(secret, "payload.ex\nsecond.ex\n")
        self.assertTrue(self._changes(ws, before))

    def test_nested_info_exclude_append_is_visible(self):
        ws, sub = self._vendored()
        before = self._snapshot(ws)
        _write(os.path.join(sub, ".git", "info", "exclude"), "planted.ex\n")
        _write(os.path.join(sub, "planted.ex"), "plant\n")
        changed = self._changes(ws, before)
        self.assertTrue(
            any("info/exclude" in name for name in changed), changed
        )

    def test_nested_repos_are_handled_recursively(self):
        ws, sub = self._vendored()
        inner = os.path.join(sub, "deps", "leaf")
        os.makedirs(inner)
        self.git(inner, "init", "-q")
        _write(os.path.join(inner, ".gitignore"), "cache/\n")
        _write(os.path.join(inner, "leaf.ex"), "leaf\n")
        self._commit_all(inner, "leaf baseline")
        _write(os.path.join(inner, "cache", "c"), "leaf artifact v1\n")
        universe = gitops.snapshot_universe(ws)
        self.assertIn("vendor/lib/deps/leaf/cache", universe["walk_skip"])
        before = self._snapshot(ws)
        _write(os.path.join(inner, "cache", "c"), "leaf artifact v2\n")
        self.assertEqual(self._changes(ws, before), [])
        before = self._snapshot(ws)
        _write(os.path.join(inner, "leaf.ex"), "leaf CHANGED\n")
        self.assertEqual(
            self._changes(ws, before),
            [os.path.join("vendor", "lib", "deps", "leaf", "leaf.ex")],
        )

    def test_declared_submodule_tolerates_churn_and_keeps_detections(self):
        src = self.make_repo("subsrc")
        _write(os.path.join(src, ".gitignore"), "_build/\n")
        _write(os.path.join(src, "lib.ex"), "lib\n")
        self._commit_all(src, "sub baseline")
        ws = self.make_repo("ws2", {"app.py": "print(1)\n"})
        self._commit_all(ws, "baseline")
        self.git(
            ws,
            "-c", "protocol.file.allow=always",
            "submodule", "add", "-q", src, "vendor/sub",
        )
        self._commit_all(ws, "add submodule")
        sub = os.path.join(ws, "vendor", "sub")
        _write(os.path.join(sub, "_build", "x"), "artifact\n")
        universe = gitops.snapshot_universe(ws)
        self.assertIn("vendor/sub/_build", universe["walk_skip"])
        # A submodule's git dir lives under the parent's .git/modules; its
        # ignore surfaces must ride the universe from there.
        self.assertTrue(
            any(
                ".git/modules/vendor/sub/info/exclude" in surface
                for surface in universe["ignore_surfaces"]
            ),
            universe["ignore_surfaces"],
        )
        before = self._snapshot(ws)
        _write(os.path.join(sub, "_build", "x"), "artifact CHURN\n")
        self.assertEqual(self._changes(ws, before), [])
        before = self._snapshot(ws)
        _write(os.path.join(sub, "lib.ex"), "lib CHANGED\n")
        self.assertEqual(
            self._changes(ws, before),
            [os.path.join("vendor", "sub", "lib.ex")],
        )
        # The gitfile that binds the submodule to its git dir is content
        # inside the walk: repointing it at a foreign repo is detected.
        before = self._snapshot(ws)
        _write(os.path.join(sub, ".git"), "gitdir: /tmp/foreign\n")
        changed = self._changes(ws, before)
        self.assertIn(os.path.join("vendor", "sub", ".git"), changed)
        # Losing the binding also drops that repo's ignore surfaces and
        # returns its whole subtree to the walk — louder, never quieter.
        self.assertTrue(
            any(name.startswith("(ignore surface)") for name in changed),
            changed,
        )

    def test_linked_worktree_surfaces_come_from_the_common_git_dir(self):
        # A linked worktree has its own git dir, but git reads info/exclude
        # and config from the COMMON one. Naming the per-worktree pair
        # would hash two files git never consults while leaving the rules
        # it does consult free to hide a plant.
        ws = self.make_repo("wtws", {"app.py": "print(1)\n"})
        self._commit_all(ws, "baseline")
        outside = self.make_repo("outside_main", {"lib.py": "lib\n"})
        self._commit_all(outside, "outside baseline")
        self.git(
            outside, "worktree", "add", "-q", os.path.join(ws, "vendor", "wt")
        )
        universe = gitops.snapshot_universe(ws)
        surfaces = " ".join(universe["ignore_surfaces"])
        self.assertNotIn("worktrees", surfaces)
        self.assertIn(
            os.path.join(outside, ".git", "info", "exclude"),
            universe["ignore_surfaces"],
        )
        before = self._snapshot(ws)
        # The rule git actually applies to the worktree lives in the
        # common dir, outside the workspace entirely.
        _write(
            os.path.join(outside, ".git", "info", "exclude"), "payload.py\n"
        )
        _write(os.path.join(ws, "vendor", "wt", "payload.py"), "plant\n")
        self.assertTrue(
            self._changes(ws, before), "a common-dir cloak must not be free"
        )

    def test_unreadable_nested_git_keeps_the_unfiltered_walk(self):
        # Trusting an ignore set that could not be read would be the
        # dangerous posture; falling back to walking everything is safe.
        ws, sub = self._vendored()
        real_toplevel = gitops._toplevel

        def broken_for_nested(path):
            if os.path.realpath(path) == os.path.realpath(sub):
                raise gitops.GitError("nested git cannot answer")
            return real_toplevel(path)

        with mock.patch.object(
            gitops, "_toplevel", side_effect=broken_for_nested
        ):
            universe = gitops.snapshot_universe(ws)
        self.assertEqual(universe["walk_skip"], [])
        snapshot = runners.snapshot_workspace(
            ws,
            paths=universe["paths"],
            walk_skip=universe["walk_skip"],
            ignore_surfaces=universe["ignore_surfaces"],
        )
        self.assertTrue(
            any("_build" in key for key in snapshot),
            "the fallback must cover the whole subtree",
        )


class WorktreeDiffTests(GitopsTestCase):
    """worktree_diff is the pending fix delta: worktree vs HEAD."""

    def test_empty_at_baseline(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_shows_modified_content(self):
        ws = self.make_repo(files={"notes.txt": "old line\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "notes.txt"), "old line\nadded line two\n")
        delta = gitops.worktree_diff(ws)
        self.assertIn("notes.txt", delta)
        self.assertIn("+added line two", delta)

    def test_shows_new_file_content_via_intent_to_add(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "brand_new.py"), "print('brand new content')\n")
        delta = gitops.worktree_diff(ws)
        self.assertIn("brand_new.py", delta)
        self.assertIn("brand new content", delta)
        # Intent-to-add must not swallow the delta: it persists until an
        # actual commit (commit_wip/amend) folds it into HEAD.
        self.assertIn("brand new content", gitops.worktree_diff(ws))

    def test_shows_deletions(self):
        # Regression: a bare `git add -N .` followed Git 2.0 pathspec
        # semantics for removed paths — it STAGED the deletion outright
        # (not intent-to-add). The staged removal (a) polluted the index
        # behind HEAD's back and (b) with the old index-based delta made a
        # deletion-only worker delta look like "no changes". With
        # `--ignore-removal`, deletions stay worktree-only and show in the
        # diff vs HEAD like every other change.
        ws = self.make_repo(files={"doomed.txt": "soon to be gone\n"})
        gitops.ensure_repo(ws)
        os.remove(os.path.join(ws, "doomed.txt"))
        delta = gitops.worktree_diff(ws)
        self.assertIn(
            "doomed.txt",
            delta,
            "deletion missing from the pending delta",
        )
        self.assertIn("-soon to be gone", delta)
        # The file is still tracked at HEAD: nothing was committed and the
        # index did not silently absorb the removal.
        self.assertIn("doomed.txt", self.git(ws, "ls-files"))

    def test_ignores_orchestrator_dir(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(
            os.path.join(ws, ".orchestrator", "state.json"),
            '{"bookkeeping": true}\n',
        )
        _write(os.path.join(ws, ".orchestrator", "raw", "call_001.txt"), "raw\n")
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_truncates_beyond_max_chars(self):
        ws = self.make_repo(files={"big.txt": "line\n"})
        gitops.ensure_repo(ws)
        _write(
            os.path.join(ws, "big.txt"),
            "".join("padding line %04d\n" % i for i in range(200)),
        )
        limit = 64
        delta = gitops.worktree_diff(ws, max_chars=limit)
        self.assertTrue(delta.endswith(gitops.TRUNCATION_MARKER))
        self.assertEqual(len(delta), limit + len(gitops.TRUNCATION_MARKER))
        self.assertTrue(delta.startswith("diff --git"))

    def test_fixed_base_includes_committed_and_uncommitted_changes(self):
        ws = self.make_repo(files={"tracked.txt": "before\n"})
        gitops.ensure_repo(ws)
        base = gitops.head_full_sha(ws)
        _write(os.path.join(ws, "tracked.txt"), "committed\n")
        self.git(ws, "add", "-A")
        self.git(ws, "commit", "-qm", "fixer-owned repair")
        _write(os.path.join(ws, "new.txt"), "uncommitted\n")

        delta = gitops.worktree_diff(ws, base_revision=base)

        self.assertIn("committed", delta)
        self.assertIn("uncommitted", delta)
        self.assertIn("fixer-owned repair", self.git(ws, "log", "--format=%s"))


class ReviewableLineCountTests(GitopsTestCase):
    def test_counts_tracked_deletions_and_nonignored_untracked(self):
        ws = self.make_repo(files={
            ".gitignore": "build/\n",
            "edit.py": "one\ntwo\nthree\n",
            "delete.py": "gone one\ngone two\n",
            "notes.md": "old note\n",
        })
        gitops.ensure_repo(ws)
        base = gitops.snapshot_index_tree(ws)

        _write(os.path.join(ws, "edit.py"), "one\nchanged\nthree\nadded\n")
        os.remove(os.path.join(ws, "delete.py"))
        _write(os.path.join(ws, "new.py"), "a\nb\nc\n")
        _write(os.path.join(ws, "notes.md"), "new note\nmore prose\n")
        _write(os.path.join(ws, "NEW.TXT"), "ignored prose\n")
        _write(os.path.join(ws, "build", "generated.py"), "x\ny\nz\n")

        self.assertEqual(gitops.reviewable_line_count(ws, base), 8)

    def test_excludes_builtin_and_actual_bookkeeping_directories(self):
        ws = self.make_repo(files={"app.py": "old\n"})
        gitops.ensure_repo(ws)
        runtime = os.path.join(ws, "implementation", "milestone", ".run")
        _write(os.path.join(runtime, "counter.py"), "old\n")
        _write(os.path.join(ws, ".orchestrator", "tracked.py"), "old\n")
        self.git(
            ws,
            "add",
            "-f",
            os.path.relpath(os.path.join(runtime, "counter.py"), ws),
            ".orchestrator/tracked.py",
        )
        self.git(ws, "commit", "-qm", "tracked bookkeeping fixture")
        base = gitops.snapshot_index_tree(ws)

        _write(os.path.join(ws, "app.py"), "new\n")
        _write(os.path.join(runtime, "counter.py"), "new\nmore\n")
        _write(os.path.join(ws, ".orchestrator", "tracked.py"), "new\nmore\n")

        self.assertEqual(
            gitops.reviewable_line_count(ws, base, bookkeeping_dir=runtime),
            2,
        )

    def test_uses_fixed_base_across_an_intervening_commit(self):
        ws = self.make_repo(files={"seed.py": "seed\n"})
        gitops.ensure_repo(ws)
        base = gitops.snapshot_index_tree(ws)
        _write(os.path.join(ws, "committed.py"), "one\ntwo\n")
        self.git(ws, "add", "committed.py")
        self.git(ws, "commit", "-qm", "worker-created commit")

        self.assertEqual(gitops.reviewable_line_count(ws, base), 2)

    def test_code_document_renames_count_only_code_side(self):
        ws = self.make_repo(files={
            "source.py": "one\ntwo\n",
            "prose.md": "a\nb\nc\n",
        })
        gitops.ensure_repo(ws)
        base = gitops.snapshot_index_tree(ws)
        self.git(ws, "mv", "source.py", "source.md")
        self.git(ws, "mv", "prose.md", "prose.py")

        self.assertEqual(gitops.reviewable_line_count(ws, base), 5)

    def test_inspection_does_not_add_untracked_files_to_the_index(self):
        ws = self.make_repo(files={"seed.py": "seed\n"})
        gitops.ensure_repo(ws)
        base = gitops.snapshot_index_tree(ws)
        _write(os.path.join(ws, "odd\tname.py"), "one\ntwo\n")
        index_before = gitops.snapshot_index_tree(ws)

        self.assertEqual(gitops.reviewable_line_count(ws, base), 2)
        self.assertEqual(gitops.snapshot_index_tree(ws), index_before)
        self.assertIn(
            "odd\tname.py",
            self.git(ws, "ls-files", "-z", "--others").split("\0"),
        )

    def test_binary_delta_is_not_misreported_as_text_lines(self):
        ws = self.make_repo(files={"seed.py": "seed\n"})
        binary = os.path.join(ws, "image.bin")
        with open(binary, "wb") as handle:
            handle.write(b"before\x00bytes")
        gitops.ensure_repo(ws)
        base = gitops.snapshot_index_tree(ws)
        with open(binary, "wb") as handle:
            handle.write(b"after\x00different\x00bytes")

        self.assertEqual(gitops.reviewable_line_count(ws, base), 0)


class HasPendingDeltaTests(GitopsTestCase):
    def test_tracks_every_change_shape_and_clears_on_commit(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.assertFalse(gitops.has_pending_delta(ws))
        # New file.
        _write(os.path.join(ws, "new.py"), "x = 1\n")
        self.assertTrue(gitops.has_pending_delta(ws))
        gitops.commit_wip(ws, "wip: skeleton")
        self.assertFalse(gitops.has_pending_delta(ws))
        # Modification.
        _write(os.path.join(ws, "new.py"), "x = 2\n")
        self.assertTrue(gitops.has_pending_delta(ws))
        gitops.amend(ws)
        self.assertFalse(gitops.has_pending_delta(ws))
        # Deletion.
        os.remove(os.path.join(ws, "seed.txt"))
        self.assertTrue(gitops.has_pending_delta(ws))
        gitops.amend(ws)
        self.assertFalse(gitops.has_pending_delta(ws))

    def test_orchestrator_writes_are_not_a_delta(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, ".orchestrator", "raw", "r1.txt"), "raw\n")
        self.assertFalse(gitops.has_pending_delta(ws))


class WipAmendGateTests(GitopsTestCase):
    """The amend discipline: one clean commit per unit, no patch stacking;
    the gate retitles it; the milestone close is a plain commit."""

    def test_commit_wip_opens_the_unit_commit(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "draft.py"), "draft = True\n")
        sha = gitops.commit_wip(ws, "wip: skeleton")
        self.assertEqual(
            sha, self.git(ws, "rev-parse", "--short", "HEAD").strip()
        )
        self.assertEqual(self.commit_count(ws), 2)
        self.assertEqual(self.subject(ws), "wip: skeleton")
        self.assertEqual(self.status(ws), "")
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_commit_wip_allows_an_empty_draft(self):
        # A unit whose draft changed nothing still opens its wip commit
        # (--allow-empty): the amend/gate machinery needs the commit.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        sha = gitops.commit_wip(ws, "wip: slice_doc-01")
        self.assertIsNotNone(sha)
        self.assertEqual(self.commit_count(ws), 2)
        self.assertEqual(self.subject(ws), "wip: slice_doc-01")

    def test_amend_keeps_message_changes_sha_history_constant(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "draft.py"), "draft = True\n")
        wip_sha = gitops.commit_wip(ws, "wip: skeleton")
        # A green fix episode: edit + new file, folded into the same commit.
        _write(os.path.join(ws, "draft.py"), "draft = 'fixed'\n")
        _write(os.path.join(ws, "extra.py"), "added_by_fix = True\n")
        new_sha = gitops.amend(ws)
        self.assertNotEqual(new_sha, wip_sha)
        self.assertEqual(self.commit_count(ws), 2)  # no patch stacking
        self.assertEqual(self.subject(ws), "wip: skeleton")
        self.assertEqual(self.status(ws), "")
        # The amended commit carries the fix content.
        show = self.git(ws, "show", "--stat", "--format=%s", "HEAD")
        self.assertIn("extra.py", show)
        self.assertIn(
            "draft = 'fixed'", self.git(ws, "show", "HEAD:draft.py")
        )

    def test_note_ratification_restores_index_when_tree_snapshot_fails(self):
        ws = self.make_repo(files={"docs/note.md": "limit 50\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "docs", "note.md"), "limit 30\n")
        note_gate = gitops.commit_wip(ws, "Seal slice 01 note")
        _write(os.path.join(ws, "impl.py"), "limit = 50\n")
        gitops.commit_wip(ws, "wip: slice_impl-01")
        _write(os.path.join(ws, "docs", "note.md"), "limit 30 corrected\n")
        _write(os.path.join(ws, "impl.py"), "limit = 30\n")
        head_before = gitops.head_full_sha(ws)
        index_before = gitops.snapshot_index_tree(ws)
        diff_before = self.git(ws, "diff", "HEAD")
        real_run = gitops._run
        writes = {"count": 0}

        def fail_second_write_tree(workspace, *args, **kwargs):
            if args == ("write-tree",):
                writes["count"] += 1
                if writes["count"] == 2:
                    raise gitops.GitError("injected write-tree failure")
            return real_run(workspace, *args, **kwargs)

        with mock.patch.object(
            gitops, "_run", side_effect=fail_second_write_tree
        ):
            with self.assertRaises(gitops.GitError):
                gitops.ratify_note_correction(
                    ws, "docs/note.md", note_gate,
                    "Ratify slice 01 note correction",
                )

        self.assertEqual(gitops.head_full_sha(ws), head_before)
        self.assertEqual(gitops.snapshot_index_tree(ws), index_before)
        self.assertEqual(self.git(ws, "diff", "HEAD"), diff_before)

    def test_finalize_gate_replaces_the_message(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "draft.py"), "draft = True\n")
        wip_sha = gitops.commit_wip(ws, "wip: skeleton")
        # The gate folds the generated ledgers in and retitles the commit.
        _write(os.path.join(ws, "docs", "MILESTONE.md"), "# Milestone\n")
        gate_sha = gitops.finalize_gate(ws, "Seal milestone skeleton")
        self.assertNotEqual(gate_sha, wip_sha)
        self.assertEqual(self.commit_count(ws), 2)
        self.assertEqual(self.subject(ws), "Seal milestone skeleton")
        self.assertEqual(self.status(ws), "")
        self.assertIn("docs/MILESTONE.md", self.git(ws, "ls-files"))
        self.assertNotIn(
            "wip: skeleton", self.git(ws, "log", "--format=%s")
        )

    def test_commit_plain_returns_sha_or_none(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        self.assertIsNone(gitops.commit_plain(ws, "Close milestone"))
        self.assertEqual(self.commit_count(ws), 1)
        _write(os.path.join(ws, "docs", "adjudications.md"), "(none)\n")
        sha = gitops.commit_plain(ws, "Close milestone")
        self.assertEqual(
            sha, self.git(ws, "rev-parse", "--short", "HEAD").strip()
        )
        self.assertEqual(self.commit_count(ws), 2)
        self.assertEqual(self.subject(ws), "Close milestone")
        # Idempotent close: nothing new -> no second commit.
        self.assertIsNone(gitops.commit_plain(ws, "Close milestone"))
        self.assertEqual(self.commit_count(ws), 2)

    def test_head_sha_none_before_first_commit_then_tracks_head(self):
        ws = self.make_workspace()
        self.git(ws, "init", "-q")
        self.assertIsNone(gitops.head_sha(ws))
        gitops.ensure_repo(ws)
        baseline = gitops.head_sha(ws)
        self.assertIsNotNone(baseline)
        _write(os.path.join(ws, "b.txt"), "b\n")
        wip = gitops.commit_wip(ws, "wip: slice_impl-01")
        self.assertEqual(gitops.head_sha(ws), wip)
        sha = gitops.finalize_gate(ws, "Seal slice 01 implementation and close")
        self.assertEqual(gitops.head_sha(ws), sha)
        self.assertNotEqual(gitops.head_sha(ws), baseline)


class RestoreCleanTests(GitopsTestCase):
    """restore_clean is the recovery path when a report-only reviewer
    tampered with a clean worktree: back to HEAD, byte for byte, without
    destroying runtime bookkeeping."""

    def test_reverts_tracked_removes_untracked_preserves_orchestrator(self):
        ws = self.make_repo(
            files={"kept.txt": "original\n", "doomed.txt": "restore me\n"}
        )
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, ".orchestrator", "state.json"), "{}\n")
        _write(os.path.join(ws, ".orchestrator", "raw", "r1.txt"), "raw\n")
        # The tampering: modify a tracked file, delete another, drop new
        # files and a new directory.
        _write(os.path.join(ws, "kept.txt"), "sneaky edit\n")
        os.remove(os.path.join(ws, "doomed.txt"))
        _write(os.path.join(ws, "evil.py"), "planted = True\n")
        _write(os.path.join(ws, "sub", "dir", "junk.txt"), "junk\n")
        gitops.restore_clean(ws)
        self.assertEqual(_read(os.path.join(ws, "kept.txt")), "original\n")
        self.assertEqual(_read(os.path.join(ws, "doomed.txt")), "restore me\n")
        self.assertFalse(os.path.exists(os.path.join(ws, "evil.py")))
        self.assertFalse(os.path.exists(os.path.join(ws, "sub")))
        # Runtime bookkeeping survives (gitignored; clean -fd honors it).
        self.assertTrue(
            os.path.exists(os.path.join(ws, ".orchestrator", "state.json"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(ws, ".orchestrator", "raw", "r1.txt"))
        )
        self.assertFalse(gitops.has_pending_delta(ws))
        self.assertEqual(gitops.worktree_diff(ws), "")

    def test_restores_to_the_amended_commit_not_the_baseline(self):
        # HEAD is "the last accepted state": after wip+amend, restore must
        # return to the amended content, not the baseline.
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        gitops.ensure_repo(ws)
        _write(os.path.join(ws, "unit.py"), "accepted = 1\n")
        gitops.commit_wip(ws, "wip: skeleton")
        _write(os.path.join(ws, "unit.py"), "accepted = 2\n")
        gitops.amend(ws)
        _write(os.path.join(ws, "unit.py"), "tampered\n")
        gitops.restore_clean(ws)
        self.assertEqual(_read(os.path.join(ws, "unit.py")), "accepted = 2\n")


class GitignoreTests(GitopsTestCase):
    def test_append_preserves_existing_content(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        # No trailing newline: the append must add its own separator.
        _write(os.path.join(ws, ".gitignore"), "*.pyc\nbuild/")
        gitops.ensure_repo(ws)
        content = _read(os.path.join(ws, ".gitignore"))
        self.assertEqual(
            content,
            "*.pyc\nbuild/\n" + "\n".join(gitops.ignore_lines()) + "\n",
        )

    def test_no_duplicate_line_on_rerun(self):
        ws = self.make_repo(files={"seed.txt": "seed\n"})
        _write(os.path.join(ws, ".gitignore"), "*.pyc\nbuild/")
        gitops.ensure_repo(ws)
        after_first = _read(os.path.join(ws, ".gitignore"))
        gitops.ensure_repo(ws)
        after_second = _read(os.path.join(ws, ".gitignore"))
        self.assertEqual(after_first, after_second)
        self.assertEqual(
            after_second.splitlines().count(gitops.IGNORE_LINE), 1
        )


class EnabledTests(GitopsTestCase):
    def test_enabled_flag(self):
        self.assertFalse(gitops.enabled({}))
        self.assertFalse(gitops.enabled({"git": None}))
        self.assertFalse(gitops.enabled({"git": {}}))
        self.assertFalse(gitops.enabled({"git": {"enabled": False}}))
        self.assertTrue(gitops.enabled({"git": {"enabled": True}}))


class HookIsolationTests(GitopsTestCase):
    """A builder-controllable git hook must never run for orchestrator commits
    — a builder could install .git/hooks/pre-commit or set core.hooksPath to
    execute its code inside an orchestrator commit."""

    def _failing_hook(self, hooks_dir):
        os.makedirs(hooks_dir, exist_ok=True)
        hook = os.path.join(hooks_dir, "pre-commit")
        _write(hook, "#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)

    def test_default_pre_commit_hook_does_not_run(self):
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        self._failing_hook(os.path.join(ws, ".git", "hooks"))
        _write(os.path.join(ws, "f.txt"), "x\n")
        # If the failing hook ran, the commit would abort with a GitError.
        self.assertTrue(gitops.commit_wip(ws, "wip"))

    def test_core_hookspath_override_is_ignored(self):
        ws = self.make_repo()
        gitops.ensure_repo(ws)
        hooks = os.path.join(ws, "evil-hooks")
        self._failing_hook(hooks)
        # A builder points hooks at its own dir via repo config; the
        # command-line -c override must still win.
        self.git(ws, "config", "core.hooksPath", hooks)
        _write(os.path.join(ws, "f.txt"), "x\n")
        self.assertTrue(gitops.commit_wip(ws, "wip"))


if __name__ == "__main__":
    unittest.main()
