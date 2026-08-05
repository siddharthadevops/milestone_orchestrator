import os
import unittest
from unittest import mock

from orchestrator import gitsync, runners


class ActiveRunGateTest(unittest.TestCase):
    """The one deterministic refusal: never hand over a live worktree."""

    def test_a_live_run_in_the_same_workspace_blocks(self):
        runs = [{"workspace": "/tmp/ws", "alive": True, "id": "r1"}]
        self.assertIsNotNone(gitsync.active_run_blocking(runs, "/tmp/ws"))

    def test_a_stopped_run_does_not_block(self):
        runs = [{"workspace": "/tmp/ws", "alive": False, "id": "r1"}]
        self.assertIsNone(gitsync.active_run_blocking(runs, "/tmp/ws"))

    def test_a_live_run_elsewhere_does_not_block(self):
        runs = [{"workspace": "/tmp/other", "alive": True, "id": "r1"}]
        self.assertIsNone(gitsync.active_run_blocking(runs, "/tmp/ws"))

    def test_the_same_directory_reached_by_another_name_still_blocks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            real = os.path.join(tmp, "ws")
            os.makedirs(real)
            link = os.path.join(tmp, "alias")
            os.symlink(real, link)
            runs = [{"workspace": link, "alive": True, "id": "r1"}]
            self.assertIsNotNone(gitsync.active_run_blocking(runs, real))

    def test_a_run_without_a_workspace_is_ignored(self):
        runs = [{"workspace": None, "alive": True, "id": "r1"}]
        self.assertIsNone(gitsync.active_run_blocking(runs, "/tmp/ws"))


class MandateTest(unittest.TestCase):
    def test_the_prompt_states_the_non_negotiables(self):
        prompt = gitsync.build_prompt("/tmp/ws")
        self.assertIn("/tmp/ws", prompt)
        for rule in ("NEVER lose committed work", "No force push",
                     "SEALED milestone document", "Uncommitted local changes"):
            self.assertIn(rule, prompt)

    def test_run_sync_calls_the_named_family_in_the_workspace(self):
        seen = {}

        class FakeResult:
            text = "  aligned: fast-forwarded 3 commits  "
            duration_s = 1.5
            token_usage = None

        class FakeRunner:
            def call(self, family, prompt, workspace, model=None, effort=None):
                seen.update(family=family, prompt=prompt, workspace=workspace,
                            model=model, effort=effort)
                return FakeResult()

        out = gitsync.run_sync(
            {}, {}, "codex", "/tmp/ws", model="m", effort="high",
            runner=FakeRunner(),
        )
        self.assertEqual(seen["family"], "codex")
        self.assertEqual(seen["workspace"], os.path.abspath("/tmp/ws"))
        self.assertEqual(seen["model"], "m")
        self.assertEqual(out["report"], "aligned: fast-forwarded 3 commits")
        self.assertEqual(out["family"], "codex")



class ExitCodeTest(unittest.TestCase):
    """A prose answer is not evidence of success."""

    class _Result:
        def __init__(self, code):
            self.text = "stopped: the remote rejected authentication"
            self.exit_code = code
            self.duration_s = 1.0
            self.token_usage = None

    def _run(self, code):
        outer = self

        class FakeRunner:
            def call(self, *_a, **_kw):
                return outer._Result(code)

        return gitsync.run_sync({}, {}, "codex", "/tmp/ws", runner=FakeRunner())

    def test_a_clean_exit_is_reported_as_such(self):
        out = self._run(0)
        self.assertEqual(out["exit_code"], 0)
        self.assertTrue(out["clean_exit"])

    def test_a_failing_exit_is_not_hidden_by_a_readable_report(self):
        out = self._run(1)
        self.assertEqual(out["exit_code"], 1)
        self.assertFalse(out["clean_exit"])
        self.assertIn("stopped", out["report"])

    def test_the_watchdog_settings_reach_the_runner(self):
        seen = {}
        real = runners.SubprocessRunner

        class Spy(real):
            def __init__(self, commands, timeouts, **kw):
                seen.update(kw)
                super().__init__(commands, timeouts, **kw)

            def call(self, *_a, **_kw):
                return ExitCodeTest._Result(0)

        with mock.patch.object(runners, "SubprocessRunner", Spy):
            gitsync.run_sync(
                {}, {}, "codex", "/tmp/ws",
                stall_window_s=900, stall_min_cpu_s=1.0,
            )
        self.assertEqual(seen.get("stall_window_s"), 900)
        self.assertEqual(seen.get("stall_min_cpu_s"), 1.0)

class PathOverlapTest(unittest.TestCase):
    """Ownership is containment in BOTH directions, and case-insensitive."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.realpath(self._tmp.name)
        self.area = os.path.join(self.base, "Area")
        self.inner = os.path.join(self.area, "nested")
        self.sibling = os.path.join(self.base, "other")
        for path in (self.area, self.inner, self.sibling):
            os.makedirs(path)

    def test_the_same_directory_overlaps(self):
        self.assertTrue(gitsync.paths_overlap(self.area, self.area))

    def test_a_worker_inside_the_area_is_an_owner(self):
        # The case the operator surfaced: a run nested in the tree being
        # merged used to pass the gate because only equality was tested.
        self.assertTrue(gitsync.paths_overlap(self.inner, self.area))

    def test_a_worker_owning_an_ancestor_is_an_owner_too(self):
        self.assertTrue(gitsync.paths_overlap(self.base, self.area))

    def test_siblings_do_not_overlap(self):
        # Letras vs Letras-milestones: syncing one must never be blocked
        # by the other, which is the whole point of choosing an area.
        self.assertFalse(gitsync.paths_overlap(self.sibling, self.area))
        self.assertFalse(
            gitsync.paths_overlap(self.area + "-milestones", self.area)
        )

    def test_case_aliases_of_one_directory_overlap(self):
        self.assertTrue(
            gitsync.paths_overlap(self.area.upper(), self.area)
        )
        self.assertTrue(
            gitsync.paths_overlap(self.inner.upper(), self.area)
        )

    def test_missing_and_empty_paths_are_not_owners(self):
        self.assertFalse(gitsync.paths_overlap(None, self.area))
        self.assertFalse(gitsync.paths_overlap("", self.area))
        self.assertFalse(
            gitsync.paths_overlap(
                os.path.join(self.base, "gone"), self.area
            )
        )

    def test_a_live_run_nested_in_the_area_blocks(self):
        runs = [{"workspace": self.inner, "alive": True, "id": "r1"}]
        self.assertIsNotNone(gitsync.active_run_blocking(runs, self.area))
        runs = [{"workspace": self.sibling, "alive": True, "id": "r1"}]
        self.assertIsNone(gitsync.active_run_blocking(runs, self.area))


class OutcomeTest(unittest.TestCase):
    """A refusal exits 0 like a success; only the verdict line tells them
    apart, and its absence is never read as good news."""

    def test_the_verdict_line_decides(self):
        self.assertEqual(
            gitsync.read_outcome("merged 2 commits\nRESULT: aligned", 0),
            "aligned",
        )
        self.assertEqual(
            gitsync.read_outcome("no remote\nRESULT: stopped", 0), "stopped"
        )

    def test_markdown_emphasis_around_the_verdict_still_reads(self):
        self.assertEqual(
            gitsync.read_outcome("done\n**RESULT: aligned**", 0), "aligned"
        )

    def test_a_missing_verdict_is_unknown_not_success(self):
        self.assertEqual(gitsync.read_outcome("I merged everything", 0),
                         "unknown")
        self.assertEqual(gitsync.read_outcome("", 0), "unknown")

    def test_a_verdict_buried_above_other_prose_does_not_count(self):
        # Only the LAST line is the verdict; text after it means the agent
        # did not follow the contract, so the answer is not trusted.
        self.assertEqual(
            gitsync.read_outcome("RESULT: aligned\nbut actually I stopped", 0),
            "unknown",
        )

    def test_a_failing_process_is_stopped_whatever_it_printed(self):
        self.assertEqual(
            gitsync.read_outcome("RESULT: aligned", 3), "stopped"
        )

    def test_run_sync_carries_the_outcome(self):
        class FakeRunner:
            def call(self, *_a, **_kw):
                class R:
                    text = "could not reach origin\nRESULT: stopped"
                    exit_code = 0
                    duration_s = 1.0
                    token_usage = None
                return R()

        out = gitsync.run_sync({}, {}, "codex", "/tmp/ws",
                               runner=FakeRunner())
        self.assertEqual(out["outcome"], "stopped")
        self.assertTrue(out["clean_exit"])


class VerdictEdgeTest(unittest.TestCase):
    """The verdict must be the last CONTENT, not merely present."""

    def test_a_fenced_verdict_with_prose_above_is_not_trusted(self):
        # A closing fence is content the agent put AFTER its verdict, so
        # the contract was not followed — and the prose above said it
        # refused. Reading that as success is the whole failure mode.
        self.assertEqual(
            gitsync.read_outcome(
                "I refused\n```\nRESULT: aligned\n```", 0
            ),
            "unknown",
        )

    def test_trailing_blank_lines_do_not_hide_the_verdict(self):
        self.assertEqual(
            gitsync.read_outcome("done\nRESULT: aligned\n\n   \n", 0),
            "aligned",
        )

    def test_a_quoted_verdict_still_reads(self):
        self.assertEqual(
            gitsync.read_outcome("done\n> RESULT: stopped", 0), "stopped"
        )

    def test_an_unknown_verdict_word_is_not_success(self):
        self.assertEqual(
            gitsync.read_outcome("done\nRESULT: probably", 0), "unknown"
        )


class RootContainmentTest(unittest.TestCase):
    def test_root_contains_everything(self):
        # "/" already ends in the separator, so the ordinary parent + sep
        # test built "//" and matched nothing.
        self.assertTrue(gitsync.paths_overlap("/", "/tmp"))
        self.assertTrue(gitsync.paths_overlap("/tmp", "/"))

    def test_root_does_not_overlap_itself_twice_over(self):
        self.assertTrue(gitsync.paths_overlap("/", "/"))

    def test_a_trailing_separator_does_not_change_ownership(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            area = os.path.join(os.path.realpath(tmp), "area")
            os.makedirs(os.path.join(area, "inner"))
            self.assertTrue(gitsync.paths_overlap(area + os.sep, area))
            self.assertTrue(
                gitsync.paths_overlap(
                    os.path.join(area, "inner"), area + os.sep
                )
            )

    def test_case_folding_follows_the_volume(self):
        # Folded only where the volume ignores case; on a case-sensitive
        # one two siblings differing in case are distinct trees and must
        # not block each other.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            upper = os.path.join(base, "Repo")
            lower = os.path.join(base, "repo")
            os.makedirs(upper)
            insensitive = os.path.lexists(lower)
            self.assertEqual(
                gitsync.paths_overlap(upper, lower), insensitive
            )


class CaseProbeTest(unittest.TestCase):
    """Case-insensitivity is proven by identity, never by existence."""

    def test_a_real_swap_cased_sibling_is_not_evidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            a = os.path.join(base, "Repo")
            b = os.path.join(base, "rEPO")
            os.makedirs(a)
            if os.path.lexists(b):
                self.skipTest("case-insensitive volume: siblings cannot exist")
            os.makedirs(b)
            # Both exist and are DIFFERENT directories, so the volume
            # honours case and they must not be treated as one tree.
            self.assertFalse(gitsync._ignores_case(a))
            self.assertFalse(gitsync.paths_overlap(a, b))

    def test_a_swap_cased_symlink_is_not_evidence(self):
        # samefile follows links, so a `rEPO -> Repo` symlink proved
        # insensitivity on a volume that has none. Identity is compared
        # without following, so the link is its own entry.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            a = os.path.join(base, "Repo")
            b = os.path.join(base, "rEPO")
            os.makedirs(a)
            if os.path.lexists(b):
                self.skipTest("case-insensitive volume: no link to make")
            os.symlink(a, b)
            self.assertFalse(gitsync._ignores_case(a))
            self.assertFalse(gitsync.paths_overlap(a, b))

    def test_an_alias_of_one_directory_is_evidence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.realpath(tmp)
            a = os.path.join(base, "Repo")
            os.makedirs(a)
            insensitive = os.path.lexists(os.path.join(base, "rEPO"))
            self.assertEqual(gitsync._ignores_case(a), insensitive)


if __name__ == "__main__":
    unittest.main()
