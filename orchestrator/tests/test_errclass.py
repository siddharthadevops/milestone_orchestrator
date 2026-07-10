"""Failure classification (orchestrator/errclass.py): deterministic
patterns, quota reset-time parsing, and the never-blocking LLM fallback.
"""

import unittest
from datetime import datetime, timedelta, timezone

from orchestrator import errclass
from orchestrator.runners import RunnerResult


class TestPatterns(unittest.TestCase):
    def test_login(self):
        # The real message from the live incident.
        self.assertEqual(
            errclass.classify_text("Not logged in · Please run /login"),
            "login",
        )
        self.assertEqual(errclass.classify_text("401 Unauthorized"), "login")

    def test_quota(self):
        self.assertEqual(
            errclass.classify_text(
                "You've hit your usage limit. Your limit resets at 00:37."
            ),
            "quota",
        )
        self.assertEqual(
            errclass.classify_text("quota exceeded, try again at 4:00 PM"),
            "quota",
        )

    def test_busy_and_network(self):
        self.assertEqual(
            errclass.classify_text("Error: 529 overloaded"), "busy")
        self.assertEqual(
            errclass.classify_text("503 Service Unavailable"), "busy")
        self.assertEqual(
            errclass.classify_text("fetch failed: getaddrinfo ENOTFOUND"),
            "network",
        )
        self.assertEqual(
            errclass.classify_text("ECONNRESET while streaming"), "network")

    def test_no_match(self):
        self.assertIsNone(errclass.classify_text("some content nonsense"))
        self.assertIsNone(errclass.classify_text(""))

    def test_provider_capacity_banners_are_busy(self):
        # Correlated outages take the LLM classifier down too, so the
        # provider's own capacity banner must be deterministically typed
        # (regression: a live seal_half stranded on "unknown" because these
        # were unclassified). See the canon incident 2026-07-06.
        codex = ("family codex exited 1 with no output; stderr tail: "
                 "ERROR: Selected model is at capacity. Please try a "
                 "different model.")
        self.assertEqual(errclass.classify_text(codex), "busy")
        self.assertIn("busy", errclass.AUTO_RESUMABLE)
        self.assertEqual(
            errclass.classify_text('API error {"type":"overloaded_error"}'),
            "busy")
        # Length guard still prevents worker prose from cosplaying as infra.
        self.assertIsNone(
            errclass.classify_text("discussing server capacity " * 40))


class TestParseResumeAt(unittest.TestCase):
    NOW = datetime(2026, 7, 5, 23, 50, tzinfo=timezone.utc)

    def test_clock_time_future_same_day(self):
        out = errclass.parse_resume_at("resets at 23:59", now=self.NOW)
        self.assertTrue(out.startswith("2026-07-05T23:59"))

    def test_clock_time_rolls_to_tomorrow(self):
        # 00:37 announced at 23:50 means tonight — the NEXT occurrence.
        out = errclass.parse_resume_at("resets at 00:37", now=self.NOW)
        self.assertTrue(out.startswith("2026-07-06T00:37"), out)

    def test_pm_and_bare_hour(self):
        now = datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc)
        out = errclass.parse_resume_at("try again at 3:15 PM", now=now)
        self.assertTrue(out.startswith("2026-07-05T15:15"), out)
        out = errclass.parse_resume_at("resets 4pm", now=now)
        self.assertTrue(out.startswith("2026-07-05T16:00"), out)

    def test_relative(self):
        now = datetime(2026, 7, 5, 4, 0, tzinfo=timezone.utc)
        out = errclass.parse_resume_at("available again in 5 hours", now=now)
        self.assertTrue(out.startswith("2026-07-05T09:00"), out)
        out = errclass.parse_resume_at("retry in 30 minutes", now=now)
        self.assertTrue(out.startswith("2026-07-05T04:30"), out)

    def test_garbage(self):
        self.assertIsNone(errclass.parse_resume_at("no time here"))
        self.assertIsNone(errclass.parse_resume_at(None))

    def test_codex_dated_banner(self):
        # The live 2026-07-10 banner: a date phrase sits between "try
        # again at" and the clock. The date must be consumed whole —
        # a partial match would read the year's digits as the hour —
        # and the announced window (00:26) must win over the +30min
        # default the run actually fell back to that night.
        now = datetime(2026, 7, 10, 23, 38, tzinfo=timezone.utc)
        out = errclass.parse_resume_at(
            "ERROR: You've hit your usage limit. Visit "
            "https://chatgpt.com/codex/settings/usage to purchase more "
            "credits or try again at Jul 11th, 2026 12:26 AM.",
            now=now,
        )
        self.assertTrue(out.startswith("2026-07-11T00:26"), out)

    def test_dated_banner_without_year(self):
        now = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
        out = errclass.parse_resume_at(
            "try again at July 10, 4:15 PM", now=now)
        self.assertTrue(out.startswith("2026-07-10T16:15"), out)


class _FakeRunner(object):
    def __init__(self, text=None, raise_exc=None):
        self.text = text
        self.raise_exc = raise_exc
        self.calls = []
        self.timeouts = {}

    def call(self, family, prompt, workspace, model=None, effort=None,
             timeout_override=None):
        self.calls.append((family, prompt))
        if self.raise_exc:
            raise self.raise_exc
        return RunnerResult(self.text, 0, 1.0)


class TestClassifyChain(unittest.TestCase):
    def test_pattern_wins_without_llm_call(self):
        runner = _FakeRunner('{"error_type": "busy"}')
        etype, resume_at, _ = errclass.classify_failure(
            ["usage limit reached, resets at 02:00"],
            runner=runner, opposite_family="claude", workspace="/ws",
        )
        self.assertEqual(etype, "quota")
        self.assertIsNotNone(resume_at)
        self.assertEqual(runner.calls, [])  # patterns decided; no LLM

    def test_llm_fallback_enum(self):
        runner = _FakeRunner(
            '{"error_type": "busy", "resume_at": null, '
            '"evidence": "weird overload phrasing"}'
        )
        etype, resume_at, evidence = errclass.classify_failure(
            ["some unrecognizable failure text"],
            runner=runner, opposite_family="claude", workspace="/ws",
        )
        self.assertEqual(etype, "busy")
        self.assertIsNone(resume_at)
        self.assertEqual(len(runner.calls), 1)
        self.assertEqual(runner.calls[0][0], "claude")

    def test_llm_garbage_degrades_to_unknown(self):
        runner = _FakeRunner("not json at all")
        etype, _, _ = errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws",
        )
        self.assertEqual(etype, "unknown")

    def test_llm_crash_degrades_to_unknown(self):
        runner = _FakeRunner(raise_exc=RuntimeError("classifier CLI dead"))
        etype, _, evidence = errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws",
        )
        self.assertEqual(etype, "unknown")
        self.assertIn("classifier unavailable", evidence)

    def test_llm_disabled(self):
        runner = _FakeRunner('{"error_type": "busy"}')
        etype, _, _ = errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws", use_llm=False,
        )
        self.assertEqual(etype, "unknown")
        self.assertEqual(runner.calls, [])

    def test_bad_enum_from_llm_is_unknown(self):
        runner = _FakeRunner('{"error_type": "meteor_strike"}')
        etype, _, _ = errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws",
        )
        self.assertEqual(etype, "unknown")

    def test_on_llm_raw_captures_classifier_response(self):
        # The classifier's I/O must be surfaced for persistence, so an
        # "unknown" verdict is auditable after the fact.
        runner = _FakeRunner('{"error_type": "network"}')
        seen = []
        errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws",
            on_llm_raw=lambda fam, prompt, raw: seen.append((fam, prompt, raw)),
        )
        self.assertEqual(len(seen), 1)
        fam, prompt, raw = seen[0]
        self.assertEqual(fam, "claude")
        self.assertIn("mystery", prompt)            # the failing text
        self.assertIn("network", raw)               # claude's actual reply

    def test_on_llm_raw_captures_the_error_when_classifier_call_fails(self):
        # The correlated-outage case: the classifier CALL itself throws. The
        # sink must still receive the error so we can tell "classifier down"
        # from "classifier judged it garbage".
        runner = _FakeRunner(raise_exc=RuntimeError("claude also at capacity"))
        seen = []
        etype, _, _ = errclass.classify_failure(
            ["mystery"], runner=runner, opposite_family="claude",
            workspace="/ws",
            on_llm_raw=lambda fam, prompt, raw: seen.append(raw),
        )
        self.assertEqual(etype, "unknown")
        self.assertEqual(len(seen), 1)
        self.assertIn("claude also at capacity", seen[0])

    def test_on_llm_raw_not_called_when_patterns_decide(self):
        runner = _FakeRunner('{"error_type": "busy"}')
        seen = []
        errclass.classify_failure(
            ["Error: 529 overloaded"], runner=runner,
            opposite_family="claude", workspace="/ws",
            on_llm_raw=lambda *a: seen.append(a),
        )
        self.assertEqual(seen, [])  # pattern matched; LLM never ran


class TestHostileProse(unittest.TestCase):
    """Worker CONTENT that merely discusses infra words must never be
    typed as an infra failure (the length gate + tightened patterns)."""

    def test_long_prose_never_classifies(self):
        prose = ("The login handler lacks proper authentication checks. "
                 "Also honor the API quota and back off. " * 20)
        self.assertGreater(len(prose), errclass.MAX_CLASSIFIABLE_CHARS)
        self.assertIsNone(errclass.classify_text(prose))

    def test_line_numbers_are_not_status_codes(self):
        self.assertIsNone(
            errclass.classify_text("See driver.py:429 where the loop increments"))
        self.assertIsNone(
            errclass.classify_text("The bug is at service.py:503 in guard_scan"))

    def test_short_infra_banners_still_classify(self):
        self.assertEqual(
            errclass.classify_text("HTTP status 529: overloaded"), "busy")
        self.assertEqual(
            errclass.classify_text("family codex timed out after 900s"),
            "timeout",
        )

    def test_prose_relative_times_do_not_parse(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 5, 13, 0, tzinfo=timezone.utc)
        self.assertIsNone(errclass.parse_resume_at(
            "quota logic appears in 3 modules", now=now))
        self.assertIsNone(errclass.parse_resume_at(
            "quota check is reached in 2 hops", now=now))

    def test_foreign_timezone_refused(self):
        self.assertIsNone(errclass.parse_resume_at(
            "resets at 5pm (America/Los_Angeles)"))
        self.assertIsNone(errclass.parse_resume_at("resets at 5pm PST"))

    def test_invalid_first_time_scans_to_valid_one(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 5, 9, 0, tzinfo=timezone.utc)
        out = errclass.parse_resume_at(
            "resets 99 nonsense, the real one resets at 3:15pm", now=now)
        self.assertTrue(out and out.startswith("2026-07-05T15:15"), out)


class TestNormalizeResumeAt(unittest.TestCase):
    from datetime import datetime, timezone
    NOW = datetime(2026, 7, 5, 12, 0, tzinfo=timezone.utc)

    def test_naive_iso_gets_offset(self):
        out = errclass.normalize_resume_at("2026-07-05T14:00:00",
                                           now=self.NOW)
        self.assertTrue(out.startswith("2026-07-05T14:00:00+"), out)

    def test_far_future_clamped_to_24h(self):
        out = errclass.normalize_resume_at("2999-01-01T00:00:00+00:00",
                                           now=self.NOW)
        self.assertTrue(out.startswith("2026-07-06T12:00"), out)

    def test_past_clamped_to_now_plus_minute(self):
        out = errclass.normalize_resume_at("2020-01-01T00:00:00+00:00",
                                           now=self.NOW)
        self.assertTrue(out.startswith("2026-07-05T12:01"), out)

    def test_garbage_is_none(self):
        self.assertIsNone(errclass.normalize_resume_at("mañana", now=self.NOW))
        self.assertIsNone(errclass.normalize_resume_at(None, now=self.NOW))


if __name__ == "__main__":
    unittest.main()
