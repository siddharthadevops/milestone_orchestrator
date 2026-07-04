"""JSON contracts between the deterministic driver and LLM CLI workers.

This module is the single source of truth for the worker output protocol:
prompts advertise these schemas, runners validate against them, the driver
trusts only validated objects, and fake CLIs / tests import them.

Design rule: the driver never parses prose. A worker that cannot produce a
valid JSON object (after one repair retry) fails the run with an explanation
recorded in the event log.
"""

SEVERITIES = ("P0", "P1", "P2", "P3")
DISPOSITIONS = ("fixed", "rejected", "blocked")

# Worker call kinds. Every prompt carries a `KIND:` header with one of these.
KIND_DRAFT_SKELETON = "draft_skeleton"
KIND_DRAFT_SLICE_NOTE = "draft_slice_note"
KIND_IMPLEMENT = "implement"
KIND_REVIEW_ROUND = "review_round"
KIND_SEAL_HALF = "seal_half"
KIND_SEAL_FIX = "seal_fix"
KIND_FIX_VERIFICATION = "fix_verification"

KINDS = (
    KIND_DRAFT_SKELETON,
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_REVIEW_ROUND,
    KIND_SEAL_HALF,
    KIND_SEAL_FIX,
    KIND_FIX_VERIFICATION,
)

# Kinds whose worker gets full edit permissions on the workspace.
EDIT_KINDS = (
    KIND_DRAFT_SKELETON,
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_REVIEW_ROUND,
    KIND_SEAL_FIX,
    KIND_FIX_VERIFICATION,
)

# Kinds that must NOT modify the workspace (enforced structurally by the
# driver via workspace snapshots, not by trusting the worker).
READONLY_KINDS = (KIND_SEAL_HALF,)


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


def validate_finding(finding, kind, ctx):
    """Validate one finding object. Returns the finding.

    review_round / seal_fix / fix_verification findings carry a disposition;
    a `rejected` disposition additionally requires a recorded consultation
    with the opposite family (this encodes the canon rule that a finding is
    never rejected on single-family judgment alone).
    seal_half findings carry no disposition: seal halves report, they do not
    triage.
    """
    if not isinstance(finding, dict):
        raise ContractError("%s: finding must be an object" % ctx)
    _require(finding, "summary", str, ctx)
    sev = _require(finding, "severity", str, ctx)
    if sev not in SEVERITIES:
        raise ContractError("%s: severity %r not in %s" % (ctx, sev, SEVERITIES))
    if kind == KIND_SEAL_HALF:
        if "disposition" in finding and finding["disposition"] is not None:
            raise ContractError(
                "%s: seal_half findings must not carry a disposition "
                "(seal halves report; they do not triage)" % ctx
            )
        return finding
    disp = _require(finding, "disposition", str, ctx)
    if disp not in DISPOSITIONS:
        raise ContractError(
            "%s: disposition %r not in %s" % (ctx, disp, DISPOSITIONS)
        )
    consultation = _optional(finding, "consultation", dict, ctx)
    if disp == "rejected":
        if not consultation or not isinstance(
            consultation.get("resolution"), str
        ):
            raise ContractError(
                "%s: a rejected finding requires a consultation object with "
                "a string 'resolution' (opposite-family dialogue result)" % ctx
            )
    return finding


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
    elif kind in (KIND_REVIEW_ROUND, KIND_SEAL_FIX, KIND_FIX_VERIFICATION):
        findings = _require(obj, "findings", list, ctx)
        for i, f in enumerate(findings):
            validate_finding(f, kind, "%s.findings[%d]" % (ctx, i))
        _optional(obj, "files_changed", list, ctx, default=[])
        # Optional updated slice plan: only meaningful when the call fixed
        # the milestone skeleton and changed its slice table.
        slices = _optional(obj, "slices", list, ctx)
        if slices is not None:
            if not slices:
                raise ContractError(
                    "%s: slices, when present, must be non-empty" % ctx
                )
            validate_slices(slices, "%s.slices" % ctx)
    elif kind == KIND_SEAL_HALF:
        findings = _require(obj, "findings", list, ctx)
        for i, f in enumerate(findings):
            validate_finding(f, kind, "%s.findings[%d]" % (ctx, i))
    return obj


def findings_clean(obj):
    """A validated review/seal output is clean when it reports no findings."""
    return len(obj.get("findings", [])) == 0


def blocking_findings(obj):
    """Findings that force the run to stop: any 'blocked' disposition."""
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
  "slices": [ {"id": 1, "title": "..."}, ... ]   (at least one; ids are
      unique integers)

Kind draft_slice_note adds:
  "artifact": "<workspace-relative path of the slice note you wrote>"

Kind implement adds:
  "files_changed": ["<workspace-relative paths you created or edited>", ...]

Kinds review_round / seal_fix / fix_verification add:
  "findings": [
    {"id": "F1", "severity": "P0"|"P1"|"P2"|"P3", "summary": "...",
     "disposition": "fixed"|"rejected"|"blocked",
     "consultation": null | {"resolution": "<one-paragraph outcome of the
                              opposite-family dialogue you ran>"}}
  ]
  "files_changed": ["...paths you edited while fixing...", ...]
  "slices": [ {"id": 1, "title": "..."}, ... ]   (optional; ONLY when the
      artifact is the milestone skeleton and your fixes changed its slice
      plan — report the full updated plan, unique integer ids, so the
      structural unit plan stays in sync with the document)
  Rules: an empty findings list means the artifact is clean. A "rejected"
  disposition REQUIRES a consultation with the opposite family (run it
  yourself with the command given above and summarize its resolution).
  Use "blocked" disposition only when neither fixing nor a consulted
  rejection is possible; the run will stop and ask the operator.

Kind seal_half adds:
  "findings": [ {"id": "F1", "severity": "P0"|"P1"|"P2"|"P3",
                 "summary": "..."} ]
  Seal halves REPORT ONLY: no disposition field, and you must not modify
  any file in the workspace (modifications are detected mechanically and
  invalidate your output).
"""
