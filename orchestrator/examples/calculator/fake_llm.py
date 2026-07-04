#!/usr/bin/env python3
"""Deterministic fake LLM CLI for end-to-end orchestrator tests.

Reads a prompt on stdin, parses the KIND/FAMILY/WORKSPACE headers, performs
scripted real file edits in the workspace, and prints the contract JSON that
a well-behaved LLM worker would produce. Persistent call counters live in
WORKSPACE/.orchestrator/fake_state.json (excluded from workspace snapshots,
like all runtime bookkeeping).

Scripted scenario ("build a CLI calculator"):
  - skeleton draft proposes one slice; first codex review round finds one P3
    (missing non-goals) and fixes it; second is clean; claude clean; seal a1
    clean on both halves.
  - slice note drafts clean; both families clean; seal a1 clean.
  - implementation ships a deliberate bug (div multiplies) so the pre-review
    verification FAILS and the driver must run a fix_verification call.
  - codex impl round 1 finds one P3 (missing docstring) and fixes it; round 2
    clean; claude clean.
  - impl seal a1: claude half reports one P3 (missing README) -> seal_fix
    writes it -> seal a2 clean on both halves -> slice closes, milestone
    closes.
"""

import argparse
import json
import os
import sys


def read_headers(prompt):
    kind = family = workspace = None
    for line in prompt.splitlines():
        if line.startswith("KIND:"):
            kind = line.split(":", 1)[1].strip()
        elif line.startswith("FAMILY:"):
            family = line.split(":", 1)[1].strip()
        elif line.startswith("WORKSPACE:"):
            workspace = line.split(":", 1)[1].strip()
    return kind, family, workspace


def bump_counter(workspace, key):
    path = os.path.join(workspace, ".orchestrator", "fake_state.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    counters = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            counters = json.load(fh)
    counters[key] = counters.get(key, 0) + 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(counters, fh)
    return counters[key]


def write(workspace, rel, content):
    path = os.path.join(workspace, rel)
    os.makedirs(os.path.dirname(path) or workspace, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


RUN_CHECKS = '''import glob
import subprocess
import sys

if not glob.glob("test_*.py"):
    print("no tests yet")
    sys.exit(0)
sys.exit(
    subprocess.call(
        [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"]
    )
)
'''

CALC_BUGGY = '''import sys


def add(a, b):
    return a + b


def sub(a, b):
    return a - b


def mul(a, b):
    return a * b


def div(a, b):
    return a * b  # BUG: should divide


def main(argv):
    op, a, b = argv[0], float(argv[1]), float(argv[2])
    ops = {"add": add, "sub": sub, "mul": mul, "div": div}
    print(ops[op](a, b))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

CALC_FIXED = CALC_BUGGY.replace("return a * b  # BUG: should divide", "return a / b")

CALC_DOCSTRING = '"""Tiny CLI calculator: add/sub/mul/div."""\n\n' + CALC_FIXED

TESTS = '''import unittest

import calculator


class TestCalculator(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calculator.add(2, 3), 5)

    def test_sub(self):
        self.assertEqual(calculator.sub(5, 3), 2)

    def test_mul(self):
        self.assertEqual(calculator.mul(4, 3), 12)

    def test_div(self):
        self.assertEqual(calculator.div(12, 3), 4)


if __name__ == "__main__":
    unittest.main()
'''


def ok(kind, **extra):
    payload = {"status": "ok", "kind": kind}
    payload.update(extra)
    return payload


def respond(kind, family, workspace, count):
    if kind == "draft_skeleton":
        write(
            workspace,
            "docs/skeleton.md",
            "# Calculator milestone\n\nGoal: CLI calculator with tests.\n\n"
            "## Slices\n\n1. Calculator core\n",
        )
        write(workspace, "run_checks.py", RUN_CHECKS)
        return ok(
            kind,
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "Calculator core"}],
        )

    if kind == "draft_slice_note":
        write(
            workspace,
            "docs/slice-01.md",
            "# Slice 01 - Calculator core\n\nContracts: add/sub/mul/div are "
            "correct over floats; CLI prints the result.\nTests: unittest "
            "suite pins all four operations.\n",
        )
        return ok(kind, artifact="docs/slice-01.md")

    if kind == "implement":
        write(workspace, "calculator.py", CALC_BUGGY)
        write(workspace, "test_calculator.py", TESTS)
        return ok(kind, files_changed=["calculator.py", "test_calculator.py"])

    if kind == "fix_verification":
        write(workspace, "calculator.py", CALC_FIXED)
        return ok(
            kind,
            findings=[
                {
                    "id": "V1",
                    "severity": "P1",
                    "summary": "div() multiplied instead of dividing; "
                    "test_div failed",
                    "disposition": "fixed",
                    "consultation": None,
                }
            ],
            files_changed=["calculator.py"],
        )

    if kind == "review_round" and family == "codex":
        if count == 1:  # skeleton round 1: one P3, fixed
            with open(os.path.join(workspace, "docs/skeleton.md"), "a", encoding="utf-8") as fh:
                fh.write("\n## Non-goals\n\nNo scientific functions.\n")
            return ok(
                kind,
                findings=[
                    {
                        "id": "F1",
                        "severity": "P3",
                        "summary": "skeleton lacked explicit non-goals",
                        "disposition": "fixed",
                        "consultation": None,
                    }
                ],
                files_changed=["docs/skeleton.md"],
            )
        if count == 4:  # impl round 1: one P3, fixed
            write(workspace, "calculator.py", CALC_DOCSTRING)
            return ok(
                kind,
                findings=[
                    {
                        "id": "F1",
                        "severity": "P3",
                        "summary": "calculator module lacked a docstring",
                        "disposition": "fixed",
                        "consultation": None,
                    }
                ],
                files_changed=["calculator.py"],
            )
        return ok(kind, findings=[], files_changed=[])

    if kind == "review_round":  # claude rounds: always clean
        return ok(kind, findings=[], files_changed=[])

    if kind == "seal_half":
        if family == "claude" and count == 3:  # impl seal a1: one P3
            return ok(
                kind,
                findings=[
                    {
                        "id": "S1",
                        "severity": "P3",
                        "summary": "workspace lacks a README describing CLI usage",
                    }
                ],
            )
        return ok(kind, findings=[])

    if kind == "seal_fix":
        write(
            workspace,
            "README.md",
            "# Calculator\n\nUsage: python3 calculator.py add|sub|mul|div A B\n",
        )
        return ok(
            kind,
            findings=[
                {
                    "id": "S1",
                    "severity": "P3",
                    "summary": "workspace lacks a README describing CLI usage",
                    "disposition": "fixed",
                    "consultation": None,
                }
            ],
            files_changed=["README.md"],
        )

    return {
        "status": "blocked",
        "kind": kind,
        "blocked_reason": "fake_llm has no script for kind %r" % kind,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()

    prompt = sys.stdin.read()
    kind, family, workspace = read_headers(prompt)
    workspace = workspace or args.workspace
    if kind is None:
        print(json.dumps({"status": "blocked", "kind": "unknown",
                          "blocked_reason": "prompt had no KIND header"}))
        return 0
    count = bump_counter(workspace, "%s:%s" % (kind, family))
    print(json.dumps(respond(kind, family, workspace, count)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
