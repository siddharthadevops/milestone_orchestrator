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
from orchestrator.runners import (
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

    def test_multiple_objects_first_valid_wins(self):
        text = '{"first": 1} and later {"second": 2}'
        self.assertEqual(extract_json(text), {"first": 1})

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


if __name__ == "__main__":
    unittest.main()
