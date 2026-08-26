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
    reports an "ambiguous goal wording" finding -> fixer REJECTS it directly
    with a prevention edit -> claude round 2 stubbornly
    re-raises the same complaint without contests -> fixer kills it by
    pointer (rejected_adjudicated) -> claude round 3
    clean -> deterministic seal from the current reviews -> gate.
  slice note: both reviews clean on the same bytes -> deterministic seal.
  implementation:
    deliberate div bug -> verification fails -> fixer repairs it (delta
    review + amend) -> codex round 1 reports a docstring finding -> fixer
    fixes -> reviews restart at codex -> claude reports a missing README ->
    fixer writes it -> reviews restart at codex again -> both clean on the
    same bytes -> deterministic seal -> gate -> milestone closes.
"""

import argparse
import json
import os
import re
import subprocess
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
    marker = "`finding` without shortening, normalizing, or dropping fields:\n"
    start = prompt.find(marker)
    if start < 0:
        return []
    payload = prompt[start + len(marker):].lstrip()
    try:
        queued, _end = json.JSONDecoder().raw_decode(payload)
    except (TypeError, ValueError):
        return []
    return [
        {
            "id": finding["id"],
            "severity": finding["severity"],
            "summary": finding["summary"],
        }
        for finding in queued
    ]


def parse_first_registry_id(prompt):
    in_block = False
    for line in prompt.splitlines():
        if line.startswith("ADJUDICATED REJECTIONS"):
            in_block = True
            continue
        if in_block:
            m = re.match(r"^- \[([^\]]+)\]", line)
            if m is None:
                m = re.search(r'"id"\s*:\s*"([^"]+)"', line)
            if m:
                return m.group(1)
            if line.startswith(("ACCESS", "PROCESS AUTHORITY", "OUTPUT CONTRACT")):
                break
    return None


def prompt_scope(prompt):
    """Stable per-unit counter scope; review restarts must not depend on how
    many calls earlier units happened to consume."""
    task = next(
        (line for line in prompt.splitlines() if line.startswith("TASK:")),
        "",
    )
    if "milestone skeleton" in task:
        return "skeleton"
    if "slice 1 note" in task:
        return "slice_doc-01"
    if "slice 1 implementation" in task or "implement slice 1" in task:
        return "slice_impl-01"
    # Reclassification has a generic TASK line; its artifact is the only
    # unit identity in that prompt. Counts do not drive its answer, but a
    # useful scope keeps the diagnostic counter readable.
    if "on docs/skeleton.md." in prompt:
        return "skeleton"
    if "on docs/slice-01.md." in prompt:
        return "slice_doc-01"
    return "run"


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

AUTHOR_QUESTIONS = {
    "draft_skeleton": (
        "due_diligence_count",
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
    "draft_slice_note": (
        "due_diligence_count",
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
    "implement": (
        "machinery_trust",
        "environment_fit",
        "human_scale",
    ),
}

JUDGMENT_QUESTION_IDS = ("environment_fit", "human_scale")


def author_questions(kind):
    return [
        {"id": question_id, "answer": "Checked by the calculator fixture."}
        for question_id in AUTHOR_QUESTIONS[kind]
    ]


def judgment_questions():
    return [
        {"id": question_id, "answer": "Checked by the calculator fixture."}
        for question_id in JUDGMENT_QUESTION_IDS
    ]


def ok(kind, **extra):
    payload = {"status": "ok", "kind": kind}
    if kind in ("review_round", "delta_review", "fix_findings", "reclassify"):
        payload["questions"] = judgment_questions()
    payload.update(extra)
    return payload


def report(kind, findings):
    for finding in findings:
        finding["plain"] = "In plain terms: %s" % finding["summary"]
        finding["example"] = "Example: %s" % finding["summary"]
        finding["validity"] = {
            "permitted_baseline": "the documented calculator behavior",
            "actual_outcome": finding["summary"],
            "incremental_harm": "the candidate misses that behavior",
            "exceeds_baseline": True,
        }
    return ok(kind, findings=findings)


def respond(kind, family, workspace, count, prompt):
    scope = prompt_scope(prompt)
    # ---- drafts ----------------------------------------------------------
    if kind == "draft_skeleton":
        write(
            workspace,
            "docs/skeleton.md",
            "# Calculator milestone\n\nGoal: CLI calculator with tests.\n\n"
            "## Canonical slice plan\n```json\n"
            '{"slices":[{"id":1,"title":"Calculator core",'
            '"intent":"Implement and test add, subtract, multiply, and '
            'divide operations.","producer_task_executor":{'
            '"draft_slice_note":"agent_call",'
            '"implement":"agent_call"}}]}\n'
            "```\n",
        )
        write(workspace, "run_checks.py", RUN_CHECKS)
        return ok(
            kind,
            artifact="docs/skeleton.md",
            questions=author_questions(kind),
        )

    if kind == "draft_slice_note":
        write(
            workspace,
            "docs/slice-01.md",
            "# Slice 01 - Calculator core\n\nContracts: add/sub/mul/div are "
            "correct over floats; CLI prints the result.\nTests: unittest "
            "suite pins all four operations.\n",
        )
        return ok(
            kind,
            artifact="docs/slice-01.md",
            questions=author_questions(kind),
        )

    if kind == "implement":
        write(workspace, "calculator.py", CALC_BUGGY)
        write(workspace, "test_calculator.py", TESTS)
        return ok(
            kind,
            files_changed=["calculator.py", "test_calculator.py"],
            questions=author_questions(kind),
        )

    # ---- scheduled complete-suite checkpoint ----------------------------
    if kind == "suite_checkpoint":
        command = "python3 run_checks.py"
        completed = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        evidence = (completed.stdout + completed.stderr).strip()
        if not evidence:
            evidence = (
                "complete suite passed"
                if completed.returncode == 0
                else "complete suite failed"
            )
        response = {
            "status": "passed" if completed.returncode == 0 else "failed",
            "kind": kind,
            "commands": [command],
            "results": [{
                "command": command,
                "exit_code": completed.returncode,
                "evidence": evidence,
            }],
            "authority": {"source": "operator_config", "evidence": []},
        }
        if completed.returncode != 0:
            response["failure_account"] = {
                "command": command,
                "exit_code": completed.returncode,
                "diagnostics": evidence,
                "affected_tests": ["test_calculator"],
            }
        return response

    # ---- report-only reviews --------------------------------------------
    if kind == "review_round" and family == "codex":
        if scope == "skeleton" and count == 1:
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "skeleton lacks explicit non-goals"}
            ])
        if scope == "slice_impl-01" and count == 1:
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "calculator module lacks a docstring"}
            ])
        return report(kind, [])

    if kind == "review_round" and family == "claude":
        if scope == "skeleton" and count == 1:
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "goal wording is ambiguous about float support"}
            ])
        if scope == "skeleton" and count == 2:
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "goal wording is ambiguous about float support"}
            ])
        if scope == "slice_impl-01" and count == 1:
            return report(kind, [
                {"id": "F1", "severity": "P3",
                 "summary": "workspace lacks a README describing CLI usage"}
            ])
        return report(kind, [])

    if kind == "delta_review":
        return report(kind, [])  # every fix delta in this scenario is green

    if kind == "reclassify":
        return ok(
            kind,
            drift_risk="high",
            drift_damage="high",
            reason="the scripted finding changes required calculator behavior",
        )

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
                    "validity": {
                        "affected_party": (
                            "calculator users"
                            if disposition in ("fixed", "blocked")
                            else "no affected party"
                        ),
                        "observable_damage": (
                            f["summary"]
                            if disposition in ("fixed", "blocked")
                            else "no observable damage"
                        ),
                        "violated_guarantee": (
                            "the documented calculator behavior"
                            if disposition in ("fixed", "blocked")
                            else "no violated guarantee"
                        ),
                        "permitted_baseline": (
                            "the documented calculator behavior"
                        ),
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

        summaries = {f["summary"] for f in queued}

        if "skeleton lacks explicit non-goals" in summaries:
            append(workspace, "docs/skeleton.md",
                   "\n## Non-goals\n\nNo scientific functions.\n")
            return ok(kind, findings=echo("fixed"),
                      files_changed=["docs/skeleton.md"])
        if ("goal wording is ambiguous about float support" in summaries
                and count == 2):
            append(workspace, "docs/skeleton.md",
                   "\nNote: operations are defined over floats "
                   "(clarified after review).\n")
            return ok(
                kind,
                findings=echo(
                    "rejected",
                    prevention={
                        "documented_in": "docs/skeleton.md",
                        "note": "explicit float-support note added",
                    },
                ),
                files_changed=["docs/skeleton.md"],
            )
        if "goal wording is ambiguous about float support" in summaries:
            ref = parse_first_registry_id(prompt) or "unknown"
            return ok(
                kind,
                findings=echo("rejected_adjudicated", adjudication_ref=ref),
                files_changed=[],
            )
        if any("verification suite failed" in summary
               for summary in summaries):
            write(workspace, "calculator.py", CALC_FIXED)
            return ok(kind, findings=echo("fixed"),
                      files_changed=["calculator.py"])
        if "calculator module lacks a docstring" in summaries:
            write(workspace, "calculator.py", CALC_DOCSTRING)
            return ok(kind, findings=echo("fixed"),
                      files_changed=["calculator.py"])
        if "workspace lacks a README describing CLI usage" in summaries:
            write(workspace, "README.md",
                  "# Calculator\n\nUsage: python3 calculator.py "
                  "add|sub|mul|div A B\n")
            return ok(kind, findings=echo("fixed"),
                      files_changed=["README.md"])
        return ok(kind, findings=echo("fixed"), files_changed=[])

    blocked = {
        "status": "blocked",
        "kind": kind,
        "blocked_reason": "fake_llm has no script for kind %r" % kind,
    }
    if kind in AUTHOR_QUESTIONS:
        blocked["questions"] = author_questions(kind)
    elif kind in ("review_round", "delta_review", "fix_findings", "reclassify"):
        blocked["questions"] = judgment_questions()
    return blocked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--family", choices=("codex", "claude"))
    args = parser.parse_args()

    prompt = sys.stdin.read()
    kind, family, workspace = read_headers(prompt)
    family = family or args.family
    workspace = workspace or args.workspace
    if kind is None:
        print(json.dumps({"status": "blocked", "kind": "unknown",
                          "blocked_reason": "prompt had no KIND header"}))
        return 0
    count = bump_counter(
        workspace, "%s:%s:%s" % (prompt_scope(prompt), kind, family)
    )
    print(json.dumps(respond(kind, family, workspace, count, prompt)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
