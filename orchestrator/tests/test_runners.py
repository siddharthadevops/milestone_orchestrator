"""Unit tests for the worker protocol layer.

Covers:
- runners.extract_json (all documented extraction forms + failure)
- contracts.validate_worker_output for every kind (happy + violations)
- runners.SubprocessRunner against real tiny python3 commands in a tempdir
- runners.call_worker repair-retry behaviour via MockRunner
- runners.MockRunner assertion semantics
- runners.snapshot_workspace determinism and exclusion rules

All test workspaces live in tempfile.TemporaryDirectory(); nothing is
written into the repository.
"""

import json
import os
import sys
import tempfile
import textwrap
import time
import unittest

from orchestrator import contracts
from orchestrator import runners
from orchestrator.runners import (
    format_changes,
    snapshot_changes,
    MockRunner,
    RunnerError,
    SubprocessRunner,
    WorkerProtocolError,
    call_worker,
    extract_json,
    prompt_kind,
    snapshot_workspace,
)


def make_prompt(kind, family="codex", workspace="/tmp/ws"):
    """Prompt with the same header layout prompts.py emits."""
    return "KIND: %s\nFAMILY: %s\nWORKSPACE: %s\n\nDo the work." % (
        kind,
        family,
        workspace,
    )


# ---------------------------------------------------------------------------
# extract_json


class TestExtractJson(unittest.TestCase):
    def test_bare_object(self):
        self.assertEqual(extract_json('{"a": 1, "b": [2, 3]}'), {"a": 1, "b": [2, 3]})

    def test_bare_object_with_surrounding_whitespace(self):
        self.assertEqual(extract_json('  \n {"a": 1} \n '), {"a": 1})

    def test_fenced_json_block(self):
        text = 'Here you go:\n```json\n{"status": "ok", "kind": "implement"}\n```\nDone.'
        self.assertEqual(
            extract_json(text), {"status": "ok", "kind": "implement"}
        )

    def test_fenced_block_without_language_tag(self):
        text = '```\n{"a": 42}\n```'
        self.assertEqual(extract_json(text), {"a": 42})

    def test_object_surrounded_by_prose(self):
        text = 'Sure! The result is {"answer": 7, "ok": true} — hope that helps.'
        self.assertEqual(extract_json(text), {"answer": 7, "ok": True})

    def test_nested_braces_inside_string_values(self):
        text = 'prose {"msg": "use {x} and {y} here", "n": 1} more prose'
        self.assertEqual(
            extract_json(text), {"msg": "use {x} and {y} here", "n": 1}
        )

    def test_nested_object_values(self):
        text = 'x {"outer": {"inner": {"deep": 1}}, "k": 2} y'
        self.assertEqual(
            extract_json(text), {"outer": {"inner": {"deep": 1}}, "k": 2}
        )

    def test_braces_in_strings_with_escaped_quotes(self):
        # Raw text: prefix {"k": "a\" } b", "n": 2} suffix
        text = 'prefix {"k": "a\\" } b", "n": 2} suffix'
        self.assertEqual(extract_json(text), {"k": 'a" } b', "n": 2})

    def test_escaped_backslash_before_quote_ends_string(self):
        # Raw text: {"k": "a\\", "n": 3} — the backslash is escaped, the
        # quote really closes the string.
        text = 'noise {"k": "a\\\\", "n": 3} noise'
        self.assertEqual(extract_json(text), {"k": "a\\", "n": 3})

    def test_multiple_objects_last_valid_wins(self):
        text = '{"first": 1} and later {"second": 2}'
        self.assertEqual(extract_json(text), {"second": 2})

    def test_json_example_before_worker_contract_is_ignored(self):
        text = (
            'The canonical empty object is {}. Fix complete.\n'
            '{"status":"ok","kind":"fix_findings","findings":[], '
            '"files_changed":[],"notes":"verified"}'
        )
        self.assertEqual(extract_json(text)["status"], "ok")

    def test_multiple_objects_skips_invalid_first_candidate(self):
        text = "{'not': json} but then {\"good\": true}"
        self.assertEqual(extract_json(text), {"good": True})

    def test_no_json_raises_value_error(self):
        with self.assertRaises(ValueError):
            extract_json("there is no JSON object here at all")

    def test_unbalanced_brace_raises_value_error(self):
        with self.assertRaises(ValueError):
            extract_json('{"never": "closed"')

    def test_none_raises_value_error(self):
        with self.assertRaises(ValueError):
            extract_json(None)


# ---------------------------------------------------------------------------
# contracts.validate_worker_output


def ok_output(kind, **extra):
    base = {"status": "ok", "kind": kind}
    base.update(extra)
    return base


def report_finding(severity="P2", contests=None):
    """A reviewer finding: no disposition (reviewers never triage)."""
    f = {"id": "F1", "severity": severity, "summary": "a finding"}
    if contests is not None:
        f["contests"] = contests
    return f


def full_finding(disposition="fixed", severity="P2", consultation=None,
                 **extra):
    """A fixer triage entry (kind fix_findings): carries the disposition."""
    f = {
        "id": "F1",
        "severity": severity,
        "summary": "a finding",
        "disposition": disposition,
    }
    if consultation is not None:
        f["consultation"] = consultation
    f.update(extra)
    return f


class TestValidateWorkerOutputHappy(unittest.TestCase):
    def test_draft_skeleton(self):
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON,
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "one"}, {"id": 2, "title": "two"}],
        )
        self.assertIs(
            contracts.validate_worker_output(obj, contracts.KIND_DRAFT_SKELETON),
            obj,
        )

    def test_draft_slice_note(self):
        obj = ok_output(contracts.KIND_DRAFT_SLICE_NOTE, artifact="docs/s1.md")
        self.assertIs(
            contracts.validate_worker_output(obj, contracts.KIND_DRAFT_SLICE_NOTE),
            obj,
        )

    def test_implement(self):
        obj = ok_output(contracts.KIND_IMPLEMENT, files_changed=["calc.py"])
        self.assertIs(
            contracts.validate_worker_output(obj, contracts.KIND_IMPLEMENT), obj
        )

    def test_review_round_clean(self):
        obj = ok_output(contracts.KIND_REVIEW_ROUND, findings=[])
        contracts.validate_worker_output(obj, contracts.KIND_REVIEW_ROUND)
        self.assertTrue(contracts.findings_clean(obj))

    def test_review_round_with_report_finding(self):
        # Reviewer findings carry NO disposition and the output claims no
        # file changes (whoever detects never fixes).
        obj = ok_output(
            contracts.KIND_REVIEW_ROUND, findings=[report_finding()]
        )
        contracts.validate_worker_output(obj, contracts.KIND_REVIEW_ROUND)
        self.assertFalse(contracts.findings_clean(obj))

    def test_report_finding_accepts_the_plain_language_mirror(self):
        # `plain` (one lay-language sentence naming what is being built
        # and what is wrong) is optional — workers spawned before the
        # field existed must keep validating — but bounded when present.
        f = report_finding()
        f["plain"] = "we are specifying a floating menu; the doc and the README disagree"
        obj = ok_output(contracts.KIND_REVIEW_ROUND, findings=[f])
        contracts.validate_worker_output(obj, contracts.KIND_REVIEW_ROUND)
        # the prompt asks ~500 but the validator tolerates DOUBLE
        # (an LLM cannot count chars); past that it refuses.
        f["plain"] = "x" * 501
        contracts.validate_worker_output(
            ok_output(contracts.KIND_REVIEW_ROUND, findings=[f]),
            contracts.KIND_REVIEW_ROUND,
        )
        f["plain"] = "x" * (contracts.FINDING_TEXT_MAX + 1)
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                ok_output(contracts.KIND_REVIEW_ROUND, findings=[f]),
                contracts.KIND_REVIEW_ROUND,
            )
        f["plain"] = 7
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                ok_output(contracts.KIND_REVIEW_ROUND, findings=[f]),
                contracts.KIND_REVIEW_ROUND,
            )

    def test_report_finding_accepts_the_minimal_example(self):
        # `example` (the smallest concrete failure scenario) follows the
        # same soft contract as `plain`: optional, bounded when present.
        f = report_finding()
        f["example"] = ("a test deletes a message without saying who is "
                        "in the thread; the fake chat allows it")
        obj = ok_output(contracts.KIND_REVIEW_ROUND, findings=[f])
        contracts.validate_worker_output(obj, contracts.KIND_REVIEW_ROUND)
        f["example"] = "x" * 501
        contracts.validate_worker_output(
            ok_output(contracts.KIND_REVIEW_ROUND, findings=[f]),
            contracts.KIND_REVIEW_ROUND,
        )
        f["example"] = "x" * (contracts.FINDING_TEXT_MAX + 1)
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                ok_output(contracts.KIND_REVIEW_ROUND, findings=[f]),
                contracts.KIND_REVIEW_ROUND,
            )

    def test_report_finding_with_valid_contests(self):
        # Re-raising a settled finding is legal only with the registry id
        # and genuinely new evidence.
        for kind in contracts.REPORT_KINDS:
            with self.subTest(kind=kind):
                obj = ok_output(
                    kind,
                    findings=[
                        report_finding(
                            contests={
                                "rejection_id": "skeleton-claude-r1/F1",
                                "new_evidence": "the CLI now parses ints",
                            }
                        )
                    ],
                )
                self.assertIs(contracts.validate_worker_output(obj, kind), obj)

    def test_rejected_with_consultation_is_valid_for_the_fixer(self):
        # fix_findings is the only kind that triages (dispositions).
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[
                full_finding(
                    "rejected",
                    consultation={"resolution": "both families agree"},
                )
            ],
        )
        contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)

    def test_rejected_with_prevention_edit(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[
                full_finding(
                    "rejected",
                    consultation={"resolution": "target was correct"},
                    prevention={
                        "documented_in": "docs/skeleton.md",
                        "note": "clarifying sentence added",
                    },
                )
            ],
            files_changed=["docs/skeleton.md"],
        )
        contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)

    def test_rejected_adjudicated_with_ref_needs_no_consultation(self):
        # A duplicate of a settled rejection dies by pointer: registry ref,
        # zero new consultations.
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[
                full_finding(
                    "rejected_adjudicated",
                    adjudication_ref="skeleton-claude-r1/F1",
                )
            ],
        )
        contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)

    def test_blocked_disposition_needs_no_consultation(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS, findings=[full_finding("blocked")]
        )
        contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)
        self.assertEqual(len(contracts.blocking_findings(obj)), 1)

    def test_seal_half_report_only_finding(self):
        obj = ok_output(
            contracts.KIND_SEAL_HALF,
            findings=[{"id": "F1", "severity": "P1", "summary": "leak"}],
        )
        self.assertIs(
            contracts.validate_worker_output(obj, contracts.KIND_SEAL_HALF), obj
        )

    def test_seal_half_clean(self):
        obj = ok_output(contracts.KIND_SEAL_HALF, findings=[])
        contracts.validate_worker_output(obj, contracts.KIND_SEAL_HALF)

    def test_delta_review_clean_and_with_finding(self):
        contracts.validate_worker_output(
            ok_output(contracts.KIND_DELTA_REVIEW, findings=[]),
            contracts.KIND_DELTA_REVIEW,
        )
        contracts.validate_worker_output(
            ok_output(
                contracts.KIND_DELTA_REVIEW, findings=[report_finding("P1")]
            ),
            contracts.KIND_DELTA_REVIEW,
        )

    def test_blocked_status_valid_for_every_kind(self):
        for kind in contracts.KINDS:
            with self.subTest(kind=kind):
                obj = {
                    "status": "blocked",
                    "kind": kind,
                    "blocked_reason": "cannot proceed: missing spec",
                }
                # Blocked outputs need no kind-specific payload.
                self.assertIs(contracts.validate_worker_output(obj, kind), obj)


class TestValidateWorkerOutputViolations(unittest.TestCase):
    def assertContract(self, obj, kind, fragment=None):
        with self.assertRaises(contracts.ContractError) as cm:
            contracts.validate_worker_output(obj, kind)
        if fragment:
            self.assertIn(fragment, str(cm.exception))

    def test_missing_status(self):
        for kind in contracts.KINDS:
            with self.subTest(kind=kind):
                self.assertContract({"kind": kind}, kind, "status")

    def test_bad_status_value(self):
        self.assertContract(
            {"status": "maybe", "kind": contracts.KIND_IMPLEMENT},
            contracts.KIND_IMPLEMENT,
        )

    def test_output_not_an_object(self):
        self.assertContract(["not", "a", "dict"], contracts.KIND_IMPLEMENT)

    def test_unknown_kind_requested(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                {"status": "ok", "kind": "nonsense"}, "nonsense"
            )

    def test_bad_kind_echo(self):
        obj = ok_output(contracts.KIND_IMPLEMENT, files_changed=[])
        self.assertContract(obj, contracts.KIND_REVIEW_ROUND, "does not match")

    def test_missing_kind_echo(self):
        self.assertContract({"status": "ok"}, contracts.KIND_IMPLEMENT, "kind")

    def test_blocked_without_reason(self):
        self.assertContract(
            {"status": "blocked", "kind": contracts.KIND_IMPLEMENT},
            contracts.KIND_IMPLEMENT,
            "blocked_reason",
        )

    def test_blocked_with_empty_reason(self):
        self.assertContract(
            {
                "status": "blocked",
                "kind": contracts.KIND_IMPLEMENT,
                "blocked_reason": "",
            },
            contracts.KIND_IMPLEMENT,
            "blocked_reason",
        )

    def test_skeleton_missing_artifact(self):
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON, slices=[{"id": 1, "title": "t"}]
        )
        self.assertContract(obj, contracts.KIND_DRAFT_SKELETON, "artifact")

    def test_skeleton_empty_slices(self):
        obj = ok_output(contracts.KIND_DRAFT_SKELETON, artifact="a.md", slices=[])
        self.assertContract(
            obj, contracts.KIND_DRAFT_SKELETON, "at least one slice"
        )

    def test_skeleton_slice_not_object(self):
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON, artifact="a.md", slices=["one"]
        )
        self.assertContract(obj, contracts.KIND_DRAFT_SKELETON)

    def test_skeleton_slice_missing_title(self):
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON, artifact="a.md", slices=[{"id": 1}]
        )
        self.assertContract(obj, contracts.KIND_DRAFT_SKELETON, "title")

    def test_skeleton_slice_id_wrong_type(self):
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON,
            artifact="a.md",
            slices=[{"id": "1", "title": "t"}],
        )
        self.assertContract(obj, contracts.KIND_DRAFT_SKELETON, "id")

    def test_skeleton_duplicate_slice_ids_rejected(self):
        # Duplicate ids would silently collapse the (kind, slice_id)-keyed
        # unit plan: the second slice would never get doc/impl units and
        # the milestone would close "complete" without them.
        obj = ok_output(
            contracts.KIND_DRAFT_SKELETON,
            artifact="a.md",
            slices=[{"id": 1, "title": "one"}, {"id": 1, "title": "two"}],
        )
        self.assertContract(obj, contracts.KIND_DRAFT_SKELETON, "duplicate")

    def test_skeleton_bool_slice_id_rejected(self):
        # JSON true/false pass isinstance(int) and alias slice 1/0.
        for bad in (True, False):
            with self.subTest(id=bad):
                obj = ok_output(
                    contracts.KIND_DRAFT_SKELETON,
                    artifact="a.md",
                    slices=[{"id": bad, "title": "t"}],
                )
                self.assertContract(obj, contracts.KIND_DRAFT_SKELETON, "boolean")

    def test_fixer_accepts_optional_valid_slices(self):
        # Only the fixer (edit permissions) may return an updated slice
        # plan — meaningful when a fix touched the skeleton's slice table.
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[],
            slices=[{"id": 1, "title": "one"},
                    {"id": 2, "title": "two"}],
        )
        contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)

    def test_fixer_rejects_bad_optional_slices(self):
        cases = [
            ([], "non-empty"),
            ([{"id": 1, "title": "a"}, {"id": 1, "title": "b"}], "duplicate"),
            ([{"id": True, "title": "a"}], "boolean"),
            (["not-an-object"], None),
        ]
        for slices, fragment in cases:
            with self.subTest(slices=slices):
                obj = ok_output(
                    contracts.KIND_FIX_FINDINGS, findings=[], slices=slices
                )
                self.assertContract(obj, contracts.KIND_FIX_FINDINGS, fragment)

    def test_slice_note_missing_artifact(self):
        self.assertContract(
            ok_output(contracts.KIND_DRAFT_SLICE_NOTE),
            contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact",
        )

    def test_implement_missing_files_changed(self):
        self.assertContract(
            ok_output(contracts.KIND_IMPLEMENT),
            contracts.KIND_IMPLEMENT,
            "files_changed",
        )

    def test_missing_findings_on_report_and_fix_kinds(self):
        for kind in contracts.REPORT_KINDS + (contracts.KIND_FIX_FINDINGS,):
            with self.subTest(kind=kind):
                self.assertContract(ok_output(kind), kind, "findings")

    def test_report_kinds_must_not_claim_file_changes(self):
        # Whoever detects never fixes: a review output claiming edits is a
        # protocol violation by itself.
        for kind in contracts.REPORT_KINDS:
            with self.subTest(kind=kind):
                obj = ok_output(
                    kind, findings=[], files_changed=["calc.py"]
                )
                self.assertContract(obj, kind, "file changes")

    def test_rejected_without_consultation_all_severities(self):
        # Encodes the never-solo-rejected rule: the contract requires a
        # consultation for EVERY severity, hence in particular P0/P1.
        for sev in contracts.SEVERITIES:
            with self.subTest(severity=sev):
                obj = ok_output(
                    contracts.KIND_FIX_FINDINGS,
                    findings=[full_finding("rejected", severity=sev)],
                )
                self.assertContract(
                    obj, contracts.KIND_FIX_FINDINGS, "consultation"
                )

    def test_rejected_with_consultation_missing_resolution(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[full_finding("rejected", consultation={})],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS, "resolution")

    def test_rejected_with_non_string_resolution(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[
                full_finding("rejected", consultation={"resolution": 42})
            ],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS)

    def test_rejected_with_consultation_wrong_type(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[full_finding("rejected", consultation="we talked")],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS)

    def test_rejected_adjudicated_without_ref(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[full_finding("rejected_adjudicated")],
        )
        self.assertContract(
            obj, contracts.KIND_FIX_FINDINGS, "adjudication_ref"
        )

    def test_prevention_missing_fields(self):
        for prevention in (
            {"documented_in": "docs/skeleton.md"},  # no note
            {"note": "clarified"},  # no documented_in
            {"documented_in": 3, "note": "clarified"},  # wrong type
        ):
            with self.subTest(prevention=prevention):
                obj = ok_output(
                    contracts.KIND_FIX_FINDINGS,
                    findings=[
                        full_finding(
                            "rejected",
                            consultation={"resolution": "agreed"},
                            prevention=prevention,
                        )
                    ],
                )
                self.assertContract(
                    obj, contracts.KIND_FIX_FINDINGS, "prevention"
                )

    def test_contests_missing_rejection_id(self):
        obj = ok_output(
            contracts.KIND_REVIEW_ROUND,
            findings=[
                report_finding(contests={"new_evidence": "new fact"})
            ],
        )
        self.assertContract(obj, contracts.KIND_REVIEW_ROUND, "rejection_id")

    def test_contests_missing_new_evidence(self):
        for contests in (
            {"rejection_id": "skeleton-claude-r1/F1"},
            {"rejection_id": "skeleton-claude-r1/F1", "new_evidence": ""},
        ):
            with self.subTest(contests=contests):
                obj = ok_output(
                    contracts.KIND_REVIEW_ROUND,
                    findings=[report_finding(contests=contests)],
                )
                self.assertContract(
                    obj, contracts.KIND_REVIEW_ROUND, "new_evidence"
                )

    def test_contests_wrong_type(self):
        obj = ok_output(
            contracts.KIND_REVIEW_ROUND,
            findings=[report_finding(contests="I disagree")],
        )
        self.assertContract(obj, contracts.KIND_REVIEW_ROUND)

    def test_seal_half_finding_with_disposition(self):
        obj = ok_output(
            contracts.KIND_SEAL_HALF,
            findings=[
                {
                    "id": "F1",
                    "severity": "P0",
                    "summary": "bad",
                    "disposition": "fixed",
                }
            ],
        )
        self.assertContract(obj, contracts.KIND_SEAL_HALF, "disposition")

    def test_bad_severity_on_report_finding(self):
        obj = ok_output(
            contracts.KIND_REVIEW_ROUND,
            findings=[report_finding(severity="P4")],
        )
        self.assertContract(obj, contracts.KIND_REVIEW_ROUND, "severity")

    def test_bad_severity_on_fix_finding(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[full_finding("fixed", severity="P4")],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS, "severity")

    def test_missing_severity(self):
        obj = ok_output(
            contracts.KIND_SEAL_HALF, findings=[{"id": "F1", "summary": "s"}]
        )
        self.assertContract(obj, contracts.KIND_SEAL_HALF, "severity")

    def test_bad_disposition(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[full_finding("wontfix")],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS, "disposition")

    def test_disposition_on_review_finding_rejected(self):
        # Old model allowed (required) dispositions on review findings; the
        # redesign forbids them on EVERY report kind: reviewers never triage.
        for kind in contracts.REPORT_KINDS:
            for disp in contracts.DISPOSITIONS:
                with self.subTest(kind=kind, disposition=disp):
                    obj = ok_output(kind, findings=[full_finding(disp)])
                    self.assertContract(obj, kind, "no disposition")

    def test_missing_disposition_on_fix_finding(self):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[{"id": "F1", "severity": "P2", "summary": "s"}],
        )
        self.assertContract(obj, contracts.KIND_FIX_FINDINGS, "disposition")

    def test_finding_not_an_object(self):
        obj = ok_output(contracts.KIND_REVIEW_ROUND, findings=["oops"])
        self.assertContract(obj, contracts.KIND_REVIEW_ROUND)

    def test_finding_missing_summary(self):
        obj = ok_output(
            contracts.KIND_SEAL_HALF, findings=[{"id": "F1", "severity": "P1"}]
        )
        self.assertContract(obj, contracts.KIND_SEAL_HALF, "summary")


# ---------------------------------------------------------------------------
# contracts.validate_fix_coverage


class TestValidateFixCoverage(unittest.TestCase):
    QUEUED = [
        {"id": "F1", "severity": "P2", "summary": "one"},
        {"id": "F2", "severity": "P3", "summary": "two"},
    ]

    def fix_output(self, ids):
        return ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[dict(full_finding("fixed"), id=i) for i in ids],
            files_changed=[],
        )

    def test_exact_coverage_passes_any_order(self):
        for ids in (["F1", "F2"], ["F2", "F1"]):
            with self.subTest(ids=ids):
                out = self.fix_output(ids)
                self.assertIs(
                    contracts.validate_fix_coverage(out, self.QUEUED), out
                )

    def test_missing_queued_id_raises(self):
        with self.assertRaises(contracts.ContractError) as cm:
            contracts.validate_fix_coverage(
                self.fix_output(["F1"]), self.QUEUED
            )
        self.assertIn("exactly the queued findings", str(cm.exception))

    def test_invented_id_raises(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_fix_coverage(
                self.fix_output(["F1", "F2", "F3"]), self.QUEUED
            )

    def test_duplicated_id_raises(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_fix_coverage(
                self.fix_output(["F1", "F1"]), self.QUEUED
            )


# ---------------------------------------------------------------------------
# SubprocessRunner against real tiny commands


class TestSubprocessRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.bindir = os.path.join(self._tmp.name, "bin")
        self.workspace = os.path.join(self._tmp.name, "ws")
        os.makedirs(self.bindir)
        os.makedirs(self.workspace)

    def write_script(self, name, body):
        path = os.path.join(self.bindir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body))
        return path

    def runner_for(self, argv, timeouts=None, family="fam"):
        return SubprocessRunner({family: argv}, timeouts or {})

    def test_prompt_arrives_on_stdin(self):
        script = self.write_script(
            "echo_stdin.py",
            """\
            import sys
            sys.stdout.write(sys.stdin.read())
            """,
        )
        runner = self.runner_for([sys.executable, script])
        result = runner.call("fam", "hello worker\nline two", self.workspace)
        self.assertEqual(result.text, "hello worker\nline two")
        self.assertEqual(result.exit_code, 0)

    def test_workspace_substitution(self):
        script = self.write_script(
            "print_args.py",
            """\
            import sys
            print(sys.argv[1])
            print(sys.argv[2])
            """,
        )
        runner = self.runner_for(
            [sys.executable, script, "{workspace}", "--dir={workspace}"]
        )
        result = runner.call("fam", "p", self.workspace)
        lines = result.text.splitlines()
        self.assertEqual(lines[0], self.workspace)
        self.assertEqual(lines[1], "--dir=%s" % self.workspace)

    def test_output_file_mode_prefers_file_over_stdout(self):
        script = self.write_script(
            "write_file.py",
            """\
            import os, sys
            with open(sys.argv[1], "w") as fh:
                fh.write("FROM FILE")
            # Record the output-file path so the test can check cleanup.
            with open(os.path.join(sys.argv[2], "of_path.txt"), "w") as fh:
                fh.write(sys.argv[1])
            print("FROM STDOUT (must be ignored)")
            """,
        )
        runner = self.runner_for(
            [sys.executable, script, "{output_file}", "{workspace}"]
        )
        result = runner.call("fam", "p", self.workspace)
        self.assertEqual(result.text, "FROM FILE")
        with open(os.path.join(self.workspace, "of_path.txt")) as fh:
            output_file_path = fh.read().strip()
        self.assertFalse(
            os.path.exists(output_file_path),
            "temp output file should be unlinked after the call",
        )

    def test_output_file_empty_falls_back_to_stdout(self):
        script = self.write_script(
            "no_file_write.py",
            """\
            print("STDOUT WINS")
            """,
        )
        runner = self.runner_for([sys.executable, script, "{output_file}"])
        result = runner.call("fam", "p", self.workspace)
        self.assertEqual(result.text.strip(), "STDOUT WINS")

    def test_nonzero_exit_with_empty_output_raises(self):
        script = self.write_script(
            "fail_silent.py",
            """\
            import sys
            sys.stderr.write("boom diagnostics")
            sys.exit(3)
            """,
        )
        runner = self.runner_for([sys.executable, script])
        with self.assertRaises(RunnerError) as cm:
            runner.call("fam", "p", self.workspace)
        msg = str(cm.exception)
        self.assertIn("exited 3", msg)
        self.assertIn("boom diagnostics", msg)

    def test_error_lines_lead_the_failure_message(self):
        # codex buries its real ERROR under plugin WARN noise (found
        # live 2026-07-10: the quota banner read as a plugin failure and
        # the resume-window time never sat near the front). ERROR lines
        # must lead the message, deduplicated; the raw tail stays.
        script = self.write_script(
            "fail_noisy.py",
            """\
            import sys
            sys.stderr.write(
                "2026-07-10T21:38:18Z WARN loader: ignoring icon\\n"
                "ERROR: usage limit hit, try again at 12:26 AM.\\n"
                "ERROR: usage limit hit, try again at 12:26 AM.\\n")
            sys.exit(1)
            """,
        )
        runner = self.runner_for([sys.executable, script])
        with self.assertRaises(RunnerError) as cm:
            runner.call("fam", "p", self.workspace)
        msg = str(cm.exception)
        lead = msg.split("stderr tail:")[0]
        self.assertIn("ERROR: usage limit hit", lead)
        self.assertEqual(lead.count("ERROR: usage limit hit"), 1)  # deduped
        self.assertIn("WARN loader", msg)  # forensic tail preserved

    def test_nonzero_exit_with_output_is_tolerated(self):
        script = self.write_script(
            "fail_loud.py",
            """\
            import sys
            print('{"partial": true}')
            sys.exit(2)
            """,
        )
        runner = self.runner_for([sys.executable, script])
        result = runner.call("fam", "p", self.workspace)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("partial", result.text)

    def test_unconfigured_family_raises(self):
        runner = SubprocessRunner({}, {})
        with self.assertRaises(RunnerError):
            runner.call("ghost", "p", self.workspace)

    def test_spawn_failure_raises(self):
        runner = self.runner_for(
            [os.path.join(self.bindir, "does-not-exist-xyz")]
        )
        with self.assertRaises(RunnerError):
            runner.call("fam", "p", self.workspace)

    def test_timeout_kills_process_group(self):
        marker = os.path.join(self._tmp.name, "grandchild_survived.txt")
        pidfile = os.path.join(self._tmp.name, "grandchild_pid.txt")
        script = self.write_script(
            "sleeper.py",
            """\
            import subprocess, sys, time
            marker, pidfile = sys.argv[1], sys.argv[2]
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import sys, time; time.sleep(1.5); "
                    "open(sys.argv[1], 'w').write('alive')",
                    marker,
                ]
            )
            with open(pidfile, "w") as fh:
                fh.write(str(child.pid))
            time.sleep(2)
            """,
        )
        runner = self.runner_for(
            [sys.executable, script, marker, pidfile], timeouts={"fam": 0.5}
        )
        started = time.time()
        with self.assertRaises(RunnerError) as cm:
            runner.call("fam", "p", self.workspace)
        self.assertIn("timed out", str(cm.exception))
        # The kill happened at ~0.5s. If the grandchild had survived the
        # group kill it would write the marker at ~1.5s after its start.
        remaining = 2.0 - (time.time() - started)
        if remaining > 0:
            time.sleep(remaining)
        self.assertFalse(
            os.path.exists(marker),
            "grandchild outlived the timeout: process group was not killed",
        )
        # Secondary check: the grandchild pid must be gone (reaped by init).
        if os.path.exists(pidfile):
            with open(pidfile) as fh:
                gpid = int(fh.read().strip())
            deadline = time.time() + 3.0
            alive = True
            while time.time() < deadline:
                try:
                    os.kill(gpid, 0)
                except ProcessLookupError:
                    alive = False
                    break
                except PermissionError:
                    # pid reused by another user's process: not our orphan
                    alive = False
                    break
                time.sleep(0.05)
            self.assertFalse(alive, "orphaned grandchild pid %d" % gpid)


# ---------------------------------------------------------------------------
# call_worker repair retry


VALID_IMPLEMENT = {
    "status": "ok",
    "kind": contracts.KIND_IMPLEMENT,
    "files_changed": ["calc.py"],
}


class TestCallWorker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name

    def test_valid_first_try_makes_single_call(self):
        runner = MockRunner(
            [{"expect_kind": "implement", "response": VALID_IMPLEMENT}]
        )
        prompt = make_prompt("implement")
        obj, result = call_worker(
            runner, "codex", prompt, "implement", self.workspace
        )
        self.assertEqual(obj, VALID_IMPLEMENT)
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("REPAIR", runner.calls[0][2])

    def test_contract_is_selected_regardless_of_json_position(self):
        contract = json.dumps(VALID_IMPLEMENT)
        for response in (
            '{} explanation before ' + contract,
            contract + ' explanation after {}',
        ):
            with self.subTest(response=response):
                runner = MockRunner(
                    [{"expect_kind": "implement", "response": response}]
                )
                obj, _ = call_worker(
                    runner, "codex", make_prompt("implement"), "implement",
                    self.workspace,
                )
                self.assertEqual(obj, VALID_IMPLEMENT)
                self.assertEqual(len(runner.calls), 1)

    def test_repair_retry_after_junk_then_valid(self):
        runner = MockRunner(
            [
                {"expect_kind": "implement", "response": "utter garbage, no json"},
                {"expect_kind": "implement", "response": VALID_IMPLEMENT},
            ]
        )
        prompt = make_prompt("implement")
        obj, result = call_worker(
            runner, "codex", prompt, "implement", self.workspace
        )
        self.assertEqual(obj, VALID_IMPLEMENT)
        self.assertEqual(len(runner.calls), 2)
        second_prompt = runner.calls[1][2]
        self.assertIn("REPAIR", second_prompt)
        self.assertTrue(second_prompt.startswith(prompt))

    def test_repair_retry_after_contract_violation(self):
        # Valid JSON but contract-violating (missing files_changed) also
        # triggers the repair path, and the repair prompt carries the error.
        bad = {"status": "ok", "kind": contracts.KIND_IMPLEMENT}
        runner = MockRunner(
            [
                {"expect_kind": "implement", "response": bad},
                {"expect_kind": "implement", "response": VALID_IMPLEMENT},
            ]
        )
        obj, _ = call_worker(
            runner, "codex", make_prompt("implement"), "implement", self.workspace
        )
        self.assertEqual(obj, VALID_IMPLEMENT)
        self.assertIn("files_changed", runner.calls[1][2])

    def test_junk_twice_raises_worker_protocol_error(self):
        runner = MockRunner(
            [
                {"response": "junk one"},
                {"response": "junk two"},
            ]
        )
        with self.assertRaises(WorkerProtocolError) as cm:
            call_worker(
                runner, "codex", make_prompt("implement"), "implement",
                self.workspace,
            )
        msg = str(cm.exception)
        self.assertIn("twice", msg)
        self.assertIn("first error", msg)
        self.assertIn("second error", msg)
        self.assertEqual(len(runner.calls), 2)
        # Both raw texts ride on the exception so the driver can persist
        # them for the operator (they are otherwise lost).
        self.assertEqual(cm.exception.raw_texts, ["junk one", "junk two"])


# ---------------------------------------------------------------------------
# Unterminated envelope recovery
#
# Live regression (life "mentions-persona-proyections", 2026-07-19): three
# claude review rounds ended without the envelope's final `}` — everything
# else complete, brackets balanced, the last string closed. The extractor
# skipped the unterminated object, matched the FINDING objects inside the
# array instead, and rejected them all for "missing required key 'status'".
# A finished, contract-valid review was thrown away and a full replacement
# re-review ran instead; on slice_impl-07 the replacement returned 0
# findings where the first pass had two, and the unit sealed clean.


# Shaped exactly like the live failures: prose preamble, single-line
# envelope, notes last, no closing brace.
UNTERMINATED_REVIEW = (
    'Review complete. Two P3 debt findings; no P0-P2.\n\n'
    '{"status": "ok", "kind": "review_round", "findings": [], '
    '"notes": "Exhaustive pass; nothing above P3."\n'
)


class TestUnterminatedEnvelopeRecovery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name

    def _validate_review(self, obj):
        return contracts.validate_worker_output(obj, "review_round")

    def test_missing_final_brace_is_recovered(self):
        obj, closers = runners._extract_contract_output(
            UNTERMINATED_REVIEW, self._validate_review
        )
        self.assertEqual(closers, "}")
        self.assertEqual(obj["status"], "ok")
        self.assertIn("Exhaustive pass", obj["notes"])

    def test_recovery_keeps_the_findings_the_worker_actually_reported(self):
        finding = {
            "id": "F1", "severity": "P3", "summary": "s",
            "plain": "p", "example": "e",
        }
        text = (
            '{"status": "ok", "kind": "review_round", "findings": ['
            + json.dumps(finding)
            + '], "notes": "n"\n'
        )
        obj, closers = runners._extract_contract_output(
            text, self._validate_review
        )
        self.assertEqual(closers, "}")
        self.assertEqual([f["id"] for f in obj["findings"]], ["F1"])

    def test_nested_open_containers_are_all_closed(self):
        text = (
            '{"status": "ok", "kind": "review_round", "findings": ['
            '{"id": "F1", "severity": "P3", "summary": "s", '
            '"plain": "p", "example": "e"'
        )
        obj, closers = runners._extract_contract_output(
            text, self._validate_review
        )
        self.assertEqual(closers, "}]}")
        self.assertEqual(obj["findings"][0]["id"], "F1")

    def test_call_worker_spends_no_retry_and_reports_the_recovery(self):
        runner = MockRunner(
            [{"expect_kind": "review_round", "response": UNTERMINATED_REVIEW}]
        )
        obj, result = call_worker(
            runner, "claude", make_prompt("review_round"), "review_round",
            self.workspace,
        )
        self.assertEqual(obj["status"], "ok")
        # The whole point: one call, not two.
        self.assertEqual(len(runner.calls), 1)
        # ...and the malformed output stays visible to the operator.
        self.assertEqual(result.recovered["closers"], "}")
        self.assertIn("unterminated", result.recovered["error"])
        self.assertEqual(result.recovered["raw_text"], UNTERMINATED_REVIEW)

    def test_clean_output_reports_no_recovery(self):
        runner = MockRunner(
            [{"expect_kind": "implement", "response": VALID_IMPLEMENT}]
        )
        _obj, result = call_worker(
            runner, "codex", make_prompt("implement"), "implement",
            self.workspace,
        )
        self.assertIsNone(getattr(result, "recovered", None))

    def test_text_cut_mid_string_is_not_recovered(self):
        # Closing this would invent the rest of the value.
        text = '{"status": "ok", "kind": "review_round", "notes": "cut here'
        with self.assertRaises((ValueError, contracts.ContractError)):
            runners._extract_contract_output(text, self._validate_review)

    def test_recovered_object_must_still_satisfy_the_contract(self):
        # Balanced-but-incomplete: the brace is all that is missing, yet a
        # required key is absent. Recovery is not a contract bypass.
        text = '{"kind": "review_round", "findings": []\n'
        with self.assertRaises(contracts.ContractError):
            runners._extract_contract_output(text, self._validate_review)

    def test_general_extractor_still_rejects_unbalanced_input(self):
        # The tolerance lives in the contract-selecting path only; the
        # schema-less extractor keeps its strict behaviour.
        with self.assertRaises(ValueError):
            extract_json('{"never": "closed"')


# ---------------------------------------------------------------------------
# MockRunner semantics


class TestMockRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name

    def test_expect_kind_mismatch_raises(self):
        runner = MockRunner(
            [{"expect_kind": "seal_half", "response": VALID_IMPLEMENT}]
        )
        with self.assertRaises(AssertionError):
            runner.call("codex", make_prompt("implement"), self.workspace)

    def test_expect_family_mismatch_raises(self):
        runner = MockRunner(
            [
                {
                    "expect_kind": "implement",
                    "expect_family": "claude",
                    "response": VALID_IMPLEMENT,
                }
            ]
        )
        with self.assertRaises(AssertionError):
            runner.call("codex", make_prompt("implement"), self.workspace)

    def test_script_exhaustion_raises(self):
        runner = MockRunner([])
        with self.assertRaises(AssertionError):
            runner.call("codex", make_prompt("implement"), self.workspace)

    def test_side_effect_runs_against_workspace(self):
        target = os.path.join(self.workspace, "made_by_side_effect.txt")

        def effect(ws):
            with open(os.path.join(ws, "made_by_side_effect.txt"), "w") as fh:
                fh.write("hi")

        runner = MockRunner(
            [
                {
                    "expect_kind": "implement",
                    "response": VALID_IMPLEMENT,
                    "side_effect": effect,
                }
            ]
        )
        result = runner.call("codex", make_prompt("implement"), self.workspace)
        self.assertTrue(os.path.exists(target))
        self.assertEqual(json.loads(result.text), VALID_IMPLEMENT)

    def test_calls_are_recorded_with_kind(self):
        runner = MockRunner([{"response": VALID_IMPLEMENT}])
        prompt = make_prompt("implement", family="claude")
        runner.call("claude", prompt, self.workspace)
        self.assertEqual(runner.calls, [("claude", "implement", prompt)])

    def test_prompt_kind_without_header_is_none(self):
        self.assertIsNone(prompt_kind("no header here\njust prose"))

    def test_string_response_passes_through_verbatim(self):
        runner = MockRunner([{"response": "raw text output"}])
        result = runner.call("codex", make_prompt("implement"), self.workspace)
        self.assertEqual(result.text, "raw text output")


# ---------------------------------------------------------------------------
# apply_model_effort (per-act agent/model/effort experiments)


class TestApplyModelEffort(unittest.TestCase):
    TPL = ["claude", "-p", "--model", "{model}", "--effort", "{effort}"]
    LEGACY = ["claude", "-p", "--model", "opus", "--effort", "max"]
    CODEX = ["codex", "exec", "--output-last-message", "{output_file}"]

    def test_placeholders_substituted(self):
        from orchestrator.runners import apply_model_effort
        self.assertEqual(
            apply_model_effort(self.TPL, "sonnet", "high"),
            ["claude", "-p", "--model", "sonnet", "--effort", "high"],
        )

    def test_placeholder_without_value_is_config_error(self):
        from orchestrator.runners import apply_model_effort, RunnerError
        with self.assertRaises(RunnerError):
            apply_model_effort(self.TPL, None, "high")

    def test_legacy_template_flag_replacement(self):
        # Frozen pre-placeholder configs (live runs) still honor hot
        # overrides via --model/--effort value replacement.
        from orchestrator.runners import apply_model_effort
        self.assertEqual(
            apply_model_effort(self.LEGACY, "sonnet", None),
            ["claude", "-p", "--model", "sonnet", "--effort", "max"],
        )

    def test_codex_default_template_takes_model_and_effort(self):
        # The shipped codex template (verified against codex-cli 0.144.0)
        # slots -m and -c model_reasoning_effort= per call.
        from orchestrator.runners import apply_model_effort
        from orchestrator.driver import DEFAULT_CONFIG
        tpl = DEFAULT_CONFIG["commands"]["codex"]
        out = apply_model_effort(tpl, "gpt-5.6-luna", "high")
        self.assertIn("gpt-5.6-luna", out)
        self.assertIn("model_reasoning_effort=high", out)
        d = DEFAULT_CONFIG["model_defaults"]
        self.assertEqual(
            d["codex"], {"model": "gpt-5.6-sol", "effort": "xhigh"}
        )
        self.assertEqual(d["claude"],
                         {"model": "claude-opus-4-8", "effort": "max"})

    def test_no_placeholder_no_flag_ignores_overrides(self):
        from orchestrator.runners import apply_model_effort
        self.assertEqual(
            apply_model_effort(self.CODEX, "sonnet", "high"), self.CODEX
        )


# implement suite_command (verification protocol discovery)


class TestImplementSuiteCommand(unittest.TestCase):
    def base(self, **extra):
        obj = {"status": "ok", "kind": "implement", "files_changed": ["x.py"]}
        obj.update(extra)
        return obj

    def test_absent_and_null_are_valid(self):
        contracts.validate_worker_output(self.base(), "implement")
        contracts.validate_worker_output(
            self.base(suite_command=None), "implement")

    def test_string_command_is_valid(self):
        contracts.validate_worker_output(
            self.base(suite_command="mix test"), "implement")

    def test_empty_or_nonstring_rejected(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                self.base(suite_command="   "), "implement")
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                self.base(suite_command=42), "implement")


class TestFixSuiteCommand(unittest.TestCase):
    def base(self, **extra):
        obj = ok_output(
            contracts.KIND_FIX_FINDINGS,
            findings=[dict(full_finding("fixed"), id="F1")],
            files_changed=[],
        )
        obj.update(extra)
        return obj

    def test_command_is_bound_to_fixed_finding(self):
        contracts.validate_worker_output(
            self.base(
                suite_command="mix precommit",
                suite_command_finding_id="F1",
            ),
            contracts.KIND_FIX_FINDINGS,
        )

    def test_command_without_finding_binding_is_rejected(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                self.base(suite_command="mix precommit"),
                contracts.KIND_FIX_FINDINGS,
            )

    def test_binding_must_name_fixed_finding(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                self.base(
                    suite_command="mix precommit",
                    suite_command_finding_id="F2",
                ),
                contracts.KIND_FIX_FINDINGS,
            )

    def test_binding_without_command_is_rejected(self):
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                self.base(suite_command_finding_id="F1"),
                contracts.KIND_FIX_FINDINGS,
            )


# snapshot_workspace


class TestSnapshotWorkspace(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name
        self._write("a.txt", "alpha")
        os.makedirs(os.path.join(self.workspace, "sub"))
        self._write(os.path.join("sub", "b.txt"), "beta")

    def _write(self, rel, content):
        path = os.path.join(self.workspace, rel)
        os.makedirs(os.path.dirname(path) or self.workspace, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_deterministic(self):
        self.assertEqual(
            snapshot_workspace(self.workspace), snapshot_workspace(self.workspace)
        )

    def test_changes_when_file_content_changes(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join("sub", "b.txt"), "beta CHANGED")
        self.assertNotEqual(before, snapshot_workspace(self.workspace))

    def test_changes_when_file_added(self):
        before = snapshot_workspace(self.workspace)
        self._write("new.txt", "new")
        self.assertNotEqual(before, snapshot_workspace(self.workspace))

    def test_ignores_runtime_dirs(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join(".orchestrator", "state.json"), '{"x": 1}')
        self._write(os.path.join(".orchestrator", "raw", "r1.txt"), "raw")
        self._write(os.path.join(".git", "config"), "[core]")
        self._write(os.path.join("__pycache__", "mod.cpython-311.pyc"), "cc")
        self.assertEqual(before, snapshot_workspace(self.workspace))
        # Changing content inside the excluded dirs is also invisible.
        self._write(os.path.join(".orchestrator", "state.json"), '{"x": 2}')
        self._write(os.path.join(".git", "config"), "[core]\nbare = true")
        self.assertEqual(before, snapshot_workspace(self.workspace))

    def test_ignores_nested_runtime_dirs(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join("sub", "__pycache__", "x.pyc"), "zz")
        self.assertEqual(before, snapshot_workspace(self.workspace))

    def test_ignores_python_tool_caches_by_default(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join(".pytest_cache", "v", "cache", "lastfailed"),
                    "{}")
        self._write(os.path.join(".mypy_cache", "3.9", "mod.meta.json"), "{}")
        self._write(os.path.join("mypkg.egg-info", "PKG-INFO"), "Name: x")
        self.assertEqual(before, snapshot_workspace(self.workspace))

    def test_extra_exclude_parameter(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join(".customcache", "f.txt"), "cc")
        self.assertNotEqual(before, snapshot_workspace(self.workspace))
        self.assertEqual(
            before,
            snapshot_workspace(self.workspace,
                               extra_exclude=[".customcache"]),
        )

    def test_extra_exclude_supports_fnmatch_patterns(self):
        before = snapshot_workspace(self.workspace)
        self._write(os.path.join("node_modules.cache-abc", "x"), "y")
        self.assertNotEqual(before, snapshot_workspace(self.workspace))
        self.assertEqual(
            before,
            snapshot_workspace(
                self.workspace, extra_exclude=["node_modules.cache-*"]
            ),
        )

    def test_detects_new_empty_directory(self):
        before = snapshot_workspace(self.workspace)
        os.makedirs(os.path.join(self.workspace, "empty_new_dir"))
        self.assertNotEqual(before, snapshot_workspace(self.workspace))

    def test_detects_new_broken_symlink(self):
        before = snapshot_workspace(self.workspace)
        os.symlink(
            "/nonexistent/target-xyz",
            os.path.join(self.workspace, "dangling"),
        )
        self.assertNotEqual(before, snapshot_workspace(self.workspace))

    def test_detects_symlink_retarget(self):
        link = os.path.join(self.workspace, "alias")
        os.symlink("a.txt", link)
        before = snapshot_workspace(self.workspace)
        os.remove(link)
        os.symlink(os.path.join("sub", "b.txt"), link)
        self.assertNotEqual(before, snapshot_workspace(self.workspace))

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root can read chmod-000 files",
    )
    def test_detects_new_unreadable_file(self):
        before = snapshot_workspace(self.workspace)
        path = os.path.join(self.workspace, "secret.bin")
        self._write("secret.bin", "hidden")
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        # The unreadable file must still register as existing (the old
        # snapshot silently skipped it, so a read-only half could create
        # one undetected).
        self.assertNotEqual(before, snapshot_workspace(self.workspace))
        # And deterministically so.
        self.assertEqual(
            snapshot_workspace(self.workspace),
            snapshot_workspace(self.workspace),
        )


# ---------------------------------------------------------------------------
# git-universe snapshots (paths=...) and snapshot diffs


class TestSnapshotWithPaths(unittest.TestCase):
    """paths= restricts the tamper universe to what the repository can see
    (gitops.snapshot_paths): ignored artifact churn is invisible, while
    changes/deletions of listed paths are still detected and nameable."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name
        self._write("a.txt", "alpha")
        self._write(os.path.join("src", "b.txt"), "beta")
        self.paths = ["a.txt", "src/b.txt"]

    def _write(self, rel, content):
        path = os.path.join(self.workspace, rel)
        os.makedirs(os.path.dirname(path) or self.workspace, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def test_unlisted_churn_is_invisible(self):
        # The whole point: a reviewer that ran the project's build does not
        # tamper the workspace when the artifacts are outside the universe.
        before = snapshot_workspace(self.workspace, paths=self.paths)
        self._write(os.path.join("_build", "app.beam"), "artifact")
        self._write(os.path.join("deps", "lib", "x.ex"), "dep")
        after = snapshot_workspace(self.workspace, paths=self.paths)
        self.assertEqual(before, after)
        self.assertEqual(snapshot_changes(before, after), [])

    def test_listed_content_change_detected_and_named(self):
        before = snapshot_workspace(self.workspace, paths=self.paths)
        self._write(os.path.join("src", "b.txt"), "beta CHANGED")
        after = snapshot_workspace(self.workspace, paths=self.paths)
        self.assertEqual(snapshot_changes(before, after), ["src/b.txt"])

    def test_listed_deletion_detected(self):
        before = snapshot_workspace(self.workspace, paths=self.paths)
        os.unlink(os.path.join(self.workspace, "a.txt"))
        after = snapshot_workspace(self.workspace, paths=self.paths)
        self.assertEqual(snapshot_changes(before, after), ["a.txt"])
        self.assertEqual(after["a.txt"], "missing")

    def test_new_path_in_after_universe_detected(self):
        # An untracked non-ignored file created by the worker enters the
        # after-listing (git sees it) and must surface as a change.
        before = snapshot_workspace(self.workspace, paths=self.paths)
        self._write("evil.txt", "reviewer edit")
        after = snapshot_workspace(
            self.workspace, paths=self.paths + ["evil.txt"]
        )
        self.assertEqual(snapshot_changes(before, after), ["evil.txt"])

    def test_exclude_patterns_still_filter_listed_paths(self):
        # Defense in depth: even if .orchestrator/ were not git-ignored in
        # some repo, runtime bookkeeping never enters the universe.
        self._write(os.path.join(".orchestrator", "raw", "r1.txt"), "raw")
        snap = snapshot_workspace(
            self.workspace, paths=self.paths + [".orchestrator/raw/r1.txt"]
        )
        self.assertEqual(sorted(snap), ["a.txt", "src/b.txt"])

    def test_tracked_file_named_like_cache_dir_stays_in_universe(self):
        # Exclusion patterns are directory patterns: a tracked FILE whose
        # basename matches one (*.egg-info) must not silently leave the
        # tamper universe in git mode.
        self._write("notes.egg-info", "v1")
        paths = self.paths + ["notes.egg-info"]
        before = snapshot_workspace(self.workspace, paths=paths)
        self.assertIn("notes.egg-info", before)
        self._write("notes.egg-info", "v2 EDITED")
        after = snapshot_workspace(self.workspace, paths=paths)
        self.assertEqual(snapshot_changes(before, after), ["notes.egg-info"])

    def test_directory_entry_folds_subtree_walk(self):
        # ls-files reports submodules/nested repos as one bare directory
        # path; the snapshot must still cover their CONTENTS, or a
        # report-only worker could edit inside them undetected.
        self._write(os.path.join("nested", "inner.txt"), "v1")
        paths = self.paths + ["nested/"]
        before = snapshot_workspace(self.workspace, paths=paths)
        self.assertIn(os.path.join("nested", "inner.txt"), before)
        self._write(os.path.join("nested", "inner.txt"), "v2 EDITED")
        after = snapshot_workspace(self.workspace, paths=paths)
        self.assertEqual(
            snapshot_changes(before, after),
            [os.path.join("nested", "inner.txt")],
        )

    def test_git_info_exclude_is_part_of_the_universe(self):
        # Appending an ignore rule mid-call must itself register as a
        # change — otherwise it cloaks same-call file plants.
        self._write(os.path.join(".git", "info", "exclude"), "# none\n")
        before = snapshot_workspace(self.workspace, paths=self.paths)
        self.assertIn(".git/info/exclude", before)
        self._write(os.path.join(".git", "info", "exclude"),
                    "# none\nbackdoor.ex\n")
        after = snapshot_workspace(self.workspace, paths=self.paths)
        self.assertEqual(snapshot_changes(before, after),
                         [".git/info/exclude"])

    def test_symlink_target_recorded(self):
        os.symlink("a.txt", os.path.join(self.workspace, "ln"))
        snap = snapshot_workspace(self.workspace, paths=self.paths + ["ln"])
        self.assertEqual(snap["ln"], "link -> a.txt")


class TestSnapshotChangesFormatting(unittest.TestCase):
    def test_changes_cover_added_removed_and_modified(self):
        before = {"a": "file 1", "b": "file 2", "c": "file 3"}
        after = {"a": "file 1", "b": "file X", "d": "file 4"}
        self.assertEqual(snapshot_changes(before, after), ["b", "c", "d"])

    def test_format_empty(self):
        self.assertEqual(format_changes([]), "no visible changes")

    def test_format_short_list_verbatim(self):
        self.assertEqual(
            format_changes(["x.txt", "y.txt"]), "files: x.txt, y.txt"
        )

    def test_format_sentinel_rendered_verbatim(self):
        sentinel = "(tamper universe changed mid-call: git -> walk snapshot)"
        self.assertEqual(format_changes([sentinel]), sentinel)

    def test_format_clips_long_lists(self):
        changed = ["f%02d" % i for i in range(12)]
        out = format_changes(changed, limit=8)
        self.assertIn("f00", out)
        self.assertIn("f07", out)
        self.assertNotIn("f08", out)
        self.assertIn("(+4 more)", out)


class TestWorkflowDisable(unittest.TestCase):
    """claude workers must run with background workflows force-disabled,
    so the one-shot call can never be deferred to a nonexistent next turn.
    Central, effort-independent, and applied via the worker environment."""

    def _echo_env_runner(self, family, tmp):
        script = os.path.join(tmp, "echo_env.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent("""\
                import os, sys
                sys.stdout.write(
                    os.environ.get("CLAUDE_CODE_DISABLE_WORKFLOWS", "UNSET"))
                """))
        return SubprocessRunner({family: [sys.executable, script]}, {})

    def test_claude_worker_has_workflows_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            os.makedirs(ws)
            result = self._echo_env_runner("claude", tmp).call(
                "claude", "p", ws, model="m", effort="max")
            self.assertEqual(result.text, "1")

    def test_codex_worker_env_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = os.path.join(tmp, "ws")
            os.makedirs(ws)
            result = self._echo_env_runner("codex", tmp).call(
                "codex", "p", ws, model="m", effort="high")
            self.assertEqual(result.text, "UNSET")

    def test_helper_returns_base_env_for_unhardened_family(self):
        # No override -> the base env object is passed through unchanged
        # (None means "inherit", the historical default).
        self.assertIsNone(runners._worker_env(None, "codex"))
        base = {"X": "1"}
        self.assertIs(runners._worker_env(base, "codex"), base)

    def test_helper_adds_override_for_claude(self):
        env = runners._worker_env({"X": "1"}, "claude")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_WORKFLOWS"], "1")
        self.assertEqual(env["X"], "1")


if __name__ == "__main__":
    unittest.main()
