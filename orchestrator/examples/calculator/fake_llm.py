#!/usr/bin/env python3
"""Deterministic fake LLM CLI for end-to-end orchestrator tests.

Reads a prompt on stdin, parses the KIND/FAMILY/WORKSPACE headers, performs
scripted real file edits in the workspace, and prints the contract JSON that
a well-behaved worker would produce. Call counters persist in
WORKSPACE/.orchestrator/fake_state.json.

Scripted scenario ("build a CLI calculator") under the review/fix
separation model (reviewers report only; a fixer triages):

  skeleton:
    codex round 1 reports a missing-non-goals finding -> fixer fixes it ->
    delta review clean -> amend -> codex round 2 clean -> claude round 1
    reports an "ambiguous goal wording" finding -> fixer REJECTS it with a
    consultation and a prevention edit -> claude round 2 stubbornly
    re-raises the same complaint without contests -> fixer kills it by
    pointer (rejected_adjudicated, zero consultations) -> claude round 3
    clean -> double seal clean -> gate.
  slice note: clean everywhere, seal first try.
  implementation:
    deliberate div bug -> verification fails -> fixer repairs it (delta
    review + amend) -> codex round 1 reports a docstring finding -> fixer
    fixes -> codex round 2 clean -> claude clean -> seal a1: claude half
    reports a missing README -> fixer writes it -> seal a2 clean -> gate ->
    milestone closes.
"""

import argparse
import json
import os
import re
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


def parse_queued(prompt):
    """Extract the queued findings a fix_findings prompt carries."""
    findings = []
    in_block = False
    for line in prompt.splitlines():
        if line.startswith("QUEUED FINDINGS"):
            in_block = True
            continue
        if in_block:
            m = re.match(r"^- (\S+) \[(P\d)\] (.*)$", line)
            if m:
                summary = re.sub(r" \[CONTESTS .*$", "", m.group(3))
                findings.append(
                    {"id": m.group(1), "severity": m.group(2), "summary": summary}
                )
            elif line.startswith("  "):
                continue
            elif findings and not line.startswith("- "):
                break
    return findings


def parse_first_registry_id(prompt):
    in_block = False
    for line in prompt.splitlines():
        if line.startswith("ADJUDICATED REJECTIONS"):
            in_block = True
            continue
        if in_block:
            m = re.match(r"^- \[([^\]]+)\]", line)
            if m:
                return m.group(1)
            if line.startswith(("ACCESS", "PROCESS AUTHORITY", "OUTPUT CONTRACT")):
                break
    return None


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


def append(workspace, rel, content):
    with open(os.path.join(workspace, rel), "a", encoding="utf-8") as fh:
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


def report(kind, findings):
    for finding in findings:
        finding["validity"] = {
            "permitted_baseline": "the documented calculator behavior",
            "actual_outcome": finding["summary"],
            "incremental_harm": "the candidate misses that behavior",
            "exceeds_baseline": True,
        }
    return ok(kind, findings=findings)


def respond(kind, family, workspace, count, prompt):
    # ---- drafts ----------------------------------------------------------
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

    # ---- report-only reviews --------------------------------------------
    if kind == "review_round" and family == "codex":
        if count == 1:  # skeleton r1
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "skeleton lacks explicit non-goals"}
            ])
        if count == 4:  # impl r1
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "calculator module lacks a docstring"}
            ])
        return report(kind, [])

    if kind == "review_round" and family == "claude":
        if count == 1:  # skeleton claude r1
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "goal wording is ambiguous about float support"}
            ])
        if count == 2:  # the stubborn re-raise, no contests, no new evidence
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "goal wording is ambiguous about float support"}
            ])
        return report(kind, [])

    if kind == "delta_review":
        return report(kind, [])  # every fix delta in this scenario is green

    if kind == "seal_half":
        if family == "claude" and count == 3:  # impl seal a1
            return report(kind, [
                {"id": "S1", "severity": "P3",
                 "summary": "workspace lacks a README describing CLI usage"}
            ])
        return report(kind, [])

    # ---- the fixer -------------------------------------------------------
    if kind == "fix_findings":
        queued = parse_queued(prompt)

        def echo(disposition, **extra):
            out = []
            for f in queued:
                entry = {
                    "id": f["id"],
                    "severity": f["severity"],
                    "summary": f["summary"],
                    "disposition": disposition,
                    "consultation": None,
                    "validity": {
                        "permitted_baseline": (
                            "the documented calculator behavior"
                        ),
                        "actual_outcome": f["summary"],
                        "incremental_harm": (
                            "the candidate misses that behavior"
                            if disposition in ("fixed", "blocked")
                            else "no harm beyond the documented behavior"
                        ),
                        "exceeds_baseline": disposition in (
                            "fixed", "blocked"
                        ),
                    },
                }
                entry.update(extra)
                out.append(entry)
            return out

        if count == 1:  # skeleton: concede non-goals
            append(workspace, "docs/skeleton.md",
                   "\n## Non-goals\n\nNo scientific functions.\n")
            return ok(kind, findings=echo("fixed"),
                      files_changed=["docs/skeleton.md"])
        if count == 2:  # skeleton: dissent on "ambiguous wording"
            append(workspace, "docs/skeleton.md",
                   "\nNote: operations are defined over floats "
                   "(clarified after review).\n")
            return ok(
                kind,
                findings=echo(
                    "rejected",
                    consultation={
                        "resolution": "opposite family agreed the goal was "
                        "already float-typed by the CLI contract; wording "
                        "clarified for readability only"
                    },
                    prevention={
                        "documented_in": "docs/skeleton.md",
                        "note": "explicit float-support note added",
                    },
                ),
                files_changed=["docs/skeleton.md"],
            )
        if count == 3:  # the stubborn duplicate dies by pointer
            ref = parse_first_registry_id(prompt) or "unknown"
            return ok(
                kind,
                findings=echo("rejected_adjudicated", adjudication_ref=ref),
                files_changed=[],
            )
        if count == 4:  # verification failure: repair div
            write(workspace, "calculator.py", CALC_FIXED)
            return ok(kind, findings=echo("fixed"),
                      files_changed=["calculator.py"])
        if count == 5:  # impl round finding: docstring
            write(workspace, "calculator.py", CALC_DOCSTRING)
            return ok(kind, findings=echo("fixed"),
                      files_changed=["calculator.py"])
        if count == 6:  # seal finding: README
            write(workspace, "README.md",
                  "# Calculator\n\nUsage: python3 calculator.py "
                  "add|sub|mul|div A B\n")
            return ok(kind, findings=echo("fixed"),
                      files_changed=["README.md"])
        return ok(kind, findings=echo("fixed"), files_changed=[])

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
    print(json.dumps(respond(kind, family, workspace, count, prompt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
