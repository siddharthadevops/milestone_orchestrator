"""JSON contracts between the deterministic driver and LLM CLI workers.

Single source of truth for the worker protocol: prompts advertise these
schemas, runners validate against them, the driver trusts only validated
objects, fake CLIs and tests import them.

Role separation (the core rule): WHOEVER DETECTS NEVER FIXES.

- Report kinds (review_round, delta_review): review a target,
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

import os

SEVERITIES = ("P0", "P1", "P2", "P3")

# The finding lay-mirror bound: the PROMPT still asks for ~500 chars;
# the VALIDATOR tolerates 10x. An LLM cannot count characters reliably,
# so a hard gate near the asked length turns honest overruns into burned
# repair retries — the doubled bound (1000) proved far too tight live:
# opus reviews kept failing on wordy-but-valid findings (operator order
# 2026-07-27 raised it to 5000). The gate now only stops true runaway
# prose; brevity stays a prompt ask, not a validity condition.
FINDING_TEXT_MAX = 5000
FINDING_ID_MAX = 200
DISPOSITIONS = ("fixed", "rejected", "rejected_adjudicated", "blocked")
RETRY_CONSULTATION_UNAVAILABLE = "consultation_unavailable"

# Worker call kinds. Every prompt carries a `KIND:` header with one of these.
KIND_DRAFT_SKELETON = "draft_skeleton"
KIND_DRAFT_SLICE_NOTE = "draft_slice_note"
KIND_IMPLEMENT = "implement"
KIND_REVIEW_ROUND = "review_round"
KIND_DELTA_REVIEW = "delta_review"
KIND_FIX_FINDINGS = "fix_findings"
# Opposite-family second opinion on whether an eligible finding is safe to
# DEFER as tracked debt. The worker RATES drift risk on a fixed
# scale; it never decides — the driver compares the rating against the
# run's configured threshold (a binary "is it safe?" question biases an
# LLM to the safe answer; a graded rating keeps it calibrated).
KIND_RECLASSIFY = "reclassify"
# One-shot workspace reconciliation is routed by the Prompt Router rather
# than the legacy builder table, so it is a valid project-policy target but
# deliberately is not added to ``KINDS`` below.
KIND_MERGE_REPAIR = "merge_repair"
# The routed full-suite checkpoint is another direct technical kind.  It has
# its own served contract and deliberately stays outside the legacy worker
# kind table until Slice 14 removes that table's remaining call lanes.
KIND_SUITE_CHECKPOINT = "suite_checkpoint"

# Ordered drift-risk scale for reclassify ratings (least to most risk).
DRIFT_RISK_LEVELS = ("low", "medium", "high", "xhigh")

KINDS = (
    KIND_DRAFT_SKELETON,
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_REVIEW_ROUND,
    KIND_DELTA_REVIEW,
    KIND_FIX_FINDINGS,
    KIND_RECLASSIFY,
)

# Reviewers report; they never edit (enforced via snapshots/git restore).
REPORT_KINDS = (KIND_REVIEW_ROUND, KIND_DELTA_REVIEW)
RETHINK_CONTINUATION_KINDS = (
    KIND_DRAFT_SLICE_NOTE,
    KIND_IMPLEMENT,
    KIND_FIX_FINDINGS,
)
RETHINK_KINDS = RETHINK_CONTINUATION_KINDS + REPORT_KINDS
RETHINK_RESULT_PROPOSAL = "proposal"
RETHINK_RESULT_DESIGN_AMENDMENT = "design_amendment"
RETHINK_RESULT_MODES = (
    RETHINK_RESULT_PROPOSAL,
    RETHINK_RESULT_DESIGN_AMENDMENT,
)
# Round limit of every milestone-attached Brainstorming (need_rethink,
# guarantee calibration) and the catalogue default for Brainstorming tasks.
# Raised from 10 to 20 (operator, 2026-08-18): sessions were reaching the
# limit while still converging. Every prompt/contract text derives its
# number from this constant; nothing else may spell it.
MILESTONE_BRAINSTORMING_ROUNDS = 20

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


def _require_keys(obj, expected, ctx):
    """Presence check only: the contract asks for these fields, nothing more.

    Operator rule (2026-08-11): a worker that filled every required field and
    then added one nobody asked for has ANSWERED. Rejecting the whole delivery
    over the surplus threw away complete work — a live P2 review was lost twice
    in a row, first for carrying `file`/`line` on its findings, then for an
    empty `incremental_harm_note` inside `validity`. Surplus is not a defect.
    """
    missing = sorted(set(expected) - set(obj))
    if missing:
        raise ContractError("%s: missing required keys %s" % (ctx, missing))
    return obj


def _prune_extras(obj, allowed):
    """Drop the surplus in place so nothing downstream can read it.

    Ignoring means ignoring: the keys never reach the ledger, so a field the
    contract does not define can neither be mistaken for one it does nor
    smuggle authority the worker lacks. The raw worker output is saved
    verbatim, so what was dropped stays auditable.
    """
    for key in sorted(set(obj) - set(allowed)):
        del obj[key]
    return obj


REPORT_VALIDITY_TEXT_FIELDS = (
    "permitted_baseline",
    "actual_outcome",
    "incremental_harm",
)

FIX_VALIDITY_TEXT_FIELDS = (
    "affected_party",
    "observable_damage",
    "violated_guarantee",
    "permitted_baseline",
    "incremental_harm",
)


def _validate_finding_validity(
    finding,
    ctx,
    expected_exceeds_baseline,
    text_fields=REPORT_VALIDITY_TEXT_FIELDS,
):
    """Validate the evidence-backed comparison that makes a finding real.

    Reviewers may report only outcomes outside the mechanism's permitted
    operating envelope. Fixers repeat that comparison independently: an
    accepted finding exceeds the baseline; a rejected one does not.
    """
    validity = _require(finding, "validity", dict, ctx)
    vctx = "%s.validity" % ctx
    expected = set(text_fields) | {"exceeds_baseline"}
    _require_keys(validity, expected, vctx)
    _prune_extras(validity, expected)
    for key in text_fields:
        value = _require(validity, key, str, vctx)
        if not value.strip():
            raise ContractError("%s: key %r must be non-empty" % (vctx, key))
        if len(value) > FINDING_TEXT_MAX:
            raise ContractError(
                "%s: key %r must be <=%d chars"
                % (vctx, key, FINDING_TEXT_MAX)
            )
    exceeds = _require(validity, "exceeds_baseline", bool, vctx)
    if exceeds is not expected_exceeds_baseline:
        raise ContractError(
            "%s: exceeds_baseline must be %s for this finding outcome"
            % (vctx, str(expected_exceeds_baseline).lower())
        )
    return validity


def _require_material(material, sctx):
    """A proposed slice material must be a string this run can store.

    Shape first, exactly as the acceptance reads: a string, or nothing.
    Then the one property a shape check cannot see. JSON admits an escaped
    unpaired surrogate and `json.loads` returns it as an ordinary `str`,
    but no UTF-8 encoder can emit it, so the promise to preserve the string
    verbatim in state and summary is unkeepable for that value: state's own
    `json.dump(..., ensure_ascii=False)` raises instead, and the planner's
    completed result never installs.

    Refusing here is what the promise leaves: worker output is validated
    before anything is recorded, so this answers with the repairable
    ContractError the malformed shapes already raise and nothing mutates.
    It is the same judgement the slice's own material route already makes
    on the other write surface (`service._require_encodable`), and it is
    not catalogue validation: an unknown name is still admitted verbatim.
    """
    if not isinstance(material, str):
        raise ContractError(
            "%s: key 'material' must be a string when present (omit it to "
            "leave the session default material in force)" % sctx
        )
    try:
        material.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError(
            "%s: key 'material' must be storable UTF-8 text (this one carries "
            "an unpaired surrogate, which no run state could preserve)" % sctx
        ) from exc


def validate_slices(slices, ctx):
    """Validate slice identity, prospective producer selections, and material.

    Producer omissions remain valid compatibility state and resolve only when
    projected or ordered.  The lazy import keeps the shared TaskExecutor
    catalogue as the sole configuration authority without a module cycle.

    `material` is the planner's word for the kind of work the slice contains.
    Only its SHAPE, and that it is storable at all, are checked here — see
    `_require_material`.  Checking it against the live document's catalogue
    would turn a harmless rename into a refused plan; the staffing router owns
    what the name means, and an unknown one already degrades there.
    """
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
        if "material" in sl:
            _require_material(sl["material"], sctx)
        if "producer_task_executor" in sl:
            from orchestrator import tasks

            tasks.validate_producer_map(
                sl["producer_task_executor"],
                "%s.producer_task_executor" % sctx,
            )
        if sid in seen:
            raise ContractError(
                "%s: duplicate slice id %d (slice ids must be unique)"
                % (sctx, sid)
            )
        seen.add(sid)
    return slices


def validate_implementation_cut(cut, ctx):
    """Validate the implementer's coherent-cut account.

    Labels and sequencing are deliberately absent: the state machine derives
    a/b/c from the current unit, so a worker cannot rename units or insert an
    arbitrary execution plan.
    """
    if not isinstance(cut, dict):
        raise ContractError("%s: must be an object" % ctx)
    expected = {"cut_scope", "remaining_scope"}
    _require_keys(cut, expected, ctx)
    _prune_extras(cut, expected)
    for key in sorted(expected):
        value = _require(cut, key, str, ctx)
        if not value.strip():
            raise ContractError("%s: key %r must be non-empty" % (ctx, key))
        if len(value) > FINDING_TEXT_MAX:
            raise ContractError(
                "%s: key %r must be <=%d chars"
                % (ctx, key, FINDING_TEXT_MAX)
            )
    return cut


def validate_report_finding(finding, ctx, require_plain=False):
    """A reviewer finding: id/severity/summary, NO disposition (reviewers
    do not triage), optional `contests` referencing an adjudicated
    rejection — then new_evidence is mandatory. The referenced id's
    existence is validated by the driver against the milestone registry.
    require_plain: reform runs hard-require the plain/example lay mirror
    on every finding (spec §7); legacy/profile-less runs keep the fields
    optional (workers spawned before they existed must keep validating)."""
    if not isinstance(finding, dict):
        raise ContractError("%s: finding must be an object" % ctx)
    finding_id = _require(finding, "id", str, ctx)
    if len(finding_id) > FINDING_ID_MAX:
        raise ContractError(
            "%s: id must be <=%d chars" % (ctx, FINDING_ID_MAX)
        )
    summary = _require(finding, "summary", str, ctx)
    if len(summary) > FINDING_TEXT_MAX:
        raise ContractError(
            "%s: summary must be <=%d chars" % (ctx, FINDING_TEXT_MAX)
        )
    sev = _require(finding, "severity", str, ctx)
    if sev not in SEVERITIES:
        raise ContractError("%s: severity %r not in %s" % (ctx, sev, SEVERITIES))
    # A reviewer that triages anyway (`disposition`) is surplus like any
    # other undefined key: pruned below, never read, so the doctrine holds
    # without costing the round.
    _validate_finding_validity(finding, ctx, expected_exceeds_baseline=True)
    # The lay-language mirror and the minimal failure example. Optional
    # for now (workers spawned before the fields existed must keep
    # validating); the prompt demands both.
    plain = _optional(finding, "plain", str, ctx)
    if plain is not None and len(plain) > FINDING_TEXT_MAX:
        raise ContractError(
            "%s: plain must stay one plain-language sentence "
            "(<=%d chars)" % (ctx, FINDING_TEXT_MAX)
        )
    example = _optional(finding, "example", str, ctx)
    if example is not None and len(example) > FINDING_TEXT_MAX:
        raise ContractError(
            "%s: example must stay one minimal concrete scenario "
            "(<=%d chars)" % (ctx, FINDING_TEXT_MAX)
        )
    if require_plain:
        if not (plain and plain.strip()):
            raise ContractError(
                "%s: missing or empty 'plain' — this run REQUIRES both "
                "'plain' and 'example' on every finding" % ctx
            )
        if not (example and example.strip()):
            raise ContractError(
                "%s: missing or empty 'example' — this run REQUIRES both "
                "'plain' and 'example' on every finding" % ctx
            )
    contests = _optional(finding, "contests", dict, ctx)
    if contests is not None:
        expected = {"rejection_id", "new_evidence"}
        _require_keys(contests, expected, "%s.contests" % ctx)
        _prune_extras(contests, expected)
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
        if len(rid) > FINDING_ID_MAX:
            raise ContractError(
                "%s.contests.rejection_id must be <=%d chars"
                % (ctx, FINDING_ID_MAX)
            )
        if len(evidence) > FINDING_TEXT_MAX:
            raise ContractError(
                "%s.contests.new_evidence must be <=%d chars"
                % (ctx, FINDING_TEXT_MAX)
            )
    allowed = {
        "id", "severity", "summary", "validity", "plain", "example",
        "contests",
    }
    _prune_extras(finding, allowed)
    return finding


def validate_fix_finding(finding, ctx):
    """A fixer triage entry: echoes the reviewed finding's id, carries the
    disposition and its per-disposition obligations."""
    if not isinstance(finding, dict):
        raise ContractError("%s: finding must be an object" % ctx)
    finding_id = _require(finding, "id", str, ctx)
    if len(finding_id) > FINDING_ID_MAX:
        raise ContractError(
            "%s: id must be <=%d chars" % (ctx, FINDING_ID_MAX)
        )
    summary = _require(finding, "summary", str, ctx)
    if len(summary) > FINDING_TEXT_MAX:
        raise ContractError(
            "%s: summary must be <=%d chars" % (ctx, FINDING_TEXT_MAX)
        )
    sev = _require(finding, "severity", str, ctx)
    if sev not in SEVERITIES:
        raise ContractError("%s: severity %r not in %s" % (ctx, sev, SEVERITIES))
    disp = _require(finding, "disposition", str, ctx)
    if disp not in DISPOSITIONS:
        raise ContractError(
            "%s: disposition %r not in %s" % (ctx, disp, DISPOSITIONS)
        )
    _validate_finding_validity(
        finding,
        ctx,
        expected_exceeds_baseline=disp in ("fixed", "blocked"),
        text_fields=FIX_VALIDITY_TEXT_FIELDS,
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


def validate_brainstorming_application(value, ctx):
    """Proof that an accepted agreement required no workspace change."""
    if not isinstance(value, dict):
        raise ContractError("%s must be an object" % ctx)
    expected = {"finding_id", "implementation_required", "reason"}
    if set(value) != expected:
        raise ContractError(
            "%s must contain exactly %s" % (ctx, sorted(expected))
        )
    finding_id = _require(value, "finding_id", str, ctx)
    if not finding_id.strip() or len(finding_id) > FINDING_ID_MAX:
        raise ContractError(
            "%s.finding_id must be non-empty and <=%d chars"
            % (ctx, FINDING_ID_MAX)
        )
    if value.get("implementation_required") is not False:
        raise ContractError(
            "%s.implementation_required must be false" % ctx
        )
    reason = _require(value, "reason", str, ctx)
    if not reason.strip() or len(reason) > FINDING_TEXT_MAX:
        raise ContractError(
            "%s.reason must be non-empty and <=%d chars"
            % (ctx, FINDING_TEXT_MAX)
        )
    return value


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


# A structured gap report (build-driven review reform §3): a draft/implement
# worker that meets a hole or a contradiction which would change what it
# builds STOPS and reports the FACTS, instead of resolving it or building
# around it. The worker CLASSIFIES the gap — it does not pick a routing
# target; the machine derives the routing from the classification.
#
# The classification is the one question a builder asks: does fixing this
# fit inside the goal it was given?
#   fits_remodel  — IN-GOAL: the fix is work the goal already asks for; the
#                   DESIGN just under-specified it (e.g. a step needs data no
#                   earlier step produces). The machine reopens the skeleton
#                   (the design authority) toward the gap as an objective —
#                   it never reaches the operator.
#   needs_operator — OUT-OF-GOAL: the fix would change something the goal does
#                   not mandate (a designated provider, the database
#                   technology, a payment contract, an external integration),
#                   OR the goal contradicts itself. Only this reaches the
#                   operator, the goal's sole author.
CLASSIFY_FITS_REMODEL = "fits_remodel"
CLASSIFY_NEEDS_OPERATOR = "needs_operator"
GAP_CLASSIFICATIONS = (CLASSIFY_FITS_REMODEL, CLASSIFY_NEEDS_OPERATOR)

GAP_REQUIRED_FIELDS = (
    "classification",    # fits_remodel | needs_operator (the goal-fit test)
    "missing_or_conflict",  # what is missing / contradicts
    "where",             # file:line on the upstream (or a verbatim quote for
                         # an inline-typed goal)
    "forced_decision",   # what must be resolved (for needs_operator, the
                         # decision the operator faces)
    "plain",             # one lay sentence a non-engineer follows
    "example",           # the smallest concrete failing scenario
)


def validate_gap(gap, ctx):
    """One entry of a gap report. `proposal` is optional and may be null
    (a MARKED proposal, never self-service — the upstream fixer verifies it
    independently); every other field is a required non-empty string, and
    `classification` must be one of GAP_CLASSIFICATIONS."""
    if not isinstance(gap, dict):
        raise ContractError("%s: gap must be an object" % ctx)
    for field in GAP_REQUIRED_FIELDS:
        val = gap.get(field)
        if not isinstance(val, str) or not val.strip():
            raise ContractError(
                "%s: gap.%s must be a non-empty string" % (ctx, field)
            )
    if gap["classification"] not in GAP_CLASSIFICATIONS:
        raise ContractError(
            "%s: gap.classification %r not in %r"
            % (ctx, gap["classification"], GAP_CLASSIFICATIONS)
        )
    proposal = gap.get("proposal")
    if proposal is not None and (
        not isinstance(proposal, str) or not proposal.strip()
    ):
        raise ContractError(
            "%s: gap.proposal, when present, must be a non-empty string "
            "or null" % ctx
        )
    return gap


# Kinds whose worker may report a gap. The BUILDERS (draft/implement) gap
# when they cannot BUILD coherently. The FIXER also gaps — but at the other
# end of the cycle: when a queued finding is valid yet UNFIXABLE in scope
# because the sealed documentation set contradicts itself (fixing it would
# require rewriting a sealed doc the fix call may not touch). The operator's
# rule (2026-07-15): the right to route a contradiction does not depend on
# WHO found it — a fixer is the same AI as a builder, and a review finding
# that exposes an insoluble-in-scope contradiction must route (fits_remodel
# -> re-documentation wave; needs_operator -> operator), never dead-end at
# a bare `blocked`. The fixer is the confirmation choke-point: a contradiction
# a reviewer merely suspected has survived into an actual repair attempt
# before it can reopen the sealed skeleton. A plain reviewer still only files
# findings (one family must not unilaterally reopen the design).
GAP_ELIGIBLE_KINDS = (
    KIND_DRAFT_SKELETON, KIND_DRAFT_SLICE_NOTE, KIND_IMPLEMENT,
    KIND_FIX_FINDINGS,
)


DESIGN_CORRECTION_DECISIONS = (
    "ratify", "retry", "remodel", "needs_operator",
)


def validate_design_correction(value, ctx):
    """A fixer's one-shot proposal to correct its own sealed slice note."""
    if not isinstance(value, dict):
        raise ContractError("%s.design_correction must be an object" % ctx)
    for field in ("artifact", "contradiction", "resolution"):
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise ContractError(
                "%s.design_correction.%s must be a non-empty string"
                % (ctx, field)
            )
    artifact_authority = value.get("authority_artifact")
    brainstorming_authority = value.get("brainstorming_authority")
    if (artifact_authority is None) == (brainstorming_authority is None):
        raise ContractError(
            "%s.design_correction requires exactly one authority_artifact "
            "or brainstorming_authority" % ctx
        )
    # Which authority is in play is decided by the pair above, never by the
    # key inventory: surplus (including the other authority left explicitly
    # null) is pruned, not rejected.
    if artifact_authority is not None:
        if (
            not isinstance(artifact_authority, str)
            or not artifact_authority.strip()
        ):
            raise ContractError(
                "%s.design_correction.authority_artifact must be the one "
                "non-empty authority" % ctx
            )
        _prune_extras(
            value,
            {
                "artifact",
                "authority_artifact",
                "contradiction",
                "resolution",
            },
        )
    else:
        if not isinstance(brainstorming_authority, dict):
            raise ContractError(
                "%s.design_correction.brainstorming_authority is invalid"
                % ctx
            )
        expected = {"session_id", "accepted_target_revision"}
        _require_keys(
            brainstorming_authority,
            expected,
            "%s.design_correction.brainstorming_authority" % ctx,
        )
        _prune_extras(brainstorming_authority, expected)
        _prune_extras(
            value,
            {
                "artifact",
                "brainstorming_authority",
                "contradiction",
                "resolution",
            },
        )
        for field in ("session_id", "accepted_target_revision"):
            item = brainstorming_authority.get(field)
            if not isinstance(item, str) or not item.strip():
                raise ContractError(
                    "%s.design_correction.brainstorming_authority.%s must "
                    "be non-empty" % (ctx, field)
                )
    return value


def validate_design_correction_verdict(value, findings, ctx):
    """Independent delta-review decision on a provisional correction."""
    if not isinstance(value, dict):
        raise ContractError(
            "%s.design_correction_verdict must be an object" % ctx
        )
    decision = value.get("decision")
    if decision not in DESIGN_CORRECTION_DECISIONS:
        raise ContractError(
            "%s.design_correction_verdict.decision must be one of %r"
            % (ctx, DESIGN_CORRECTION_DECISIONS)
        )
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ContractError(
            "%s.design_correction_verdict.reason must be non-empty" % ctx
        )
    if decision == "ratify" and findings:
        raise ContractError(
            "%s: ratify requires a clean delta; use retry with findings"
            % ctx
        )
    if decision == "retry" and not findings:
        raise ContractError(
            "%s: retry requires at least one actionable finding" % ctx
        )
    return value


# The engineering question battery (build-driven review reform §4): under
# a reform profile every DOC draft answers a fixed set of engineering
# questions as STRUCTURE — one entry per question with its answer and
# evidence citations — mirrored in the contract JSON. The skeleton
# carries the milestone-level battery; a slice note inherits it and
# answers only the slice-scoped remainder.
#
# threat_model and enforceability were added after a live failure
# (2026-07-10, LPC rich-content impl-02): a sealed note asserted a
# security universal no pinned mechanism could enforce and never named
# the attacker, so implementation burned 100+ rounds discovering at the
# CODE phase what these questions surface at the DOC phase — reviewers
# treated trusted product configuration as hostile, and the impossible
# guarantee could only be met by forbidden custom machinery or by
# rewriting the sealed note. enforceability is asked at BOTH doc levels
# (the same id in both tuples): the skeleton answers it for the design's
# guarantees, each note re-answers it for the slice-scoped facts it pins
# — it is exempt from the note's inherit-don't-re-answer rule.
BATTERY_QUESTIONS_SKELETON = (
    "victim", "machinery", "consumers", "cheaper_alternative", "cost",
    "threat_model", "enforceability",
)
BATTERY_QUESTIONS_SLICE_NOTE = (
    "consumers_touched", "pinned_facts", "verification", "reuse_posture",
    "enforceability",
)
BATTERY_ANSWER_CLIP = 2000
BATTERY_EVIDENCE_CLIP = 300


def validate_battery(battery, required_questions, ctx):
    """Validate a doc draft's structured question battery (reform §4).

    Presence and SHAPE are machine-checked here: every required question
    answered exactly once (order free), each with a non-empty answer and
    at least one non-empty evidence citation. SUBSTANCE — does the cited
    evidence exist and say what the answer claims — is review work, never
    the validator's; the project-concept reuse-audit contract (enumerated
    entries with file:line evidence, machine-checked for presence) is the
    prototype this form generalizes."""
    if not isinstance(battery, list):
        raise ContractError(
            "%s.battery: must be a list of entry objects" % ctx
        )
    seen = set()
    for i, entry in enumerate(battery):
        ectx = "%s.battery[%d]" % (ctx, i)
        if not isinstance(entry, dict):
            raise ContractError("%s: entry must be an object" % ectx)
        question = _require(entry, "question", str, ectx)
        if question not in required_questions:
            raise ContractError(
                "%s: question %r is not one of the required questions %s"
                % (ectx, question, list(required_questions))
            )
        if question in seen:
            raise ContractError(
                "%s: duplicate entry for question %r (answer each "
                "question exactly once)" % (ectx, question)
            )
        seen.add(question)
        answer = _require(entry, "answer", str, ectx)
        if not answer.strip():
            raise ContractError(
                "%s: answer must be a non-empty string" % ectx
            )
        if len(answer) > BATTERY_ANSWER_CLIP:
            raise ContractError(
                "%s: answer exceeds %d chars — answer as structure, not "
                "prose" % (ectx, BATTERY_ANSWER_CLIP)
            )
        evidence = _require(entry, "evidence", list, ectx)
        if not evidence:
            raise ContractError(
                "%s: evidence must be a non-empty list of citations" % ectx
            )
        for j, cite in enumerate(evidence):
            if not isinstance(cite, str) or not cite.strip():
                raise ContractError(
                    "%s.evidence[%d]: each citation must be a non-empty "
                    "string" % (ectx, j)
                )
            if len(cite) > BATTERY_EVIDENCE_CLIP:
                raise ContractError(
                    "%s.evidence[%d]: citation exceeds %d chars"
                    % (ectx, j, BATTERY_EVIDENCE_CLIP)
                )
    missing = [q for q in required_questions if q not in seen]
    if missing:
        raise ContractError(
            "%s.battery: missing required question(s) %s (every required "
            "question must be answered)" % (ctx, missing)
        )
    return battery


def validate_suite_command(command, ctx):
    if not isinstance(command, str) or not command.strip():
        raise ContractError(
            "%s: suite_command, when present, must be a non-empty string"
            % ctx
        )
    lowered = command.strip().lower()
    if (
        lowered in ("true", "false", ":", "exit 0", "exit")
        or lowered.startswith("echo ")
        or lowered.startswith("printf ")
    ):
        raise ContractError(
            "%s: suite_command %r is a no-op, not a test suite"
            % (ctx, command)
        )


def validate_need_rethink(
    obj, kind, ctx, require_plain=False, require_failure_gap=False
):
    """Validate the closed, non-completing milestone adapter signal."""
    if kind not in RETHINK_KINDS:
        raise ContractError(
            "%s: need_rethink is not allowed for kind %r" % (ctx, kind)
        )
    required = {
        "status",
        "kind",
        "request",
        "finding",
        "target_path",
        "max_rounds",
    }
    _require_keys(obj, required, "%s: need_rethink" % ctx)
    # Surplus is ignored here as everywhere else (an envelope carrying
    # `notes` used to be rejected on this path alone) — with ONE exception
    # that is not noise: the kind's own work product. need_rethink is
    # help-seeking, not completion, so a rethink that also claims
    # files_changed / artifact / findings is a contradiction, not a
    # surplus field.
    claimed = sorted(set(obj) & KIND_OUTPUT_KEYS.get(kind, frozenset()))
    if claimed:
        raise ContractError(
            "%s: need_rethink is help-seeking, not completion; it must not "
            "also claim %s" % (ctx, claimed)
        )
    result_mode = obj.get("result_mode", RETHINK_RESULT_PROPOSAL)
    if result_mode not in RETHINK_RESULT_MODES:
        raise ContractError(
            "%s: need_rethink.result_mode %r not in %r"
            % (ctx, result_mode, RETHINK_RESULT_MODES)
        )
    request = obj["request"]
    if not isinstance(request, str) or not request.strip():
        raise ContractError(
            "%s: need_rethink.request must be non-empty" % ctx
        )
    finding = obj["finding"]
    if not isinstance(finding, dict) or not finding:
        raise ContractError(
            "%s: need_rethink.finding must be one non-empty object" % ctx
        )
    if kind in REPORT_KINDS:
        validate_report_finding(
            finding, "%s.finding" % ctx, require_plain=require_plain
        )
    target = obj["target_path"]
    if not isinstance(target, str) or not target.strip():
        raise ContractError(
            "%s: need_rethink.target_path must be non-empty" % ctx
        )
    if (
        os.path.isabs(target)
        or "\x00" in target
        or os.path.normpath(target) != target
        or target in (".", "..")
        or target.startswith(".." + os.sep)
    ):
        raise ContractError(
            "%s: need_rethink.target_path must be normalized and "
            "workspace-relative" % ctx
        )
    if (
        type(obj["max_rounds"]) is not int
        or obj["max_rounds"] != MILESTONE_BRAINSTORMING_ROUNDS
    ):
        raise ContractError(
            "%s: need_rethink.max_rounds must be exactly %d"
            % (ctx, MILESTONE_BRAINSTORMING_ROUNDS)
        )
    if require_failure_gap and "failure_gap" not in obj:
        raise ContractError(
            "%s: legacy continuation need_rethink requires failure_gap"
            % ctx
        )
    if "failure_gap" in obj:
        if kind not in RETHINK_CONTINUATION_KINDS:
            raise ContractError(
                "%s: failure_gap is allowed only for a continuable legacy "
                "builder/fixer" % ctx
            )
        validate_gap(obj["failure_gap"], "%s.failure_gap" % ctx)
    if result_mode == RETHINK_RESULT_DESIGN_AMENDMENT:
        if kind not in RETHINK_CONTINUATION_KINDS:
            raise ContractError(
                "%s: design_amendment is allowed only for a continuable "
                "builder/fixer" % ctx
            )
    return obj


def validate_worker_output(obj, kind, require_plain=False,
                           battery_questions=None,
                           require_drift_damage=False,
                           allow_design_correction=False,
                           require_design_correction_verdict=False,
                           require_failure_gap=False,
                           verification_repair=False):
    """Validate the full worker JSON output for a call of `kind`.

    require_plain: reform runs hard-require the plain/example lay mirror
    on every reviewer finding. battery_questions: when non-None, a doc
    draft (skeleton/slice note) must carry a `battery` answering exactly
    these question ids (reform §4). Both checks run only on `ok` outputs
    — blocked, retry, and gap outputs are exempt (none finishes work).

    Returns the object unchanged on success; raises ContractError otherwise.
    """
    if kind not in KINDS:
        raise ContractError("unknown kind %r" % (kind,))
    if verification_repair and kind != KIND_FIX_FINDINGS:
        raise ContractError(
            "verification_repair is only valid for fix_findings"
        )
    ctx = "worker[%s]" % kind
    if not isinstance(obj, dict):
        raise ContractError("%s: output must be a JSON object" % ctx)

    status = _require(obj, "status", str, ctx)
    if status not in ("ok", "blocked", "retry", "gap", "need_rethink"):
        raise ContractError(
            "%s: status %r not in "
            "('ok','blocked','retry','gap','need_rethink')"
            % (ctx, status)
        )
    echoed = _require(obj, "kind", str, ctx)
    if echoed != kind:
        raise ContractError(
            "%s: echoed kind %r does not match requested kind %r"
            % (ctx, echoed, kind)
        )
    if status == "need_rethink":
        return validate_need_rethink(
            obj,
            kind,
            ctx,
            require_plain=require_plain,
            require_failure_gap=require_failure_gap,
        )
    # gaps ride ONLY with a gap status — an `ok` carrying a non-empty gaps
    # array is a contract violation (nothing was finished, or nothing was
    # reported; the two cannot both be true). §3.
    if status != "gap" and obj.get("gaps"):
        raise ContractError(
            "%s: a non-empty `gaps` array is only allowed with status "
            "'gap' (got %r)" % (ctx, status)
        )
    if status == "blocked":
        reason = _optional(obj, "blocked_reason", str, ctx)
        if not reason:
            raise ContractError(
                "%s: blocked status requires a non-empty blocked_reason" % ctx
            )
        return obj
    if status == "retry":
        if verification_repair:
            raise ContractError(
                "%s: verification repair does not support retry" % ctx
            )
        if kind != KIND_FIX_FINDINGS:
            raise ContractError(
                "%s: retry status is only allowed for fix_findings" % ctx
            )
        reason = _require(obj, "retry_reason", str, ctx)
        if reason != RETRY_CONSULTATION_UNAVAILABLE:
            raise ContractError(
                "%s: retry_reason must be %r"
                % (ctx, RETRY_CONSULTATION_UNAVAILABLE)
            )
        for claim in (
            "findings", "files_changed", "slices", "artifact", "gaps",
            "battery", "suite_command", "suite_command_finding_id",
            "design_correction", "design_correction_verdict",
            "implementation_cut",
        ):
            if claim in obj:
                raise ContractError(
                    "%s: a retry response must not include %r "
                    "(nothing was finished)" % (ctx, claim)
                )
        return obj
    if status == "gap":
        if kind not in GAP_ELIGIBLE_KINDS:
            raise ContractError(
                "%s: only draft/implement kinds may report a gap; %r may "
                "not" % (ctx, kind)
            )
        gaps = _require(obj, "gaps", list, ctx)
        if not gaps:
            raise ContractError(
                "%s: gap status requires a non-empty `gaps` array" % ctx
            )
        for i, g in enumerate(gaps):
            validate_gap(g, "%s.gaps[%d]" % (ctx, i))
        # A gap carries NO artifact claim — nothing was finished.
        for claim in (
            "artifact", "files_changed", "slices", "battery",
            "design_correction", "design_correction_verdict",
            "implementation_cut",
        ):
            if obj.get(claim):
                raise ContractError(
                    "%s: a gap response must not also claim %r "
                    "(nothing was finished)" % (ctx, claim)
                )
        return obj

    if kind == KIND_DRAFT_SKELETON:
        _require(obj, "artifact", str, ctx)
        slices = _require(obj, "slices", list, ctx)
        if not slices:
            raise ContractError("%s: skeleton must propose at least one slice" % ctx)
        validate_slices(slices, "%s.slices" % ctx)
        if battery_questions is not None:
            _require(obj, "battery", list, ctx)
            validate_battery(obj["battery"], battery_questions, ctx)
    elif kind == KIND_DRAFT_SLICE_NOTE:
        _require(obj, "artifact", str, ctx)
        slices = _optional(obj, "slices", list, ctx)
        if slices is not None:
            if not slices:
                raise ContractError(
                    "%s: slices, when present, must be non-empty" % ctx
                )
            validate_slices(slices, "%s.slices" % ctx)
        if battery_questions is not None:
            _require(obj, "battery", list, ctx)
            validate_battery(obj["battery"], battery_questions, ctx)
    elif kind == KIND_IMPLEMENT:
        _require(obj, "files_changed", list, ctx)
        cut = _optional(obj, "implementation_cut", dict, ctx)
        if cut is not None:
            validate_implementation_cut(cut, "%s.implementation_cut" % ctx)
        slices = _optional(obj, "slices", list, ctx)
        if slices is not None:
            if not slices:
                raise ContractError(
                    "%s: slices, when present, must be non-empty" % ctx
                )
            validate_slices(slices, "%s.slices" % ctx)
        if obj.get("suite_command") is not None:
            validate_suite_command(obj["suite_command"], ctx)
    elif kind in REPORT_KINDS:
        findings = _require(obj, "findings", list, ctx)
        for i, f in enumerate(findings):
            validate_report_finding(
                f, "%s.findings[%d]" % (ctx, i), require_plain=require_plain
            )
        _assert_unique_finding_ids(findings, ctx)
        if obj.get("files_changed"):
            raise ContractError(
                "%s: report kinds must not claim file changes" % ctx
            )
        verdict = obj.get("design_correction_verdict")
        if require_design_correction_verdict:
            if kind != KIND_DELTA_REVIEW:
                raise ContractError(
                    "%s: a design-correction verdict is delta-review only"
                    % ctx
                )
            validate_design_correction_verdict(verdict, findings, ctx)
        elif verdict is not None:
            raise ContractError(
                "%s: unexpected design_correction_verdict" % ctx
            )
    elif kind == KIND_FIX_FINDINGS:
        findings = _require(obj, "findings", list, ctx)
        if verification_repair and findings:
            raise ContractError(
                "%s: verification repair requires an empty findings list; "
                "ok certifies the live full suite" % ctx
            )
        for i, f in enumerate(findings):
            validate_fix_finding(f, "%s.findings[%d]" % (ctx, i))
        _assert_unique_finding_ids(findings, ctx)
        _optional(obj, "files_changed", list, ctx, default=[])
        application = obj.get("brainstorming_application")
        if application is not None:
            validate_brainstorming_application(
                application, "%s.brainstorming_application" % ctx
            )
        if verification_repair:
            if application is not None:
                raise ContractError(
                    "%s: verification repair cannot claim a Brainstorming "
                    "application" % ctx
                )
            for claim in ("suite_command", "suite_command_finding_id"):
                if claim in obj:
                    raise ContractError(
                        "%s: verification repair must not include %r"
                        % (ctx, claim)
                    )
            # The suite is certified by this envelope alone, so the ONE
            # thing that decides whether the certification can be trusted
            # is whether the tests themselves were altered to obtain it.
            # Declared, never inferred: "a test" is language-specific and
            # in Rust or Elixir lives INSIDE the source file, so no path
            # rule could decide it without inventing false violations.
            # The declaration is therefore trusted, like the rest of the
            # report-only contract — it only routes the review.
            tests_modified = obj.get("tests_modified")
            if not isinstance(tests_modified, bool):
                raise ContractError(
                    "%s: verification repair must declare tests_modified "
                    "as a boolean" % ctx
                )
            changed_tests = _optional(obj, "tests_changed", list, ctx)
            if tests_modified:
                if not changed_tests:
                    raise ContractError(
                        "%s: tests_modified requires tests_changed naming "
                        "every altered test file" % ctx
                    )
                for i, path in enumerate(changed_tests):
                    if not isinstance(path, str) or not path.strip():
                        raise ContractError(
                            "%s.tests_changed[%d] must be a non-empty path"
                            % (ctx, i)
                        )
            elif changed_tests:
                raise ContractError(
                    "%s: tests_changed contradicts tests_modified false"
                    % ctx
                )
        else:
            suite_command = obj.get("suite_command")
            suite_finding_id = obj.get("suite_command_finding_id")
            if suite_command is not None:
                validate_suite_command(suite_command, ctx)
                suite_finding_id = _require(
                    obj, "suite_command_finding_id", str, ctx
                )
                matches = [
                    finding for finding in findings
                    if finding.get("id") == suite_finding_id
                ]
                if (
                    len(matches) != 1
                    or matches[0].get("disposition") != "fixed"
                ):
                    raise ContractError(
                        "%s: suite_command_finding_id must name exactly one "
                        "finding disposed 'fixed'" % ctx
                    )
            elif suite_finding_id is not None:
                raise ContractError(
                    "%s: suite_command_finding_id requires suite_command" % ctx
                )
        # Optional updated slice plan: only meaningful when the fix touched
        # the milestone skeleton's slice table (before the skeleton seals).
        slices = _optional(obj, "slices", list, ctx)
        if slices is not None:
            if not slices:
                raise ContractError(
                    "%s: slices, when present, must be non-empty" % ctx
                )
            validate_slices(slices, "%s.slices" % ctx)
        correction = obj.get("design_correction")
        if correction is not None:
            if not allow_design_correction:
                raise ContractError(
                    "%s: design_correction was not offered for this call"
                    % ctx
                )
            validate_design_correction(correction, ctx)
    elif kind == KIND_RECLASSIFY:
        risk = _require(obj, "drift_risk", str, ctx)
        if risk not in DRIFT_RISK_LEVELS:
            raise ContractError(
                "%s: drift_risk must be one of %s"
                % (ctx, "|".join(DRIFT_RISK_LEVELS))
            )
        # The reform's two-axis rating (probability x damage): reform
        # runs REQUIRE the damage axis — the deferral decision gates on
        # it; legacy raters never see or send it (bit-identical).
        if require_drift_damage:
            damage = _require(obj, "drift_damage", str, ctx)
        else:
            damage = _optional(obj, "drift_damage", str, ctx)
        if damage is not None and damage not in DRIFT_RISK_LEVELS:
            raise ContractError(
                "%s: drift_damage must be one of %s"
                % (ctx, "|".join(DRIFT_RISK_LEVELS))
            )
        reason = _require(obj, "reason", str, ctx)
        if not reason.strip():
            raise ContractError("%s: reason must be non-empty" % ctx)
    return obj


# Reserved top-level output keys: the base protocol's own output surface,
# kept beside validate_worker_output as the single source. A project
# contract extension may never name one of these as its `field` — the
# extension would shadow a key the validator or driver already reads
# (verifiers.py derives collisions from here; it never re-lists them).
COMMON_OUTPUT_KEYS = frozenset(
    {
        "status",
        "kind",
        "blocked_reason",
        "notes",
        "gaps",
        "request",
        "finding",
        "target_path",
        "max_rounds",
        "result_mode",
        "failure_gap",
    })

KIND_OUTPUT_KEYS = {
    # Doc drafts reserve "battery" even though only reform runs require
    # it: a project contract extension must never collide with the
    # question battery's output field.
    KIND_DRAFT_SKELETON: frozenset({"artifact", "slices", "battery"}),
    KIND_DRAFT_SLICE_NOTE: frozenset({"artifact", "battery", "slices"}),
    KIND_IMPLEMENT: frozenset(
        {"files_changed", "suite_command", "slices", "implementation_cut"}
    ),
    KIND_REVIEW_ROUND: frozenset({"findings", "files_changed"}),
    KIND_DELTA_REVIEW: frozenset(
        {"findings", "files_changed", "design_correction_verdict"}
    ),
    # fix_findings may also carry suite_command (the driver adopts it when
    # correcting/arming the verification gate).
    KIND_FIX_FINDINGS: frozenset(
        {
            "findings", "files_changed", "slices", "suite_command",
            "suite_command_finding_id", "design_correction",
            "retry_reason", "brainstorming_application",
        }
    ),
    KIND_RECLASSIFY: frozenset(
        {"drift_risk", "drift_damage", "reason", "questions"}
    ),
    # Routed directly through prompt_contracts rather than the legacy worker
    # validator, but project safeguards still need the same collision source.
    KIND_MERGE_REPAIR: frozenset({"files_changed"}),
    KIND_SUITE_CHECKPOINT: frozenset(
        {"commands", "authority", "results", "failure_account"}
    ),
}


def reserved_output_keys(kind):
    """Top-level output keys the worker protocol itself uses for `kind`
    (the common keys plus the kind's own)."""
    if kind not in KIND_OUTPUT_KEYS:
        raise ContractError("unknown kind %r" % (kind,))
    return COMMON_OUTPUT_KEYS | KIND_OUTPUT_KEYS[kind]


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
    return all_in_severity(findings, ("P3",))


def all_in_severity(findings, scope):
    """True when there is at least one finding and EVERY finding's severity
    is in `scope` — the round is eligible for the reclassify/debt path.
    Any finding whose severity is OUTSIDE scope (e.g. a P0/P1 when scope is
    the reform's {P2,P3}) means a fix round fires anyway. Generalizes
    all_p3 from the pre-reform P3-only gate to a profile-chosen scope; the
    canonical rule that P0/P1 ALWAYS fix (spec decision 1) is the invariant
    that P0/P1 are never in any deferral scope."""
    findings = list(findings or [])
    scope = set(scope)
    return bool(findings) and all(
        f.get("severity") in scope for f in findings
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
  "status": "ok" | "blocked" | "retry" | "need_rethink"
  "kind": "<echo the KIND header of this prompt>"
  "blocked_reason": string    (required when status is "blocked": explain
                               precisely what stops you; the run will end
                               with this explanation in the log)
  "notes": string             (optional, short)

`status: "retry"` is allowed ONLY for kind fix_findings when its mandatory
opposite-family consultation could not run or ended without a clear result:
  "retry_reason": "consultation_unavailable"
Return no findings or work claims with it. The driver records a transient
failure and the process guard retries the same fix episode after 15 minutes.

`status: "need_rethink"` is allowed ONLY for draft_slice_note, implement,
fix_findings, review_round and delta_review when one focused design request
should be resolved by the independent Brainstorming process before this worker
can finish its current judgment. It is help-seeking, not completion. Return
EXACTLY:
  "status": "need_rethink"
  "kind": "<echo the current eligible kind>"
  "request": "<one non-empty focused request or desired outcome>"
  "finding": {<the one current finding, preserved as source evidence>}
  "target_path": "<normalized workspace-relative source artifact to isolate>"
  "max_rounds": __ROUNDS__
  "result_mode": "proposal" | "design_amendment"
Use `design_amendment` only when one conservative, bounded clarification of
the current reviewed design can resolve an in-goal contradiction without
changing the operator goal or an operator-reserved decision. It may amend the
skeleton and affected slice notes and may assign bounded repair work to the
current slice or a new future slice. In that mode
`target_path` names the smallest source artifact for context; Brainstorming
constructs a separate concise amendment target. Use `proposal` for an ordinary
focused request. Set max_rounds to __ROUNDS__; the session may close earlier on
agreement. Review
kinds may use only `proposal`. The validator accepts
an omitted result_mode as `proposal` solely for in-flight run compatibility.
Do not mix need_rethink with notes, ordinary findings/results, work/file claims,
retry, disposition, verdict, gap arrays, or slice plans. A fixer must put
exactly one currently queued finding in `finding`; its queued siblings remain
pending. Any materializable workspace artifact may be selected as the source,
including one also named in context, a generated milestone record, or
the artifact currently under judgment; the adapter supplies isolation by
copying it into the Brainstorming-owned work area.

Kind draft_skeleton adds:
  "artifact": "<workspace-relative path of the skeleton document you wrote>"
  "slices": [ {"id": 1, "title": "...",
                 "producer_task_executor": {
                   "draft_slice_note": {"task_executor": "...",
                                          "configuration": <optional object>},
                   "implement": {"task_executor": "...",
                                  "configuration": <optional object>}}}, ... ]
  (unique integer ids; propose both producer choices independently)

Kind draft_slice_note adds:
  "artifact": "<workspace-relative path of the slice note you wrote>"
  When the prompt includes SLICE PRODUCER PLANNING, also return the complete
  updated plan in "slices", using the same shape as draft_skeleton above.

Kind implement adds:
  "files_changed": ["<workspace-relative paths you created or edited>", ...]
  When the prompt includes SLICE PRODUCER PLANNING, also return the complete
  updated plan in "slices", using the same shape as draft_skeleton above.
  "suite_command": "<the repo's official full-test-suite command, exactly
   as you would run it from the workspace root; it must
   be non-interactive and run the suite exactly ONCE and exit — never a
   watch mode; null or omitted if the repo has no suite>"
  "implementation_cut": {"cut_scope": "<the coherent functional cut now
                            complete and ready for review>",
                         "remaining_scope": "<the original slice obligations
                            deliberately delegated to the next sequential
                            implementation part>"}
   Include `implementation_cut` proactively when you close a coherent unit
   while original slice work remains, or when responding to the driver's live
   close instruction or forced-cutoff stabilization. Omit it when the original
   slice scope is complete. Both strings must be concrete and non-empty. This
   field reports the boundary; it does not let you choose labels or
   create/renumber design slices. The orchestrator derives a/b/c sequentially
   and opens the next part only after this one completes its full review cycle.

Kind fix_findings may ALSO include "suite_command" when a queued finding
identifies a missing, narrowed, or wrong final verification command — whether the
finding came from verification or review. The driver adopts that
state correction, makes the updated command part of review evidence, and
runs it at the final boundary after current-byte reviews are clean.
It must also include "suite_command_finding_id", naming that queued finding;
the referenced finding must be disposed "fixed".

REVIEW kinds (review_round / delta_review) add:
  "findings": [
    {"id": "F1", "severity": "P0"|"P1"|"P2"|"P3", "summary": "...",
     "validity": {
       "permitted_baseline": "<the normal/allowed outcome under the goal,
                              design, and declared guarantee posture>",
       "actual_outcome": "<the concrete observed outcome>",
       "incremental_harm": "<harm beyond that permitted baseline>",
       "exceeds_baseline": true},
     "plain": "<ONE sentence, <500 chars, a non-engineer understands: name what is
      being built and what is actually wrong, in everyday words — e.g.
      'we are specifying a floating menu; the doc and the package README
      disagree about whether it ships JavaScript'. No file:line, no
      spec vocabulary. Write this sentence BEFORE choosing severity:
      the technical register makes everything sound grave; the plain
      sentence shows the real size of the problem>",
     "example": "<the SMALLEST (<500 chars) concrete scenario where this bites — one
      actor, one action, the wrong outcome vs the expected one, in plain
      words. E.g. 'a test deletes a message without saying who is in the
      thread; the fake chat allows it; the real one rejects it with an
      authorization error'. For a CONTRADICTION, two colliding facts
      beat a scenario: 'the doc closes the list at four types — no
      more, ever. The plan requires a fifth.' If you cannot write such
      a scenario, the finding may not be real. THE BAR for plain AND
      example: a reader who has NEVER seen this codebase must
      understand what is wrong, judge how big it is, and know where to
      act — WITHOUT opening a single file. If understanding requires
      reading code, your expression failed: rewrite it>",
     "contests": null | {"rejection_id": "<id from the ADJUDICATED
      REJECTIONS list>", "new_evidence": "<the new fact that contradicts
      the recorded rationale>"}}
  ]
  Rules: you REVIEW ONLY — you return findings, no disposition field.
  Finding ids must be unique within this
  response. An empty findings list means the target is clean. EVERY
  finding MUST include `plain` AND `example` — a finding without its
  plain-language sentence and its smallest (<500 chars) concrete failure
  scenario is incomplete. `validity.exceeds_baseline` MUST be true: if the
  actual outcome stays within the permitted baseline, emit no finding.
  Before filing any finding, check the ADJUDICATED REJECTIONS list
  in this prompt: if your finding challenges one of them you MUST fill
  `contests` with its id and genuinely new evidence; re-raising an
  adjudicated finding without new evidence is a protocol violation.

Kind fix_findings adds:
  "findings": [
    {"id": "<echo the queued finding's id>", "severity": "<echo>",
     "summary": "...",
     "validity": {
       "affected_party": "<who or what is concretely affected, or why none>",
       "observable_damage": "<the concrete observable damage, or why none>",
       "violated_guarantee": "<the exact violated guarantee, or why none>",
       "permitted_baseline": "<independently verified normal/allowed outcome>",
       "incremental_harm": "<harm beyond that permitted baseline, or why
                            there is none>",
       "exceeds_baseline": true | false},
     "disposition": "fixed" | "rejected" | "rejected_adjudicated" | "blocked",
     "consultation": null | {"resolution": "<one-paragraph outcome of the
                              opposite-family dialogue you ran>"},
     "prevention": null | {"documented_in": "<path you edited>",
                           "note": "<what now documents the decision>"},
     "adjudication_ref": null | "<registry id of the prior rejection>"}
  ]
  "files_changed": ["...paths you edited...", ...]
  "slices": [ {"id": 1, "title": "...",
                 "producer_task_executor": {
                   "draft_slice_note": {"task_executor": "...",
                                          "configuration": <optional object>},
                   "implement": {"task_executor": "...",
                                  "configuration": <optional object>}}}, ... ]
   (REQUIRED whenever your
   fix changed the milestone skeleton's slice TABLE — split, added,
   removed, or renumbered slices: return the FULL updated plan exactly
   as the table now reads. The orchestrator builds units from THIS
   field, never by parsing the document; omitting it after a table
   change leaves the added slices unbuilt. Omit it when the table is
   untouched.)
  Rules: triage EXACTLY the queued findings (same ids, nothing else).
  Verify each against the real code/doc before deciding. A finding is valid
  only when affected_party, observable_damage, and violated_guarantee are
  concrete and evidence-backed and `exceeds_baseline` is true. If any cannot
  be demonstrated, the finding is invalid: use `rejected` and its mandatory
  consultation (or `rejected_adjudicated` for a settled duplicate). `fixed`
  and `blocked` require `validity.exceeds_baseline: true`; `rejected` and
  `rejected_adjudicated` require false. "rejected"
  REQUIRES the consultation; when the target was correct but misreadable,
  ALSO make the minimal clarifying edit and record it in `prevention` so
  the finding cannot keep being reborn. "rejected_adjudicated" is for
  findings duplicating an entry of the ADJUDICATED REJECTIONS list without
  new evidence: cite it in adjudication_ref, no consultation needed, do
  not re-litigate. Use "blocked" only when neither fixing nor a justified
  rejection is possible for a CONFIRMED finding; the run will stop and show
  your reason. An unresolved or unavailable consultation is NOT a finding
  disposition: return top-level `status: "retry"` as specified above.
"""


# Review/fix prompts use narrow contracts.  CONTRACT_TEXT remains the
# compatibility contract for draft/implement continuations, but making a
# reviewer read every other worker kind buried its own schema under thousands
# of irrelevant words.
REPORT_CONTRACT_TEXT = """OUTPUT CONTRACT (mandatory)
Return exactly one JSON object; no prose or markdown fences.

Clean or findings:
{"status":"ok","kind":"<echo KIND>","findings":[<finding>, ...],
 "notes":"<optional short note>"}
Each finding is exactly:
{"id":"<unique id>","severity":"P0|P1|P2|P3","summary":"...",
 "validity":{"permitted_baseline":"...","actual_outcome":"...",
             "incremental_harm":"...","exceeds_baseline":true},
 "plain":"<one lay sentence, under 500 chars>",
 "example":"<smallest concrete scenario, under 500 chars>",
 "contests":null|{"rejection_id":"<settled id>",
                   "new_evidence":"<what changes it>"}}
Reviewers report only: never add a disposition. Empty findings means clean.
If the outcome does not exceed the permitted baseline, emit no finding.
Plain and example must expose the defect and its scale without opening files.
If a finding challenges a listed rejection, `contests` is mandatory: cite its
id and genuinely new evidence. Without new evidence, emit no finding.
Include any extra field explicitly required by an active project-safeguard or
design-correction block above.

Impossible task:
{"status":"blocked","kind":"<echo KIND>","blocked_reason":"..."}

Focused discussion before finishing this judgment:
{"status":"need_rethink","kind":"<echo KIND>","request":"...",
 "finding":{<one complete current finding>},
 "target_path":"<normalized workspace-relative path>",
 "max_rounds":__ROUNDS__,"result_mode":"proposal"}
The session may close earlier on agreement.
Return no other fields with `blocked` or `need_rethink`.
"""


FIX_CONTRACT_TEXT = """OUTPUT CONTRACT (mandatory)
Return exactly one JSON object; no prose or markdown fences.

Completed fix pass:
{"status":"ok","kind":"fix_findings","findings":[<result>, ...],
 "files_changed":["..."],"notes":"<optional short note>"}
Return one result for every queued id, and no others:
{"id":"<echo>","severity":"<echo>","summary":"...",
 "validity":{"affected_party":"...","observable_damage":"...",
             "violated_guarantee":"...","permitted_baseline":"...",
             "incremental_harm":"...","exceeds_baseline":true|false},
 "disposition":"fixed|rejected|rejected_adjudicated|blocked",
 "consultation":null|{"resolution":"..."},
 "prevention":null|{"documented_in":"<edited path>","note":"..."},
 "adjudication_ref":null|"<settled rejection id>"}
`fixed`/`blocked` require a concrete, evidence-backed affected party,
observable damage, and violated guarantee, plus exceeds_baseline=true. If any
cannot be demonstrated, the finding is invalid: `rejected` requires its
consultation (`rejected_adjudicated` remains the settled-duplicate path), and
both rejection dispositions require exceeds_baseline=false. Include extra
fields required by an active block.
When fixing a queued final-suite-command finding, also return `suite_command`
and `suite_command_finding_id`; the command must run the official full suite
once, non-interactively, from the workspace root.

Impossible worker task (not a finding disposition):
{"status":"blocked","kind":"fix_findings","blocked_reason":"..."}

Unavailable or unresolved mandatory consultation:
{"status":"retry","kind":"fix_findings",
 "retry_reason":"consultation_unavailable","notes":"<optional>"}

Focused discussion before deciding one queued finding:
{"status":"need_rethink","kind":"fix_findings","request":"...",
 "finding":{<one complete queued finding>},
 "target_path":"<normalized workspace-relative path>",
 "max_rounds":__ROUNDS__,"result_mode":"proposal|design_amendment"}
The session may close earlier on agreement. Return no work claims or sibling
findings with this status.
"""


SUITE_FIX_CONTRACT_TEXT = """OUTPUT CONTRACT (mandatory)
Return exactly one JSON object; no prose or markdown fences.

Completed suite repair:
{"status":"ok","kind":"fix_findings","findings":[],
 "files_changed":["..."],"tests_modified":false,"tests_changed":[],
 "notes":"<optional short note>"}
`status: "ok"` certifies that you ran the configured full suite on the final
workspace bytes and it passed. `findings` must be empty: this task repairs the
live suite result, not a stored review finding.
`tests_modified` is REQUIRED and boolean: true if you altered any test CODE to
reach green — wherever it lives, including tests embedded in a source file —
false otherwise, naming what you altered in `tests_changed`. It is taken at
its word: a false `no` skips the review that would have caught it.
When the prompt explicitly requires slice-plan synchronization or offers a
legacy design correction, include its normal `slices` or `design_correction`
field as well; those fields receive their ordinary validation.

Impossible worker task:
{"status":"blocked","kind":"fix_findings","blocked_reason":"..."}

Focused discussion before completing a required in-goal design change:
{"status":"need_rethink","kind":"fix_findings","request":"...",
 "finding":{<copy the complete SOURCE SIGNAL from the prompt>},
 "target_path":"<normalized workspace-relative path>",
 "max_rounds":__ROUNDS__,"result_mode":"proposal|design_amendment"}
The session may close earlier on agreement. Return no work claims with this
status.
"""

# One source for the milestone Brainstorming round limit inside the contract
# texts: substituted here so the number can never drift from the validator.
CONTRACT_TEXT, REPORT_CONTRACT_TEXT, FIX_CONTRACT_TEXT, SUITE_FIX_CONTRACT_TEXT = (
    _text.replace("__ROUNDS__", str(MILESTONE_BRAINSTORMING_ROUNDS))
    for _text in (
        CONTRACT_TEXT, REPORT_CONTRACT_TEXT, FIX_CONTRACT_TEXT,
        SUITE_FIX_CONTRACT_TEXT,
    )
)

LEGACY_FAILURE_GAP_CONTRACT = """
Legacy fallback for a focused discussion:
When returning `need_rethink`, also include exactly one `failure_gap` object
using the normal GAP EXIT entry schema. It is required only so the historical
repair route can resume if Brainstorming ends without agreement.
"""


def prompt_contract(kind, gap_enabled=False):
    """Smallest output contract relevant to one worker call."""
    if kind in REPORT_KINDS:
        return REPORT_CONTRACT_TEXT
    if kind == KIND_FIX_FINDINGS:
        gap = (
            "\nDesign contradiction:\n"
            "When GAP EXIT applies, return exactly "
            "{\"status\":\"gap\",\"kind\":\"fix_findings\","
            "\"gaps\":[<one or more gap entries>]}; no findings or work "
            "claims.\n"
            if gap_enabled else ""
        )
        legacy_rethink = (
            LEGACY_FAILURE_GAP_CONTRACT if gap_enabled else ""
        )
        return FIX_CONTRACT_TEXT + gap + legacy_rethink
    legacy_rethink = (
        LEGACY_FAILURE_GAP_CONTRACT
        if gap_enabled and kind in RETHINK_CONTINUATION_KINDS
        else ""
    )
    return CONTRACT_TEXT + legacy_rethink


def suite_fix_contract(gap_enabled=False):
    """Output contract for a fixer that owns full-suite convergence."""
    gap = (
        "\nDesign contradiction:\n"
        "When GAP EXIT applies, return exactly "
        "{\"status\":\"gap\",\"kind\":\"fix_findings\","
        "\"gaps\":[<one or more gap entries>]}; no findings or work "
        "claims.\n"
        if gap_enabled else ""
    )
    legacy_rethink = LEGACY_FAILURE_GAP_CONTRACT if gap_enabled else ""
    return SUITE_FIX_CONTRACT_TEXT + gap + legacy_rethink
