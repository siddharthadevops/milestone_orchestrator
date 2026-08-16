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
a documentation unit and an implementation unit. Documentation goes straight
through review without running the code suite. Implementations rely on their
focused checks while bytes change; the complete suite runs after every four
completed logical slices (implementation parts still count as one slice) and
at milestone close. There is no full-suite tax per document, implementation
part, or review/fix cycle.
"""

import copy
import contextlib
from datetime import datetime
import json
import math
import os
import tempfile
import time

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX keeps existing fallback
    fcntl = None

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


class ConcurrentStateMutation(RuntimeError):
    """The state's existing advisory mutation lock is already held."""


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
        # The repo's official full-suite command, discovered by an implement
        # worker (its contract's suite_command field). Scheduled checkpoints
        # use it when config verification is not explicitly set.
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


def _new_unit(kind, slice_id, part=None):
    unit = {
        "kind": kind,
        "slice_id": slice_id,
        "status": U_PENDING,
        "artifact": None,
        "draft": None,              # write-once draft record
        "family_index": 0,          # index into config families_order
        "rounds": [],               # append-only
        # First round belonging to the current candidate bytes. Accepted
        # edits advance this boundary and restart review from family zero.
        "review_cycle_start": 0,
        # Driver-computed digest of the exact candidate and hot governing
        # context reviewed in this cycle. It binds separate reviewer calls
        # across process boundaries.
        "review_evidence_fingerprint": None,
        "seals": [],                # append-only
        # Historical per-stage shape retained for compatible state. Current
        # full-suite repair resets pre_seal when its fixer certifies green;
        # pre_review is a no-suite waypoint.
        "verify_fix_attempts": {"pre_review": 0, "pre_seal": 0},
        # Never-reset sequence for durable suite-repair source ids. The
        # attempt counter resets on success, so it cannot number re-entry.
        "verify_episode_seq": {"pre_review": 0, "pre_seal": 0},
        "closed_record": None,      # slice_impl closure bookkeeping
        "gate_commit": None,        # short sha of this unit's seal gate commit
        "failed_from": None,        # status at failure time (resume target)
        # Index into `rounds` set at each resume; the per-family review cap
        # counts only records after it while immutable history stays intact.
        "rounds_amnesty": 0,
        # The active fix episode (working fields; history lives in rounds):
        "fix_queue": [],            # findings currently queued for the fixer
        "fix_source": None,         # {"type": verification|round|seal|delta,
                                    #  "family": origin family or None,
                                    #  "source_round_id": ...,
                                    #  "return_to": status after green+amend}
        "fix_loop_rounds": 0,       # fixer+delta iterations on this episode
        "debt": [],                 # rated findings deferred as debt (append-only)
    }
    # Implementation continuations share the original slice's reviewed note
    # and integer slice_id.  `part` is therefore the third component of unit
    # identity, not a new design-slice id.  Omit it for every historical and
    # ordinary unit so pre-feature state keeps its exact shape.
    if part is not None:
        unit["part"] = part
    return unit


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


def _json_values_equal(left, right):
    """Compare JSON values without Python's bool/number coercion."""
    try:
        return json.dumps(
            left,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ) == json.dumps(
            right,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def assert_append_only(old_state, new_state_):
    """Raise HistoryRewriteError if new_state_ rewrites recorded history."""
    _assert_list_prefix(old_state.get("events", []), new_state_.get("events", []), "events")
    _assert_task_history(old_state.get("tasks", []), new_state_.get("tasks", []))
    old_units = old_state.get("units", [])
    new_units = new_state_.get("units", [])
    if len(new_units) < len(old_units):
        raise HistoryRewriteError("units: history shrank")
    for i, old_unit in enumerate(old_units):
        nu = new_units[i]
        uctx = "units[%d]" % i
        if unit_identity(nu) != unit_identity(old_unit):
            raise HistoryRewriteError("%s: identity changed" % uctx)
        # Once a budget cut has assigned the current coherent part and the
        # delegated remainder, that boundary is immutable evidence.  Future
        # parts are derived from it; rewriting it would silently change the
        # execution plan and the scope earlier reviews judged.
        old_cut = old_unit.get("implementation_cut")
        if old_cut is not None and nu.get("implementation_cut") != old_cut:
            raise HistoryRewriteError(
                "%s.implementation_cut: recorded boundary was modified" % uctx
            )
        for transient in (
            "implementation_attempt_snapshot",
            "implementation_stabilization",
            "pending_wip",
        ):
            old_value = old_unit.get(transient)
            new_value = nu.get(transient)
            if old_value is not None and new_value not in (old_value, None):
                raise HistoryRewriteError(
                    "%s.%s: pending intent was modified" % (uctx, transient)
                )
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
            # transition.  A design update may also be retired once, but it
            # may never be added or rewritten after the unit seals.
            old_update = old_unit.get("design_update")
            new_update = nu.get("design_update")
            if new_update not in (old_update, None):
                raise HistoryRewriteError(
                    "%s.design_update: terminal update was modified" % uctx
                )
            _post_seal = ("closed_record", "gate_commit", "design_update")
            frozen_old = {k: v for k, v in old_unit.items() if k not in _post_seal}
            frozen_new = {k: v for k, v in nu.items() if k not in _post_seal}
            if frozen_old != frozen_new:
                raise HistoryRewriteError("%s: terminal unit was modified" % uctx)


def _assert_task_history(old_tasks, new_tasks):
    """Allow only append and the first null-to-result task transition."""
    if not isinstance(old_tasks, list) or not isinstance(new_tasks, list):
        raise HistoryRewriteError("tasks: history must be a list")
    if len(new_tasks) < len(old_tasks):
        raise HistoryRewriteError("tasks: history shrank")
    ids = []
    for index, record in enumerate(new_tasks):
        if not isinstance(record, dict):
            raise HistoryRewriteError("tasks[%d]: record must be an object" % index)
        if set(record) != {"id", "order", "resolved_staffing", "result"}:
            raise HistoryRewriteError(
                "tasks[%d]: record has invalid fields" % index
            )
        task_id = record.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise HistoryRewriteError("tasks[%d]: invalid identity" % index)
        ids.append(task_id)
    if len(ids) != len(set(ids)):
        raise HistoryRewriteError("tasks: identities must be unique")
    for index, old_record in enumerate(old_tasks):
        new_record = new_tasks[index]
        ctx = "tasks[%d]" % index
        if old_record.get("id") != new_record.get("id"):
            raise HistoryRewriteError("%s: identity changed" % ctx)
        old_frozen = dict(old_record)
        new_frozen = dict(new_record)
        old_result = old_frozen.pop("result", None)
        new_result = new_frozen.pop("result", None)
        if not _json_values_equal(old_frozen, new_frozen):
            raise HistoryRewriteError("%s: frozen order was modified" % ctx)
        if (
            old_result is not None
            and not _json_values_equal(old_result, new_result)
        ):
            raise HistoryRewriteError("%s: terminal result was modified" % ctx)
        if old_result is None and new_result is not None:
            from orchestrator import tasks  # lazy: tasks imports this module
            try:
                tasks.validate_result(new_result)
            except tasks.ContractError as exc:
                raise HistoryRewriteError(
                    "%s: terminal result is invalid" % ctx
                ) from exc
    for index in range(len(old_tasks), len(new_tasks)):
        if new_tasks[index]["result"] is not None:
            raise HistoryRewriteError(
                "tasks[%d]: a new task must be non-terminal" % index
            )


@contextlib.contextmanager
def exclusive_mutation(path, wait=False):
    """Share the one ``<state>.lock`` authority across state writers."""
    if fcntl is None:
        yield
        return
    lock_path = path + ".lock"
    os.makedirs(os.path.dirname(os.path.abspath(lock_path)), exist_ok=True)
    handle = open(lock_path, "a+")
    try:
        flags = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
        try:
            fcntl.flock(handle.fileno(), flags)
        except OSError as exc:
            raise ConcurrentStateMutation(
                "another mutation is active on %s (advisory lock %s is held)"
                % (path, lock_path)
            ) from exc
        yield
    finally:
        handle.close()


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
    by_key = {unit_identity(u): u for u in state["units"]}
    for key in planned_execution_units(state):
        unit = by_key.get(key)
        if unit is not None and unit["status"] != U_SEALED:
            return unit
    return None


def unit_identity(unit):
    """Stable structural identity, compatible with all pre-part states."""
    return (unit.get("kind"), unit.get("slice_id"), unit.get("part"))


def _slice_token(slice_id, part=None):
    token = "%02d" % slice_id
    return "%s-%s" % (token, part) if part else token


def implementation_part(unit):
    """Visible implementation part, without changing historical identity.

    The original implementation unit keeps ``part`` absent forever so all of
    its already-recorded event/raw/API keys remain stable.  When it is cut, its
    immutable cut record gives it the visible label ``a``.  Continuations carry
    their part as identity from creation.
    """
    part = unit.get("part")
    if part is None and unit.get("kind") == UNIT_SLICE_IMPL:
        part = (unit.get("implementation_cut") or {}).get("part")
    return part


def slice_token(unit):
    if unit.get("slice_id") is None:
        return None
    return _slice_token(unit["slice_id"], implementation_part(unit))


def unit_key(unit):
    if unit["slice_id"] is None:
        return unit["kind"]
    # Canonical identity keys never retroactively gain "-a": events emitted
    # before the live cut must keep resolving to the same unit.  Newly-created
    # continuation units are born with part b/c/... and are unambiguous.
    return "%s-%s" % (
        unit["kind"], _slice_token(unit["slice_id"], unit.get("part"))
    )


def display_unit_key(unit):
    """Human label; unlike unit_key, the original cut is rendered as -a."""
    if unit["slice_id"] is None:
        return unit["kind"]
    return "%s-%s" % (unit["kind"], slice_token(unit))


def _next_part(part):
    """a -> b, z -> aa; labels are generated by code, never by a worker."""
    if not isinstance(part, str) or not part or not part.isalpha() \
            or part.lower() != part or not part.isascii():
        raise ValueError("implementation part must be lowercase ASCII letters")
    digits = [ord(ch) - ord("a") + 1 for ch in part]
    index = len(digits) - 1
    while index >= 0 and digits[index] == 26:
        digits[index] = 1
        index -= 1
    if index < 0:
        digits.insert(0, 1)
    else:
        digits[index] += 1
    return "".join(chr(ord("a") + digit - 1) for digit in digits)


def record_implementation_cut(state, unit, cut_scope, remaining_scope,
                              steer_lines=None, interrupt_lines=None):
    """Freeze one coherent implementation cut and its delegated remainder.

    The current unit remains the only in-flight unit.  Its immutable record is
    enough for planned_execution_units to derive the next part; no skeleton
    row, new slice note, or separately mutable execution-plan list is needed.
    """
    if unit.get("kind") != UNIT_SLICE_IMPL:
        raise IllegalTransition("only a slice_impl can record an implementation cut")
    if unit.get("status") != U_PENDING or unit.get("draft") is not None:
        raise IllegalTransition(
            "implementation cut must be recorded before the unit draft"
        )
    for name, value in (
        ("cut_scope", cut_scope), ("remaining_scope", remaining_scope)
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("%s must be a non-empty string" % name)
    current_part = unit.get("part") or "a"
    cut = {
        "part": current_part,
        "next_part": _next_part(current_part),
        "cut_scope": cut_scope.strip(),
        "remaining_scope": remaining_scope.strip(),
    }
    if steer_lines is not None:
        if type(steer_lines) is not int or steer_lines < 0:
            raise ValueError("steer_lines must be a non-negative integer")
        cut["steer_lines"] = steer_lines
    if interrupt_lines is not None:
        if type(interrupt_lines) is not int or interrupt_lines < 0:
            raise ValueError("interrupt_lines must be a non-negative integer")
        cut["interrupt_lines"] = interrupt_lines
    existing = unit.get("implementation_cut")
    if existing is not None:
        if (
            existing.get("cut_scope") == cut["cut_scope"]
            and existing.get("remaining_scope") == cut["remaining_scope"]
        ):
            return existing
        raise IllegalTransition("implementation cut is already recorded")
    unit["implementation_cut"] = cut
    append_event(
        state,
        "implementation_cut_recorded",
        unit=unit_key(unit),
        display_unit=display_unit_key(unit),
        part=current_part,
        next_part=cut["next_part"],
        steer_lines=steer_lines,
        interrupt_lines=interrupt_lines,
    )
    return cut


def implementation_scope(state, unit):
    """Prompt-ready scope for one implementation part, or None when whole.

    A unit's own cut governs its review/fix cycle.  An uncut continuation gets
    its assigned scope from the predecessor that delegated it.
    """
    if unit.get("kind") != UNIT_SLICE_IMPL:
        return None
    own = unit.get("implementation_cut")
    if own:
        return {
            "part": own["part"],
            "scope": own["cut_scope"],
            "delegated_remaining": own["remaining_scope"],
            "source_unit": unit_key(unit),
        }
    part = unit.get("part")
    if not part:
        return None
    predecessors = [
        candidate
        for candidate in state.get("units", [])
        if candidate.get("kind") == UNIT_SLICE_IMPL
        and candidate.get("slice_id") == unit.get("slice_id")
        and (candidate.get("implementation_cut") or {}).get("next_part") == part
    ]
    if len(predecessors) != 1:
        raise IllegalTransition(
            "implementation part %s has %d predecessors"
            % (display_unit_key(unit), len(predecessors))
        )
    predecessor = predecessors[0]
    cut = predecessor["implementation_cut"]
    return {
        "part": part,
        "scope": cut["remaining_scope"],
        "delegated_remaining": None,
        "source_unit": unit_key(predecessor),
    }


def planned_units(state):
    """Canonical DESIGN plan: skeleton plus doc+impl per known slice.

    Kept as the historical pair-shaped API for callers that enumerate design
    documents.  Runtime implementation cuts do not rewrite the sealed slice
    table; state navigation uses planned_execution_units below.
    """
    plan = [(UNIT_SKELETON, None)]
    for sl in state["milestone"]["slices"]:
        plan.append((UNIT_SLICE_DOC, sl["id"]))
        plan.append((UNIT_SLICE_IMPL, sl["id"]))
    return plan


def planned_execution_units(state):
    """Runtime plan identities, including sequential implementation parts.

    Each next part is derived solely from its predecessor unit's immutable
    ``implementation_cut``.  Merely recording a cut makes the continuation due
    in plan order, but the driver calls ensure_next_unit only after the
    predecessor seals, so no continuation record/commit coexists in flight.
    """
    plan = [(UNIT_SKELETON, None, None)]
    by_identity = {unit_identity(u): u for u in state.get("units", [])}
    for sl in state["milestone"]["slices"]:
        slice_id = sl["id"]
        plan.append((UNIT_SLICE_DOC, slice_id, None))
        identity = (UNIT_SLICE_IMPL, slice_id, None)
        plan.append(identity)
        seen_parts = set()
        while True:
            predecessor = by_identity.get(identity)
            cut = (predecessor or {}).get("implementation_cut") or {}
            next_part = cut.get("next_part")
            if not next_part:
                break
            if next_part in seen_parts:
                raise IllegalTransition(
                    "implementation part cycle on slice %02d at %s"
                    % (slice_id, next_part)
                )
            seen_parts.add(next_part)
            identity = (UNIT_SLICE_IMPL, slice_id, next_part)
            plan.append(identity)
    return plan


def ensure_next_unit(state):
    """After a unit seals, append the next planned unit record (if any).

    Returns the appended unit or None when the plan is complete."""
    existing = [unit_identity(u) for u in state["units"]]
    for kind, slice_id, part in planned_execution_units(state):
        if (kind, slice_id, part) not in existing:
            unit = _new_unit(kind, slice_id, part=part)
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
    by_key = {unit_identity(u): u for u in state["units"]}
    for key in planned_execution_units(state):
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
        U_ROUNDS: (U_ROUNDS, U_FIXING, U_PRE_REVIEW_VERIFY,
                   U_PRE_SEAL_VERIFY, U_FAILED),
        U_FIXING: (U_DELTA_REVIEW, U_PRE_REVIEW_VERIFY, U_ROUNDS,
                   U_PRE_SEAL_VERIFY, U_FAILED),
        U_DELTA_REVIEW: (U_FIXING, U_PRE_REVIEW_VERIFY, U_ROUNDS,
                         U_PRE_SEAL_VERIFY, U_FAILED),
        U_PRE_SEAL_VERIFY: (U_SEALING, U_FIXING, U_PRE_REVIEW_VERIFY,
                            U_FAILED),
        # U_SEALING is now only a transient/recovery state for deterministic
        # closure. Older persisted states without current review evidence
        # restart the ordinary review cycle.
        U_SEALING: (U_SEALED, U_PRE_REVIEW_VERIFY, U_FAILED),
        # A sealed unit is terminal EXCEPT for reopen_for_repair, which
        # reopens it to resolve a downstream builder's gap (reform §3). The
        # repair immediately enters a fix episode (U_REPAIRING -> U_FIXING)
        # and reseals through the normal seal path.
        U_SEALED: (U_REPAIRING,),
        # REPAIRING -> SEALED is the re-documentation wave's close: a slice
        # note co-reopened with the skeleton reseals when the ANCHOR's reviews
        # certify the whole documentation set; it never runs its own episode.
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
                 duration=None, model=None, effort=None, token_usage=None,
                 token_usage_partial=False, cost=None, cost_partial=False,
                 task_id=None):
    """Write-once record of the unit's draft/implement call."""
    if task_id is not None and (
        not isinstance(task_id, str) or not task_id
    ):
        raise IllegalTransition("task_id must be a non-empty string")
    if unit["status"] != U_PENDING:
        raise IllegalTransition(
            "unit %s: draft can only be recorded from pending (is %s)"
            % (unit_key(unit), unit["status"])
        )
    if unit["draft"] is not None:
        raise IllegalTransition("unit %s: draft already recorded" % unit_key(unit))
    implementation_cut = result.get("implementation_cut")
    if implementation_cut is not None:
        if kind != "implement":
            raise IllegalTransition(
                "implementation_cut is valid only on an implement draft"
            )
        record_implementation_cut(
            state,
            unit,
            implementation_cut["cut_scope"],
            implementation_cut["remaining_scope"],
        )
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
    if token_usage is not None:
        unit["draft"]["token_usage"] = copy.deepcopy(token_usage)
    if token_usage_partial:
        unit["draft"]["token_usage_partial"] = True
    if cost is not None:
        unit["draft"]["cost"] = copy.deepcopy(cost)
    if cost_partial or cost is None:
        unit["draft"]["cost_partial"] = True
    if task_id is not None:
        unit["draft"]["task_id"] = task_id
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
        token_usage_partial=bool(token_usage_partial),
        cost_partial=bool(cost_partial or cost is None),
        **(
            {"token_usage": copy.deepcopy(token_usage)}
            if token_usage is not None else {}
        ),
        **({"cost": copy.deepcopy(cost)} if cost is not None else {}),
        **({"task_id": task_id} if task_id is not None else {}),
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
                 meta=None, token_usage=None, token_usage_partial=False,
                 cost=None, cost_partial=False, task_id=None):
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
    if token_usage is not None:
        rec["token_usage"] = copy.deepcopy(token_usage)
    if token_usage_partial:
        rec["token_usage_partial"] = True
    if cost is not None:
        rec["cost"] = copy.deepcopy(cost)
    if cost_partial or cost is None:
        rec["cost_partial"] = True
    if meta and "task_id" in meta:
        raise IllegalTransition("task_id must use the explicit record link")
    if meta:
        rec.update(copy.deepcopy(meta))
    if task_id is not None:
        if not isinstance(task_id, str) or not task_id:
            raise IllegalTransition("task_id must be a non-empty string")
        rec["task_id"] = task_id
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


def restart_reviews_after_candidate_change(state, unit, reason):
    """Start a fresh whole-artifact review cycle after accepted byte changes.

    Earlier reviews and debt remain immutable audit history, but cannot satisfy
    the seal predicate for the new candidate.
    """
    start = len(unit.get("rounds") or [])
    unit["review_cycle_start"] = start
    unit["review_evidence_fingerprint"] = None
    unit["family_index"] = 0
    append_event(
        state,
        "review_cycle_restarted",
        unit=unit_key(unit),
        round_index=start,
        reason=str(reason or "candidate bytes changed")[:300],
    )
    return start


def advance_family_if_clean(state, unit, last_result):
    """After a clean review round, move to the next family or to pre-seal.

    Families run in configured order for one candidate. Accepted byte changes
    start a new cycle from the first family.
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
    """Whether every family is effectively clean in the current review cycle."""
    return seal_predicate_reviews(
        unit, state["config"]["families_order"]
    ) is not None


def seal_predicate_reviews(unit, families, current_fingerprint=None):
    """The seal predicate over the ledger. Returns the list
    of review-round ids that SATISFY it — every family's most recent
    whole-artifact review is clean (or clean-with-deferred-debt) AND on the
    CURRENT bytes and immutable execution plan — or None when it is not
    satisfied (a family never reviewed in the current cycle, its latest look
    is dirty, or its evidence fingerprint is stale).

    New states persist ``review_cycle_start`` when accepted edits change the
    candidate. For an older state without that marker, retain the conservative
    historical rule that any later fix round makes prior reviews stale.
    """
    rounds = unit["rounds"]
    cycle_start = unit.get("review_cycle_start")
    if cycle_start is None:
        cycle_start = 1 + max(
            (i for i, r in enumerate(rounds) if r["kind"] == "fix_findings"),
            default=-1,
        )
    cycle_start = max(0, min(int(cycle_start), len(rounds)))
    if current_fingerprint is not None:
        if unit.get("review_evidence_fingerprint") != current_fingerprint:
            return None
    cite = []
    for fam in families:
        revs = [
            (i, r) for i, r in enumerate(rounds)
            if i >= cycle_start
            and r["family"] == fam and r["kind"] == "review_round"
            and not r.get("invalidated")
        ]
        if not revs:
            return None
        _idx, last = revs[-1]
        if not _round_effectively_clean(last):
            return None
        if (current_fingerprint is not None
                and last.get("evidence_fingerprint")
                != current_fingerprint):
            return None
        cite.append(last["id"])
    return cite


def record_seal_attempt(state, unit, halves, passed, invalidated=None,
                        reviews=None, verification_event_seq=None):
    """Append an immutable seal record.

    New records derive their evidence from ``reviews`` and carry empty halves.
    The halves argument remains part of the persisted-history reader shape.
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
        "reviews": list(reviews or []),
        "passed": passed,
        "invalidated": invalidated,
    }
    # New deterministic seals always record whether verification was due.
    # Historical seals lack the key entirely, which lets projections preserve
    # their legacy verified status instead of relabelling them as "not due".
    if reviews is not None:
        rec["verification_event_seq"] = verification_event_seq
    unit["seals"].append(rec)
    if reviews is None:
        # Compatibility path for a genuinely attempted historical seal
        # worker pair. A derived seal has no attempt ceremony; its caller
        # records the single ``seal_satisfied`` result event instead.
        append_event(
            state,
            "seal_attempt",
            unit=unit_key(unit),
            attempt=rec["attempt"],
            passed=passed,
            invalidated=invalidated,
            reviews=[],
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
            # A recovered transient sealing state re-enters through the
            # pre-seal gate so verification is re-proven before closure.
            target = U_PRE_SEAL_VERIFY
        unit["status"] = target
        unit["failed_from"] = None
        # Grant fresh convergence state: a run that exhausted max_fix_loops
        # must not re-fail instantly on resume.
        unit["fix_loop_rounds"] = 0
        unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
        unit.pop("baseline_unstable_runs", None)
        # The gap-repair back-edge counter is a convergence cap too: a
        # deliberate resume grants it a fresh budget.
        unit["gap_repairs"] = 0
        # The review-round cap counts immutable history, so move its marker
        # to grant a fresh post-resume budget.
        unit["rounds_amnesty"] = len(unit["rounds"])
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
        "part": implementation_part(unit),
        "slice": slice_token(unit),
        "rounds": len(unit["rounds"]),
        "seal_attempts": len(unit["seals"]),
    }
    append_event(
        state,
        "slice_closed",
        slice_id=unit["slice_id"],
        part=implementation_part(unit),
        slice=slice_token(unit),
        unit=unit_key(unit),
        display_unit=display_unit_key(unit),
    )


def maybe_close_milestone(state):
    if state["milestone"]["status"] == M_CLOSED:
        return True  # idempotent: never records milestone_closed twice
    plan = planned_execution_units(state)
    have = {unit_identity(u): u for u in state["units"]}
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


def contested_debt_refs(state):
    """(unit_key, debt_id) pairs retired from active debt by a contest."""
    return {
        (e.get("unit"), e.get("debt_id"))
        for e in state.get("events", [])
        if e.get("type") == "debt_contested"
    }


def debt_ids(state):
    """Every ACTIVE tracked-debt entry id across all units.

    Deferral is the second way a finding gets dispatched without a fix, so
    a debt entry must be contestable exactly like an adjudicated rejection:
    a reviewer that brings new evidence against a deferral needs a legal
    reference to name, or the protocol check reads the contest as garbage
    and kills the run (the N46 incident: a deferred P3 escalated to P2
    with shipped-state-machine evidence had no legal way to say so).
    Already-contested entries are excluded: they are re-opened, not
    settled, so there is nothing left to contest."""
    return {
        entry["id"]
        for unit in state["units"]
        for entry in active_debt(state, unit)
    }


def reopen_contested_debt(state, findings):
    """Re-open every debt entry a queued finding contests.

    Debt arrays are immutable history, so — exactly like the requeue and
    overturn machinery — the contest is recorded as an append-only
    `debt_contested` event and active_debt() derives the entry's
    retirement from it. Searched across all units because debt ids are
    milestone-wide (a later unit's reviewer may contest an earlier unit's
    deferral). Returns the re-opened ids."""
    refs = {
        (f.get("contests") or {}).get("rejection_id"): f.get("id")
        for f in findings or []
        if f.get("contests")
    }
    reopened = []
    if not refs:
        return reopened
    for unit in state["units"]:
        for entry in active_debt(state, unit):
            if entry["id"] in refs:
                reopened.append(entry["id"])
                append_event(
                    state, "debt_contested",
                    unit=unit_key(unit),
                    debt_id=entry["id"],
                    contested_by=refs[entry["id"]],
                )
    return reopened


def reopen_for_repair(state, unit, gap, reason, reported_by=None):
    """Reopen a SEALED unit to resolve a downstream builder's gap (reform
    §3, stop-report-repair-resume). Transitions sealed -> repairing and
    grants FRESH fix/review budgets — the repair and its reseal must not
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
    # deterministic reseal) must know the unit's own artifact is editable —
    # not just
    # the first fix episode. The fix prompt's editability line keys off
    # this flag, which only the reseal clears; keying off the queue's
    # source type instead dropped the line on delta-loop fix rounds and
    # made the fixer refuse its own repair (found live 2026-07-11,
    # certification-llm skeleton repair).
    unit["under_repair"] = True
    unit["fix_loop_rounds"] = 0
    unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
    unit["rounds_amnesty"] = len(unit["rounds"])
    restart_reviews_after_candidate_change(
        state, unit, "sealed unit reopened for repair"
    )
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
    """Explicitly abandon a candidate and return its unit to a fresh draft.

    Production fixer gaps preserve and later replay their existing candidate;
    this helper remains for callers that have independently established that a
    draft must be discarded.  It grants fresh review budgets, clears the
    abandoned fix episode, and preserves append-only review/seal history.
    Status is set directly because this is an intentional backward reset,
    outside the normal forward transition table."""
    prior = unit["status"]
    unit["draft"] = None
    unit["artifact"] = None
    unit["fix_queue"] = []
    unit["fix_source"] = None
    unit.pop("under_repair", None)
    unit.pop("design_correction", None)
    unit.pop("design_correction_attempted", None)
    unit.pop("baseline_verification", None)
    unit.pop("baseline_unstable_runs", None)
    unit.pop("implementation_attempt_snapshot", None)
    unit.pop("implementation_stabilization", None)
    unit.pop("pending_wip", None)
    discarded_handoff = unit.pop("brainstorming_review_handoff", None)
    unit["fix_loop_rounds"] = 0
    unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
    unit["rounds_amnesty"] = len(unit["rounds"])
    # The re-draft starts a FRESH review cycle from the first family; a unit
    # whose family_index had advanced (for example, a gap after the
    # first family cleared) would otherwise reach U_ROUNDS with no family to
    # run (IllegalTransition) or silently skip the first family's review.
    unit["family_index"] = 0
    unit["review_cycle_start"] = len(unit["rounds"])
    unit["review_evidence_fingerprint"] = None
    unit["status"] = U_PENDING
    if discarded_handoff is not None:
        append_event(
            state,
            "brainstorming_review_handoff_discarded",
            unit=unit_key(unit),
            reason="unit reset for a new draft",
        )
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
    references the anchor's passing result and cited reviews. Those reviews
    certified the ENTIRE documentation set — edited or not — so the notes
    never run their own review cycles. KEEPS state["redoc_wave"]
    (phase 2, stamp_redoc_wave_gate, clears it after the gate commit binds
    the shas — a crash between the phases must stay recoverable).
    Idempotent: already-sealed notes are skipped. Returns the closed keys."""
    wave = state.get("redoc_wave") or {}
    anchor_key = unit_key(anchor)
    if wave.get("anchor") != anchor_key:
        return []
    attempt = len(anchor["seals"])
    anchor_reviews = list(
        (anchor["seals"][-1] if anchor["seals"] else {}).get("reviews") or []
    )
    anchor_seal = anchor["seals"][-1] if anchor["seals"] else {}
    verification_recorded = "verification_event_seq" in anchor_seal
    verification_event_seq = anchor_seal.get("verification_event_seq")
    by_key = {unit_key(u): u for u in state["units"]}
    closed = []
    for key in wave.get("docs") or []:
        unit = by_key.get(key)
        if unit is None or unit["status"] != U_REPAIRING:
            continue
        seal = {
            "attempt": len(unit["seals"]) + 1,
            "at": now_iso(),
            "passed": True,
            "invalidated": None,
            "halves": {},
            "reviews": list(anchor_reviews),
            "wave": "%s-a%d" % (anchor_key, attempt),
        }
        if verification_recorded:
            seal["verification_event_seq"] = verification_event_seq
        unit["seals"].append(seal)
        transition_unit(
            state, unit, U_SEALED, reason="re-documentation wave reseal"
        )
        closed.append(key)
    if closed:
        event = {
            "anchor": anchor_key,
            "attempt": attempt,
            "docs": closed,
        }
        if verification_event_seq is not None:
            event["verification_event_seq"] = verification_event_seq
        append_event(state, "redoc_wave_closed", **event)
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
    reopen_contested_debt(state, findings)
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
    """Debt entries still deferred: recorded history minus implementation
    requeues and minus contested entries (a contest re-opens the deferral
    for the fixer, so the entry is no longer settled)."""
    hidden = requeued_debt_refs(state)
    contested = contested_debt_refs(state)
    key = unit_key(unit)
    return [
        debt for index, debt in enumerate(unit.get("debt", []))
        if (key, index) not in hidden
        and (key, debt.get("id")) not in contested
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
    if target.get("status") not in (U_ROUNDS, U_PRE_SEAL_VERIFY):
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
                "id": "IMPL-DEBT-%s-%02d"
                      % (slice_token(unit) or "00", index + 1),
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
            "task_id": source.get("task_id"),
            "family": source.get("family"),
            "model": source.get("model"),
            "effort": source.get("effort"),
            "duration_s": source.get("duration_s"),
            "token_usage": copy.deepcopy(source.get("token_usage")),
            "token_usage_partial": bool(
                source.get("token_usage_partial", False)
            ),
            "cost": copy.deepcopy(source.get("cost")),
            "cost_partial": bool(source.get("cost_partial", False)),
            "at": source.get("at"),
            "raw_path": source.get("raw_path"),
            "current": is_current,
        })
    if current and not current_matched:
        records.append({
            "kind": current.get("kind"),
            "task_id": current.get("task_id"),
            "family": current.get("family"),
            "model": current.get("model"),
            "effort": current.get("effort"),
            "duration_s": current.get("duration_s"),
            "token_usage": copy.deepcopy(current.get("token_usage")),
            "token_usage_partial": bool(
                current.get("token_usage_partial", False)
            ),
            "cost": copy.deepcopy(current.get("cost")),
            "cost_partial": bool(current.get("cost_partial", False)),
            "at": current.get("at"),
            "raw_path": current.get("raw_path"),
            "current": True,
        })
    return records


def _work_durations(state):
    """Return ({unit_key: seconds}, unassigned_malformed_seconds).

    This is *work consumed*, not elapsed wall time. Every completed live call
    has one durable home (draft, round, reclassification, verification, or a
    repaired malformed first strike); persisted historical seal-half
    durations are included too. Deriving the total keeps it restart-safe.
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
        if etype in (
            "reclassify_recorded",
            "gap_reported",
            "brainstorming_origin_recorded",
            "brainstorming_work_recorded",
            "implementation_size_interrupted",
            "worker_interrupted",
            "worker_unaccepted",
            "error_classifier_call",
        ):
            key = event.get("unit")
            if key in totals:
                totals[key] += _completed_duration(event.get("duration_s"))
            continue
        if etype == "verification":
            # A fixer-certified event describes the suite work already
            # counted in that fix round; reused events execute no new work.
            if not event.get("fixer_certified") and not event.get("reused"):
                key = event.get("unit")
                if key in totals:
                    totals[key] += _completed_duration(
                        event.get("duration_s")
                    )
            continue
        if etype != "worker_malformed":
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


_TOKEN_USAGE_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def _normalized_token_usage(value):
    if not isinstance(value, dict):
        return None
    checked = {}
    for field in _TOKEN_USAGE_FIELDS:
        count = value.get(field)
        if type(count) is not int or count < 0:
            return None
        checked[field] = count
    if checked["cached_input_tokens"] > checked["input_tokens"]:
        return None
    if checked["reasoning_output_tokens"] > checked["output_tokens"]:
        return None
    if checked["total_tokens"] != (
        checked["input_tokens"] + checked["output_tokens"]
    ):
        return None
    return checked


def _add_token_usage(current, value):
    value = _normalized_token_usage(value)
    if value is None:
        return current
    if current is None:
        return value
    return {
        field: current[field] + value[field]
        for field in _TOKEN_USAGE_FIELDS
    }


# What a call cost, under the two readings the panel keeps apart: what it
# WOULD cost at published rates, and what money actually left. See pricing.py.
_COST_FIELDS = ("api_usd", "real_usd")


def _normalized_cost(value):
    if not isinstance(value, dict):
        return None
    checked = {}
    for field in _COST_FIELDS:
        amount = value.get(field)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return None
        amount = float(amount)
        if not math.isfinite(amount) or amount < 0:
            return None
        checked[field] = amount
    # Real money is the API-equivalent when the family is metered and zero
    # when it is a seat; it can never exceed the equivalent.
    if checked["real_usd"] > checked["api_usd"]:
        return None
    return checked


def _add_cost(current, value):
    value = _normalized_cost(value)
    if value is None:
        return current
    if current is None:
        return value
    return {field: current[field] + value[field] for field in _COST_FIELDS}


def _work_token_usage(state):
    """Mirror work-duration ownership with provider tokens AND their price.

    One traversal owns both so the two can never drift apart: a record that
    counts toward a unit's tokens counts toward its cost, and a record whose
    price is unknown marks the same unit partial that a missing token count
    would.
    """
    keys = [unit_key(unit) for unit in state.get("units") or []]
    totals = dict((key, None) for key in keys)
    partial = dict((key, False) for key in keys)
    unassigned = None
    unassigned_partial = False
    cost_totals = dict((key, None) for key in keys)
    cost_partial = dict((key, False) for key in keys)
    unassigned_cost = None
    unassigned_cost_partial = False

    def account(key, duration, usage, known_partial=False,
                cost=None, cost_known_partial=False):
        nonlocal unassigned, unassigned_partial
        nonlocal unassigned_cost, unassigned_cost_partial
        normalized = _normalized_token_usage(usage)
        priced = _normalized_cost(cost)
        worked = _completed_duration(duration) > 0
        missing = worked and normalized is None
        cost_missing = (worked and priced is None) or (
            cost is not None and priced is None
        )
        if key in totals:
            totals[key] = _add_token_usage(totals[key], normalized)
            partial[key] = partial[key] or missing or bool(known_partial)
            cost_totals[key] = _add_cost(cost_totals[key], priced)
            cost_partial[key] = (
                cost_partial[key] or cost_missing or bool(cost_known_partial)
            )
        else:
            unassigned = _add_token_usage(unassigned, normalized)
            unassigned_partial = (
                unassigned_partial or missing or bool(known_partial)
            )
            unassigned_cost = _add_cost(unassigned_cost, priced)
            unassigned_cost_partial = (
                unassigned_cost_partial or cost_missing
                or bool(cost_known_partial)
            )

    for unit in state.get("units") or []:
        key = unit_key(unit)
        stabilization = (
            (unit.get("implementation_stabilization") or {}).get(
                "implementation_size"
            )
        )
        if isinstance(stabilization, dict):
            episode_id = stabilization.get("episode_id")
            has_interrupt_accounting = bool(
                episode_id
                and any(
                    event.get("type") == "implementation_size_interrupted"
                    and event.get("unit") == key
                    and event.get("episode_id") == episode_id
                    for event in state.get("events") or []
                )
            )
            if not has_interrupt_accounting:
                partial[key] = True
                cost_partial[key] = True
        for draft in _draft_history(state, unit):
            account(
                key,
                draft.get("duration_s"),
                draft.get("token_usage"),
                draft.get("token_usage_partial", False)
                or draft.get("token_usage") is None,
                cost=draft.get("cost"),
                cost_known_partial=draft.get("cost_partial", False)
                or draft.get("cost") is None,
            )
        for round_ in unit.get("rounds") or []:
            account(
                key,
                round_.get("duration_s"),
                round_.get("token_usage"),
                round_.get("token_usage_partial", False)
                or round_.get("token_usage") is None,
                cost=round_.get("cost"),
                cost_known_partial=round_.get("cost_partial", False)
                or round_.get("cost") is None,
            )
        for seal in unit.get("seals") or []:
            for half in (seal.get("halves") or {}).values():
                if half:
                    account(
                        key,
                        half.get("duration_s"),
                        half.get("token_usage"),
                        half.get("token_usage_partial", False)
                        or half.get("token_usage") is None,
                        cost=half.get("cost"),
                        cost_known_partial=half.get("cost_partial", False)
                        or half.get("cost") is None,
                    )

    for event in state.get("events") or []:
        etype = event.get("type")
        if etype in (
            "reclassify_recorded",
            "gap_reported",
            "brainstorming_origin_recorded",
            "brainstorming_work_recorded",
            "implementation_size_interrupted",
            "worker_interrupted",
            "worker_unaccepted",
            "error_classifier_call",
        ):
            account(
                event.get("unit"),
                event.get("duration_s"),
                event.get("token_usage"),
                event.get("token_usage_partial", False),
                cost=event.get("cost"),
                cost_known_partial=event.get("cost_partial", False),
            )
            continue
        if etype != "worker_malformed":
            continue
        key = event.get("unit")
        if not key:
            label = str(event.get("label") or "")
            key = next(
                (
                    candidate
                    for candidate in keys
                    if label == candidate or label.startswith(candidate + "-")
                ),
                None,
            )
        if (
            event.get("duration_s") is None
            and event.get("token_usage") is None
            and not event.get("fatal")
        ):
            continue
        account(
            key,
            event.get("duration_s"),
            event.get("token_usage"),
            event.get("token_usage_partial", False)
            or (event.get("fatal") and event.get("token_usage") is None),
            cost=event.get("cost"),
            cost_known_partial=event.get("cost_partial", False)
            or (event.get("fatal") and event.get("cost") is None),
        )
    return (
        totals, partial, unassigned, unassigned_partial,
        cost_totals, cost_partial, unassigned_cost, unassigned_cost_partial,
    )


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
    "brainstorming_missing_detached": "detached",
    "guarantee_calibration_completed": "continued",
    "guarantee_calibration_failed": "failed",
}


def summary(state, acts_overlay=None, current_review_model=None):
    unit = current_unit(state)
    model_defaults = state["config"].get("model_defaults") or {}
    debt_requeues = requeued_debt_refs(state)
    requeued_ids = requeued_debt_ids(state)
    work_by_unit, unassigned_work = _work_durations(state)
    token_by_unit, token_partial_by_unit, unassigned_tokens, \
        unassigned_tokens_partial, cost_by_unit, cost_partial_by_unit, \
        unassigned_cost, unassigned_cost_partial = _work_token_usage(state)
    repairs_by_unit = _repair_episodes(state)

    def effective_setting(family, explicit, field):
        if explicit:
            return explicit
        return (model_defaults.get(family) or {}).get(field)

    opened_at = {}
    closed_at = {}
    wip_sha = {}
    reclassify_by_unit = {}
    verification_by_unit = {}
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
                "duration_s": None,
                "token_usage": None,
                "token_usage_partial": False,
                "cost": None,
                "cost_partial": False,
            }
            brainstorming_by_unit.setdefault(uk, []).append(entry)
            brainstorming_index[(uk, e.get("session_id"))] = entry
        elif e.get("type") in _BRAINSTORMING_OUTCOMES:
            entry = brainstorming_index.get((uk, e.get("session_id")))
            if entry is not None:
                entry["outcome"] = _BRAINSTORMING_OUTCOMES[e.get("type")]
                entry["outcome_at"] = e.get("at")
        elif e.get("type") == "brainstorming_work_recorded":
            entry = brainstorming_index.get((uk, e.get("session_id")))
            if entry is not None:
                entry["duration_s"] = e.get("duration_s")
                entry["token_usage"] = copy.deepcopy(e.get("token_usage"))
                entry["token_usage_partial"] = bool(
                    e.get("token_usage_partial", False)
                )
                entry["cost"] = copy.deepcopy(e.get("cost"))
                entry["cost_partial"] = bool(e.get("cost_partial", False))
        if e.get("type") == "unit_opened" and uk not in opened_at:
            opened_at[uk] = _epoch(e.get("at"))
        if e.get("type") == "unit_transition" and e.get("to_status") == U_SEALED:
            closed_at[uk] = _epoch(e.get("at"))
        if e.get("type") in ("wip_commit", "amended"):
            # Latest sha of the unit's working commit (amends replace it);
            # the panel links the CURRENT unit's work-so-far through it.
            wip_sha[uk] = e.get("sha")
        if e.get("type") == "reclassify_recorded":
            reclassify_by_unit.setdefault(uk, []).append(
                {
                    "seq": e.get("seq"),
                    "at": e.get("at"),
                    "source_round": e.get("source_round"),
                    "finding_id": e.get("finding_id"),
                    "reclassifier": e.get("reclassifier"),
                    "model": e.get("model"),
                    "effort": e.get("effort"),
                    "logical_duration_s": e.get("logical_duration_s"),
                    "drift_risk": e.get("drift_risk"),
                    "drift_damage": e.get("drift_damage"),
                    "threshold": e.get("threshold"),
                    "defer_ok": e.get("defer_ok"),
                    "requeued": bool(
                        e.get("defer_ok")
                        and e.get("finding_id")
                        in requeued_ids.get(uk, set())
                    ),
                    "duration_s": e.get("duration_s"),
                    "token_usage": copy.deepcopy(e.get("token_usage")),
                    "cost": copy.deepcopy(e.get("cost")),
                    "cost_partial": bool(e.get("cost_partial", False)),
                    "token_usage_partial": bool(
                        e.get("token_usage_partial", False)
                    ),
                }
            )
        if e.get("type") == "verification":
            verification_by_unit.setdefault(uk, []).append(
                {
                    "seq": e.get("seq"),
                    "at": e.get("at"),
                    "stage": e.get("stage"),
                    "boundary": e.get("boundary"),
                    "cadence": e.get("cadence"),
                    "ok": e.get("ok"),
                    "stable": e.get("stable"),
                    "reused": bool(e.get("reused")),
                    "vacuous": bool(e.get("vacuous")),
                    "fixer_certified": bool(e.get("fixer_certified")),
                    "duration_s": e.get("duration_s"),
                }
            )
    units_view = []
    for u in state["units"]:
        draft_history = _draft_history(state, u)
        units_view.append(
            {
                "unit": unit_key(u),
                # `unit` remains the stable API/history key. The visible key
                # may add -a once the original implementation is cut.
                "display_unit": display_unit_key(u),
                "slice_id": u.get("slice_id"),
                "part": implementation_part(u),
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
                "work_token_usage": copy.deepcopy(
                    token_by_unit.get(unit_key(u))
                ),
                "work_token_usage_partial": token_partial_by_unit.get(
                    unit_key(u), False
                ),
                "work_cost": copy.deepcopy(cost_by_unit.get(unit_key(u))),
                "work_cost_partial": cost_partial_by_unit.get(
                    unit_key(u), False
                ),
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
                        "token_usage": copy.deepcopy(
                            draft.get("token_usage")
                        ),
                        "token_usage_partial": bool(
                            draft.get("token_usage_partial", False)
                        ),
                        "cost": copy.deepcopy(draft.get("cost")),
                        "cost_partial": bool(draft.get("cost_partial", False)),
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
                        "token_usage": copy.deepcopy(
                            u["draft"].get("token_usage")
                        ),
                        "token_usage_partial": bool(
                            u["draft"].get("token_usage_partial", False)
                        ),
                        "cost": copy.deepcopy(u["draft"].get("cost")),
                        "cost_partial": bool(
                            u["draft"].get("cost_partial", False)
                        ),
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
                        "deferred_clean": bool(r.get("deferred_clean")),
                        "invalidated": r.get("invalidated"),
                        "duration_s": r.get("duration_s"),
                        "token_usage": copy.deepcopy(r.get("token_usage")),
                        "token_usage_partial": bool(
                            r.get("token_usage_partial", False)
                        ),
                        "cost": copy.deepcopy(r.get("cost")),
                        "cost_partial": bool(r.get("cost_partial", False)),
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
                        "reviews": list(s.get("reviews") or []),
                        "verification_event_seq": s.get(
                            "verification_event_seq"
                        ),
                        "verification_recorded": (
                            "verification_event_seq" in s
                        ),
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
                # Every complete-suite decision that actually ran or reused
                # a fixer proof. Deferred checkpoints are ordinary routing
                # events and do not pretend work was performed.
                "verifications": verification_by_unit.get(unit_key(u), []),
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
        if current_review_model:
            current_model = current_review_model
        else:
            review_key = "review_%s" % current_fam
            if isinstance(acts_overlay, dict) and review_key in acts_overlay:
                review_act = acts_overlay[review_key]
            else:
                review_act = (state["config"].get("acts") or {}).get(
                    review_key
                )
            if isinstance(review_act, dict) and review_act.get("model"):
                current_model = review_act["model"]
    total_token_usage = unassigned_tokens
    for unit_token_usage in token_by_unit.values():
        total_token_usage = _add_token_usage(
            total_token_usage, unit_token_usage
        )
    total_cost = unassigned_cost
    for unit_cost in cost_by_unit.values():
        total_cost = _add_cost(total_cost, unit_cost)
    # Producer defaults are a read-time compatibility rule.  Keep old and
    # partial durable plans byte-stable while every current projection exposes
    # the complete pair.
    from orchestrator import tasks

    effective_slices = tasks.effective_slice_plan(
        state["milestone"]["slices"]
    )
    out = {
        "goal": state["goal"],
        "workspace": state["workspace"],
        "milestone_status": state["milestone"]["status"],
        "slices": effective_slices,
        "current_unit": unit_key(unit) if unit else None,
        "display_current_unit": display_unit_key(unit) if unit else None,
        "current_unit_status": unit["status"] if unit else None,
        # A cutoff interrupt is persisted before the transport is stopped.
        # Keep that crash-gap truth visible without exposing the internal
        # timing/transport marker through the summary contract.
        "implementation_stabilization": bool(
            unit is not None
            and unit.get("implementation_stabilization") is not None
        ),
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
        "work_token_usage": total_token_usage,
        "work_token_usage_partial": (
            unassigned_tokens_partial or any(token_partial_by_unit.values())
        ),
        "work_cost": total_cost,
        "work_cost_partial": (
            unassigned_cost_partial or any(cost_partial_by_unit.values())
        ),
        # Which families are metered decides whether the panel is showing
        # money or an equivalent; it cannot be inferred from the amounts,
        # because a genuinely free seat and a zero-cost call look alike.
        "billing": copy.deepcopy(state["config"].get("billing") or {}),
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
