"""Phase-2 bit-equivalence GATE for the stage interpreter.

A run under the `legacy` compatibility profile MUST be ledger-equivalent to
the same run with no profile at all — the interpreter's family_until_clean
path may not diverge by a single byte from the pre-reform flow. This test
is that gate; nothing in phase 2 advances until it is green.

"Ledger-equivalent" is pinned PRECISELY (operator rider): identical event
sequence AND identical final unit states, modulo an EXPLICIT list of
fields that are legitimately nondeterministic between two runs living in
two different workspaces — timestamps, wall-clock durations, raw-output
paths, git object ids, epoch stamps, and the absolute workspace path. Any
difference in a field NOT on that list is a REAL divergence and fails the
gate: the exclusion list can never rot into "roughly similar".

Both runs drive the calculator fake-CLI scenario through the real CLI
entrypoints, exactly like test_e2e_fakecli — one run with a bare config,
one with `legacy` embedded in its config — and the two on-disk ledgers are
compared field-by-field.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

from orchestrator import profiles, state as st

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FAKE_LLM = os.path.join(
    REPO, "orchestrator", "examples", "calculator", "fake_llm.py"
)
GOAL = "Build a small CLI calculator (add/sub/mul/div) with unit tests"

# Fields whose values are legitimately nondeterministic between two runs in
# two different workspaces. Stripped RECURSIVELY (by key name) before the
# comparison. Anything not listed here that differs is a real divergence.
# This list is the whole contract of the gate — keep it explicit and small.
NONDET_FIELDS = frozenset({
    "at",             # ISO timestamps on every event / round / seal
    "duration_s",     # wall-clock worker durations
    "raw_path",       # per-workspace path to the raw worker output
    "workspace",      # the two runs live in different absolute dirs
    "created_at",     # state creation timestamp
    "created_epoch",
    "last_event_epoch",
    "opened_epoch",
    "closed_epoch",
    "resume_at",
    # git object ids — different repos, different shas
    "sha", "wip_sha", "gate_sha", "gate_commit", "commit", "parent", "head",
})


def _strip(obj):
    """A deep copy with every NONDET_FIELDS key removed at any depth."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items()
                if k not in NONDET_FIELDS}
    if isinstance(obj, list):
        return [_strip(x) for x in obj]
    return obj


def _normalize_ws(obj, ws):
    """Neutralize the one nondeterministic SUBSTRING that survives key
    stripping: the run's absolute workspace path, which is embedded inside
    captured suite output (tracebacks name `<ws>/test_calculator.py`). Each
    run's own workspace path is replaced with a fixed placeholder, so the
    deterministic remainder of the output is still compared byte-for-byte —
    a genuinely different suite output would still fail the gate."""
    if isinstance(obj, dict):
        return {k: _normalize_ws(v, ws) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_ws(x, ws) for x in obj]
    if isinstance(obj, str):
        return obj.replace(ws, "<WS>")
    return obj


def _diffs(a, b, path=""):
    """Every leaf-level difference between two stripped structures, as
    (path, a_value, b_value) triples. Structural mismatches (differing
    keys / list lengths) are reported at their path and not descended."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            out.append((path + " {keys}", sorted(a), sorted(b)))
            return out
        for k in a:
            out.extend(_diffs(a[k], b[k], "%s.%s" % (path, k)))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path + " {len}", len(a), len(b)))
            return out
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(_diffs(x, y, "%s[%d]" % (path, i)))
    elif a != b:
        out.append((path, a, b))
    return out


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "orchestrator.driver"] + list(args),
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )


def _base_config():
    return {
        "commands": {
            "codex": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
            "claude": ["python3", FAKE_LLM, "--workspace", "{workspace}"],
        },
        "timeouts": {"codex": 60, "claude": 60},
        "verification": ["python3 run_checks.py"],
        "max_rounds_per_family": 6,
        "max_seal_attempts": 4,
        "git": {"enabled": True},
        "acts": {"fixer": "codex", "delta_review": "codex",
                 "consultation": "opposite"},
        "max_fix_loops": 4,
        "docs_dir": "docs",
        "error_classifier": False,
    }


def _run_scenario(tmpdir, name, extra_config):
    """Init + run the calculator scenario in its own git workspace under
    tmpdir; return the final on-disk state dict."""
    work = os.path.join(tmpdir, name)
    os.makedirs(work)
    subprocess.run(["git", "-C", work, "init", "-q"], check=True, timeout=60)
    config = _base_config()
    config.update(extra_config)
    cfg_path = os.path.join(tmpdir, "%s-config.json" % name)
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    p_init = _cli("init", "--goal", GOAL, "--workspace", work,
                  "--config", cfg_path)
    assert p_init.returncode == 0, "init failed: %s" % p_init.stderr
    p_run = _cli("run", "--workspace", work)
    assert p_run.returncode == 0, "run failed:\n%s\n%s" % (
        p_run.stdout, p_run.stderr)
    return st.load(os.path.join(work, ".orchestrator", "state.json"))


class ProfileEquivalenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="orch-equiv-")
        cls.addClassCleanup(cls.tmp.cleanup)
        # Run A: no profile (the pre-reform flow).
        cls.state_plain = _run_scenario(cls.tmp.name, "plain", {})
        # Run B: the `legacy` compatibility profile, embedded in the config
        # exactly as service.create_run will embed a service-created run's
        # profile snapshot.
        legacy = copy.deepcopy(profiles.SEEDS["legacy"]["profile"])
        cls.state_legacy = _run_scenario(cls.tmp.name, "legacy", {
            "profile": legacy,
            "profile_ref": {"name": "legacy", "version": 1,
                            "hash": profiles.semantic_hash(legacy)},
        })

    def _assert_equivalent(self, a, b, what):
        # `a` is always the plain run, `b` the legacy run (all call sites).
        a = _strip(_normalize_ws(a, self.state_plain["workspace"]))
        b = _strip(_normalize_ws(b, self.state_legacy["workspace"]))
        diffs = _diffs(a, b)
        if diffs:
            lines = ["%s: %d divergence(s) after stripping nondeterministic "
                     "fields:" % (what, len(diffs))]
            for p, x, y in diffs[:25]:
                lines.append("  %s\n    plain : %r\n    legacy: %r"
                             % (p, x, y))
            self.fail("\n".join(lines))

    def test_event_sequence_equivalent(self):
        # The full event ledger: same length, same types, same payloads
        # (minus the excluded fields), in the same order.
        self.assertEqual(
            [e["type"] for e in self.state_plain["events"]],
            [e["type"] for e in self.state_legacy["events"]],
            "event TYPE sequence diverged",
        )
        self._assert_equivalent(
            self.state_plain["events"], self.state_legacy["events"],
            "event ledger")

    def test_unit_states_equivalent(self):
        # Every unit's kind/status/rounds/seals/draft — the whole record.
        self._assert_equivalent(
            self.state_plain["units"], self.state_legacy["units"],
            "unit states")

    def test_milestone_and_shape_equivalent(self):
        for key in ("goal", "milestone", "suite_command", "failure"):
            self._assert_equivalent(
                self.state_plain.get(key), self.state_legacy.get(key),
                "state[%r]" % key)
        # Both actually reached a closed milestone (guards against two
        # runs that "agree" only because both died identically early).
        self.assertEqual(self.state_plain["milestone"]["status"], "closed")
        self.assertEqual(self.state_legacy["milestone"]["status"], "closed")

    def test_legacy_run_recorded_the_profile(self):
        # Sanity: run B really did carry the legacy profile (else the gate
        # would be comparing two profile-less runs and proving nothing).
        cfg = self.state_legacy["config"]
        self.assertEqual(cfg["profile_ref"]["name"], "legacy")
        self.assertEqual(cfg["profile"]["compat"], True)
        self.assertNotIn("profile", self.state_plain["config"])


class EquivalenceMachineryTest(unittest.TestCase):
    """Guards the gate's OWN comparison logic against rot: it must catch a
    real payload difference and must ignore exactly the excluded fields —
    no more, no less. Cheap (no scenario runs)."""

    def test_real_difference_is_caught(self):
        a = {"type": "round_recorded", "findings": 1}
        b = {"type": "round_recorded", "findings": 2}
        self.assertTrue(_diffs(_strip(a), _strip(b)))

    def test_excluded_fields_are_ignored(self):
        a = {"type": "x", "at": "t1", "duration_s": 3, "sha": "aaa",
             "findings": 0}
        b = {"type": "x", "at": "t2", "duration_s": 9, "sha": "bbb",
             "findings": 0}
        self.assertEqual(_diffs(_strip(a), _strip(b)), [])

    def test_non_excluded_field_still_compared(self):
        # A field that merely LOOKS incidental but is not on the list must
        # still be compared — the list is closed.
        a = {"stage": "pre_review"}
        b = {"stage": "pre_seal"}
        self.assertTrue(_diffs(_strip(a), _strip(b)))

    def test_structural_mismatch_is_caught(self):
        self.assertTrue(_diffs({"a": 1}, {"a": 1, "b": 2}))
        self.assertTrue(_diffs([1, 2], [1, 2, 3]))

    def test_ws_normalization_neutralizes_only_the_path(self):
        norm = _normalize_ws({"out": "/tmp/ws/x.py failed: 3 != 4"}, "/tmp/ws")
        self.assertEqual(norm, {"out": "<WS>/x.py failed: 3 != 4"})


if __name__ == "__main__":
    unittest.main()
