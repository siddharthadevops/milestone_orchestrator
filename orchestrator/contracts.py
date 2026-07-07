"""JSON contracts between the deterministic driver and LLM CLI workers.

Single source of truth for the worker protocol: prompts advertise these
schemas, runners validate against them, the driver trusts only validated
objects, fake CLIs and tests import them.

Role separation (the core rule): WHOEVER DETECTS NEVER FIXES.

- Report kinds (review_round, delta_review, seal_half): review a target,
  return findings, edit NOTHING (enforced mechanically by the driver via
  workspace snapshots, never by trust). Findings carry no disposition —
  reviewers do not triage. A finding that contests a previously adjudicated
  rejection MUST reference it (`contests`) and bring new evidence.
- Fix kind (fix_findings): receives a findings list, verifies each against
  the real code/doc, and either concedes-and-fixes or dissents-and-
  justifies. Dispositions:
    fixed                 the finding was right; corrected in this pass.
    rejected              the finding is wrong; REQUIRES the opposite-family
                          consultation resolution, and, when the artifact
                          was correct-but-misreadable, a `prevention` edit
                          documented in the target so the finding cannot
                          keep being reborn.
    rejected_adjudicated  the finding duplicates an already-adjudicated
                          rejection; REQUIRES `adjudication_ref` (validated
                          by the driver against the milestone registry);
                          costs no new consultation.
    blocked               neither fixing nor a justified rejection is
                          possible; the run stops with the explanation.
- Draft kinds (draft_skeleton, draft_slice_note, implement): produce the
  unit's artifact with full edit permissions.

A worker that cannot produce contract JSON (after one repair retry) fails
the run with the explanation recorded.
"""

SEVERITIES = ("P0", "P1", "P2", "P3")
DISPOSITIONS = ("fixed", "rejected", "rejected_adjudicated", "blocked")

# Worker call kinds. Every prompt carries a `KIND:` header with one of these.
KIND_DRAFT_SKELETON = "draft_skeleton"
KIND_DRAFT_SLICE_NOTE = "draft_slice_note"
KIND_IMPLEMENT = "implement"
KIND_REVIEW_ROUND = "review_round"
KIND_DELTA_REVIEW = "delta_review"
KIND_SEAL_HALF = "seal_half"
KIND_FIX_FINDINGS = "fix_findings"
# Opposite-family second opinion on whether a lone P3 is safe to DEFER as
# tracked debt (genuinely trivial, no correctness/behaviour/coverage impact
# and no implementation-drift risk). The worker RATES drift risk on a fixed
# scale; it never decides — the driver compares the rating against the
# run's configured threshold (a binary "is it safe?" question biases an
# LLM to the safe answer; a graded rating keeps it calibrated).
KIND_RECLASSIFY = "reclassify"

# Ordered drift-risk scale for reclassify ratings (least to most risk).
DRIFT_RISK_LEVELS = ("low", "medium", "high", "xhigh")

KINDS = (
    KIND_DRAFT_SKELETON,
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_REVIEW_ROUND,
    KIND_DELTA_REVIEW,
    KIND_SEAL_HALF,
    KIND_FIX_FINDINGS,
    KIND_RECLASSIFY,
)

# Reviewers report; they never edit (enforced via snapshots/git restore).
REPORT_KINDS = (KIND_REVIEW_ROUND, KIND_DELTA_REVIEW, KIND_SEAL_HALF)

# Kinds whose worker gets full edit permissions inside the workspace.
EDIT_KINDS = (
    KIND_DRAFT_SKELETON,
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_FIX_FINDINGS,
)


class ContractError(ValueError):
    """Worker output does not satisfy the JSON contract."""


def _require(obj, key, types, ctx):
    if key not in obj:
        raise ContractError("%s: missing required key %r" % (ctx, key))
    val = obj[key]
    if not isinstance(val, types):
        raise ContractError(
            "%s: key %r has type %s, expected %s"
            % (ctx, key, type(val).__name__, types)
        )
    return val


def _optional(obj, key, types, ctx, default=None):
    if key not in obj or obj[key] is None:
        return default
    val = obj[key]
    if not isinstance(val, types):
        raise ContractError(
            "%s: key %r has type %s, expected %s"
            % (ctx, key, type(val).__name__, types)
        )
    return val


def validate_slices(slices, ctx):
    """Validate a slice-plan list: every entry is {"id": int, "title": str},
    ids are true integers (bool is rejected: JSON true/false would alias
    slice 1/0) and unique. Duplicate or aliased ids would silently collapse
    the structural unit plan keyed on (kind, slice_id)."""
    seen = set()
    for i, sl in enumerate(slices):
        sctx = "%s[%d]" % (ctx, i)
        if not isinstance(sl, dict):
            raise ContractError("%s: must be an object" % sctx)
        sid = _require(sl, "id", int, sctx)
        if isinstance(sid, bool):
            raise ContractError(
                "%s: key 'id' must be an integer, not a boolean" % sctx
            )
        _require(sl, "title", str, sctx)
        if sid in seen:
            raise ContractError(
                "%s: duplicate slice id %d (slice ids must be unique)"
                % (sctx, sid)
            )
        seen.add(sid)
    return slices


def validate_report_finding(finding, ctx):
    """A reviewer finding: id/severity/summary, NO disposition (reviewers
    do not triage), optional `contests` referencing an adjudicated
    rejection — then new_evidence is mandatory. The referenced id's
    existence is validated by the driver against the milestone registry."""
    if not isinstance(finding, dict):
        raise ContractError("%s: finding must be an object" % ctx)
    _require(finding, "id", str, ctx)
    _require(finding, "summary", str, ctx)
    sev = _require(finding, "severity", str, ctx)
    if sev not in SEVERITIES:
        raise ContractError("%s: severity %r not in %s" % (ctx, sev, SEVERITIES))
    # The lay-language mirror and the minimal failure example. Optional
    # for now (workers spawned before the fields existed must keep
    # validating); the prompt demands both.
    plain = _optional(finding, "plain", str, ctx)
    if plain is not None and len(plain) > 500:
        raise ContractError(
            "%s: plain must stay one plain-language sentence "
            "(<=500 chars)" % ctx
        )
    example = _optional(finding, "example", str, ctx)
    if example is not None and len(example) > 500:
        raise ContractError(
            "%s: example must stay one minimal concrete scenario "
            "(<=500 chars)" % ctx
        )
    if finding.get("disposition") is not None:
        raise ContractError(
            "%s: reviewer findings carry no disposition (whoever detects "
            "never fixes; triage belongs to the fixer)" % ctx
        )
    contests = _optional(finding, "contests", dict, ctx)
    if contests is not None:
        rid = contests.get("rejection_id")
        evidence = contests.get("new_evidence")
        if not rid or not isinstance(rid, str):
            raise ContractError(
                "%s: contests requires the adjudicated rejection_id" % ctx
            )
        if not evidence or not isinstance(evidence, str):
            raise ContractError(
                "%s: contesting an adjudicated rejection requires "
                "non-empty new_evidence" % ctx
            )
    return finding


def validate_fix_finding(finding, ctx):
    """A fixer triage entry: echoes the reviewed finding's id, carries the
    disposition and its per-disposition obligations."""
    if not isinstance(finding, dict):
        raise ContractError("%s: finding must be an object" % ctx)
    _require(finding, "id", str, ctx)
    _require(finding, "summary", str, ctx)
    sev = _require(finding, "severity", str, ctx)
    if sev not in SEVERITIES:
        raise ContractError("%s: severity %r not in %s" % (ctx, sev, SEVERITIES))
    disp = _require(finding, "disposition", str, ctx)
    if disp not in DISPOSITIONS:
        raise ContractError(
            "%s: disposition %r not in %s" % (ctx, disp, DISPOSITIONS)
        )
    consultation = _optional(finding, "consultation", dict, ctx)
    prevention = _optional(finding, "prevention", dict, ctx)
    if prevention is not None:
        if not isinstance(prevention.get("documented_in"), str) or not isinstance(
            prevention.get("note"), str
        ):
            raise ContractError(
                "%s: prevention requires string 'documented_in' (workspace-"
                "relative path edited) and 'note'" % ctx
            )
    if disp == "rejected":
        if not consultation or not isinstance(
            consultation.get("resolution"), str
        ):
            raise ContractError(
                "%s: a rejected finding requires a consultation object with "
                "a string 'resolution' (opposite-family dialogue result)" % ctx
            )
    if disp == "rejected_adjudicated":
        ref = finding.get("adjudication_ref")
        if not ref or not isinstance(ref, str):
            raise ContractError(
                "%s: rejected_adjudicated requires adjudication_ref (the "
                "registry id of the prior rejection)" % ctx
            )
    return finding


def _assert_unique_finding_ids(findings, ctx):
    """Finding ids must be unique within one output. A reviewer emitting
    the same id twice would poison everything keyed on ids downstream: an
    honest fixer deduplicating the queue fails validate_fix_coverage (the
    run dies), while a fixer echoing the id twice and rejecting both would
    mint two adjudication registry entries with the SAME id, making
    contests / adjudication_ref targets ambiguous."""
    seen = set()
    for i, f in enumerate(findings):
        fid = f.get("id")
        if fid in seen:
            raise ContractError(
                "%s.findings[%d]: duplicate finding id %r (finding ids "
                "must be unique within one output)" % (ctx, i, fid)
            )
        seen.add(fid)


def validate_worker_output(obj, kind):
    """Validate the full worker JSON output for a call of `kind`.

    Returns the object unchanged on success; raises ContractError otherwise.
    """
    if kind not in KINDS:
        raise ContractError("unknown kind %r" % (kind,))
    ctx = "worker[%s]" % kind
    if not isinstance(obj, dict):
        raise ContractError("%s: output must be a JSON object" % ctx)

    status = _require(obj, "status", str, ctx)
    if status not in ("ok", "blocked"):
        raise ContractError("%s: status %r not in ('ok','blocked')" % (ctx, status))
    echoed = _require(obj, "kind", str, ctx)
    if echoed != kind:
        raise ContractError(
            "%s: echoed kind %r does not match requested kind %r"
            % (ctx, echoed, kind)
        )
    if status == "blocked":
        reason = _optional(obj, "blocked_reason", str, ctx)
        if not reason:
            raise ContractError(
                "%s: blocked status requires a non-empty blocked_reason" % ctx
            )
        return obj

    if kind == KIND_DRAFT_SKELETON:
        _require(obj, "artifact", str, ctx)
        slices = _require(obj, "slices", list, ctx)
        if not slices:
            raise ContractError("%s: skeleton must propose at least one slice" % ctx)
        validate_slices(slices, "%s.slices" % ctx)
    elif kind == KIND_DRAFT_SLICE_NOTE:
        _require(obj, "artifact", str, ctx)
    elif kind == KIND_IMPLEMENT:
        _require(obj, "files_changed", list, ctx)
        if obj.get("suite_command") is not None:
            sc = obj["suite_command"]
            if not isinstance(sc, str) or not sc.strip():
                raise ContractError(
                    "%s: suite_command, when present, must be a non-empty "
                    "string" % ctx
                )
            lowered = sc.strip().lower()
            if (
                lowered in ("true", "false", ":", "exit 0", "exit")
                or lowered.startswith("echo ")
                or lowered.startswith("printf ")
            ):
                raise ContractError(
                    "%s: suite_command %r is a no-op, not a test suite"
                    % (ctx, sc)
                )
    elif kind in REPORT_KINDS:
        findings = _require(obj, "findings", list, ctx)
        for i, f in enumerate(findings):
            validate_report_finding(f, "%s.findings[%d]" % (ctx, i))
        _assert_unique_finding_ids(findings, ctx)
        if obj.get("files_changed"):
            raise ContractError(
                "%s: report kinds must not claim file changes" % ctx
            )
    elif kind == KIND_FIX_FINDINGS:
        findings = _require(obj, "findings", list, ctx)
        for i, f in enumerate(findings):
            validate_fix_finding(f, "%s.findings[%d]" % (ctx, i))
        _assert_unique_finding_ids(findings, ctx)
        _optional(obj, "files_changed", list, ctx, default=[])
        # Optional updated slice plan: only meaningful when the fix touched
        # the milestone skeleton's slice table (before the skeleton seals).
        slices = _optional(obj, "slices", list, ctx)
        if slices is not None:
            if not slices:
                raise ContractError(
                    "%s: slices, when present, must be non-empty" % ctx
                )
            validate_slices(slices, "%s.slices" % ctx)
    elif kind == KIND_RECLASSIFY:
        risk = _require(obj, "drift_risk", str, ctx)
        if risk not in DRIFT_RISK_LEVELS:
            raise ContractError(
                "%s: drift_risk must be one of %s"
                % (ctx, "|".join(DRIFT_RISK_LEVELS))
            )
        reason = _require(obj, "reason", str, ctx)
        if not reason.strip():
            raise ContractError("%s: reason must be non-empty" % ctx)
    return obj


def validate_fix_coverage(output, queued_findings):
    """Driver-side check with context: the fixer must triage EXACTLY the
    queued findings — every queued id appears once, no invented ids."""
    ctx = "worker[%s]" % KIND_FIX_FINDINGS
    queued_ids = [f["id"] for f in queued_findings]
    got_ids = [f["id"] for f in output.get("findings", [])]
    if sorted(queued_ids) != sorted(got_ids):
        raise ContractError(
            "%s: triage must cover exactly the queued findings; queued=%s "
            "got=%s" % (ctx, sorted(queued_ids), sorted(got_ids))
        )
    return output


def findings_clean(obj):
    """A validated review output is clean when it reports no findings."""
    return len(obj.get("findings", [])) == 0


def all_p3(findings):
    """True when there is at least one finding and EVERY finding is P3 —
    the 'lone trivial nit(s)' case eligible for the reclassify/debt path.
    Any P0/P1/P2 present means a fix round fires anyway (P3s ride along)."""
    findings = list(findings or [])
    return bool(findings) and all(
        f.get("severity") == "P3" for f in findings
    )


def blocking_findings(obj):
    """Fixer findings that force the run to stop."""
    return [
        f
        for f in obj.get("findings", [])
        if f.get("disposition") == "blocked"
    ]


CONTRACT_TEXT = """OUTPUT CONTRACT (mandatory)
Respond with EXACTLY ONE JSON object and nothing else: no prose before or
after it, no markdown fences. The object must satisfy:

Common fields (all kinds):
  "status": "ok" | "blocked"
  "kind": "<echo the KIND header of this prompt>"
  "blocked_reason": string    (required when status is "blocked": explain
                               precisely what stops you; the run will end
                               with this explanation in the log)
  "notes": string             (optional, short)

Kind draft_skeleton adds:
  "artifact": "<workspace-relative path of the skeleton document you wrote>"
  "slices": [ {"id": 1, "title": "..."}, ... ]   (unique integer ids)

Kind draft_slice_note adds:
  "artifact": "<workspace-relative path of the slice note you wrote>"

Kind implement adds:
  "files_changed": ["<workspace-relative paths you created or edited>", ...]
  "suite_command": "<the repo's official full-test-suite command, exactly
   as you would run it from the workspace root (e.g. 'mix test'); it must
   be non-interactive and run the suite exactly ONCE and exit — never a
   watch mode; null or omitted if the repo has no suite>"

Kind fix_findings may ALSO include "suite_command" when the queued
findings came from a failing verification gate (correcting a wrong
command) or when the run has no recorded suite yet (arming it) — the
driver adopts it.

REVIEW kinds (review_round / delta_review / seal_half) add:
  "findings": [
    {"id": "F1", "severity": "P0"|"P1"|"P2"|"P3", "summary": "...",
     "plain": "<ONE sentence a non-engineer understands: name what is
      being built and what is actually wrong, in everyday words — e.g.
      'we are specifying a floating menu; the doc and the package README
      disagree about whether it ships JavaScript'. No file:line, no
      spec vocabulary. Write this sentence BEFORE choosing severity:
      the technical register makes everything sound grave; the plain
      sentence shows the real size of the problem>",
     "example": "<the SMALLEST concrete scenario where this bites — one
      actor, one action, the wrong outcome vs the expected one, in plain
      words. E.g. 'a test deletes a message without saying who is in the
      thread; the fake chat allows it; the real one rejects it with an
      authorization error'. If you cannot write such a scenario, the
      finding may not be real>",
     "contests": null | {"rejection_id": "<id from the ADJUDICATED
      REJECTIONS list>", "new_evidence": "<the new fact that contradicts
      the recorded rationale>"}}
  ]
  Rules: you REVIEW ONLY — no disposition field, and you must not create,
  edit, delete, or move ANY file (modifications are detected mechanically
  and invalidate your output). Finding ids must be unique within this
  response. An empty findings list means the target is clean. EVERY
  finding MUST include `plain` AND `example` — a finding without its
  plain-language sentence and its smallest concrete failure scenario is
  incomplete. Before filing any finding, check the ADJUDICATED REJECTIONS list
  in this prompt: if your finding challenges one of them you MUST fill
  `contests` with its id and genuinely new evidence; re-raising an
  adjudicated finding without new evidence is a protocol violation.

Kind fix_findings adds:
  "findings": [
    {"id": "<echo the queued finding's id>", "severity": "<echo>",
     "summary": "...",
     "disposition": "fixed" | "rejected" | "rejected_adjudicated" | "blocked",
     "consultation": null | {"resolution": "<one-paragraph outcome of the
                              opposite-family dialogue you ran>"},
     "prevention": null | {"documented_in": "<path you edited>",
                           "note": "<what now documents the decision>"},
     "adjudication_ref": null | "<registry id of the prior rejection>"}
  ]
  "files_changed": ["...paths you edited...", ...]
  Rules: triage EXACTLY the queued findings (same ids, nothing else).
  Verify each against the real code/doc before deciding. "rejected"
  REQUIRES the consultation; when the target was correct but misreadable,
  ALSO make the minimal clarifying edit and record it in `prevention` so
  the finding cannot keep being reborn. "rejected_adjudicated" is for
  findings duplicating an entry of the ADJUDICATED REJECTIONS list without
  new evidence: cite it in adjudication_ref, no consultation needed, do
  not re-litigate. Use "blocked" only when neither fixing nor a justified
  rejection is possible (an unresolved or unavailable consultation means a
  justified rejection is NOT possible); the run will stop and show your
  reason.
"""
