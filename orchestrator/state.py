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
# A SEALED unit reopened for an upstream repair (build-driven review reform
# §3): a downstream builder reported a gap this unit must resolve. Transient
# — the driver immediately queues the repair as a fix episode, so a persisted
# unit is never left in bare U_REPAIRING at a step boundary. Sealed units are
# otherwise terminal; this is the one reopen path.
U_REPAIRING = "repairing"

UNIT_STATUSES = (
    U_PENDING,
    U_PRE_REVIEW_VERIFY,
    U_ROUNDS,
    U_FIXING,
    U_DELTA_REVIEW,
    U_PRE_SEAL_VERIFY,
    U_SEALING,
    U_SEALED,
    U_REPAIRING,
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
        # Indexes into `rounds`/`seals` set at each resume; the per-family
        # review-round cap and the seal-attempt cap count only records after
        # them (both lists are immutable history, so the caps need markers
        # to be resettable). Seal attempt NUMBERING stays global.
        "rounds_amnesty": 0,
        "seals_amnesty": 0,
        # The active fix episode (working fields; history lives in rounds):
        "fix_queue": [],            # findings currently queued for the fixer
        "fix_source": None,         # {"type": verification|round|seal|delta,
                                    #  "family": origin family or None,
                                    #  "source_round_id": ...,
                                    #  "return_to": status after green+amend}
        "fix_loop_rounds": 0,       # fixer+delta iterations on this episode
        "debt": [],                 # rated findings deferred as debt (append-only)
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
        _assert_list_prefix(old_unit.get("debt", []), nu.get("debt", []), uctx + ".debt")
        # A unit that is sealed in BOTH the old and new state is frozen
        # except for post-seal bookkeeping. Failed units are deliberately
        # NOT frozen (resume_run restores them). Nor is a sealed unit that
        # is being reopened for repair (sealed -> repairing): that
        # transition is validated by transition_unit's adjacency table and
        # is the one deliberate exit from sealed; once reopened the unit is
        # no longer sealed, so its rounds/seals grow append-only like
        # everyone's (the prefix checks above still hold).
        if old_unit.get("status") == U_SEALED and nu.get("status") == U_SEALED:
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
    """The first not-sealed unit in PLAN order — the skeleton's slice-table
    row order, exactly the order maybe_close_milestone checks. NOT the
    units-list (creation) order: a skeleton remodel may INSERT a slice
    mid-table while unit records for later slices already exist, and its
    fresh records land at the END of the list — list order would run the
    very slices that depend on the inserted one first (seen live:
    certification-llm ran slice 13 before the slice 19 it needs). A unit
    whose slice is no longer in the plan is never current, mirroring
    closure (it does not block the milestone). None when the plan is
    fully sealed."""
    by_key = {(u["kind"], u["slice_id"]): u for u in state["units"]}
    for key in planned_units(state):
        unit = by_key.get(key)
        if unit is not None and unit["status"] != U_SEALED:
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


def ensure_due_unit(state):
    """Materialize the DUE unit's record when it is missing: the first
    planned unit with no record while every planned unit before it is
    sealed. That hole opens when a crash lands between a seal and its
    _after_seal ensure_next_unit — with a mid-table remodel insert, the
    inserted slice's record would not exist and navigation would fall
    through to a later pre-created record, re-running the very slices
    that depend on the inserted one. No-op in every other situation
    (an earlier planned unit still in flight, or no record missing), so
    it never pre-creates future records. Returns the appended unit or
    None."""
    by_key = {(u["kind"], u["slice_id"]): u for u in state["units"]}
    for key in planned_units(state):
        unit = by_key.get(key)
        if unit is None:
            return ensure_next_unit(state)  # appends exactly this key
        if unit["status"] != U_SEALED:
            return None
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
        U_SEALING: (U_SEALED, U_FIXING, U_PRE_SEAL_VERIFY, U_FAILED),
        # A sealed unit is terminal EXCEPT for reopen_for_repair, which
        # reopens it to resolve a downstream builder's gap (reform §3). The
        # repair immediately enters a fix episode (U_REPAIRING -> U_FIXING)
        # and reseals through the normal seal path.
        U_SEALED: (U_REPAIRING,),
        # REPAIRING -> SEALED is the re-documentation wave's close: a slice
        # note co-reopened with the skeleton reseals when the ANCHOR's wave
        # seal passes (the wave certifies the whole documentation set); it
        # never runs its own episode.
        U_REPAIRING: (U_FIXING, U_SEALED, U_FAILED),
        U_FAILED: (),
    }
    old = unit["status"]
    if new_status not in _ALLOWED[old]:
        raise IllegalTransition(
            "unit %s: %s -> %s is not a legal transition"
            % (unit_key(unit), old, new_status)
        )
    unit["status"] = new_status
    if new_status == U_SEALED:
        # A reseal ends the repair cycle: the artifact is read-only again.
        unit.pop("under_repair", None)
    append_event(
        state,
        "unit_transition",
        unit=unit_key(unit),
        from_status=old,
        to_status=new_status,
        reason=reason,
    )


def set_discovered_suite(state, command, replace=False):
    """Record the official suite command discovered for this run.

    The first implementer arms the zero-config gate.  A later implementer
    reporting a different command cannot silently replace an already proven
    gate; the discrepancy is recorded and needs an explicit fixer correction.
    ``replace`` is that correction lane.  Explicit config verification still
    wins at gate time.
    """
    command = str(command or "").strip()
    if not command or state.get("suite_command") == command:
        return False
    previous = state.get("suite_command")
    if previous and not replace:
        append_event(
            state,
            "suite_discovery_ignored",
            command=command,
            established=previous,
        )
        return False
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
    # Keep the lightweight implementation/draft history in the immutable
    # ledger too. A unit can exceptionally be reset to pending after a
    # documentation repair; its singular `draft` slot is then reused, but
    # the panel and work-time projection must not lose the earlier call.
    append_event(
        state,
        "draft_recorded",
        at=unit["draft"]["at"],
        unit=unit_key(unit),
        kind=kind,
        family=family,
        model=model,
        effort=effort,
        duration_s=duration,
        raw_path=raw_path,
    )
    return unit["draft"]


def current_family(state, unit):
    families = state["config"]["families_order"]
    idx = unit["family_index"]
    if idx >= len(families):
        return None
    return families[idx]


def family_rounds(unit, family):
    return [r for r in unit["rounds"] if r["family"] == family]


# enter_fix_episode logs this suffix on the episode-root transition; the
# origin source_type ("round"/"seal"/"verification"/a gap-repair key) is
# the prefix. Reconstructing origin_type from it lets pre-feature episodes
# (persisted before fix_source carried origin_type) still be classified.
_FIX_QUEUED_SUFFIX = " findings queued for fixing"


def _active_fix_root_index(events, key):
    """Index of the transition that OPENED the unit's active fix episode.

    The episode root is the latest transition into FIXING whose source was
    not DELTA_REVIEW; later delta -> fixing back-edges stay inside the same
    episode. Returns None when no such transition exists.
    """
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if (
            event.get("type") == "unit_transition"
            and event.get("unit") == key
            and event.get("to_status") == U_FIXING
            and event.get("from_status") != U_DELTA_REVIEW
        ):
            return index
    return None


def active_fix_origin_type(state, unit):
    """The active fix episode's ORIGINAL source_type, independent of the
    mutable fix_source["type"] that a dirty-delta re-queue clobbers to
    "delta". Returns "round", "seal", "verification", a gap-repair key, or
    None when the episode or its origin cannot be resolved.

    New episodes carry origin_type on the source directly. Episodes
    persisted before that field existed are reconstructed from the immutable
    root transition, whose reason enter_fix_episode wrote as
    "<source_type> findings queued for fixing" -- the same append-only
    evidence active_fix_dirty_delta_rounds trusts, so Stop/Start and Resume
    cannot erase it.
    """
    source = unit.get("fix_source") or {}
    if not source:
        return None
    origin = source.get("origin_type")
    if origin:
        return origin
    events = state.get("events") or []
    root = _active_fix_root_index(events, unit_key(unit))
    if root is None:
        return None
    reason = events[root].get("reason") or ""
    if reason.endswith(_FIX_QUEUED_SUFFIX):
        return reason[: -len(_FIX_QUEUED_SUFFIX)] or None
    return None


def active_fix_dirty_delta_rounds(state, unit):
    """Accepted dirty delta rounds in the unit's ACTIVE fix episode.

    This is deliberately derived from append-only events rather than a
    mutable counter: resume_run grants fresh loop budgets, but it must not
    erase the evidence that the same fix chain has already been circling.
    A real episode starts at the latest transition into FIXING whose source
    was not DELTA_REVIEW; later delta -> fixing back-edges stay inside it.
    """
    if not unit.get("fix_source"):
        return []
    key = unit_key(unit)
    events = state.get("events") or []
    root = _active_fix_root_index(events, key)
    if root is None:
        return []
    dirty_ids = [
        event.get("round")
        for event in events[root + 1 :]
        if (
            event.get("type") == "round_recorded"
            and event.get("unit") == key
            and event.get("kind") == "delta_review"
            and int(event.get("findings") or 0) > 0
            and not event.get("invalidated")
        )
    ]
    by_id = {round_["id"]: round_ for round_ in unit.get("rounds") or []}
    return [by_id[round_id] for round_id in dirty_ids if round_id in by_id]


def active_fix_dirty_deltas(state, unit):
    """Number of dirty delta reviews in the active fix chain."""
    return len(active_fix_dirty_delta_rounds(state, unit))


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


def _round_effectively_clean(round_rec):
    """A round is 'clean enough' to advance/seal when it reported no
    findings OR when all of its findings were independently deferred as tracked
    debt (meta.deferred_clean, set by the reclassify path)."""
    from . import contracts

    if contracts.findings_clean(round_rec.get("result", {})):
        return True
    # record_round flattens meta fields to the record's top level.
    return bool(round_rec.get("deferred_clean"))


def advance_family_deferred(state, unit):
    """Advance after a review round whose findings were all deferred as debt.

    This is equivalent to a clean round for family ordering.
    (The clean case goes through advance_family_if_clean.)"""
    families = state["config"]["families_order"]
    unit["family_index"] += 1
    if unit["family_index"] >= len(families):
        transition_unit(state, unit, U_PRE_SEAL_VERIFY,
                        reason="all families clean (findings deferred as debt)")
    else:
        append_event(
            state, "family_clean", unit=unit_key(unit),
            next_family=families[unit["family_index"]], deferred_debt=True,
        )


def can_open_seal(state, unit):
    """Seal opens only when every configured family has a recorded clean
    round and the unit passed pre-seal verification (status sealing)."""
    families = state["config"]["families_order"]
    for fam in families:
        rounds = family_rounds(unit, fam)
        review_rounds = [
            r
            for r in rounds
            if r["kind"] == "review_round" and not r.get("invalidated")
        ]
        if not review_rounds or not _round_effectively_clean(review_rounds[-1]):
            return False
    return True


def seal_predicate_reviews(unit, families):
    """The reform seal PREDICATE over the ledger (spec §5). Returns the list
    of review-round ids that SATISFY it — every family's most recent
    whole-artifact review is clean (or clean-with-deferred-debt) AND on the
    CURRENT bytes — or None when it is not satisfied (a family never
    reviewed, its last look is dirty, or a later fix changed the artifact
    after it, making the look stale).

    Git-agnostic: a fix_findings round is the only thing that changes the
    artifact bytes, so a family's clean review is on the current bytes iff
    no fix round follows it. When the predicate holds, the dedicated
    seal-half re-reads would re-read bytes each family already blessed —
    exactly the redundant call this replaces; when it does not, that
    family owes a fresh look (the caller falls back to the seal halves,
    which give it)."""
    rounds = unit["rounds"]
    last_fix = max(
        (i for i, r in enumerate(rounds) if r["kind"] == "fix_findings"),
        default=-1,
    )
    cite = []
    for fam in families:
        revs = [
            (i, r) for i, r in enumerate(rounds)
            if r["family"] == fam and r["kind"] == "review_round"
            and not r.get("invalidated")
        ]
        if not revs:
            return None
        idx, last = revs[-1]           # most recent whole-artifact review
        if not _round_effectively_clean(last) or idx < last_fix:
            return None                 # dirty, or stale after a later fix
        cite.append(last["id"])
    return cite


def stale_seal_families(unit, families):
    """The reform predicate's REFINED fallback (spec §5, realized
    2026-07-09 after the conservative full-double fallback showed its
    cost live — a claude a1 half re-reading bytes claude had blessed 15
    minutes earlier): when the predicate does not hold, only the
    families whose most recent whole-artifact look is missing, dirty,
    or stale owe a fresh seal half; a family clean on the CURRENT bytes
    stands on its cited review. Returns (stale_families, fresh_cites)
    where fresh_cites maps each fresh family to the standing review id.
    When the predicate returned None, stale_families is never empty."""
    rounds = unit["rounds"]
    last_fix = max(
        (i for i, r in enumerate(rounds) if r["kind"] == "fix_findings"),
        default=-1,
    )
    stale, fresh = [], {}
    for fam in families:
        revs = [
            (i, r) for i, r in enumerate(rounds)
            if r["family"] == fam and r["kind"] == "review_round"
            and not r.get("invalidated")
        ]
        if not revs:
            stale.append(fam)
            continue
        idx, last = revs[-1]
        if not _round_effectively_clean(last) or idx < last_fix:
            stale.append(fam)
        else:
            fresh[fam] = last["id"]
    return stale, fresh


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


def fail_run(state, reason, unit=None, type_="unknown", resume_at=None,
             evidence=None):
    """Terminal failure: record the explanation and stop. Resumable by a
    deliberate operator action (resume_run) or, for auto-resumable typed
    failures (quota/network/busy/timeout), by the service guard at
    resume_at. type_ and resume_at come from errclass for CLI failures;
    "login" is never auto-resumed, and "unknown" gets the guard's spaced
    EMERGENCY probing (every 15 min, forever) — so a failure that stops
    to ask the OPERATOR a question must carry an explicit operator-gated
    type (goal_gap, gap_stall, gap_route, worker_blocked): typed failures
    outside errclass.AUTO_RESUMABLE are never touched by the guard.
    evidence is the classifier's distilled verdict ("pattern match" /
    "classifier returned ..." / "classifier unavailable: ...") — recorded
    so an "unknown" is auditable."""
    state["failure"] = {
        "at": now_iso(),
        "reason": reason,
        "unit": unit_key(unit) if unit else None,
        "type": type_,
        "resume_at": resume_at,
        "classify_evidence": evidence,
    }
    if unit is not None and unit["status"] not in (U_SEALED, U_FAILED):
        unit["failed_from"] = unit["status"]
        unit["status"] = U_FAILED
    state["milestone"]["status"] = M_FAILED
    event_fields = dict(
        reason=reason, unit=state["failure"]["unit"],
        failure_type=type_, resume_at=resume_at,
    )
    if evidence:
        event_fields["classify_evidence"] = evidence
    append_event(state, "run_failed", **event_fields)


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
        if target not in UNIT_STATUSES or target in (
            U_FAILED, U_SEALED, U_REPAIRING
        ):
            # Pre-failed_from states, or the transient U_REPAIRING (which
            # never persists alone — reopen queues the repair fix in the
            # same step — but guard it anyway): infer the safe re-entry.
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
        # Grant a FRESH fix/verify budget: a run that failed by exhausting
        # max_fix_loops (or max_verify_fix_attempts) would otherwise re-fail
        # instantly on resume, since these counters carry across the failure
        # boundary. Resetting them makes resume a genuine "try again" — the
        # convergence cap is a soft ceiling the operator (or the guard's
        # emergency resume) can lift, not a dead end.
        unit["fix_loop_rounds"] = 0
        unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
        # The gap-repair back-edge counter is a convergence cap too: a
        # deliberate resume grants it a fresh budget.
        unit["gap_repairs"] = 0
        # The review-round cap (max_rounds_per_family) and the seal-attempt
        # cap (max_seal_attempts) count immutable history, so they would
        # re-fire instantly on resume; move the amnesty markers so the caps
        # only count post-resume records.
        unit["rounds_amnesty"] = len(unit["rounds"])
        unit["seals_amnesty"] = len(unit["seals"])
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


def reopen_for_repair(state, unit, gap, reason, reported_by=None):
    """Reopen a SEALED unit to resolve a downstream builder's gap (reform
    §3, stop-report-repair-resume). Transitions sealed -> repairing and
    grants FRESH fix/seal budgets — the repair and its reseal must not
    inherit the exhausted counters of the original build (same amnesty as
    resume_run). Two callers: the wave ANCHOR (the skeleton) immediately
    enters a fix episode (U_REPAIRING -> U_FIXING); a slice note
    co-reopened by a re-documentation wave WAITS in U_REPAIRING while the
    anchor's episode runs (the anchor's fixer may edit it) and reseals via
    close_redoc_wave when the anchor's wave seal passes. New machinery:
    sealed units are otherwise terminal."""
    if unit["status"] != U_SEALED:
        raise IllegalTransition(
            "reopen_for_repair requires a sealed unit (%s is %s)"
            % (unit_key(unit), unit["status"])
        )
    transition_unit(state, unit, U_REPAIRING, reason=reason)
    # The whole repair CYCLE (first fix, delta reviews, follow-up fixes,
    # reseal) must know the unit's own artifact is editable — not just
    # the first fix episode. The fix prompt's editability line keys off
    # this flag, which only the reseal clears; keying off the queue's
    # source type instead dropped the line on delta-loop fix rounds and
    # made the fixer refuse its own repair (found live 2026-07-11,
    # certification-llm skeleton repair).
    unit["under_repair"] = True
    unit["fix_loop_rounds"] = 0
    unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
    unit["rounds_amnesty"] = len(unit["rounds"])
    unit["seals_amnesty"] = len(unit["seals"])
    append_event(
        state,
        "reopened_for_repair",
        unit=unit_key(unit),
        reported_by=reported_by,
        classification=gap.get("classification"),
        forced_decision=str(gap.get("forced_decision", ""))[:300],
        plain=str(gap.get("plain", ""))[:300],
        rounds_before=len(unit["rounds"]),
        seals_before=len(unit["seals"]),
    )
    return unit


def reset_for_redraft(state, unit, reason):
    """Return a non-pending unit to a fresh re-draft, mirroring the state a
    BUILDER-gap reporter is already left in (pending, draft=None). This is the
    FIXER-gap counterpart: when a fixer gaps (a queued finding was unfixable in
    scope because the sealed set contradicted itself), its unit was mid-episode
    (fixing/sealing), not pending. After the machine reopens the design as a
    re-documentation wave, that unit must redo its slice AGAINST the remodelled
    design — exactly as a builder-gap reporter re-drafts. Grants fresh
    review/seal budgets (same amnesty as reopen_for_repair/resume) and clears
    the abandoned fix episode. `has_gap_remodel`/`gap_repairs` are set by the
    caller (_reopen_and_repair) and deliberately preserved so the re-draft
    reads the remodelled skeleton. History (rounds/seals) is append-only and
    stays; the amnesty markers reset the caps. Status is set directly (a
    backward reset, like resume_run, is outside the forward transition table)."""
    prior = unit["status"]
    unit["draft"] = None
    unit["artifact"] = None
    unit["fix_queue"] = []
    unit["fix_source"] = None
    unit.pop("under_repair", None)
    unit.pop("design_correction", None)
    unit.pop("design_correction_attempted", None)
    unit["fix_loop_rounds"] = 0
    unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
    unit["rounds_amnesty"] = len(unit["rounds"])
    unit["seals_amnesty"] = len(unit["seals"])
    # The re-draft starts a FRESH review cycle from the first family; a unit
    # whose family_index had advanced (a seal-fixer gap, or a gap after the
    # first family cleared) would otherwise reach U_ROUNDS with no family to
    # run (IllegalTransition) or silently skip the first family's review.
    unit["family_index"] = 0
    unit["status"] = U_PENDING
    append_event(
        state,
        "reset_for_redraft",
        unit=unit_key(unit),
        from_status=prior,
        reason=reason,
        rounds_before=len(unit["rounds"]),
        seals_before=len(unit["seals"]),
    )
    return unit


def close_redoc_wave(state, anchor):
    """PHASE 1 of the wave close, run BEFORE the anchor's gate commit so
    the gate's generated ledgers render the truth: every co-reopened slice
    note returns repairing -> sealed carrying a WAVE seal record that
    references the anchor's passing attempt. The wave seal certified the
    ENTIRE documentation set — edited or not, a note the re-documenter
    chose to leave untouched was asserted coherent and the seal verified
    it — so the notes never run their own episodes. KEEPS state["redoc_wave"]
    (phase 2, stamp_redoc_wave_gate, clears it after the gate commit binds
    the shas — a crash between the phases must stay recoverable).
    Idempotent: already-sealed notes are skipped. Returns the closed keys."""
    wave = state.get("redoc_wave") or {}
    anchor_key = unit_key(anchor)
    if wave.get("anchor") != anchor_key:
        return []
    attempt = len(anchor["seals"])
    by_key = {unit_key(u): u for u in state["units"]}
    closed = []
    for key in wave.get("docs") or []:
        unit = by_key.get(key)
        if unit is None or unit["status"] != U_REPAIRING:
            continue
        unit["seals"].append({
            "attempt": len(unit["seals"]) + 1,
            "at": now_iso(),
            "passed": True,
            "invalidated": None,
            "halves": {},
            "wave": "%s-a%d" % (anchor_key, attempt),
        })
        transition_unit(
            state, unit, U_SEALED, reason="re-documentation wave reseal"
        )
        closed.append(key)
    if closed:
        append_event(
            state,
            "redoc_wave_closed",
            anchor=anchor_key,
            attempt=attempt,
            docs=closed,
        )
    return closed


def stamp_redoc_wave_gate(state, anchor, gate_sha):
    """PHASE 2 of the wave close, run AFTER the anchor's gate commit:
    stamp the wave gate's sha as every co-closed note's gate_commit (the
    anchor's gate holds every note's current bytes; the sealed-artifact
    guard baselines on the run's newest gate anyway) and clear the wave
    record. Safe with gate_sha None (git disabled): it only clears.
    Returns the stamped keys."""
    wave = state.get("redoc_wave") or {}
    anchor_key = unit_key(anchor)
    if wave.get("anchor") != anchor_key:
        return []
    by_key = {unit_key(u): u for u in state["units"]}
    stamped = []
    for key in wave.get("docs") or []:
        unit = by_key.get(key)
        if unit is None or unit["status"] != U_SEALED:
            continue
        if gate_sha:
            unit["gate_commit"] = gate_sha
            stamped.append(key)
    state["redoc_wave"] = None
    return stamped


def enter_fix_episode(state, unit, findings, source_type, source_family,
                      source_round_id, return_to):
    """Queue a findings list for the fixer and transition to U_FIXING."""
    unit["fix_queue"] = copy.deepcopy(findings)
    unit["fix_source"] = {
        "type": source_type,
        # The episode's ORIGINAL kind, never clobbered: a dirty-delta
        # re-queue rewrites `type` to "delta", so the convergence checkpoint
        # (which must know a round/seal episode from a verification/repair
        # one) reads this instead.
        "origin_type": source_type,
        "family": source_family,
        "source_round_id": source_round_id,
        "return_to": return_to,
    }
    unit["fix_loop_rounds"] = 0
    unit.pop("phantom_retried", None)
    transition_unit(state, unit, U_FIXING,
                    reason="%s findings queued for fixing" % source_type)


def record_debt(state, unit, entries, source, source_round_id):
    """Record independently rated findings as tracked debt.

    Entries retain the technical summary and rating metadata, not the lay
    `plain`/`example` calibration text. They are appended to the unit and
    ledger for operator visibility and are never sent to the fixer.
    """
    unit.setdefault("debt", [])
    for e in entries:
        unit["debt"].append(dict(e))
    append_event(
        state, "debt_recorded",
        unit=unit_key(unit),
        source=source,
        source_round_id=source_round_id,
        count=len(entries),
        ids=[e.get("id") for e in entries],
    )


def requeued_debt_refs(state):
    """Immutable debt records moved back into an implementation fix queue.

    Debt history stays append-only. A requeue event makes the referenced
    entries inactive for prompts and projections without rewriting sealed
    units or erasing the original classification evidence.
    """
    refs = set()
    for event in state.get("events", []):
        if event.get("type") != "implementation_debt_requeued":
            continue
        for ref in event.get("debts", []):
            unit = ref.get("unit")
            index = ref.get("index")
            if isinstance(unit, str) and isinstance(index, int) and index >= 0:
                refs.add((unit, index))
    return refs


def active_debt(state, unit):
    """Debt entries still deferred, excluding implementation requeues."""
    hidden = requeued_debt_refs(state)
    key = unit_key(unit)
    return [
        debt for index, debt in enumerate(unit.get("debt", []))
        if (key, index) not in hidden
    ]


def requeued_debt_ids(state):
    """Finding ids retired by implementation-debt requeue, per unit."""
    hidden = requeued_debt_refs(state)
    ids = {}
    for unit in state.get("units", []):
        key = unit_key(unit)
        for index, debt in enumerate(unit.get("debt", [])):
            if (key, index) in hidden:
                ids.setdefault(key, set()).add(debt.get("id"))
    return ids


def requeue_implementation_debt(state, target_unit=None):
    """Move every active implementation debt entry into the current fixer.

    Historical debt arrays remain immutable; the append-only requeue event
    retires them from active debt views. Repairs land in the current
    implementation unit so already-sealed slices are not rewound underneath
    later work.
    """
    target = target_unit or current_unit(state)
    if target is None or target.get("kind") != UNIT_SLICE_IMPL:
        raise IllegalTransition(
            "implementation debt requires a current slice_impl target"
        )
    if target.get("status") not in (U_ROUNDS, U_PRE_SEAL_VERIFY, U_SEALING):
        raise IllegalTransition(
            "cannot requeue implementation debt from status %s"
            % target.get("status")
        )
    if target.get("fix_queue"):
        raise IllegalTransition("target already has an active fix queue")

    refs = []
    findings = []
    hidden = requeued_debt_refs(state)
    for unit in state["units"]:
        if unit.get("kind") != UNIT_SLICE_IMPL:
            continue
        key = unit_key(unit)
        for index, debt in enumerate(unit.get("debt", [])):
            if (key, index) in hidden:
                continue
            original_id = str(debt.get("id") or "unknown")
            refs.append({"unit": key, "index": index, "id": original_id})
            findings.append({
                "id": "IMPL-DEBT-%02d-%02d"
                      % (int(unit.get("slice_id") or 0), index + 1),
                "severity": debt.get("severity") or "P3",
                "summary": (
                    "[reopened from %s/%s] %s"
                    % (key, original_id, debt.get("summary") or "")
                ),
            })
    if not findings:
        raise ValueError("run has no active implementation debt")

    return_to = (
        U_ROUNDS if target.get("status") == U_ROUNDS else U_PRE_SEAL_VERIFY
    )
    append_event(
        state, "implementation_debt_requeued",
        target=unit_key(target), debts=refs, count=len(refs),
    )
    enter_fix_episode(
        state, target, findings, "implementation_debt", None,
        "operator-implementation-debt-requeue", return_to,
    )
    return findings


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


def _completed_duration(value):
    """A persisted, completed worker-call duration, normalized for sums."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if seconds <= 0:
        return 0.0
    return seconds


def _draft_history(state, unit):
    """All draft/implementation calls for a unit, oldest first.

    Older ledgers recorded only the event kind. The current singular draft
    fills its matching event with full metadata; superseded legacy calls stay
    visible as generic historical chips instead of disappearing or borrowing
    today's model configuration.
    """
    key = unit_key(unit)
    current = unit.get("draft") or None
    current_matched = False
    records = []
    draft_events = [
        event for event in (state.get("events") or [])
        if event.get("type") == "draft_recorded" and event.get("unit") == key
    ]
    current_position = None
    if current:
        for index, event in enumerate(draft_events):
            if (
                event.get("at") == current.get("at")
                and event.get("kind") == current.get("kind")
            ):
                # Timestamps have one-second resolution; two fast test calls
                # (or a future fast worker) may share it. The singular slot is
                # always the latest matching immutable event.
                current_position = index
    for index, event in enumerate(draft_events):
        is_current = bool(
            current and index == current_position
        )
        source = dict(event)
        if is_current:
            source.update(current)
            current_matched = True
        records.append({
            "kind": source.get("kind"),
            "family": source.get("family"),
            "model": source.get("model"),
            "effort": source.get("effort"),
            "duration_s": source.get("duration_s"),
            "at": source.get("at"),
            "raw_path": source.get("raw_path"),
            "current": is_current,
        })
    if current and not current_matched:
        records.append({
            "kind": current.get("kind"),
            "family": current.get("family"),
            "model": current.get("model"),
            "effort": current.get("effort"),
            "duration_s": current.get("duration_s"),
            "at": current.get("at"),
            "raw_path": current.get("raw_path"),
            "current": True,
        })
    return records


def _work_durations(state):
    """Return ({unit_key: seconds}, unassigned_malformed_seconds).

    This is *work consumed*, not elapsed wall time: concurrent seal halves
    both count.  Every completed call has one durable home (draft, round,
    seal half, reclassification, or a repaired malformed first strike), so
    deriving the total here keeps it restart-safe and avoids mutable counters.
    """
    keys = [unit_key(unit) for unit in state.get("units") or []]
    totals = dict((key, 0.0) for key in keys)

    for unit in state.get("units") or []:
        key = unit_key(unit)
        totals[key] += sum(
            _completed_duration(draft.get("duration_s"))
            for draft in _draft_history(state, unit)
        )
        totals[key] += sum(
            _completed_duration(round_.get("duration_s"))
            for round_ in unit.get("rounds") or []
        )
        totals[key] += sum(
            _completed_duration(half.get("duration_s"))
            for seal in unit.get("seals") or []
            for half in (seal.get("halves") or {}).values()
            if half
        )

    unassigned = 0.0
    for event in state.get("events") or []:
        etype = event.get("type")
        if etype in ("reclassify_recorded", "gap_reported"):
            key = event.get("unit")
            if key in totals:
                totals[key] += _completed_duration(event.get("duration_s"))
            continue
        if etype != "worker_malformed" or event.get("fatal"):
            continue
        seconds = _completed_duration(event.get("duration_s"))
        if not seconds:
            continue
        key = event.get("unit")
        if not key:
            # Compatibility for historical repaired strikes: raw labels have
            # always begun with the owning unit key.
            label = str(event.get("label") or "")
            key = next(
                (
                    candidate
                    for candidate in keys
                    if label == candidate or label.startswith(candidate + "-")
                ),
                None,
            )
        if key in totals:
            totals[key] += seconds
        else:
            unassigned += seconds
    return totals, unassigned


def _repair_episodes(state):
    """Compact downstream-gap repair history, grouped by target unit.

    Rounds and seals remain append-only on the unit.  These episode handles
    let viewers collapse that exceptional detour without losing its trigger
    or confusing repair work with the unit's original review history.
    """
    events = state.get("events") or []
    units = dict((unit_key(unit), unit) for unit in state.get("units") or [])
    opened = [
        (index, event)
        for index, event in enumerate(events)
        if event.get("type") == "reopened_for_repair" and event.get("unit")
    ]
    by_unit = {}
    for position, (start_index, start) in enumerate(opened):
        key = start["unit"]
        next_index = len(events)
        next_start = None
        for later_index, later in opened[position + 1:]:
            if later.get("unit") == key:
                next_index = later_index
                next_start = later
                break
        window = events[start_index:next_index]
        completed = next((
            event for event in window
            if event.get("type") == "unit_transition"
            and event.get("unit") == key
            and event.get("to_status") == U_SEALED
        ), None)
        start_at = start.get("at") or ""
        end_at = (completed or {}).get("at") or ""

        def in_episode(record):
            at = record.get("at") or ""
            return bool(at and at >= start_at and (not end_at or at <= end_at))

        unit = units.get(key) or {}
        rounds = unit.get("rounds") or []
        seals = unit.get("seals") or []
        if start.get("rounds_before") is not None:
            round_end = (
                next_start.get("rounds_before")
                if next_start and next_start.get("rounds_before") is not None
                else len(rounds)
            )
            episode_rounds = rounds[start["rounds_before"]:round_end]
        else:
            episode_rounds = [record for record in rounds if in_episode(record)]
        if start.get("seals_before") is not None:
            seal_end = (
                next_start.get("seals_before")
                if next_start and next_start.get("seals_before") is not None
                else len(seals)
            )
            episode_seals = seals[start["seals_before"]:seal_end]
        else:
            episode_seals = [record for record in seals if in_episode(record)]
        round_ids = [record.get("id") for record in episode_rounds]
        seal_attempts = [record.get("attempt") for record in episode_seals]
        duration = None
        if start_at and end_at:
            duration = max(0.0, _epoch(end_at) - _epoch(start_at))
        by_unit.setdefault(key, []).append({
            "seq": start.get("seq"),
            "at": start_at,
            "completed_at": end_at or None,
            "duration_s": duration,
            "reported_by": start.get("reported_by"),
            "classification": start.get("classification"),
            "plain": start.get("plain"),
            "forced_decision": start.get("forced_decision"),
            "round_ids": round_ids,
            "seal_attempts": seal_attempts,
            "reclassifications": sum(
                event.get("type") == "reclassify_recorded"
                for event in window
            ),
            "malformed": sum(
                event.get("type") == "worker_malformed"
                for event in window
            ),
        })
    return by_unit


# Every terminal routing of one attached Brainstorming session, keyed by the
# event the driver appends when the session's result comes back. The wait
# itself opens the entry ("waiting"); these close it.
_BRAINSTORMING_OUTCOMES = {
    "brainstorming_builder_continued": "continued",
    "brainstorming_review_restarted": "restarted",
    "brainstorming_failure_routed": "failed",
    "brainstorming_operational_detached": "detached",
}


def summary(state):
    unit = current_unit(state)
    model_defaults = state["config"].get("model_defaults") or {}
    debt_requeues = requeued_debt_refs(state)
    requeued_ids = requeued_debt_ids(state)
    work_by_unit, unassigned_work = _work_durations(state)
    repairs_by_unit = _repair_episodes(state)

    def effective_setting(family, explicit, field):
        if explicit:
            return explicit
        return (model_defaults.get(family) or {}).get(field)

    opened_at = {}
    closed_at = {}
    wip_sha = {}
    reclassify_by_unit = {}
    # Attached Brainstorming sessions, in ledger order per unit. The full
    # trail is derived here (not from the 30-event tail the panel receives)
    # so an old detour keeps its chip for the life of the run.
    brainstorming_by_unit = {}
    brainstorming_index = {}
    for e in state["events"]:
        uk = e.get("unit")
        if not uk:
            continue
        if e.get("type") == "brainstorming_wait_started":
            entry = {
                "session_id": e.get("session_id"),
                "kind": e.get("kind"),
                "family": e.get("family"),
                "target_path": e.get("target_path"),
                "at": e.get("at"),
                "outcome": "waiting",
                "outcome_at": None,
            }
            brainstorming_by_unit.setdefault(uk, []).append(entry)
            brainstorming_index[(uk, e.get("session_id"))] = entry
        elif e.get("type") in _BRAINSTORMING_OUTCOMES:
            entry = brainstorming_index.get((uk, e.get("session_id")))
            if entry is not None:
                entry["outcome"] = _BRAINSTORMING_OUTCOMES[e.get("type")]
                entry["outcome_at"] = e.get("at")
        if e.get("type") == "unit_opened" and uk not in opened_at:
            opened_at[uk] = _epoch(e.get("at"))
        if e.get("type") == "unit_transition" and e.get("to_status") == U_SEALED:
            closed_at[uk] = _epoch(e.get("at"))
        if e.get("type") in ("wip_commit", "amended"):
            # Latest sha of the unit's working commit (amends replace it);
            # the panel links the CURRENT unit's work-so-far through it.
            wip_sha[uk] = e.get("sha")
        if e.get("type") == "reclassify_recorded":
            if (e.get("defer_ok")
                    and e.get("finding_id") in requeued_ids.get(uk, set())):
                continue
            reclassify_by_unit.setdefault(uk, []).append(
                {
                    "at": e.get("at"),
                    "finding_id": e.get("finding_id"),
                    "drift_risk": e.get("drift_risk"),
                    "drift_damage": e.get("drift_damage"),
                    "threshold": e.get("threshold"),
                    "defer_ok": e.get("defer_ok"),
                    "duration_s": e.get("duration_s"),
                }
            )
    units_view = []
    for u in state["units"]:
        draft_history = _draft_history(state, u)
        units_view.append(
            {
                "unit": unit_key(u),
                "status": u["status"],
                "artifact": u["artifact"],
                # Short sha of the unit's finalized seal gate commit — the
                # only sha that survives the amend discipline (wip/amended
                # shas are rewritten away). Panel links it to git web.
                "gate_sha": u.get("gate_commit"),
                # ...and, for a unit still in flight, its current working
                # commit (superseded once the gate commit lands).
                "wip_sha": (
                    None if u.get("gate_commit")
                    else wip_sha.get(unit_key(u))
                ),
                "opened_epoch": (
                    opened_at.get(unit_key(u))
                    or _epoch((u.get("draft") or {}).get("at"))
                ),
                "closed_epoch": closed_at.get(unit_key(u)),
                "work_duration_s": work_by_unit.get(unit_key(u), 0.0),
                "drafts": [
                    {
                        "kind": draft.get("kind"),
                        "family": draft.get("family"),
                        "model": effective_setting(
                            draft.get("family"), draft.get("model"), "model"
                        ),
                        "effort": effective_setting(
                            draft.get("family"), draft.get("effort"), "effort"
                        ),
                        "duration_s": draft.get("duration_s"),
                        "at": draft.get("at"),
                        "current": draft.get("current", False),
                    }
                    for draft in draft_history
                ],
                "draft": (
                    {
                        "kind": u["draft"]["kind"],
                        "family": u["draft"].get("family"),
                        "model": effective_setting(
                            u["draft"].get("family"),
                            u["draft"].get("model"), "model"
                        ),
                        "effort": effective_setting(
                            u["draft"].get("family"),
                            u["draft"].get("effort"), "effort"
                        ),
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
                        "model": effective_setting(
                            r["family"], r.get("model"), "model"
                        ),
                        "effort": effective_setting(
                            r["family"], r.get("effort"), "effort"
                        ),
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
                        # Wave provenance: resealed by the anchor's wave
                        # seal, no episode of its own (None otherwise).
                        "wave": s.get("wave"),
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
                # Deferred debt (opposite-family reclassification). The
                # reclassify calls leave no round, so without this the panel
                # loses the resolution once the in-flight chip clears.
                "debt": [
                    {
                        "id": dd.get("id"),
                        "severity": dd.get("severity"),
                        "summary": dd.get("summary"),
                        "raised_by": dd.get("raised_by"),
                        "cleared_by": dd.get("cleared_by"),
                        "drift_risk": dd.get("drift_risk"),
                        "reason": dd.get("reason"),
                    }
                    for index, dd in enumerate(u.get("debt", []))
                    if (unit_key(u), index) not in debt_requeues
                ],
                # Every reclassify outcome (deferred AND kept), timestamped
                # so the panel can place each episode chronologically among
                # the unit's round/seal chips and leave it there.
                "reclassify": reclassify_by_unit.get(unit_key(u), []),
                # A compact handle for every stop-report-repair-resume trip.
                # Full immutable rounds/seals stay in their normal fields;
                # the panel uses these ids to collapse the detour.
                "repairs": repairs_by_unit.get(unit_key(u), []),
                # Every Brainstorming session this unit opened to resolve a
                # design question, with how its result was routed back. The
                # panel chips these and links each to the session's page.
                "brainstormings": brainstorming_by_unit.get(unit_key(u), []),
            }
        )
    families = state["config"].get("families_order", [])
    current_fam = None
    if unit is not None and unit.get("family_index", 0) < len(families):
        current_fam = families[unit["family_index"]]
    current_model = effective_setting(current_fam, None, "model")
    if current_fam and unit is not None and unit.get("status") == U_ROUNDS:
        review_act = (state["config"].get("acts") or {}).get(
            "review_%s" % current_fam
        )
        if isinstance(review_act, dict) and review_act.get("model"):
            current_model = review_act["model"]
    out = {
        "goal": state["goal"],
        "workspace": state["workspace"],
        "milestone_status": state["milestone"]["status"],
        "slices": state["milestone"]["slices"],
        "current_unit": unit_key(unit) if unit else None,
        "current_unit_status": unit["status"] if unit else None,
        "current_family": current_fam,
        "current_model": current_model,
        "suite_command": state.get("suite_command"),
        "name": state.get("name"),
        "docs_dir": state.get("docs_dir") or "docs",
        "created_epoch": _epoch(state.get("created_at")),
        "last_event_epoch": _epoch(
            state["events"][-1]["at"] if state["events"] else None
        ),
        "failure": state["failure"],
        "work_duration_s": sum(work_by_unit.values()) + unassigned_work,
        "units": units_view,
        "events_total": len(state["events"]),
        "last_events": state["events"][-30:],
        # The launch config's act assignments: the panel shows EFFECTIVE
        # acts (this merged under the hot overlay) — showing the overlay
        # alone reads "default" for a run launched with acts in its
        # config (found live 2026-07-09).
        "acts_config": (state["config"].get("acts") or {}),
        "model_defaults": model_defaults,
        # Every repaired first strike of the whole run (not just the event
        # tail): the panel renders these as chips — prompt/contract tuning
        # needs the full trail. Bounded; the ledger keeps the rest.
        "malformed": [
            e for e in state["events"] if e.get("type") == "worker_malformed"
        ][-50:],
    }
    block = state.get("project")
    if block is not None:
        # The two path-free handles of a project-bound run (goal doc:
        # "run status carries the project name"). Mirrors the state block:
        # ABSENT for a project-less run, never present-null, so
        # pre-project summaries stay key-identical.
        out["project"] = block["project"]
        out["work_area"] = block["work_area"]
    return out
