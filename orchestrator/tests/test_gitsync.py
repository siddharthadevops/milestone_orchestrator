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


if __name__ == "__main__":
    unittest.main()


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
