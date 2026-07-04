"""Prompt builders for every worker call kind.

Every prompt starts with a machine-parseable header (KIND / FAMILY /
WORKSPACE) — consumed by MockRunner assertions and by the fake CLIs used in
end-to-end tests — followed by phase instructions and the JSON output
contract from orchestrator.contracts.

The consultation instruction embeds the opposite family's exact command so
the worker can run the dialogue itself and report the resolution in JSON;
the driver only records outcomes, it never adjudicates content.
"""

from . import contracts


def _header(kind, family, workspace):
    return "KIND: %s\nFAMILY: %s\nWORKSPACE: %s\n" % (kind, family, workspace)


def _consultation_block(opposite_family, opposite_cmd):
    cmd = " ".join(opposite_cmd) if opposite_cmd else "(not configured)"
    return (
        "CONSULTATION PROTOCOL\n"
        "If you disagree with a finding, or you are about to reject one, you\n"
        "must first run ONE consultation dialogue with the opposite family\n"
        "(%s) yourself, passing it the disputed finding, your proposed\n"
        "resolution, and the evidence you checked. Command (prompt on stdin):\n"
        "  %s\n"
        "Save the transcript under WORKSPACE/.orchestrator/scratch/ and\n"
        "summarize the outcome in the finding's consultation.resolution\n"
        "field. Findings with severity P0 or P1 can NEVER be rejected\n"
        "without that consultation.\n"
    ) % (opposite_family, cmd)


def _rules_block(edit_allowed):
    lines = [
        "GROUND RULES",
        "- Base every claim on files, diffs, tests, or command output in the",
        "  workspace; never on assumptions about what the code should say.",
        "- Work only inside WORKSPACE.",
    ]
    if edit_allowed:
        lines += [
            "- You have full edit permissions inside WORKSPACE: apply the",
            "  fixes yourself; do not describe fixes without applying them.",
        ]
    else:
        lines += [
            "- READ-ONLY: do not create, edit, delete, or move any file.",
            "  Workspace modifications are detected mechanically and",
            "  invalidate your entire output.",
        ]
    lines += [
        "- If something makes it impossible to proceed correctly, return",
        '  status "blocked" with a precise blocked_reason; the run will stop',
        "  and the operator will read your explanation in the log.",
    ]
    return "\n".join(lines) + "\n"


def build_draft_skeleton(family, workspace, goal):
    return (
        _header(contracts.KIND_DRAFT_SKELETON, family, workspace)
        + "\nTASK: draft the milestone skeleton for this goal.\n"
        + "GOAL: %s\n\n" % goal
        + "Write a concise skeleton document at docs/skeleton.md inside the\n"
        "workspace: goal restatement, boundary/non-goals, and a short table\n"
        "of planned slices (small, independently reviewable increments).\n"
        "Keep it thin: intent and contracts, no implementation detail.\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_draft_slice_note(family, workspace, goal, slice_info, skeleton_path):
    return (
        _header(contracts.KIND_DRAFT_SLICE_NOTE, family, workspace)
        + "\nTASK: draft the slice note for slice %d (%s).\n"
        % (slice_info["id"], slice_info["title"])
        + "GOAL: %s\n" % goal
        + "SKELETON: %s (sealed; stay inside its boundary)\n\n" % skeleton_path
        + "Write docs/slice-%02d.md: scope as observable contracts and the\n"
        % slice_info["id"]
        + "tests that pin them, non-goals, acceptance criteria. State WHAT\n"
        "must be observably true, not HOW code will do it.\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_implement(family, workspace, goal, slice_info, note_path, verification):
    ver = "\n".join("  %s" % c for c in verification) or "  (none configured)"
    return (
        _header(contracts.KIND_IMPLEMENT, family, workspace)
        + "\nTASK: implement slice %d (%s) exactly per its sealed note.\n"
        % (slice_info["id"], slice_info["title"])
        + "GOAL: %s\n" % goal
        + "SLICE NOTE: %s\n\n" % note_path
        + "Implement the scope, including its tests. The verification\n"
        "commands that must pass (run from the workspace root):\n"
        + ver
        + "\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_review_round(
    family, workspace, goal, unit_desc, artifact, opposite_family, opposite_cmd
):
    return (
        _header(contracts.KIND_REVIEW_ROUND, family, workspace)
        + "\nTASK: review-and-fix round on %s.\n" % unit_desc
        + "GOAL: %s\n" % goal
        + "ARTIFACT: %s (plus any code/tests it governs)\n\n" % artifact
        + "Do a complete pass of the artifact and the code it cites. Do not\n"
        "stop at the first defect: verify and FIX every defect you find in\n"
        "this same pass (an exhaustive pass with zero findings is a valid\n"
        "outcome). Report each defect as a finding with its disposition.\n"
        "Prior rounds may have recorded findings; treat them as claims, not\n"
        "facts — re-verify against the current files before relying on them.\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + _consultation_block(opposite_family, opposite_cmd)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_seal_half(family, workspace, goal, unit_desc, artifact):
    return (
        _header(contracts.KIND_SEAL_HALF, family, workspace)
        + "\nTASK: independent final seal review of %s.\n" % unit_desc
        + "GOAL: %s\n" % goal
        + "ARTIFACT: %s (plus any code/tests it governs)\n\n" % artifact
        + "You are one half of a double seal: a fresh, independent, final\n"
        "check on an artifact other agents already reviewed and fixed. Do a\n"
        "complete pass; report every defect you can verify. You fix nothing\n"
        "and triage nothing — findings only.\n\n"
        + _rules_block(edit_allowed=False)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_seal_fix(
    family,
    workspace,
    goal,
    unit_desc,
    artifact,
    seal_findings,
    opposite_family,
    opposite_cmd,
):
    lines = []
    for fam, findings in seal_findings.items():
        for f in findings:
            lines.append(
                "- [%s half] %s %s" % (fam, f.get("severity"), f.get("summary"))
            )
    findings_text = "\n".join(lines) or "(none)"
    return (
        _header(contracts.KIND_SEAL_FIX, family, workspace)
        + "\nTASK: triage and fix the double-seal findings on %s.\n" % unit_desc
        + "GOAL: %s\n" % goal
        + "ARTIFACT: %s\n\n" % artifact
        + "SEAL FINDINGS (claims, not facts — verify each against the\n"
        "current files before acting):\n"
        + findings_text
        + "\n\n"
        "For each: verify it; if valid, fix it; if invalid, reject it WITH\n"
        "the consultation protocol below. Report every one in findings[]\n"
        "with its disposition.\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + _consultation_block(opposite_family, opposite_cmd)
        + "\n"
        + contracts.CONTRACT_TEXT
    )


def build_fix_verification(
    family, workspace, goal, unit_desc, verification_output, opposite_family, opposite_cmd
):
    return (
        _header(contracts.KIND_FIX_VERIFICATION, family, workspace)
        + "\nTASK: the verification suite failed after work on %s. Fix it.\n"
        % unit_desc
        + "GOAL: %s\n\n" % goal
        + "VERIFICATION OUTPUT (tail):\n"
        + verification_output[-4000:]
        + "\n\n"
        "Diagnose against the actual code and tests, apply the fix, and\n"
        "re-run the failing command locally to confirm before answering.\n"
        "Report what you fixed as findings with disposition 'fixed'.\n\n"
        + _rules_block(edit_allowed=True)
        + "\n"
        + _consultation_block(opposite_family, opposite_cmd)
        + "\n"
        + contracts.CONTRACT_TEXT
    )
