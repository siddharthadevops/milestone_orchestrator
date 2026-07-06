"""Orchestrator state: a JSON document with structurally enforced history.

Properties this module guarantees in code (they used to be prose rules that
LLM orchestrators kept getting wrong):

1. Append-only history. Events, rounds, and seal attempts are lists that can
   only grow; `save()` refuses to persist a state whose history diverges from
   what is already on disk (no rewriting round N's record when round N+1
   learns something).
2. Atomic writes. State is written to a temp file and renamed, so a crash
   mid-step never leaves a half-written state file. Note the flip side:
   records are persisted only after a step completes, so a crash between a
   worker CLI call and that save re-executes the call on resume. Worker
   calls therefore have at-least-once semantics (see the README,
   "Operational semantics").
3. Explicit phase gates. Transition helpers raise IllegalTransition instead
   of silently doing the wrong thing.

The unit sequence mirrors the canon cycle: one skeleton unit, then per slice
a documentation unit and an implementation unit. Every unit runs the same
review machinery: draft -> verify -> codex rounds until clean -> claude
rounds until clean -> verify -> double seal until both halves are clean on
an unchanged workspace.
"""

import copy
from datetime import datetime
import json
import os
import tempfile
import time

SCHEMA_VERSION = 2

# Unit kinds
UNIT_SKELETON = "skeleton"
UNIT_SLICE_DOC = "slice_doc"
UNIT_SLICE_IMPL = "slice_impl"

# Unit statuses (the per-unit state machine)
U_PENDING = "pending"
U_PRE_REVIEW_VERIFY = "pre_review_verify"
U_ROUNDS = "rounds"            # report-only review rounds, families in order
U_FIXING = "fixing"            # a fixer call triages the queued findings
U_DELTA_REVIEW = "delta_review"  # report-only review of the pending fix diff
U_PRE_SEAL_VERIFY = "pre_seal_verify"
U_SEALING = "sealing"
U_SEALED = "sealed"
U_FAILED = "failed"

UNIT_STATUSES = (
    U_PENDING,
    U_PRE_REVIEW_VERIFY,
    U_ROUNDS,
    U_FIXING,
    U_DELTA_REVIEW,
    U_PRE_SEAL_VERIFY,
    U_SEALING,
    U_SEALED,
    U_FAILED,
)

# Milestone statuses
M_OPEN = "open"
M_CLOSED = "closed"
M_FAILED = "failed"


class IllegalTransition(RuntimeError):
    """A driver bug or corrupted state asked for a transition the canon
    flow does not allow."""


class HistoryRewriteError(RuntimeError):
    """An attempt was made to persist a state whose recorded history
    differs from the history already on disk."""


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def slugify(name):
    """Directory-safe milestone slug from a run name."""
    out = []
    for ch in str(name or "").lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    slug = "".join(out).strip("-")[:60].strip("-")
    return slug or "milestone"


def _orchestrator_rev():
    """Best-effort provenance: the orchestrator repo commit that created
    this run. The honest replacement for canon version pinning — the
    process travels in the orchestrator, so each run records which
    orchestrator ran it. None when git is unavailable."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        proc = subprocess.run(
            ["git", "-C", here, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    rev = (proc.stdout or "").strip()
    return rev if proc.returncode == 0 and rev else None


def new_state(goal, workspace, config, name=None, slug=None, project=None):
    docs_template = (config or {}).get("docs_dir") or "docs"
    docs_dir = os.path.normpath(
        docs_template.replace("{slug}", slug or slugify(name))
    ).strip("/")
    if os.path.isabs(docs_dir) or docs_dir.split("/")[0] == "..":
        raise ValueError(
            "docs_dir must stay inside the workspace: %r" % docs_dir
        )
    state = {
        "schema_version": SCHEMA_VERSION,
        "goal": goal,
        "workspace": workspace,
        "name": name,
        # Resolved once at init and stable for the run's life: the
        # milestone docs directory (artifacts + generated ledgers).
        # "docs" is the legacy flat layout (pre-docs_dir runs); anything
        # else uses the canonical milestone layout (README.md, slices/).
        "docs_dir": docs_dir,
        "orchestrator_rev": _orchestrator_rev(),
        "created_at": now_iso(),
        "milestone": {
            "status": M_OPEN,
            "slices": [],          # filled by the skeleton draft; skeleton
                                   # fix rounds may update it until the
                                   # skeleton unit seals
        },
        "units": [
            _new_unit(UNIT_SKELETON, None),
        ],
        "events": [],
        # The repo's official full-suite command, discovered by the first
        # implement worker (its contract's suite_command field). Gates use
        # it when config verification is not explicitly set.
        "suite_command": None,
        "failure": None,
        "config": config,
    }
    if project is not None:
        # The resolved (project, work_area) binding a project-bound init
        # records: {directory, project, work_area, primary, additional}.
        # Like docs_dir, resolved once at init and stable for the run's
        # life; the key is ABSENT for a project-less run, never
        # present-null, so pre-project state documents gain nothing.
        state["project"] = project
    return state


def _new_unit(kind, slice_id):
    return {
        "kind": kind,
        "slice_id": slice_id,
        "status": U_PENDING,
        "artifact": None,
        "draft": None,              # write-once draft record
        "family_index": 0,          # index into config families_order
        "rounds": [],               # append-only
        "seals": [],                # append-only
        # Per-stage fix-attempt counters; each resets when its stage's
        # verification passes (the cap bounds consecutive failures of the
        # current stage, not lifetime fixes of the unit).
        "verify_fix_attempts": {"pre_review": 0, "pre_seal": 0},
        # Never-reset per-stage sequence for synthetic verification fix
        # episodes: verify_fix_attempts resets on a pass, so it cannot
        # number the episode ids (ids must stay unique when a stage is
        # re-entered after a dirty seal attempt).
        "verify_episode_seq": {"pre_review": 0, "pre_seal": 0},
        "closed_record": None,      # slice_impl closure bookkeeping
        "gate_commit": None,        # short sha of this unit's seal gate commit
        "failed_from": None,        # status at failure time (resume target)
        # The active fix episode (working fields; history lives in rounds):
        "fix_queue": [],            # findings currently queued for the fixer
        "fix_source": None,         # {"type": verification|round|seal|delta,
                                    #  "family": origin family or None,
                                    #  "source_round_id": ...,
                                    #  "return_to": status after green+amend}
        "fix_loop_rounds": 0,       # fixer+delta iterations on this episode
    }


# ---------------------------------------------------------------------------
# Persistence with append-only enforcement


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        state = json.load(fh)
    if state.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            "state schema_version %r != %d" % (state.get("schema_version"), SCHEMA_VERSION)
        )
    return state


def _assert_list_prefix(old_list, new_list, ctx):
    if len(new_list) < len(old_list):
        raise HistoryRewriteError("%s: history shrank (%d -> %d)" % (ctx, len(old_list), len(new_list)))
    for i, old_item in enumerate(old_list):
        if new_list[i] != old_item:
            raise HistoryRewriteError(
                "%s[%d]: recorded history was modified; records are "
                "append-only and immutable" % (ctx, i)
            )


def assert_append_only(old_state, new_state_):
    """Raise HistoryRewriteError if new_state_ rewrites recorded history."""
    _assert_list_prefix(old_state.get("events", []), new_state_.get("events", []), "events")
    old_units = old_state.get("units", [])
    new_units = new_state_.get("units", [])
    if len(new_units) < len(old_units):
        raise HistoryRewriteError("units: history shrank")
    for i, old_unit in enumerate(old_units):
        nu = new_units[i]
        uctx = "units[%d]" % i
        if (nu.get("kind"), nu.get("slice_id")) != (old_unit.get("kind"), old_unit.get("slice_id")):
            raise HistoryRewriteError("%s: identity changed" % uctx)
        _assert_list_prefix(old_unit.get("rounds", []), nu.get("rounds", []), uctx + ".rounds")
        _assert_list_prefix(old_unit.get("seals", []), nu.get("seals", []), uctx + ".seals")
        # A SEALED unit is frozen except for post-seal bookkeeping. Failed
        # units are deliberately NOT frozen: resume_run (an explicit
        # operator action, recorded as a `resumed` event) restores them;
        # their rounds/seals history stays append-only like everyone's.
        if old_unit.get("status") == U_SEALED:
            # closed_record and gate_commit are post-seal bookkeeping
            # written by the driver itself right after the terminal
            # transition; everything else in a terminal unit is frozen.
            _post_seal = ("closed_record", "gate_commit")
            frozen_old = {k: v for k, v in old_unit.items() if k not in _post_seal}
            frozen_new = {k: v for k, v in nu.items() if k not in _post_seal}
            if frozen_old != frozen_new:
                raise HistoryRewriteError("%s: terminal unit was modified" % uctx)


def save_new(path, state):
    """Atomically create a NEW state file; raises FileExistsError when path
    already exists. The claim is an exclusive hard link of a fully written
    temp file: atomic against crashes (like save) AND race-free against a
    concurrent init of the same path (unlike an exists() pre-check, where
    two same-second inits with equal goals could pass save()'s append-only
    comparison and one config would silently replace the other)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        try:
            os.link(tmp, path)  # atomic exclusive claim of `path`
        except FileExistsError:
            raise FileExistsError(
                "refusing to overwrite existing state at %s" % path
            )
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def save(path, state):
    """Atomically persist state, enforcing append-only history against the
    current on-disk version (if any)."""
    if os.path.exists(path):
        assert_append_only(load(path), state)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# Events


def append_event(state, etype, **data):
    evt = {"seq": len(state["events"]), "at": now_iso(), "type": etype}
    evt.update(data)
    state["events"].append(evt)
    return evt


# ---------------------------------------------------------------------------
# Unit navigation and transitions


def current_unit(state):
    """The first unit that is not sealed. None when all units are sealed."""
    for unit in state["units"]:
        if unit["status"] != U_SEALED:
            return unit
    return None


def unit_key(unit):
    if unit["slice_id"] is None:
        return unit["kind"]
    return "%s-%02d" % (unit["kind"], unit["slice_id"])


def planned_units(state):
    """Full unit plan: skeleton plus doc+impl per known slice."""
    plan = [(UNIT_SKELETON, None)]
    for sl in state["milestone"]["slices"]:
        plan.append((UNIT_SLICE_DOC, sl["id"]))
        plan.append((UNIT_SLICE_IMPL, sl["id"]))
    return plan


def ensure_next_unit(state):
    """After a unit seals, append the next planned unit record (if any).

    Returns the appended unit or None when the plan is complete."""
    existing = [(u["kind"], u["slice_id"]) for u in state["units"]]
    for kind, slice_id in planned_units(state):
        if (kind, slice_id) not in existing:
            unit = _new_unit(kind, slice_id)
            state["units"].append(unit)
            append_event(state, "unit_opened", unit=unit_key(unit))
            return unit
    return None


def transition_unit(state, unit, new_status, reason=None):
    _ALLOWED = {
        # Review/fix separation: dirty reviews (any source: verification,
        # a review round, a seal) enter U_FIXING; the fixer's pending diff
        # is checked in U_DELTA_REVIEW (report-only); a dirty delta loops
        # back to U_FIXING; a green delta is amended and the unit returns
        # exactly where the dirty review would have gone.
        U_PENDING: (U_PRE_REVIEW_VERIFY, U_FAILED),
        U_PRE_REVIEW_VERIFY: (U_ROUNDS, U_FIXING, U_FAILED),
        U_ROUNDS: (U_ROUNDS, U_FIXING, U_PRE_SEAL_VERIFY, U_FAILED),
        U_FIXING: (U_DELTA_REVIEW, U_PRE_REVIEW_VERIFY, U_ROUNDS,
                   U_PRE_SEAL_VERIFY, U_FAILED),
        U_DELTA_REVIEW: (U_FIXING, U_PRE_REVIEW_VERIFY, U_ROUNDS,
                         U_PRE_SEAL_VERIFY, U_FAILED),
        U_PRE_SEAL_VERIFY: (U_SEALING, U_FIXING, U_FAILED),
        # U_SEALING stays on an invalidated attempt (the workspace is
        # restored to the sealed candidate commit and the attempt retries).
        U_SEALING: (U_SEALED, U_FIXING, U_FAILED),
        U_SEALED: (),
        U_FAILED: (),
    }
    old = unit["status"]
    if new_status not in _ALLOWED[old]:
        raise IllegalTransition(
            "unit %s: %s -> %s is not a legal transition"
            % (unit_key(unit), old, new_status)
        )
    unit["status"] = new_status
    append_event(
        state,
        "unit_transition",
        unit=unit_key(unit),
        from_status=old,
        to_status=new_status,
        reason=reason,
    )


def set_discovered_suite(state, command):
    """Record the official suite command the implementer discovered. The
    ledger gets a suite_discovered event; re-discovery of a different
    command overwrites (latest implementer knows best) with a fresh
    event. Explicit config verification always wins over this at gate
    time — this is the zero-config path."""
    command = str(command or "").strip()
    if not command or state.get("suite_command") == command:
        return False
    previous = state.get("suite_command")
    state["suite_command"] = command
    append_event(
        state, "suite_discovered", command=command, previous=previous
    )
    return True


def record_draft(state, unit, kind, result, raw_path=None, family=None,
                 duration=None, model=None, effort=None):
    """Write-once record of the unit's draft/implement call."""
    if unit["status"] != U_PENDING:
        raise IllegalTransition(
            "unit %s: draft can only be recorded from pending (is %s)"
            % (unit_key(unit), unit["status"])
        )
    if unit["draft"] is not None:
        raise IllegalTransition("unit %s: draft already recorded" % unit_key(unit))
    unit["draft"] = {
        "kind": kind,
        "family": family,
        "model": model,
        "effort": effort,
        "duration_s": duration,
        "at": now_iso(),
        "raw_path": raw_path,
        "result": copy.deepcopy(result),
    }
    unit["artifact"] = result.get("artifact")
    append_event(state, "draft_recorded", unit=unit_key(unit), kind=kind)
    return unit["draft"]


def current_family(state, unit):
    families = state["config"]["families_order"]
    idx = unit["family_index"]
    if idx >= len(families):
        return None
    return families[idx]


def family_rounds(unit, family):
    return [r for r in unit["rounds"] if r["family"] == family]


def record_round(state, unit, family, kind, result, raw_path=None, duration=None,
                 meta=None):
    """Append an immutable round record. Never edited afterwards.

    meta: optional extra record fields (e.g. the fixer's source round id,
    an invalidation marker for a tampering reviewer)."""
    if unit["status"] not in (U_ROUNDS, U_FIXING, U_DELTA_REVIEW):
        raise IllegalTransition(
            "unit %s: cannot record a %s round in status %s"
            % (unit_key(unit), kind, unit["status"])
        )
    rec = {
        "id": "%s-%s-r%d" % (unit_key(unit), family, len(family_rounds(unit, family)) + 1),
        "family": family,
        "kind": kind,
        "at": now_iso(),
        "duration_s": duration,
        "raw_path": raw_path,
        "result": copy.deepcopy(result),
    }
    if meta:
        rec.update(copy.deepcopy(meta))
    unit["rounds"].append(rec)
    event_fields = {
        "unit": unit_key(unit),
        "round": rec["id"],
        "kind": kind,
        "findings": len(result.get("findings", [])),
    }
    if rec.get("invalidated"):
        event_fields["invalidated"] = rec["invalidated"]
    append_event(state, "round_recorded", **event_fields)
    return rec


def advance_family_if_clean(state, unit, last_result):
    """After a clean review round, move to the next family or to pre-seal.

    Encodes the canon ordering rule: families run in configured order and a
    later family's rounds never reopen an earlier family's normal rounds.
    """
    from . import contracts

    if not contracts.findings_clean(last_result):
        return  # stay in rounds with same family
    families = state["config"]["families_order"]
    unit["family_index"] += 1
    if unit["family_index"] >= len(families):
        transition_unit(state, unit, U_PRE_SEAL_VERIFY, reason="all families clean")
    else:
        append_event(
            state,
            "family_clean",
            unit=unit_key(unit),
            next_family=families[unit["family_index"]],
        )


def can_open_seal(state, unit):
    """Seal opens only when every configured family has a recorded clean
    round and the unit passed pre-seal verification (status sealing)."""
    from . import contracts

    families = state["config"]["families_order"]
    for fam in families:
        rounds = family_rounds(unit, fam)
        review_rounds = [
            r
            for r in rounds
            if r["kind"] == "review_round" and not r.get("invalidated")
        ]
        if not review_rounds or not contracts.findings_clean(review_rounds[-1]["result"]):
            return False
    return True


def record_seal_attempt(state, unit, halves, passed, invalidated=None):
    """Append an immutable seal attempt record.

    halves: {family: {"result": <validated seal_half output or None>,
                      "raw_path": ..., "duration_s": ...,
                      "workspace_modified": bool}}
    """
    if unit["status"] != U_SEALING:
        raise IllegalTransition(
            "unit %s: cannot record a seal attempt in status %s"
            % (unit_key(unit), unit["status"])
        )
    rec = {
        "attempt": len(unit["seals"]) + 1,
        "at": now_iso(),
        "halves": copy.deepcopy(halves),
        "passed": passed,
        "invalidated": invalidated,
    }
    unit["seals"].append(rec)
    append_event(
        state,
        "seal_attempt",
        unit=unit_key(unit),
        attempt=rec["attempt"],
        passed=passed,
        invalidated=invalidated,
    )
    return rec


def fail_run(state, reason, unit=None, type_="unknown", resume_at=None):
    """Terminal failure: record the explanation and stop. Resumable by a
    deliberate operator action (resume_run) or, for auto-resumable typed
    failures (quota/network/busy/timeout), by the service guard at
    resume_at. type_ and resume_at come from errclass; "unknown" and
    "login" are never auto-resumed."""
    state["failure"] = {
        "at": now_iso(),
        "reason": reason,
        "unit": unit_key(unit) if unit else None,
        "type": type_,
        "resume_at": resume_at,
    }
    if unit is not None and unit["status"] not in (U_SEALED, U_FAILED):
        unit["failed_from"] = unit["status"]
        unit["status"] = U_FAILED
    state["milestone"]["status"] = M_FAILED
    append_event(
        state, "run_failed", reason=reason, unit=state["failure"]["unit"],
        failure_type=type_, resume_at=resume_at,
    )


def resume_run(state):
    """Operator-deliberate revival of a failed run (transient CLI failures:
    a logged-out reviewer, a quota window, a network hiccup).

    Clears the failure, reopens the milestone, and restores every failed
    unit to the status it was in when it failed (`failed_from`; a heuristic
    covers states recorded before that field existed). History is never
    rewritten — the run_failed event stays and a `resumed` event is
    appended. Raises ValueError when there is nothing to resume."""
    if state.get("failure") is None:
        raise ValueError("nothing to resume: the run has no recorded failure")
    failure_type = (state["failure"] or {}).get("type")
    restored = {}
    for unit in state["units"]:
        if unit["status"] != U_FAILED:
            continue
        target = unit.get("failed_from")
        if target not in UNIT_STATUSES or target in (U_FAILED, U_SEALED):
            # Pre-failed_from states: infer the least-surprising spot.
            if unit.get("fix_queue"):
                target = U_FIXING
            elif unit["rounds"]:
                target = U_ROUNDS
            elif unit.get("draft"):
                target = U_PRE_REVIEW_VERIFY
            else:
                target = U_PENDING
        if failure_type == "phantom_fix" and target == U_DELTA_REVIEW:
            # The phantom check would re-fire instantly on the recorded
            # claim + empty delta; the cure is re-running the fixer.
            target = U_FIXING
        if target == U_SEALING:
            # A run that died while sealing re-enters through the pre-seal
            # gate: a crashed/killed seal half may have left unverified
            # edits behind, and seal reviewers are told the suite passed
            # at the last gate — that claim must be re-proven, not
            # assumed across a failure boundary. The gate is idempotent.
            target = U_PRE_SEAL_VERIFY
        unit["status"] = target
        unit["failed_from"] = None
        restored[unit_key(unit)] = target
    old_reason = state["failure"].get("reason")
    state["failure"] = None
    if state["milestone"]["status"] == M_FAILED:
        state["milestone"]["status"] = M_OPEN
    append_event(
        state,
        "resumed",
        restored=restored,
        previous_failure=(old_reason or "")[:300],
    )
    return restored


def close_slice(state, unit):
    if unit["kind"] != UNIT_SLICE_IMPL or unit["status"] != U_SEALED:
        raise IllegalTransition("close_slice requires a sealed slice_impl unit")
    unit["closed_record"] = {
        "at": now_iso(),
        "slice_id": unit["slice_id"],
        "rounds": len(unit["rounds"]),
        "seal_attempts": len(unit["seals"]),
    }
    append_event(state, "slice_closed", slice_id=unit["slice_id"])


def maybe_close_milestone(state):
    if state["milestone"]["status"] == M_CLOSED:
        return True  # idempotent: never records milestone_closed twice
    plan = planned_units(state)
    have = {(u["kind"], u["slice_id"]): u for u in state["units"]}
    for key in plan:
        unit = have.get(key)
        if unit is None or unit["status"] != U_SEALED:
            return False
    state["milestone"]["status"] = M_CLOSED
    append_event(state, "milestone_closed")
    return True


# ---------------------------------------------------------------------------
# Adjudication registry (milestone-global, derived from immutable rounds)


def _overturned_rejections(state):
    """Registry ids whose adjudication was CONTESTED with new evidence and
    CONCEDED: the fixer disposed the contested re-raise 'fixed'. Derived
    from each fix round's recorded `queued` findings (which carry the
    contests link). An overturned adjudication is no longer settled law —
    it must not appear in prompts, must not satisfy adjudication_ref, and
    a genuine recurrence may be re-raised without contests."""
    overturned = set()
    for unit in state["units"]:
        for rec in unit["rounds"]:
            if rec["kind"] != "fix_findings":
                continue
            contested = {
                q.get("id"): (q.get("contests") or {}).get("rejection_id")
                for q in rec.get("queued") or []
                if q.get("contests")
            }
            if not contested:
                continue
            for f in rec["result"].get("findings", []):
                if f.get("disposition") == "fixed":
                    ref = contested.get(f.get("id"))
                    if ref:
                        overturned.add(ref)
    return overturned


def adjudicated_rejections(state):
    """Every rejected finding across ALL units, with stable ids.

    Entry id = "<source_round_id>/<finding_id>" where source_round_id is the
    review round (or synthetic verification id) whose finding was rejected.
    Derived on demand from the append-only round records, so the registry
    survives the whole milestone by construction and can never disagree
    with history. Adjudications later overturned by a conceded contest
    (_overturned_rejections) are excluded: they are no longer settled."""
    overturned = _overturned_rejections(state)
    entries = []
    for unit in state["units"]:
        for rec in unit["rounds"]:
            if rec["kind"] != "fix_findings":
                continue
            source = rec.get("source_round_id") or rec["id"]
            for f in rec["result"].get("findings", []):
                if f.get("disposition") == "rejected":
                    if "%s/%s" % (source, f["id"]) in overturned:
                        continue
                    entries.append(
                        {
                            "id": "%s/%s" % (source, f["id"]),
                            "unit": unit_key(unit),
                            "severity": f.get("severity"),
                            "summary": f.get("summary"),
                            "rationale": (f.get("consultation") or {}).get(
                                "resolution"
                            ),
                            "prevention": f.get("prevention"),
                        }
                    )
    return entries


def registry_ids(state):
    return {e["id"] for e in adjudicated_rejections(state)}


def enter_fix_episode(state, unit, findings, source_type, source_family,
                      source_round_id, return_to):
    """Queue a findings list for the fixer and transition to U_FIXING."""
    unit["fix_queue"] = copy.deepcopy(findings)
    unit["fix_source"] = {
        "type": source_type,
        "family": source_family,
        "source_round_id": source_round_id,
        "return_to": return_to,
    }
    unit["fix_loop_rounds"] = 0
    unit.pop("phantom_retried", None)
    transition_unit(state, unit, U_FIXING,
                    reason="%s findings queued for fixing" % source_type)


# ---------------------------------------------------------------------------
# Derived summary (consumed by `status --json` and the web app)


def _epoch(iso):
    """ISO-with-offset timestamp -> epoch seconds (None if unparsable)."""
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S%z").timestamp()
    except (ValueError, TypeError):
        return None


_SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _worst_severity(findings):
    """The most severe P-level among findings (P0 worst), None if clean."""
    worst = None
    for f in findings or []:
        sev = f.get("severity")
        if sev in _SEVERITY_ORDER and (
            worst is None or _SEVERITY_ORDER[sev] < _SEVERITY_ORDER[worst]
        ):
            worst = sev
    return worst


def summary(state):
    unit = current_unit(state)
    opened_at = {}
    closed_at = {}
    for e in state["events"]:
        uk = e.get("unit")
        if not uk:
            continue
        if e.get("type") == "unit_opened" and uk not in opened_at:
            opened_at[uk] = _epoch(e.get("at"))
        if e.get("type") == "unit_transition" and e.get("to_status") == U_SEALED:
            closed_at[uk] = _epoch(e.get("at"))
    units_view = []
    for u in state["units"]:
        units_view.append(
            {
                "unit": unit_key(u),
                "status": u["status"],
                "artifact": u["artifact"],
                "opened_epoch": (
                    opened_at.get(unit_key(u))
                    or _epoch((u.get("draft") or {}).get("at"))
                ),
                "closed_epoch": closed_at.get(unit_key(u)),
                "draft": (
                    {
                        "kind": u["draft"]["kind"],
                        "family": u["draft"].get("family"),
                        "duration_s": u["draft"].get("duration_s"),
                        "at": u["draft"]["at"],
                    }
                    if u.get("draft")
                    else None
                ),
                "rounds": [
                    {
                        "id": r["id"],
                        "family": r["family"],
                        "kind": r["kind"],
                        "findings": len(r["result"].get("findings", [])),
                        "severity": _worst_severity(
                            r["result"].get("findings", [])
                        ),
                        "invalidated": r.get("invalidated"),
                        "duration_s": r.get("duration_s"),
                        "at": r["at"],
                    }
                    for r in u["rounds"]
                ],
                "seals": [
                    {
                        "attempt": s["attempt"],
                        "passed": s["passed"],
                        "invalidated": s["invalidated"],
                        "findings": {
                            fam: (
                                len(h["result"].get("findings", []))
                                if h.get("result")
                                else None
                            )
                            for fam, h in s["halves"].items()
                        },
                        "duration_s": sum(
                            h.get("duration_s") or 0 for h in s["halves"].values()
                        ) or None,
                        "severity": _worst_severity(
                            [
                                f
                                for h in s["halves"].values()
                                if h and h.get("result")
                                for f in h["result"].get("findings", [])
                            ]
                        ),
                        "at": s["at"],
                    }
                    for s in u["seals"]
                ],
            }
        )
    families = state["config"].get("families_order", [])
    current_fam = None
    if unit is not None and unit.get("family_index", 0) < len(families):
        current_fam = families[unit["family_index"]]
    return {
        "goal": state["goal"],
        "workspace": state["workspace"],
        "milestone_status": state["milestone"]["status"],
        "slices": state["milestone"]["slices"],
        "current_unit": unit_key(unit) if unit else None,
        "current_unit_status": unit["status"] if unit else None,
        "current_family": current_fam,
        "suite_command": state.get("suite_command"),
        "name": state.get("name"),
        "docs_dir": state.get("docs_dir") or "docs",
        "created_epoch": _epoch(state.get("created_at")),
        "last_event_epoch": _epoch(
            state["events"][-1]["at"] if state["events"] else None
        ),
        "failure": state["failure"],
        "units": units_view,
        "events_total": len(state["events"]),
        "last_events": state["events"][-30:],
    }
