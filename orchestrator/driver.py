"""Deterministic orchestrator driver.

The control loop the canon used to delegate to an LLM orchestrator, now
hardcoded: read state -> decide the single legal next action -> execute it
(usually one full-permission CLI worker call) -> append immutable records ->
save -> repeat. Content judgment stays with the LLM workers; sequencing,
bookkeeping, and gate enforcement live here, in tested code.

Usage:
  python3 -m orchestrator.driver init --goal "..." --workspace DIR [--config F]
  python3 -m orchestrator.driver status [--json]
  python3 -m orchestrator.driver next
  python3 -m orchestrator.driver step
  python3 -m orchestrator.driver run [--max-steps N]
  python3 -m orchestrator.driver serve [--port 8765]
"""

import argparse
import base64
import contextlib
import copy
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX: flock degrades to the
    fcntl = None     # staleness check in step(); documented in the README

from . import author_calls, brainstorming, brainstorming_lifecycle
from . import brainstorming_milestone, canonical_plan
from . import contracts, errclass, gitops, interpreter, kvstore, ledgers
from . import model_profiles, pricing, profiles, projects, prompt_sets, prompts
from . import registry, runners
from . import staffing
from . import tasks
from . import verifiers, workareas
from . import state as st

IMPLEMENTATION_SIZE_ACK = "IMPLEMENTATION_SIZE_CUTOFF_ACK"
FULL_VERIFICATION_SLICE_INTERVAL = 4
# A producer write owns only a local state-file critical section.  Give that
# handoff enough time to finish without turning unrelated driver contention
# into a queued invocation.
PRODUCER_HANDOFF_GRACE_S = 1.0
PRODUCER_HANDOFF_POLL_S = 0.01


class _NoIndependentReclassifier(runners.RunnerError):
    """Current structural policy leaves no separate rating call."""

DEFAULT_CONFIG = {
    "families_order": ["codex", "claude"],
    "fix_family": None,  # default: first family in families_order
    "commands": {
        "codex": [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m",
            "{model}",
            "-c",
            "model_reasoning_effort={effort}",
            "--output-last-message",
            "{output_file}",
        ],
        "claude": [
            "claude",
            "-p",
            "--model",
            "{model}",
            "--effort",
            "{effort}",
            "--permission-mode",
            "bypassPermissions",
        ],
    },
    # Family-level model/effort used when an act does not override them.
    # {model}/{effort} placeholders in the command template are filled per
    # call; templates without placeholders (codex: its model lives in its
    # own CLI config) ignore overrides.
    # Verified against the installed CLIs (2026-07-09, claude ids
    # re-verified 2026-07-26): claude accepts explicit ids
    # (claude-fable-5 / claude-opus-5 / claude-sonnet-5)
    # and efforts low|medium|high|xhigh|max; codex models come from its
    # live catalog (gpt-5.6-sol / gpt-5.6-terra / gpt-5.6-luna) with
    # reasoning efforts low|medium|high|xhigh|max set via
    # `-c model_reasoning_effort=...` (bare value: failed TOML parse
    # falls back to the literal string, per codex --help).
    # claude workers run with background workflows force-disabled
    # (runners.WORKFLOW_DISABLED_ENV): the async workflow model is
    # incompatible with the one-shot call contract.
    "model_defaults": {
        "claude": {"model": "claude-opus-5", "effort": "xhigh"},
        "codex": {"model": "gpt-5.6-sol", "effort": "xhigh"},
    },
    # How each family is PAID FOR, which is what separates the two costs the
    # panel shows. "subscription": the call spends a seat, so its real cost is
    # 0.00 and only the API-equivalent is informative. "api": metered, so the
    # equivalent IS the money. Set per family; see pricing.py.
    "billing": {
        "claude": pricing.BILLING_SUBSCRIPTION,
        "codex": pricing.BILLING_SUBSCRIPTION,
    },
    # No hard wall-clock timeout: worker calls run as long as the work needs
    # (an implement call may legitimately run hours of test suites). A fixed
    # cap killed a real 15-minute-plus implement mid-flight. Instead a
    # LIVENESS watchdog (below) kills only a FROZEN worker. Operators can
    # still set per-family hard caps here when a run warrants them.
    "timeouts": {},
    # Liveness watchdog: a worker whose whole process TREE burns less than
    # worker_stall_min_cpu_s of CPU across a full worker_stall_window_s
    # window is frozen (dead CLI spawn, or a provider-side hang with no
    # bytes flowing) and gets SIGKILLed + typed `stalled` (recoverable,
    # auto-resumed; a fresh call re-issues the work). Measured live: a hung
    # codex burned 0.03s over 5h (~0.001s/window); a WORKING worker — even a
    # report-only review that mostly waits on the LLM — burns ~7-75s/window
    # (streaming keeps CPU flowing). 1s/15min sits ~1000x above frozen and
    # ~7x below the lightest real work. Set the window to 0 to disable.
    "worker_stall_window_s": 900,
    "worker_stall_min_cpu_s": 1.0,
    # Keep implementation commits reviewable.  The live worker is first
    # asked to acknowledge and close one coherent functional cut. Crossing
    # the hard boundary starts a 3-minute grace, extended to 10 minutes by a
    # real model acknowledgement; expiry hands the work to a stabilizer.
    # Git is the sole meter.  Markdown/text and runtime bookkeeping are
    # excluded by gitops.reviewable_line_count().
    "implementation_size_control": {
        # Tightened from 1000/1500 (operator, 2026-08-20): parts were
        # landing at 1000+ reviewable lines every time — workers ride to
        # the boundary, so the boundary IS the slice size. 500 matches the
        # WORKSPACE.md sizing guidance; 750 is the containment wall.
        "soft_lines": 500,
        "hard_lines": 750,
        "poll_interval_s": 2,
        "unconfirmed_grace_s": 180,
        "confirmed_grace_s": 600,
    },
    "verification": [],
    # Unlimited by default, same philosophy as worker timeouts: a real
    # suite may take 15+ minutes and a gate that kills it converts honest
    # work into failures. Set a number (seconds) to cap it per run.
    "verification_timeout": None,
    "max_rounds_per_family": 12,
    # Gate commits + the reviewed-point index discipline (see gitops.py).
    # Off by default for pure-state CLI runs; the demo config and the
    # service panel (service.create_run forces it on unless the operator
    # explicitly disables it) enable it.
    "git": {"enabled": False},
    # Per-act family policy: a family name ("codex"/"claude"), "self"
    # (same family as the act's origin), or "opposite". Delta review is not
    # independently configurable: it always uses the fixer's family and that
    # family's Review profile.
    # Acts may also be objects: {"agent": "claude", "model": "sonnet",
    # "effort": "high"} — who leads SKELETON content work ("skeletoner":
    # its draft, re-drafts, AND fixes — only skeleton reviews stay on the
    # review families), slice-note drafting ("drafter"), implementation
    # ("implementer") and fixes ("fixer"), and with which model/effort.
    # `review_codex` / `review_claude` tune each fixed review family
    # independently without changing family rotation; they apply to
    # whole-artifact rounds and delta reviews. Absent
    # drafter / implementer fall back to fix_family (legacy behavior). The
    # operator can hot-edit all of this mid-run via acts.json; the driver
    # re-reads it before every act resolution.
    "acts": {
        "fixer": "codex",
        # The normal implementation owner also presents the Initial Position in every
        # milestone-owned Brainstorming session.  Pinning the profile here
        # avoids silently dropping from max effort to the family default.
        "implementer": {
            "agent": "claude",
            "model": "claude-fable-5",
            "effort": "max",
        },
        # The second voice answers the Initial Position, so it is ALWAYS
        # the opposite family of whoever leads the session, at the LEAD'S
        # effort: a counterpart from the same family, or arguing below the
        # proposer's weight, is not a second opinion. The model comes from
        # the resolved family; an override may tune model/effort, but not
        # move the seat back onto the lead's family
        # (see _brainstorming_profiles).
        "brainstorming_counterpart": "opposite",
        # The skeleton is drafted, re-drafted, and fixed by one chosen
        # model — skeleton work is high-leverage planning, so it defaults
        # to claude-fable-5 at max effort. Reviews of the skeleton are
        # unaffected (they use review_codex/review_claude).
        "skeletoner": {
            "agent": "claude",
            "model": "claude-fable-5",
            "effort": "max",
        },
        # The consulted family is the opposite of the fixer's; it runs at
        # the CALLER'S effort (see _consultation_command) so a rejection
        # is never argued by a lighter opponent than the one rejecting.
        "consultation": "opposite",
        # Who RATES findings for debt deferral: a fixed family (operator
        # 2026-07-09: an 8-minute opposite-family rating of a
        # 4-minute review's findings is upside down; a fixed fast
        # rater is still a fresh stateless look). "opposite" remains a
        # valid policy for operators who want the pre-reform doctrine.
        "reclassifier": {"agent": "codex", "effort": "xhigh"},
    },
    # New runs calibrate the skeleton's declared guarantees once, before its
    # ordinary review cycle. Persisted runs created before this key existed
    # continue without inserting a new stage into their chronology.
    "guarantee_calibration": {
        "enabled": True,
        "max_rounds": contracts.MILESTONE_BRAINSTORMING_ROUNDS,
    },
    # A delta stops being meaningfully incremental after enough cumulative
    # fixes.  After this many fixes in one episode born from a review round
    # or a seal, amend the pending diff without fabricating a clean delta
    # result and return exactly where a real clean delta would return: a
    # review episode re-reviews the whole amended commit, a seal episode
    # re-runs the suite and opens a fresh full seal.
    "delta_full_review_after_fixes": 5,
    # Fixer+delta iterations allowed per fix episode before failing. A
    # deliberate resume grants a fresh budget (state.resume_run resets the
    # counter), so this is a soft ceiling, not a dead end.
    "max_fix_loops": 20,
    # Back-edge budget (reform decision 13): how many times a downstream
    # builder may reopen an upstream unit for repair before the driver
    # stops for the operator (the same gap bouncing = a real stall, not
    # convergence). Amnesty on resume, like the other convergence caps.
    "max_gap_repairs": 3,
    # Rated DOC-debt deferral. Eligible doc findings (P3 in legacy, P2/P3 in
    # a reform profile), whether raised in rounds or seals, are rated
    # independently. Findings below the threshold become tracked debt; only
    # retained findings enter a fix cycle. Implementation and delta findings
    # always enter the normal fix/reject flow. A refused verdict or failed
    # rating retains that finding for the fixer.
    "p3_reclassify_debt": True,
    # Deferral threshold over the reclassifier's drift-risk rating
    # (low|medium|high|xhigh): an eligible finding defers at/below this.
    # The worker only RATES; this config makes the decision — set per
    # project by the operator's cost-of-being-wrong: storage/contract
    # work (Life/Spanner) -> "low"; UI shell work (chat components) ->
    # "medium". high/xhigh are never sensible thresholds.
    "p3_defer_max_risk": "low",
    # Reform runs: a goal LONGER than this (chars) is not inlined into
    # the skeleton-phase prompts — it rides as the generated goal.md
    # ledger and the prompt orders a full read. Short goals (the common
    # panel-typed case) stay inline: zero indirection. Instructions must
    # dominate a prompt, and a FILE survives the worker's own context
    # compaction where inline prose does not.
    "goal_inline_max": 8000,
    # Infra-failure handling (errclass): short in-place retries for
    # network/busy before a typed failure, and the opposite-family LLM
    # classifier fallback for noisy failure output. The service guard
    # auto-resumes typed failures at their resume_at; login/unknown
    # always wait for the operator.
    "infra_retry_backoff_s": [10, 30],
    "error_classifier": True,
    # Where the milestone's documents live inside the workspace: worker
    # artifacts (skeleton.md, slices/) and driver-generated ledgers
    # (README.md record, review-log.md, adjudications.md, closures/).
    # {slug} resolves from the run name at init. The parent directory
    # gains a machine-maintained milestone index (README.md marker
    # block). Set to "docs" for the legacy flat layout.
    "docs_dir": "implementation/milestones/{slug}",
    # Extra directory names excluded from workspace snapshots, on top of
    # runners.SNAPSHOT_EXCLUDE_DIRS (runtime dirs + common Python tool
    # caches). Add tool caches your verification suite writes so report-only
    # reviewers are not falsely invalidated. With git
    # enabled the same names are also git-ignored in the workspace repo
    # (gitops.ignore_lines), so cache writes never enter micro-review
    # diffs or gate commits.
    "snapshot_exclude_dirs": [],
}

RETIRED_CONFIG_KEYS = frozenset({
    "max_seal_attempts",
    "seal_concurrent",
    "single_seal_first_attempt",
})
RETIRED_SEAL_WORKER_KIND = "seal_half"


def merge_config(config, override):
    """Merge a user override into a config dict, in place: one level deep —
    dict values update key-wise, everything else replaces. The single
    source of truth for config merge semantics; both the CLI (load_config)
    and the service panel (service.create_run) go through here, so the two
    entry points can never drift."""
    for key, value in override.items():
        if key in RETIRED_CONFIG_KEYS:
            continue
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key].update(value)
        else:
            config[key] = value
    return config


def load_config(path=None):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            user = json.load(fh)
        merge_config(cfg, user)
    return cfg


# ---------------------------------------------------------------------------
# Actions


class Action(object):
    def __init__(self, type_, **params):
        self.type = type_
        self.params = params

    def __repr__(self):
        if self.params:
            inner = ", ".join("%s=%r" % kv for kv in sorted(self.params.items()))
            return "%s(%s)" % (self.type, inner)
        return self.type


A_DRAFT = "draft"
A_VERIFY = "verify"
A_REVIEW_ROUND = "review_round"
A_FIX = "fix_findings"
A_DELTA_REVIEW = "delta_review"
A_SEAL_ATTEMPT = "seal_attempt"
A_BRAINSTORM_WAIT = "brainstorming_wait"
A_DONE = "done"
A_FAILED = "failed"

BRAINSTORMING_POLL_INTERVAL_S = 1.0


def _current_author_unit(state):
    """Keep one admitted direct-author episode current until it terminates."""
    expected_kind = {
        st.UNIT_SKELETON: contracts.KIND_DRAFT_SKELETON,
        st.UNIT_SLICE_DOC: contracts.KIND_DRAFT_SLICE_NOTE,
        st.UNIT_SLICE_IMPL: contracts.KIND_IMPLEMENT,
    }
    active = [
        unit for unit in state.get("units", [])
        if unit.get("status") == st.U_PENDING
        and isinstance(unit.get("active_task"), dict)
        and unit["active_task"].get("kind")
        == expected_kind.get(unit.get("kind"))
    ]
    if len(active) > 1:
        raise st.IllegalTransition("multiple direct-author tasks are active")
    return active[0] if active else st.current_unit(state)


def decide(state):
    """Pure decision function: the single legal next action for a state."""
    if state["failure"] is not None or state["milestone"]["status"] == st.M_FAILED:
        return Action(A_FAILED, reason=(state["failure"] or {}).get("reason"))
    if state["milestone"]["status"] == st.M_CLOSED:
        return Action(A_DONE)
    unit = _current_author_unit(state)
    if unit is None:
        return Action(A_DONE)  # run() closes the milestone
    if unit.get("brainstorming_wait"):
        return Action(A_BRAINSTORM_WAIT, unit=st.unit_key(unit))
    status = unit["status"]
    if status == st.U_PENDING:
        return Action(A_DRAFT, unit=st.unit_key(unit))
    if status in (st.U_PRE_REVIEW_VERIFY, st.U_PRE_SEAL_VERIFY):
        return Action(A_VERIFY, unit=st.unit_key(unit), stage=status)
    if status == st.U_ROUNDS:
        # The stage interpreter chooses the review-rounds loop from the
        # run's governing profile. Phase 2 interprets only
        # family_until_clean — the canonical flow, and the answer for every
        # profile-less run — so this branch is byte-identical to the
        # pre-reform driver for those runs; other loop kinds are rejected
        # loudly until their phase lands.
        loop = interpreter.rounds_loop(state)
        if loop != interpreter.FAMILY_UNTIL_CLEAN:
            raise st.IllegalTransition(
                "rounds loop %r is not interpreted yet (later phase)" % loop
            )
        family = st.current_family(state, unit)
        return Action(A_REVIEW_ROUND, unit=st.unit_key(unit), family=family)
    if status == st.U_FIXING:
        return Action(A_FIX, unit=st.unit_key(unit))
    if status == st.U_DELTA_REVIEW:
        return Action(A_DELTA_REVIEW, unit=st.unit_key(unit))
    if status == st.U_SEALING:
        return Action(A_SEAL_ATTEMPT, unit=st.unit_key(unit))
    raise st.IllegalTransition("no action for unit status %r" % status)


# ---------------------------------------------------------------------------
# Driver


class ConcurrentRunError(RuntimeError):
    """Another driver invocation is active on the same state (the advisory
    lock is held) or advanced it on disk since this driver loaded it. Raised
    BEFORE any side-effectful worker call is made."""


class _StandingLawError(RuntimeError):
    """Internal: a project-bound run's standing law (the policy store or
    the work-area meta family) could not be read or validated for a worker
    call. Routed into a recorded run failure — never a silent skip (a run
    proceeding without its standing safeguards is the incident this
    machinery exists to prevent), never a worker repair (the fault is the
    operator's store, not the worker's output)."""


def _runtime_sidecar_path(state_path, filename):
    return os.path.join(os.path.dirname(os.path.abspath(state_path)), filename)


def read_current_acts_overlay(state_path, strict=False):
    """Read the live per-run override layer without retaining a copy."""
    path = _runtime_sidecar_path(state_path, "acts.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        if strict and os.path.lexists(path):
            raise model_profiles.ModelProfileError(
                "current act overrides are unavailable: %s" % exc
            ) from exc
        return {}
    except (OSError, ValueError) as exc:
        if strict:
            raise model_profiles.ModelProfileError(
                "current act overrides are unreadable: %s" % exc
            ) from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise model_profiles.ModelProfileError(
                "current act overrides must be an object"
            )
        return {}
    if strict:
        normalized = {}
        for act, value in data.items():
            # Empty known entries are meaningful at creation: their presence
            # suppresses the profile and exposes structural defaults.  They
            # still must name a real act; every non-empty entry must satisfy
            # that act's complete authority ceiling before any act dispatches.
            if value in (None, "", {}):
                if act not in model_profiles.PROFILE_ACT_KEYS:
                    model_profiles.validate_act_entry(
                        "current act overrides", act, value
                    )
                normalized[act] = value
                continue
            normalized[act] = model_profiles.validate_act_entry(
                "current act overrides", act, value
            )
        return normalized
    return data


def read_current_model_profile_selection(state_path):
    """Read the current selection sidecar; absence means default@medium."""
    path = _runtime_sidecar_path(state_path, "model_profile.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            value = json.load(fh)
    except FileNotFoundError as exc:
        if os.path.lexists(path):
            raise model_profiles.ModelProfileError(
                "current model-profile selection is unavailable: %s" % exc
            ) from exc
        return None
    except (OSError, ValueError) as exc:
        raise model_profiles.ModelProfileError(
            "current model-profile selection is unreadable: %s" % exc
        ) from exc
    return model_profiles.validate_selection(value)


def _read_current_profile_layers(state_path, model_profiles_home):
    """Read one ephemeral current-state view for one physical dispatch."""
    strict = model_profiles_home is not None
    overlay = read_current_acts_overlay(state_path, strict=strict)
    configuration = None
    if strict:
        selection = read_current_model_profile_selection(state_path)
        _selected, configuration = model_profiles.resolve_selection(
            model_profiles_home, selection
        )
    return strict, overlay, configuration


def _resolve_act_from_layers(
    config,
    strict,
    overlay,
    configuration,
    act,
    origin_family=None,
    default_family=None,
    include_explicit=False,
):
    """Resolve one act from an already-read dispatch-local current view."""
    if not strict:
        acts = dict(config.get("acts") or {})
        for key, value in overlay.items():
            if value:
                acts[key] = value
        policy = acts.get(act)
        policy_has_explicit_authority = True
    elif act in overlay:
        policy = overlay[act]
        if policy in (None, "", {}):
            # Creation-time empties are retained in the live layer so their
            # presence suppresses the profile.  They deliberately expose the
            # structural/family fallback, not the shipped config entry that
            # was restored after creation acts were single-homed.
            policy = None
            policy_has_explicit_authority = False
        else:
            policy = model_profiles.validate_act_entry(
                "current act overrides", act, policy
            )
            policy_has_explicit_authority = True
    elif act in configuration:
        policy = configuration[act]
        policy_has_explicit_authority = True
    else:
        acts = dict(config.get("acts") or {})
        policy = acts.get(act)
        policy_has_explicit_authority = act in acts

    raw_family_policy = policy
    if isinstance(raw_family_policy, dict):
        raw_family_policy = (
            raw_family_policy.get("agent")
            or raw_family_policy.get("family")
            or ""
        ).strip()
    explicit_family_policy = policy_has_explicit_authority and bool(
        raw_family_policy and raw_family_policy != "opposite"
    )

    model = effort = None
    if isinstance(policy, dict):
        model = (policy.get("model") or "").strip() or None
        effort = (policy.get("effort") or "").strip() or None
        policy = (
            policy.get("agent") or policy.get("family") or ""
        ).strip() or None
    families = config["families_order"]
    if not policy:
        family = (
            default_family
            or config.get("fix_family")
            or families[0]
        )
    elif policy == "self":
        family = origin_family or families[0]
    elif policy == "opposite":
        family = next(
            (candidate for candidate in families
             if candidate != (origin_family or families[0])),
            origin_family or families[0],
        )
    else:
        family = policy
    resolved = (family, model, effort)
    if include_explicit:
        return resolved + (explicit_family_policy,)
    return resolved


def resolve_current_acts(
    state_path,
    config,
    model_profiles_home,
    requests,
):
    """Resolve several related acts from one dispatch-local source read.

    ``requests`` contains dictionaries accepted by
    :func:`_resolve_act_from_layers`.  Nothing is retained after the caller's
    dispatch; the grouping only prevents one physical call from combining two
    catalogue generations.
    """
    strict, overlay, configuration = _read_current_profile_layers(
        state_path, model_profiles_home
    )
    return [
        _resolve_act_from_layers(
            config,
            strict,
            overlay,
            configuration,
            **request,
        )
        for request in requests
    ]


def resolve_current_act(
    state_path,
    config,
    model_profiles_home,
    act,
    origin_family=None,
    default_family=None,
    include_explicit=False,
):
    """Resolve one act from the current selection, profile, and overrides.

    This is the one side-effect-free resolution seam used by the milestone
    driver and by each independently supervised Brainstorming dispatch.
    """
    return resolve_current_acts(
        state_path,
        config,
        model_profiles_home,
        [{
            "act": act,
            "origin_family": origin_family,
            "default_family": default_family,
            "include_explicit": include_explicit,
        }],
    )[0]


def staffing_work_area(run_state):
    """The `work_area` handles the run's own session records.

    The run's binding when it has one — project and work area are one
    authority and travel together — always beside the workspace path, which
    every run has. Nothing here invents a handle: this is the same pair the
    service and the Brainstorming adapter already carry.
    """
    block = run_state.get("project") or {}
    handles = {}
    if block.get("project") and block.get("work_area"):
        handles["project"] = block["project"]
        handles["work_area"] = block["work_area"]
    handles["workspace_path"] = os.path.abspath(run_state["workspace"])
    return handles


def open_run_staffing_session(state_path, model_profiles_home, document,
                              rigor, material=None, run_state=None,
                              derived=False):
    """Open the run's ONE staffing session and record its id in run state.

    Both writers come through here — the launch, which is told the document
    and rigor, and the first resume of a run that has none, which derives
    them (amendment A2). The session REFERENCES the document by name and
    never copies it, so an edit to either reaches the next call. A run that
    already carries an id keeps it: this binds once and never rebinds.

    Returns the session id now in force.
    """
    run_state = run_state if run_state is not None else st.load(state_path)
    bound = st.staffing_session(run_state)
    if bound:
        return bound
    config = interpreter.effective_config(run_state)
    body = {
        "work_area": staffing_work_area(run_state),
        "families": list(config["families_order"]),
        "document": document,
        "rigor": rigor,
    }
    if material:
        body["material"] = material
    record = staffing.create_session(model_profiles_home, body)
    st.bind_staffing_session(run_state, record["id"])
    st.append_event(
        run_state,
        "staffing_session_bound",
        staffing_session=record["id"],
        document=body["document"],
        rigor=body["rigor"],
        derived=bool(derived),
    )
    st.save(state_path, run_state)
    return record["id"]


# How many times one review dispatch re-reads its seat to settle the round
# its family wants. Two is the stable-document cost (ask, derive, confirm);
# the third is the margin a save landing between two of those reads needs,
# and stopping there keeps a document saved over and over from holding a
# dispatch open.
_REVIEW_SEAT_SETTLE_READS = 3


def _review_rounds_done(unit, family):
    """*family*'s review rounds already recorded in the current cycle.

    The count the round cap takes, and the count a `review` request carries
    plus one. Two independent boundaries grant a fresh budget: resume
    amnesty forgives rounds from before an operator retry, a new review
    cycle forgives rounds over obsolete candidate bytes — count only rounds
    after whichever boundary is newer.
    """
    budget_start = max(
        int(unit.get("rounds_amnesty") or 0),
        int(unit.get("review_cycle_start") or 0),
    )
    return len([
        r
        for r in unit["rounds"][budget_start:]
        if r["family"] == family and r["kind"] == contracts.KIND_REVIEW_ROUND
    ])


def resolve_current_review_model(state_path, model_profiles_home, run_state=None):
    """The (family, model) the next review round would run on, or None.

    Best-effort projection for read-only rounds-time status, read exactly
    where the dispatch will read it: the run's session, its document's
    `review` seats, and the seat the cycle stands on. It names the family
    as well as the model because the review cycle is those seats and no
    longer the run's configured family order.

    Withheld — None — when nothing can be read, when the cycle stands past
    its last assigned seat, and when the router refuses the role, since in
    none of those cases is there a review round to project. Status and the
    service guard are generic diagnostic paths: a withheld projection never
    hides the run, and nothing here decides a dispatch.
    """
    run_state = run_state or st.load(state_path)
    unit = st.current_unit(run_state)
    if unit is None or unit.get("status") != st.U_ROUNDS:
        return None
    config = interpreter.effective_config(run_state)
    families = list(config.get("families_order") or [])
    session = st.staffing_session(run_state)
    try:
        seats = staffing.session_seats(
            model_profiles_home, session, "review", families=families
        )
        index = int(unit.get("family_index") or 0)
        if index >= len(seats):
            return None

        def answer(round_number):
            return staffing.resolve(
                model_profiles_home,
                session,
                "review",
                index=seats[index],
                round=round_number,
                families=families,
            ).answer

        projected = answer(1)
        round_number = 1 + _review_rounds_done(unit, projected["agent"])
        if round_number > 1:
            projected = answer(round_number)
    except (staffing.StaffingError, OSError):
        return None
    return projected["agent"], projected["model"]


def resolve_current_structural_dispatch(
    state_path, model_profiles_home, family
):
    """Validate current profile state for a structurally staffed call."""
    run_state = st.load(state_path)
    config = interpreter.effective_config(run_state)
    _read_current_profile_layers(state_path, model_profiles_home)
    defaults = (config.get("model_defaults") or {}).get(family) or {}
    return family, defaults.get("model"), defaults.get("effort")


def _resolve_current_brainstorming_profiles(
    state_path, model_profiles_home, include_counterpart
):
    """Read one current generation and derive the requested seats."""
    run_state = st.load(state_path)
    config = interpreter.effective_config(run_state)
    requests = [{"act": "implementer"}]
    if include_counterpart:
        # The counterpart's structural family depends on the lead, so resolve
        # both from one ephemeral catalogue/override read and derive below.
        requests.append({"act": "brainstorming_counterpart"})
    resolved = resolve_current_acts(
        state_path, config, model_profiles_home, requests
    )
    lead_family, lead_model, lead_effort = resolved[0]
    lead_defaults = (config.get("model_defaults") or {}).get(
        lead_family
    ) or {}
    lead = {
        "agent": lead_family,
        "model": lead_model or lead_defaults.get("model"),
        "effort": lead_effort or lead_defaults.get("effort"),
    }
    if not include_counterpart:
        return lead, None

    opposite = next(
        (family for family in config["families_order"]
         if family != lead_family),
        lead_family,
    )
    _ignored_family, model, effort = resolved[1]
    defaults = (config.get("model_defaults") or {}).get(opposite) or {}
    counterpart = {
        "agent": opposite,
        "model": model or defaults.get("model"),
        "effort": effort or lead["effort"],
    }
    return lead, counterpart


def resolve_current_brainstorming_profiles(state_path, model_profiles_home):
    """Project both current Brainstorming seats from one source read."""
    return _resolve_current_brainstorming_profiles(
        state_path, model_profiles_home, True
    )


def resolve_current_brainstorming_profile(
    state_path, model_profiles_home, counterpart=False
):
    """Resolve one Brainstorming seat immediately before its dispatch."""
    lead, contrary = _resolve_current_brainstorming_profiles(
        state_path, model_profiles_home, counterpart
    )
    return contrary if counterpart else lead


class _RoleDispatch(object):
    """One driver-made call's staffing, resolved afresh at every physical
    dispatch.

    Callable, so `runners.call_worker` uses it exactly as it uses any other
    dispatch resolver, and it carries the LAST answer's fallback note beside
    itself so the in-flight marker can say that the default document
    answered. The note travels on the resolver rather than as a fourth
    return value the runner would have to learn about.
    """

    def __init__(self, driver, role, index=1, round=1, material=None,
                 episode_unit=None):
        self._driver = driver
        self.role = role
        self.index = index
        self.round = round
        self.material = material
        self.episode_unit = episode_unit
        self.staffing_fallback = None

    def __call__(self):
        resolution = self._driver._staffing_resolution(
            self.role, self.index, self.round, material=self.material,
            episode_unit=self.episode_unit,
        )
        self.staffing_fallback = resolution.staffing_fallback
        answer = resolution.answer
        return answer["agent"], answer["model"], answer["effort"]


class _ReviewSeatDispatch(_RoleDispatch):
    """A review dispatch whose round — and cap — follow the family it
    resolves.

    The seat is this dispatch's and does not move, but the family behind it
    is a live document read: a save completing between the driver's
    pre-dispatch read and this one changes who runs. Review law is keyed to
    that family — the round a `review` request carries is the count of its
    review rounds in this cycle plus one, and the round cap takes the same
    count — so both are derived HERE, from the family this dispatch
    actually resolves, and neither is carried from the earlier read.
    """

    def __init__(self, driver, unit, index=1, capped=False):
        _RoleDispatch.__init__(self, driver, "review", index=index)
        self._unit = unit
        self._capped = capped

    def __call__(self):
        self.round, resolution = self._driver._settled_review_seat(
            self._unit, self.index
        )
        family = resolution.answer["agent"]
        if self._capped:
            self._driver._enforce_review_round_cap(self._unit, family)
        self.staffing_fallback = resolution.staffing_fallback
        answer = resolution.answer
        return answer["agent"], answer["model"], answer["effort"]


class Driver(object):
    model_profiles_home = None

    def __init__(self, state_path, runner=None, model_profiles_home=None):
        self.state_path = state_path
        self.state = st.load(state_path)
        self.model_profiles_home = (
            os.path.abspath(model_profiles_home)
            if model_profiles_home is not None else None
        )
        # Fail loudly before interpreting any retained strategy pair.
        interpreter.verify_embedded(self.state)
        # Merge strategy dials here and whenever an active-run replacement
        # is applied at a later step boundary. Profile-less and dial-less
        # runs keep the raw config unchanged.
        self.config = interpreter.effective_config(self.state)
        self._validate_billing()
        self.workspace = self.state["workspace"]
        self._busy_lock = threading.RLock()
        self._allow_producer_handoff = False
        self.runner = runner or runners.SubprocessRunner(
            self.config["commands"], self.config.get("timeouts", {}),
            stall_window_s=self.config.get("worker_stall_window_s"),
            stall_min_cpu_s=self.config.get("worker_stall_min_cpu_s"),
            prompt_recorder=self._record_llm_prompt,
        )
        # Account for an interrupted provider before any startup check can
        # append a different state transition and obscure the stale call.
        self._consume_stale_marker()
        if self.model_profiles_home is not None:
            prompt_sets.ensure_default(self.model_profiles_home)
            # Whether the profile catalogue's floor could be read at all.
            # The conversion below is the one thing that must NOT run when
            # it could not: see the two comments that follow.
            profile_floor_readable = True
            try:
                # Startup readiness only: seed absence, never repair or
                # rewrite what the catalogue already holds. Generic crash
                # accounting above must remain independent of this optional
                # catalogue.
                model_profiles.ensure_default(self.model_profiles_home)
            except model_profiles.ModelProfileError:
                # A damaged catalogue no longer stops a HOMED run. This gate
                # was loud because the driver's own calls resolved through a
                # profile; slice 6 moved the last of them — the Brainstorming
                # seats — onto the router, so every seat of a homed run is
                # now staffed by the run's staffing session
                # (`_worker_staffing`, `_staff`, `_dispatch_for_role`,
                # `_brainstorming_staffing`) and every remaining
                # `_act_profile` reader is reached only when there is no
                # catalogue home at all. Failing here would gate a
                # router-backed call — an attached discussion's included —
                # on an input nothing dispatches from, which this slice
                # forbids. The file is left exactly as the operator's bytes
                # are: the catalogue stays an operator surface until slice 8
                # retires it, and the service's own start-up and its profile
                # routes still report a damaged one there.
                profile_floor_readable = False
            if profile_floor_readable:
                try:
                    # Beside the profile seed: a started driver converts what
                    # the profile catalogue holds and seeds the `default`
                    # staffing document. Missing-only, so this is a no-op on
                    # every start after the first; a damaged profile is skipped
                    # inside rather than making start-up louder than today.
                    staffing.ensure_documents(self.model_profiles_home)
                except (staffing.StaffingError, OSError):
                    # And UNLIKE the profile seed in what a failure means
                    # here: a damaged staffing catalogue never stops a run.
                    # The initialization itself stays exactly as loud as it
                    # is — it raises, repairs nothing, and leaves the
                    # operator's own bytes untouched — but every resolution
                    # below has the mandatory fallback that cannot fail (an
                    # unreadable stored `default` answers from the in-code
                    # seed), so the run dispatches on the default document
                    # and the marker's `staffing_fallback` note records what
                    # answered. Failing the run here would be a start-up
                    # validation gate for an unreadable input, which is what
                    # this milestone retires, and it would block a resume
                    # this cut promises never to block.
                    pass
            # Not gating the CALL on a damaged profile is this slice's
            # licence; writing a durable document from that fault is not.
            # `ensure_documents` skips the profile it cannot read and then
            # finds no `default` document to read, so it would seed the
            # in-code `default` OVER a stored `default` profile that exists
            # and is merely unreadable — the seeding-over the skeleton names
            # a conversion defect rather than a compatibility exception, and
            # conversion is missing-only, so repairing the profile afterwards
            # would never convert it. Deferring the whole conversion to a
            # later start costs nothing it does not already promise: it is
            # missing-only and runs at every service and driver start, so it
            # converts once the profile is readable again, and until then the
            # resolver's mandatory fallback answers with the same in-code
            # seed WITH the marker's `staffing_fallback` note — the same
            # reasoning `_derive_staffing_session` gives for refusing to
            # write a once-only binding derived from a fault, silently.
            # A run opened before the cutover has no session; this is the
            # first resume that finds none, so it gets one here — before any
            # dispatch can ask for one, and whether or not the conversion
            # above ran or completed: the session names a document, it does
            # not need one to exist.
            self._derive_staffing_session()
        # Before repo validation: if a pending gap's cleanup never ran (a crash
        # between recording the gap and cleaning up), worker junk such as a
        # nested repo could make ensure_repo reject the workspace and deadlock
        # every resume.
        self._pre_clean_pending_gap()
        if gitops.enabled(self.config):
            try:
                gitops.ensure_repo(
                    self.workspace,
                    extra_ignore_dirs=self.config.get("snapshot_exclude_dirs"),
                )
            except gitops.GitError as exc:
                # A driver that cannot keep its gate ledger must not run.
                # Idempotent across operator retries: an already-recorded
                # failure is not overwritten and the ledger gains no
                # duplicate run_failed events.
                if self.state["failure"] is None:
                    st.fail_run(self.state, "git unavailable: %s" % exc)
                    self._save()
        self._consume_pending_gap()
        self._migrate_active_redoc_wave()
        # A crash between a seal and its _after_seal ensure_next_unit can
        # leave the DUE planned unit without a record; with a mid-table
        # remodel insert, navigation would fall through to a later
        # pre-created record. Materialize it before any navigation — under
        # the run lock with fresh state (a concurrent invocation may be
        # mid-step; mutating beside it would surface as HistoryRewriteError
        # instead of a clean refusal). On contention, skip: the lock holder
        # materializes it.
        if self.state.get("failure") is None:
            try:
                with self._exclusive():
                    self.state = st.load(self.state_path)
                    if self.state.get("failure") is None:
                        closure_recovered = self._consume_pending_closure()
                        materialized = st.ensure_due_unit(self.state) is not None
                        try:
                            # A parked implementation must remain assigned to
                            # a planned slice across operator resume as well as
                            # across the redoc close that first detected the
                            # problem.  Otherwise clearing the failure could
                            # let navigation reach DONE with work still held
                            # only by its durable parking ref.
                            self._guard_unplanned_preserved_candidates()
                        except StopStep:
                            pass  # the guard persisted the typed failure
                        else:
                            closed_now = False
                            final_committed = False
                            if (
                                _current_author_unit(self.state) is None
                                and self.state.get("failure") is None
                            ):
                                was_closed = (
                                    self.state["milestone"]["status"]
                                    == st.M_CLOSED
                                )
                                if st.maybe_close_milestone(self.state):
                                    closed_now = not was_closed
                                    if (
                                        closed_now
                                        or self.state.get(
                                            "pending_final_commit"
                                        )
                                    ):
                                        self._final_commit()
                                        final_committed = True
                            if (
                                materialized
                                or closure_recovered
                                or closed_now
                                or final_committed
                            ):
                                self._save()
            except ConcurrentRunError:
                pass
            except StopStep:
                pass  # closure/final-commit recovery persisted its failure

    # -- helpers ----------------------------------------------------------

    def _save(self):
        st.save(self.state_path, self.state)

    def _state_file_digest(self):
        try:
            with open(self.state_path, "rb") as handle:
                return hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return None

    # -- operator control (safe pause) -------------------------------------
    # control.json lives NEXT to state.json and is written by the service
    # while the driver runs — it must never ride state.json itself, whose
    # single writer is the driver. The driver only READS it (at step
    # boundaries) and clears the one-shot flag after honoring it, so the
    # two processes never contend on the same file for writes.

    def _control_path(self):
        return os.path.join(os.path.dirname(self.state_path), "control.json")

    def _profile_swap_path(self):
        return os.path.join(
            os.path.dirname(self.state_path), "profile_swap.json"
        )

    def _read_profile_swap(self):
        """Read and validate the operator's retained strategy replacement."""
        try:
            with open(self._profile_swap_path(), "r", encoding="utf-8") as fh:
                overlay = json.load(fh)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise profiles.ProfileError(
                "strategy profile change is unreadable: %s" % exc
            )
        if not isinstance(overlay, dict):
            raise profiles.ProfileError(
                "strategy profile change must be an object"
            )
        ref = overlay.get("ref")
        if (
            set(overlay) == {"ref", "at"}
            and isinstance(ref, dict)
            and set(ref) == {"name", "version", "hash"}
            and isinstance(ref.get("name"), str)
            and bool(ref["name"])
            and isinstance(ref.get("version"), int)
            and ref["version"] >= 1
            and isinstance(ref.get("hash"), str)
            and bool(ref["hash"])
            and isinstance(overlay.get("at"), str)
        ):
            # The pre-retention service wrote this identity-only shape but
            # never applied it. It cannot be upgraded from mutable catalogue
            # state without inventing retained content, so it stays inert.
            return None
        profiles.verify_retained(
            ref, overlay.get("profile")
        )
        return overlay

    def _apply_profile_swap(self):
        """Apply one pending replacement before the next action decision.

        The generic event becomes the interpreter's new authority. Leaving
        the overlay in place makes restart recovery idempotent because an
        already-governing identity is a no-op.
        """
        overlay = self._read_profile_swap()
        if overlay is None:
            return False
        prior = interpreter.governing_profile_ref(self.state)
        if overlay["ref"] == prior:
            return False
        st.append_event(
            self.state,
            "profile_changed",
            **{
                "from": copy.deepcopy(prior),
                "to": copy.deepcopy(overlay["ref"]),
                "profile": copy.deepcopy(overlay["profile"]),
            }
        )
        interpreter.verify_embedded(self.state)
        self.config = interpreter.effective_config(self.state)
        return True

    def _control(self):
        try:
            with open(self._control_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _clear_stop_after_seal(self):
        ctl = self._control()
        if not ctl.get("stop_after_seal"):
            return
        ctl.pop("stop_after_seal", None)
        tmp = self._control_path() + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(ctl, fh)
            os.replace(tmp, self._control_path())
        except OSError:
            # Worst case the stale flag pauses the run once more at the
            # next seal — an extra safe stop, never lost work.
            pass

    def _sealed_keys(self):
        return {
            st.unit_key(u) for u in self.state["units"]
            if u["status"] == st.U_SEALED
        }

    def _snapshot(self):
        """(mode, entries) content snapshot for tamper checks.

        With git enabled the tamper universe is what the repository can
        see (tracked + untracked non-ignored): a report-only reviewer
        that runs the project's build/tests is not invalidated by
        .gitignore'd artifact churn (_build, deps, caches). If git cannot
        list, the raw walk is used and the mode says so — _snapshot_diff
        refuses to compare universes of different modes, so a mid-call
        git breakage (e.g. a worker damaging .git) yields one honest
        invalidation instead of a bogus everything-changed file list."""
        paths = None
        walk_skip = None
        ignore_surfaces = None
        mode = "walk"
        if gitops.enabled(self.config):
            try:
                universe = gitops.snapshot_universe(self.workspace)
                paths = universe["paths"]
                walk_skip = universe["walk_skip"]
                ignore_surfaces = universe["ignore_surfaces"]
                mode = "git"
            except gitops.GitError:
                paths = None
        entries = runners.snapshot_workspace(
            self.workspace,
            extra_exclude=self.config.get("snapshot_exclude_dirs"),
            paths=paths,
            walk_skip=walk_skip,
            ignore_surfaces=ignore_surfaces,
        )
        return mode, entries

    def _candidate_fingerprint(self, snapshot=None):
        """Stable digest of every candidate byte visible to tamper checks."""
        mode, entries = snapshot if snapshot is not None else self._snapshot()
        payload = json.dumps(
            [mode, sorted(entries.items())],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "snapshot-sha256:%s" % hashlib.sha256(payload).hexdigest()

    def _verification_candidate_fingerprint(self, snapshot=None):
        """Digest the bytes a full suite is expected to certify.

        Gate-generated ledgers are deterministic projections written after
        unit completion. They are not product bytes covered by the suite, so
        excluding them keeps checkpoint fingerprints honest.
        """
        mode, entries = snapshot if snapshot is not None else self._snapshot()
        generated = set(ledgers.generated_paths(self.state))
        index = ledgers.index_path(self.state)
        # The canonical parent index is mixed ownership: only its marker
        # block is generated, while prose around it belongs to the repo.
        # Hash that prose instead of dropping the whole file.
        if index:
            generated.discard(index)
        closure_root = ledgers.closures_dir(self.state).rstrip("/")
        filtered = {
            path: value
            for path, value in entries.items()
            if path not in generated
            and path != closure_root
        }
        if index and index in filtered:
            filtered[index] = self._verification_index_descriptor(
                index, filtered[index]
            )
        payload = json.dumps(
            [mode, sorted(filtered.items())],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "verification-sha256:%s" % hashlib.sha256(payload).hexdigest()

    def _verification_index_descriptor(self, relpath, snapshot_value):
        """Hash operator-owned bytes around the generated index block.

        If the file is not a regular UTF-8 index with one valid marker pair,
        retain the snapshot's whole-file descriptor. That is conservative:
        malformed or not-yet-managed indexes never gain proof reuse.
        """
        path = os.path.join(self.workspace, relpath)
        if os.path.islink(path) or not os.path.isfile(path):
            return snapshot_value
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            current = "file %s" % hashlib.sha256(raw).hexdigest()
            if current != snapshot_value:
                return snapshot_value
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return snapshot_value
        if (
            text.count(ledgers.INDEX_START) != 1
            or text.count(ledgers.INDEX_END) != 1
            or text.index(ledgers.INDEX_END)
            < text.index(ledgers.INDEX_START)
        ):
            return snapshot_value
        before, rest = text.split(ledgers.INDEX_START, 1)
        _generated, after = rest.split(ledgers.INDEX_END, 1)
        operator_bytes = json.dumps(
            [before, after], ensure_ascii=True, separators=(",", ":")
        ).encode("utf-8")
        return "index-operator-sha256:%s" % hashlib.sha256(
            operator_bytes
        ).hexdigest()

    def _matching_fixer_verification(self, commands, fingerprint):
        """Return a fixer's full-suite success for these exact inputs."""
        commands = list(commands)
        for event in reversed(self.state.get("events") or []):
            if (
                event.get("type") == "verification"
                and event.get("boundary") == "final"
                and event.get("ok") is True
                and event.get("stable") is True
                and event.get("fixer_certified") is True
                and not event.get("vacuous")
                and event.get("commands") == commands
                and event.get("candidate_after") == fingerprint
            ):
                return event
        return None

    def _latest_full_verification_checkpoint(self):
        """Latest full-suite proof whose logical slice actually closed.

        A fixer can certify the suite before its delta and fresh reviews have
        finished.  That proof is reusable only for the exact same bytes; it is
        not a cadence anchor until the owning slice closes.  Requiring an
        explicit cadence also excludes historical implementation baselines.
        """
        closed_after = set()
        for event in reversed(self.state.get("events") or []):
            if event.get("type") == "slice_closed":
                closed_after.add(event.get("unit"))
                continue
            if (
                event.get("type") == "verification"
                and event.get("unit") in closed_after
                and event.get("cadence") in (
                    "four_slice_checkpoint", "milestone_final"
                )
                and event.get("ok") is True
                and event.get("stable") is True
            ):
                return event
        return None

    def _completed_logical_slices_since_full_verification(self):
        """Count completed slices, never their implementation parts."""
        anchor = self._latest_full_verification_checkpoint()
        after_seq = -1 if anchor is None else int(anchor.get("seq") or -1)
        anchor_unit = None if anchor is None else anchor.get("unit")
        by_key = {
            st.unit_key(candidate): candidate
            for candidate in self.state.get("units") or []
        }
        completed = set()
        for event in self.state.get("events") or []:
            if (
                event.get("type") != "slice_closed"
                or int(event.get("seq") or -1) <= after_seq
                or event.get("unit") == anchor_unit
            ):
                continue
            closed = by_key.get(event.get("unit"))
            if (
                closed is None
                or closed.get("kind") != st.UNIT_SLICE_IMPL
                or closed.get("implementation_cut")
            ):
                continue
            completed.add(closed.get("slice_id"))
        return len(completed)

    def _full_verification_cadence(self, unit):
        """Return the only two ordinary reasons to run the complete suite."""
        if (
            unit.get("kind") != st.UNIT_SLICE_IMPL
            or unit.get("implementation_cut")
        ):
            return None
        plan = st.planned_execution_units(self.state)
        milestone_final = bool(
            plan and st.unit_identity(unit) == plan[-1]
        )
        if milestone_final:
            return "milestone_final"
        completed = self._completed_logical_slices_since_full_verification()
        if completed + 1 >= FULL_VERIFICATION_SLICE_INTERVAL:
            return "four_slice_checkpoint"
        return None

    def _review_evidence_inputs(self, unit):
        """Return immutable review evidence plus this episode's hot rules.

        Hot operator amendments and safeguards govern the next Worker episode,
        but a later change to them does not make an already validated review
        result stale.  Reading is side-effect free: no ``*_seen`` event may
        imply that a reviewer saw the snapshot before dispatch actually runs.
        """
        snapshot = self._snapshot()
        authority = self._worker_episode_authority(
            unit, contracts.KIND_REVIEW_ROUND
        )
        project_context = authority["project_context"]
        extensions = authority["extensions"]
        roots = authority["roots"]
        amendments = authority["amendments"]
        fingerprint = self._review_evidence_fingerprint(
            unit, snapshot=snapshot
        )
        return (
            fingerprint,
            project_context,
            extensions,
            roots,
            amendments,
            authority["operator_complete"],
        )

    def _review_evidence_fingerprint(self, unit, snapshot=None):
        """Bind approvals to immutable review inputs, not episode authority."""
        if snapshot is None:
            snapshot = self._snapshot()
        payload = json.dumps(
            {
                "candidate": self._candidate_fingerprint(snapshot),
                "implementation_scope": self._implementation_scope(unit),
                # Bind approvals to the exact execution plan, including
                # command boundaries. Joining with ``&&`` is only a prompt
                # rendering: separate list items run in separate shells and
                # therefore are not equivalent to one joined command.
                "suite_commands": self._verification_commands(unit),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return "review-evidence-sha256:%s" % hashlib.sha256(
            payload
        ).hexdigest()

    @staticmethod
    def _snapshot_diff(before, after):
        """Changed paths between two _snapshot() results; a mode mismatch
        is itself evidence (the git universe appeared/vanished mid-call)."""
        before_mode, before_entries = before
        after_mode, after_entries = after
        if before_mode != after_mode:
            return [
                "(tamper universe changed mid-call: %s -> %s snapshot)"
                % (before_mode, after_mode)
            ]
        return runners.snapshot_changes(before_entries, after_entries)

    @contextlib.contextmanager
    def _exclusive(self, adopt_producer_handoff=None):
        """Advisory inter-process lock on <state>.lock for one step. Two
        concurrent invocations on the same state would each run
        side-effectful worker calls; without this, the divergence would be
        detected only afterwards, at save time, as HistoryRewriteError.

        A continuous driver may briefly lose the between-step handoff to a
        prospective slice write.  It retries only long enough for that local
        write to finish and proceeds only if the resulting state is unchanged
        or exactly an adoptable slice-write delta.  Direct steps and every
        unrelated durable change retain the ordinary non-blocking refusal."""
        if adopt_producer_handoff is None:
            adopt_producer_handoff = self._allow_producer_handoff

        def collision_error():
            return ConcurrentRunError(
                "another orchestrator invocation is active on %s "
                "(advisory lock %s is held)"
                % (self.state_path, self.state_path + ".lock")
            )

        collision = None
        deadline = None
        lock = None
        while lock is None:
            candidate = contextlib.ExitStack()
            try:
                candidate.enter_context(st.exclusive_mutation(self.state_path))
            except st.ConcurrentStateMutation as exc:
                candidate.close()
                if not adopt_producer_handoff:
                    raise collision_error() from exc
                if collision is None:
                    collision = collision_error()
                    deadline = time.monotonic() + PRODUCER_HANDOFF_GRACE_S
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise collision from exc
                time.sleep(min(PRODUCER_HANDOFF_POLL_S, remaining))
            else:
                lock = candidate

        try:
            if collision is not None:
                disk = st.load(self.state_path)
                if disk != self.state and not self._adopt_live_producer_updates(
                    disk
                ):
                    raise collision
            yield
        finally:
            lock.close()

    def _assert_not_stale(self):
        """Adopt authorized prospective slice writes; refuse every other stale
        state."""
        if not os.path.exists(self.state_path):
            return
        disk = st.load(self.state_path)
        if disk.get("events") != self.state.get("events"):
            if self._adopt_live_producer_updates(disk):
                return
            raise ConcurrentRunError(
                "state file %s changed on disk since this driver loaded it "
                "(another invocation ran); start a new driver to continue"
                % self.state_path
            )

    def _adopt_live_producer_updates(self, disk):
        """Refresh only when disk is exactly this state plus prospective
        slice writes: a producer choice, or a slice material. Both come
        through the same route family and the same exclusive mutation, so a
        loaded driver adopts either one rather than refusing the run over a
        write it authorized itself."""
        current_events = self.state.get("events")
        disk_events = disk.get("events")
        if not isinstance(current_events, list) or not isinstance(
            disk_events, list
        ):
            return False
        if (
            len(disk_events) <= len(current_events)
            or disk_events[:len(current_events)] != current_events
        ):
            return False
        candidate = copy.deepcopy(self.state)
        for index, event in enumerate(
            disk_events[len(current_events):], start=len(current_events)
        ):
            if not isinstance(event, dict) or event.get("seq") != index:
                return False
            if not self._replay_prospective_slice_write(candidate, event):
                return False
            candidate["events"][-1] = copy.deepcopy(event)
        if candidate != disk:
            return False
        self.state = disk
        return True

    @staticmethod
    def _replay_prospective_slice_write(candidate, event):
        """Apply one recorded prospective slice write to *candidate* state.

        Replayed through the very writers the route used, so an event this
        driver cannot reproduce exactly is refused rather than guessed at;
        the caller then keeps the ordinary stale-state refusal."""
        kind = event.get("type")
        try:
            if kind == "slice_producer_updated":
                selection = event.get("selection")
                if not isinstance(selection, dict):
                    return False
                checked = tasks.validate_producer_selection(
                    selection, "live producer update"
                )
                tasks.update_slice_producer(
                    candidate,
                    event.get("slice_id"),
                    {
                        "task_kind": event.get("task_kind"),
                        **checked,
                    },
                )
            elif kind == "slice_material_updated":
                # A cleared material is recorded as an explicit null, so the
                # key must be PRESENT: an event missing it is not a write
                # this driver can replay.
                if "material" not in event:
                    return False
                tasks.update_slice_material(
                    candidate,
                    event.get("slice_id"),
                    {"material": event["material"]},
                )
            else:
                return False
        except tasks.TaskRequestError:
            return False
        return True

    def _fix_family(self):
        return self.config.get("fix_family") or self.config["families_order"][0]

    def _opposite(self, family):
        for fam in self.config["families_order"]:
            if fam != family:
                return fam
        return family

    def _opposite_cmd(self, family):
        return self.config["commands"].get(self._opposite(family), [])

    def _consultation_command(self, family, caller_effort):
        """The consulted family's command line, ready to run.

        The fixer runs this line VERBATIM, so the template must arrive
        resolved: an unsubstituted {model}/{effort} would reach the CLI
        as a literal brace-string. Homed, the line resolves the `consult 1`
        seat through the run's session AT THE MOMENT the fixer runs it, so a
        session or document edit reaches the consultation like every other
        call and nothing is derived from the caller. Without a home there is
        no session to read: the model comes from the consulted family's
        defaults and the effort is the CALLER'S, so a rejection is never
        argued by a lighter opponent than the one rejecting.
        """
        if self.model_profiles_home is not None:
            return [
                sys.executable,
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "current_model_call.py",
                ),
                "--state",
                os.path.abspath(self.state_path),
                "--home",
                os.path.abspath(self.model_profiles_home),
            ]
        template = self.config["commands"].get(family) or []
        if not template:
            return []
        model, family_effort = self._family_defaults(family)
        return runners.apply_model_effort(
            template, model, caller_effort or family_effort
        )

    def _runtime_dir(self):
        # All runtime bookkeeping lives beside the state file: for a
        # per-milestone run that is <milestone>/.run/, for a legacy run
        # <workspace>/.orchestrator/. Deriving from the state path keeps
        # both layouts working with identical code.
        return os.path.dirname(self.state_path)

    def _raw_dir(self):
        path = os.path.join(self._runtime_dir(), "raw")
        os.makedirs(path, exist_ok=True)
        return path

    def _prompt_dir(self):
        path = os.path.join(self._runtime_dir(), "prompts")
        os.makedirs(path, exist_ok=True)
        return path

    def _record_llm_prompt(self, family, prompt):
        """Persist one exact physical worker prompt outside the Git ledger."""
        label = None
        try:
            with open(self._busy_path(), "r", encoding="utf-8") as handle:
                current = json.load(handle)
            if isinstance(current, dict):
                label = current.get("label")
        except (OSError, ValueError, TypeError):
            pass
        return runners.save_prompt_trace(
            self._prompt_dir(), family, prompt, label=label
        )

    def _save_raw(self, name, text):
        path = os.path.join(self._raw_dir(), name + ".txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        return os.path.relpath(path, self.workspace)

    def _save_raw_noclobber(self, name, text):
        """Like _save_raw but never overwrites an existing file, appending
        -2, -3 ... instead. Used whenever a failed or non-completing call can
        legitimately reuse its label, including malformed strikes and reviews
        that leave no round record. Distinct per-family names keep concurrent
        calls from racing; this guards only across-resume reuse."""
        raw_dir = self._raw_dir()
        candidate = name
        n = 1
        while os.path.exists(os.path.join(raw_dir, candidate + ".txt")):
            n += 1
            candidate = "%s-%d" % (name, n)
        return self._save_raw(candidate, text)

    def _unit_desc(self, unit):
        if unit["kind"] == st.UNIT_SKELETON:
            return "the milestone skeleton"
        title = ""
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == unit["slice_id"]:
                title = sl["title"]
                break  # ids are unique (contract) and first match wins,
                       # consistent with _slice_info
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return "the slice %d note (%s)" % (unit["slice_id"], title)
        part = st.implementation_part(unit)
        token = "%d%s" % (
            unit["slice_id"], "-%s" % part if part else ""
        )
        return "the slice %s implementation (%s)" % (token, title)

    def _implementation_scope(self, unit):
        return st.implementation_scope(self.state, unit)

    def _author_prompt_home(self):
        """The configured prompt store, or a seed-only local read root."""
        return self.model_profiles_home or os.path.dirname(self.state_path)

    def _author_material(self, unit, kind, task=None):
        if kind == contracts.KIND_DRAFT_SKELETON:
            return "document"
        material = (
            tasks.order_staffing_material(task["order"])
            if task is not None
            else self._worker_staffing_material(unit, kind)
        )
        if material:
            return material
        return (
            "document"
            if kind == contracts.KIND_DRAFT_SLICE_NOTE else "code"
        )

    def _author_coordinates(self, unit, kind, task=None):
        """Freeze or recover the slice coordinates of one author episode."""
        if kind == contracts.KIND_DRAFT_SKELETON:
            return None
        if task is None:
            slice_info = self._slice_info(unit["slice_id"])
            return {
                "slice_id": slice_info["id"],
                "slice_title": slice_info["title"],
                "slice_note_path": self._slice_note_artifact(
                    unit["slice_id"]
                ),
            }
        context = ((task.get("order") or {}).get("request") or {}).get(
            "context"
        ) or {}
        coordinates = context.get("author_coordinates")
        if (
            not isinstance(coordinates, dict)
            or set(coordinates) != {
                "slice_id", "slice_title", "slice_note_path"
            }
            or type(coordinates.get("slice_id")) is not int
            or coordinates.get("slice_id") != unit.get("slice_id")
            or not isinstance(coordinates.get("slice_title"), str)
            or not coordinates["slice_title"].strip()
            or coordinates.get("slice_note_path")
            != self._slice_note_artifact(unit["slice_id"])
        ):
            detail = (
                "active author task has invalid frozen slice coordinates"
            )
            st.fail_run(
                self.state, detail, unit=unit, type_="orchestrator"
            )
            self._save()
            raise StopStep(detail)
        return copy.deepcopy(coordinates)

    def _author_values(
        self, unit, kind, authority, recovery=None, meter=None,
        author_coordinates=None,
    ):
        self._ensure_goal_ledger()
        skeleton_path = self._skeleton_artifact()
        values = {
            "kind": kind,
            "workspace": self.workspace,
            "goal_path": ledgers.goal_path(self.state),
            "skeleton_path": skeleton_path,
        }
        if kind == contracts.KIND_DRAFT_SKELETON:
            catalogue = [
                {"id": item["id"], "description": item["description"]}
                for item in tasks.task_executor_catalogue()
            ]
            values["task_executor_catalogue"] = json.dumps(
                catalogue, ensure_ascii=False, sort_keys=True, indent=2
            )
        else:
            coordinates = (
                author_coordinates
                if author_coordinates is not None
                else self._author_coordinates(unit, kind)
            )
            values.update({
                "slice_id": str(coordinates["slice_id"]),
                "slice_title": coordinates["slice_title"],
                "slice_note_path": coordinates["slice_note_path"],
            })
        amendments = prompts._amendments_block(
            authority.get("amendments") or []
        ).strip()
        if amendments:
            values["operator_amendments"] = amendments
        if kind == contracts.KIND_IMPLEMENT:
            scope = self._implementation_scope(unit)
            if scope is not None:
                values["implementation_scope"] = scope
            if meter is not None:
                values["soft_lines"] = str(meter["soft_lines"])
                values["hard_lines"] = str(meter["hard_lines"])
        if recovery:
            values["author_recovery"] = recovery
        return values

    def _prepare_author_package(
        self, unit, kind, material, authority, recovery=None, meter=None,
        author_coordinates=None,
    ):
        job = {
            contracts.KIND_DRAFT_SKELETON: "draft_skeleton@skeleton",
            contracts.KIND_DRAFT_SLICE_NOTE: "draft_slice_note@slice_doc",
            contracts.KIND_IMPLEMENT: "implement@slice_impl",
        }[kind]
        return author_calls.prepare(
            self._author_prompt_home(),
            job=job,
            material=material,
            values=self._author_values(
                unit,
                kind,
                authority,
                recovery=recovery,
                meter=meter,
                author_coordinates=author_coordinates,
            ),
            prompt_set=self.state.get(
                st.PROMPT_SET_KEY, prompt_sets.DEFAULT_SET_NAME
            ),
            project_context=authority.get("project_context"),
            workspace=self.workspace,
        )

    def _author_prepare_call(
        self, unit, kind, material, raw_name, recovery=None, meter=None,
        author_coordinates=None,
    ):
        """Build the fresh routed package and proportional plan boundary."""
        skeleton_path = self._skeleton_artifact()

        def prepare(repair_error):
            authority = self._worker_episode_authority(unit, kind)
            self._activate_worker_episode_authority(authority)
            call_recovery = recovery
            if repair_error is not None:
                correction = (
                    "CONTRACT CORRECTION\n"
                    "The previous reply was rejected: %s\n"
                    "Return a fresh reply satisfying this routed contract."
                    % repair_error
                )
                call_recovery = (
                    "%s\n\n%s" % (call_recovery, correction)
                    if call_recovery else correction
                )
            prepared = self._prepare_author_package(
                unit,
                kind,
                material,
                authority,
                recovery=call_recovery,
                meter=meter,
                author_coordinates=author_coordinates,
            )
            snapshot = canonical_plan.begin_author_call(
                self.state,
                skeleton_path,
                allow_unanchored=(
                    kind == contracts.KIND_DRAFT_SKELETON
                    and self.state["milestone"].get(
                        canonical_plan.ANCHOR_KEY
                    ) is None
                ),
            )

            def complete():
                plan_result = canonical_plan.complete_author_call(
                    self.state,
                    snapshot,
                    message="canonical plan after %s" % kind,
                )
                if plan_result["changed"]:
                    if st.unit_identity(unit) in st.planned_execution_units(
                        self.state
                    ):
                        unit.pop(st.AUTHOR_PLAN_REVIEW_KEY, None)
                    else:
                        unit[st.AUTHOR_PLAN_REVIEW_KEY] = True
                    st.ensure_due_unit(self.state)
                self._enforce_sealed_artifacts(
                    raw_name,
                    editable_sealed=self._editable_design_paths(unit),
                    preserve_canonical_plan=True,
                )
                self._save()

            return prepared._replace(complete=complete)

        return prepare

    def _ensure_author_plan(self, unit, kind):
        """Adopt the plan and report when it changes the selected unit."""
        if (
            kind == contracts.KIND_DRAFT_SKELETON
            or self.state["milestone"].get(canonical_plan.ANCHOR_KEY)
            is not None
        ):
            return False
        try:
            canonical_plan.establish_current_plan(
                self.state, self._skeleton_artifact()
            )
            st.ensure_due_unit(self.state)
            self._save()
        except (canonical_plan.CanonicalPlanError, gitops.GitError) as exc:
            st.fail_run(
                self.state,
                "canonical plan could not be established: %s" % exc,
                unit=unit,
                type_="orchestrator",
            )
            self._save()
            raise StopStep(str(exc))
        return st.current_unit(self.state) is not unit

    def _implementation_size_settings(self):
        configured = self.config.get("implementation_size_control")
        if configured is None:
            configured = DEFAULT_CONFIG["implementation_size_control"]
        if not isinstance(configured, dict):
            return None
        try:
            settings = {
                "soft_lines": int(configured.get("soft_lines", 500)),
                "hard_lines": int(configured.get("hard_lines", 750)),
                "poll_interval_s": float(
                    configured.get("poll_interval_s", 2)
                ),
                "unconfirmed_grace_s": float(
                    configured.get("unconfirmed_grace_s", 180)
                ),
                "confirmed_grace_s": float(
                    configured.get("confirmed_grace_s", 600)
                ),
            }
        except (TypeError, ValueError):
            return None
        if (
            settings["soft_lines"] <= 0
            or settings["hard_lines"] <= settings["soft_lines"]
            or not all(
                math.isfinite(value) and value > 0
                for value in (
                    settings["poll_interval_s"],
                    settings["unconfirmed_grace_s"],
                    settings["confirmed_grace_s"],
                )
            )
        ):
            return None
        return settings

    def _implementation_size_control(self, base_tree, task_id=None, unit=None):
        """Live Git budget monitor for one implementation call.

        The observer never mutates Git. It asks once for a coherent cut at the
        soft boundary. A hard stop follows when the worker remains beyond the
        hard boundary after that request; accepting that stop durably records
        stabilization. Stabilizers never use this monitor: once recovery
        starts, they must close coherently without another size interruption.
        """
        if not base_tree or not gitops.enabled(self.config):
            return None, None
        unit = unit if unit is not None else st.current_unit(self.state)
        settings = self._implementation_size_settings()
        if settings is None:
            return None, None
        soft = settings["soft_lines"]
        hard = settings["hard_lines"]
        poll = settings["poll_interval_s"]
        unconfirmed_grace = settings["unconfirmed_grace_s"]
        confirmed_grace = settings["confirmed_grace_s"]
        marker = {
            "episode_id": uuid.uuid4().hex,
            "soft_lines": soft,
            "hard_lines": hard,
            "unconfirmed_grace_s": unconfirmed_grace,
            "confirmed_grace_s": confirmed_grace,
            "steer_attempted": False,
            "steer_delivered": False,
            "steer_confirmed": False,
            "steer_lines": None,
            "hard_crossed_lines": None,
            "grace_kind": None,
            "interrupt_lines": None,
            "last_lines": 0,
        }
        steer_text = (
            "CONTROLLED SIZE CUTOFF: before any further tool call or edit, "
            "send one standalone commentary line containing exactly "
            "%s. Then stop expanding the slice and bring the "
            "current changes to one coherent, functional and reviewable cut; "
            "run only focused checks needed for that cut. Do not implement "
            "the remaining obligations in this turn. If obligations remain, "
            "return implementation_cut with concise non-empty cut_scope and "
            "remaining_scope. If the complete original slice is already "
            "finished, omit implementation_cut and return the normal result."
            % IMPLEMENTATION_SIZE_ACK
        )

        def observe(control):
            call_steered = False
            hard_crossed_at = None
            grace_deadline = None
            while not control.closed:
                if hard_crossed_at is not None:
                    confirmed_at = control.model_confirmation_at
                    if confirmed_at is not None \
                            and marker["grace_kind"] != "confirmed":
                        # The exact model-authored token is stronger delivery
                        # evidence than a missing/timed-out steer RPC reply.
                        marker["steer_delivered"] = True
                        marker["steer_confirmed"] = True
                        marker["grace_kind"] = "confirmed"
                        grace_deadline = confirmed_at + confirmed_grace
                    now = time.monotonic()
                    if now >= grace_deadline:
                        marker["interrupt_lines"] = marker["last_lines"]
                        accepted = control.interrupt(
                            "implementation exceeded the controlled size "
                            "cutoff and did not close within %g seconds "
                            "(%s model confirmation)"
                            % (
                                marker[
                                    "confirmed_grace_s"
                                    if marker["grace_kind"] == "confirmed"
                                    else "unconfirmed_grace_s"
                                ],
                                "with" if marker["grace_kind"] == "confirmed"
                                else "without",
                            )
                        )
                        if accepted:
                            return
                        # Write-ahead persistence or transport delivery may
                        # fail transiently. Keep watching and retry instead of
                        # silently leaving an oversized live worker unbounded.
                        if control.wait_closed(poll):
                            return
                        continue
                    if control.wait_closed(
                        min(poll, max(0.001, grace_deadline - now))
                    ):
                        return
                    continue
                try:
                    lines = gitops.reviewable_line_count(
                        self.workspace,
                        base_tree,
                        bookkeeping_dir=self._runtime_dir(),
                    )
                except gitops.GitError:
                    # A checkout race while files are being replaced is not a
                    # reason to kill useful work.  The next poll tries again.
                    if control.wait_closed(poll):
                        return
                    continue
                observed_at = time.monotonic()
                marker["last_lines"] = lines
                if not call_steered and lines >= soft:
                    call_steered = True
                    marker["steer_attempted"] = True
                    marker["steer_lines"] = lines
                    control.expect_model_confirmation(
                        IMPLEMENTATION_SIZE_ACK
                    )
                    delivered = bool(control.steer(steer_text))
                    marker["steer_delivered"] = bool(
                        marker["steer_delivered"] or delivered
                    )
                confirmed_at = control.model_confirmation_at
                if confirmed_at is not None:
                    # Codex may consume the steer and answer it after the
                    # app-server RPC acknowledgement has timed out.
                    marker["steer_delivered"] = True
                    marker["steer_confirmed"] = True
                if call_steered and lines > hard:
                    hard_crossed_at = observed_at
                    marker["hard_crossed_lines"] = lines
                    if confirmed_at is not None:
                        marker["grace_kind"] = "confirmed"
                        grace_deadline = (
                            hard_crossed_at + confirmed_grace
                            if confirmed_at <= hard_crossed_at
                            else confirmed_at + confirmed_grace
                        )
                    else:
                        marker["grace_kind"] = "unconfirmed"
                        grace_deadline = hard_crossed_at + unconfirmed_grace
                if control.wait_closed(poll):
                    return

        return runners.ActiveCallControl(
            observer=observe,
            on_interrupt=lambda reason: (
                self._persist_implementation_stabilization(
                    marker, interrupt_reason=reason, task_id=task_id,
                    unit=unit,
                )
            ),
            on_interrupt_rejected=lambda _reason: (
                self._clear_rejected_implementation_stabilization(
                    marker, unit=unit
                )
            ),
        ), marker

    def _persist_implementation_stabilization(
        self, marker, interrupt_reason=None, task_id=None, unit=None
    ):
        """Durably cross the cutoff boundary before exposing interruption."""
        unit = unit if unit is not None else st.current_unit(self.state)
        created = unit.get("implementation_stabilization") is None
        if created:
            durable_marker = copy.deepcopy(marker)
            call = self._matching_busy_call(kind=contracts.KIND_IMPLEMENT)
            for key in ("family", "model", "effort", "task_id"):
                if key in call:
                    durable_marker[key] = copy.deepcopy(call[key])
            durable_marker.update(self._task_id_fields(task_id))
            if interrupt_reason:
                durable_marker["interrupt_reason"] = interrupt_reason
            unit["implementation_stabilization"] = {
                "implementation_size": durable_marker,
            }
        try:
            self._save()
        except Exception:
            if created:
                unit.pop("implementation_stabilization", None)
            raise

    def _clear_rejected_implementation_stabilization(self, marker, unit=None):
        """Clear this episode's write-ahead marker after transport refusal."""
        unit = unit if unit is not None else st.current_unit(self.state)
        pending = unit.get("implementation_stabilization")
        durable = (
            pending.get("implementation_size")
            if isinstance(pending, dict) else None
        )
        if not isinstance(durable, dict) or durable.get("episode_id") \
                != marker.get("episode_id"):
            return
        removed = unit.pop("implementation_stabilization")
        try:
            self._save()
        except Exception:
            unit["implementation_stabilization"] = removed
            raise

    def _ensure_implementation_stabilization_events(self, unit, marker):
        """Repair a crash gap between an accepted stop and runner return."""
        unit_key = st.unit_key(unit)
        episode_id = marker.get("episode_id")

        def already_recorded(event_type, fields):
            candidates = (
                event for event in self.state.get("events", [])
                if event.get("unit") == unit_key
                and event.get("type") == event_type
            )
            if episode_id:
                return any(
                    event.get("episode_id") == episode_id
                    for event in candidates
                )
            # Legacy markers cannot name their episode. Match only an
            # untagged event with the same observable cutoff evidence.
            return any(
                event.get("episode_id") is None
                and all(event.get(key) == value
                        for key, value in fields.items())
                for event in candidates
            )

        steer_fields = {
            "lines": marker.get("steer_lines"),
            "delivered": marker.get("steer_delivered"),
            "confirmed": marker.get("steer_confirmed"),
            "grace_kind": marker.get("grace_kind"),
            "soft_lines": marker.get("soft_lines"),
            "hard_lines": marker.get("hard_lines"),
        }
        interrupt_fields = {
            "lines": marker.get("interrupt_lines"),
            "reason": (
                marker.get("interrupt_reason")
                or "implementation size cutoff accepted before restart"
            ),
            "confirmed": marker.get("steer_confirmed"),
            "grace_kind": marker.get("grace_kind"),
            "hard_crossed_lines": marker.get("hard_crossed_lines"),
        }
        call_fields = {
            key: copy.deepcopy(marker[key])
            for key in ("family", "model", "effort", "task_id")
            if key in marker
        }
        added = False
        if (
            marker.get("steer_attempted")
            and not already_recorded(
                "implementation_size_steer", steer_fields
            )
        ):
            st.append_event(
                self.state,
                "implementation_size_steer",
                unit=unit_key,
                episode_id=episode_id,
                **steer_fields,
            )
            added = True
        if (
            marker.get("interrupt_lines") is not None
            and not already_recorded(
                "implementation_size_interrupted", interrupt_fields
            )
        ):
            st.append_event(
                self.state,
                "implementation_size_interrupted",
                unit=unit_key,
                episode_id=episode_id,
                duration_s=None,
                token_usage_partial=True,
                # Without this the mere existence of this synthesized event
                # stops state.py force-marking the unit, and the killed
                # implementer's spend disappears with no floor marker.
                cost_partial=True,
                raw_path=None,
                **call_fields,
                **interrupt_fields,
            )
            added = True
        if added:
            self._save()

    @staticmethod
    def _implementation_stabilizer_context():
        return (
            "FORCED CONTROLLED-CUTOFF RECOVERY\n"
            "A previous implementer was stopped after continuing beyond the "
            "size limit. Its uncommitted workspace changes are intentionally "
            "present. Inspect and preserve sound work. Close the work already "
            "in progress as one coherent, functional delivery and run focused "
            "checks only. Do not continue into the full remaining slice, but "
            "also do not compress, rewrite, discard, or reimplement sound work "
            "merely to meet a line count. No further size cutoff applies to "
            "this stabilization. If the "
            "original slice still has obligations, return implementation_cut "
            "with concise non-empty cut_scope and remaining_scope; otherwise "
            "omit it. Return the ordinary implement envelope.\n"
        )

    @classmethod
    def _implementation_stabilizer_prompt(cls, prompt, marker):
        """Retained for the not-yet-routed Brainstorming return path."""
        del marker
        return (
            prompt.replace(prompts.IMPLEMENTATION_SIZE_GUIDANCE, "")
            + "\n\n"
            + cls._implementation_stabilizer_context()
        )

    def _implementation_line_count(self, base_tree):
        for attempt in range(3):
            try:
                return gitops.reviewable_line_count(
                    self.workspace,
                    base_tree,
                    bookkeeping_dir=self._runtime_dir(),
                )
            except gitops.GitError:
                if attempt < 2:
                    time.sleep(0.05)
        return None

    def _fail_implementation_size(self, lines, hard, reason, family=None,
                                  result=None, unit=None):
        unit = unit if unit is not None else st.current_unit(self.state)
        detail = (
            "%s; the current implementation delta is %s reviewable Git "
            "lines and must be at most %d"
            % (reason, "unknown" if lines is None else lines, hard)
        )
        if result is not None:
            self._record_worker_unaccepted(
                unit, contracts.KIND_IMPLEMENT,
                family, result, detail,
            )
        st.fail_run(
            self.state,
            detail,
            unit=unit,
            type_="worker_protocol",
        )
        self._save()
        raise StopStep("implementation size cutoff recovery failed")

    def _call_implementation(
        self, family, prompt, raw_name, model, effort, extensions, roots,
        validate_opts, start_session, base_tree, session_ref=None,
        stabilizing=False, dispatch_resolver=None,
        continuation_family=None, task_id=None, episode_refresher=None,
        prepare_author=None, author_recovery=None, episode_unit=None,
    ):
        episode_unit = (
            episode_unit
            if episode_unit is not None else st.current_unit(self.state)
        )
        if task_id is None and stabilizing:
            pending = (
                (episode_unit or {}).get("implementation_stabilization") or {}
            ).get("implementation_size") or {}
            task_id = pending.get("task_id")
        if stabilizing:
            output, result, raw_path = self._call(
                family,
                prompt,
                contracts.KIND_IMPLEMENT,
                raw_name,
                model=model,
                effort=effort,
                extensions=extensions,
                roots=roots,
                validate_opts=validate_opts,
                start_session=start_session,
                session_ref=session_ref,
                active_control=None,
                repeat_protocol=True,
                dispatch_resolver=dispatch_resolver,
                continuation_family=continuation_family,
                task_id=task_id,
                episode_unit=episode_unit,
                prepare_call=(
                    prepare_author(
                        self._implementation_stabilizer_context(), None
                    )
                    if prepare_author is not None else None
                ),
            )
            return output, result, raw_path, None, True
        control, marker = self._implementation_size_control(
            base_tree, task_id=task_id, unit=episode_unit
        )
        if marker is None and gitops.enabled(self.config):
            st.fail_run(
                self.state,
                "implementation size control is unavailable: the fixed Git "
                "baseline is missing or implementation_size_control is "
                "invalid",
                unit=episode_unit,
                type_="orchestrator",
            )
            self._save()
            raise StopStep("implementation size control unavailable")
        output, result, raw_path = self._call(
            family,
            prompt,
            contracts.KIND_IMPLEMENT,
            raw_name,
            model=model,
            effort=effort,
            extensions=extensions,
            roots=roots,
            validate_opts=validate_opts,
            start_session=start_session,
            session_ref=session_ref,
            active_control=control,
            dispatch_resolver=dispatch_resolver,
            continuation_family=continuation_family,
            task_id=task_id,
            episode_unit=episode_unit,
            cutoff_marker=marker,
            prepare_call=(
                prepare_author(author_recovery, marker)
                if prepare_author is not None else None
            ),
        )
        if marker is None:
            return output, result, raw_path, None, False
        # The exact ACK may arrive immediately before provider completion;
        # consolidate it even if closing the control woke the observer before
        # its next polling iteration.
        if control.model_confirmation_at is not None:
            marker["steer_delivered"] = True
            marker["steer_confirmed"] = True
        if marker.get("steer_attempted"):
            st.append_event(
                self.state,
                "implementation_size_steer",
                unit=st.unit_key(episode_unit),
                episode_id=marker.get("episode_id"),
                lines=marker.get("steer_lines"),
                delivered=marker.get("steer_delivered"),
                confirmed=marker.get("steer_confirmed"),
                grace_kind=marker.get("grace_kind"),
                soft_lines=marker.get("soft_lines"),
                hard_lines=marker.get("hard_lines"),
            )
        interrupted = isinstance(result, runners.ControlledInterruptionResult)
        final_lines = self._implementation_line_count(base_tree)
        if final_lines is not None:
            marker["last_lines"] = final_lines
        if (
            not interrupted
            and output is not None
            and output.get("status") == "ok"
            and not control.interrupted
            and marker.get("interrupt_lines") is not None
            and final_lines is not None
            and final_lines > marker["hard_lines"]
        ):
            self._fail_implementation_size(
                final_lines,
                marker["hard_lines"],
                "the controlled cutoff could not be accepted before the "
                "worker completed",
                family=family,
                result=result,
                unit=episode_unit,
            )
        if (
            not interrupted
            and output is not None
            and output.get("status") == "ok"
            and final_lines is None
        ):
            self._fail_implementation_size(
                None,
                marker["hard_lines"],
                "the final implementation size could not be measured",
                family=family,
                result=result,
                unit=episode_unit,
            )
        if not interrupted:
            # The monitor controls a call while it is live. If a valid worker
            # delivery jumps over the hard boundary between the last poll and
            # process completion, there is nothing left to interrupt: accept
            # that ordinary envelope and send it into the normal review flow.
            # Keep the oversize observation as telemetry; never re-run a
            # completed implementer merely to manufacture a cutoff.
            if (
                output is not None
                and output.get("status") == "ok"
                and final_lines is not None
                and final_lines > marker["hard_lines"]
                and marker.get("hard_crossed_lines") is None
            ):
                st.append_event(
                    self.state,
                    "implementation_size_overflow",
                    unit=st.unit_key(episode_unit),
                    lines=final_lines,
                    hard_lines=marker["hard_lines"],
                    completed=True,
                )
            return output, result, raw_path, marker, False
        interrupted_call = self._matching_busy_call(
            kind=contracts.KIND_IMPLEMENT, label=raw_name
        )
        interrupted_family, interrupted_model, interrupted_effort = (
            self._result_identity(result, family, model, effort)
        )
        st.append_event(
            self.state,
            "implementation_size_interrupted",
            unit=st.unit_key(episode_unit),
            episode_id=marker.get("episode_id"),
            family=interrupted_call.get("family") or interrupted_family,
            model=interrupted_call.get("model") or interrupted_model,
            effort=interrupted_call.get("effort") or interrupted_effort,
            lines=marker.get("interrupt_lines"),
            reason=result.interrupt_reason,
            duration_s=result.duration_s,
            token_usage=copy.deepcopy(getattr(result, "token_usage", None)),
            provider_session_token_usage=copy.deepcopy(
                getattr(result, "session_token_usage", None)
            ),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=copy.deepcopy(getattr(result, "cost", None)),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            raw_path=raw_path,
            confirmed=marker.get("steer_confirmed"),
            grace_kind=marker.get("grace_kind"),
            hard_crossed_lines=marker.get("hard_crossed_lines"),
            **self._prompt_set_fallback_fields(result),
            **self._task_id_fields(interrupted_call.get("task_id")),
        )
        recovery_prompt = prompt
        # Crossing into stabilization is a durable process boundary.  Save it
        # before the fresh worker starts so a provider failure or driver crash
        # cannot send Resume back through the ordinary size-monitored draft.
        # The marker stays until a valid implementation delivery is recorded.
        self._persist_implementation_stabilization(
            marker, task_id=task_id, unit=episode_unit
        )
        recovery_extensions, recovery_roots = extensions, roots
        if episode_refresher is not None:
            (
                recovery_prompt,
                recovery_extensions,
                recovery_roots,
            ) = episode_refresher(recovery_prompt)
        output, result, raw_path = self._call(
            family,
            recovery_prompt,
            contracts.KIND_IMPLEMENT,
            raw_name + "-stabilize",
            model=model,
            effort=effort,
            extensions=recovery_extensions,
            roots=recovery_roots,
            validate_opts=validate_opts,
            # An interrupted continuation cannot safely reuse its provider
            # turn.  The stabilizer is deliberately a fresh conversation.
            start_session=True,
            # Recovery owns the delivery boundary now.  It is neither
            # size-monitored nor failed for an oversized coherent result.
            active_control=None,
            repeat_protocol=True,
            dispatch_resolver=dispatch_resolver,
            continuation_family=continuation_family,
            task_id=task_id,
            episode_unit=episode_unit,
            prepare_call=(
                prepare_author(
                    self._implementation_stabilizer_context(), None
                )
                if prepare_author is not None else None
            ),
        )
        return output, result, raw_path, marker, True

    def _artifact(self, unit):
        return unit["artifact"] or "(workspace)"

    def _verification_commands(self, unit):
        """Gate commands for a unit: explicit config verification wins;
        a fixer-supplied suite correction can replace a stale explicit
        gate; otherwise use the suite command an implementer discovered.

        Documentation does not run the full suite. The command discovered by
        implementation is used at the scheduled four-slice checkpoints and
        at milestone completion.
        """
        configured = self.config.get("verification") or []
        corrected = self._corrected_suite_command()
        if corrected:
            return [corrected]
        if configured:
            return list(configured)
        discovered = self.state.get("suite_command")
        if discovered:
            return [discovered]
        return []

    def _review_verification_commands(self, unit):
        """Expose an empty-suite handoff only for Brainstorming production.

        Older drafts without a task link are Worker-produced.  A linked draft
        uses its frozen task order rather than the current prospective slice
        choice, which may govern only a later successor.
        """
        if unit.get("kind") != st.UNIT_SLICE_IMPL:
            return None
        task_id = (unit.get("draft") or {}).get("task_id")
        if task_id is None:
            return None
        record = tasks.task_record(self.state, task_id)
        if record["order"]["task_executor"] != "brainstorming":
            return None
        return self._verification_commands(unit)

    def _corrected_suite_command(self):
        """A fix_findings output with suite_command is allowed to correct
        a wrong verification gate. Without this, stale explicit config keeps
        winning and the same suite-command finding is reborn."""
        discovered = self.state.get("suite_command")
        configured = self.config.get("verification") or []
        if (
            not discovered
            or not configured
            or configured == [discovered]
        ):
            return None
        for unit in self.state.get("units", []):
            for round_info in unit.get("rounds", []):
                if round_info.get("kind") != contracts.KIND_FIX_FINDINGS:
                    continue
                result = round_info.get("result") or {}
                reported = result.get("suite_command")
                if (
                    not isinstance(reported, str)
                    or reported.strip() != discovered
                ):
                    continue
                if any(
                    f.get("disposition") == "fixed"
                    for f in result.get("findings", [])
                ):
                    return discovered
        return None

    def _governing(self, unit):
        """The sealed document the unit's artifact answers to (the
        reviewer's explicit standard): the skeleton for a slice note, the
        slice note for an implementation, nothing for the skeleton."""
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return self._skeleton_artifact()
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            return self._slice_note_artifact(unit["slice_id"])
        return None

    def _save_protocol_raws(self, raw_name, exc):
        """Persist the raw texts of a protocol-violating call (original and
        repair retry) so the operator can inspect what the model actually
        said; state.failure keeps only the truncated error strings.
        Returns the saved workspace-relative paths."""
        paths = []
        for i, text in enumerate(getattr(exc, "raw_texts", []) or [], 1):
            paths.append(
                self._save_raw_noclobber(
                    "%s-protoerr%d" % (raw_name, i), text
                )
            )
        return paths

    def _worker_event_unit(self, unit=None):
        """Owning unit for worker incidents recorded outside unit records."""
        unit = unit if unit is not None else st.current_unit(self.state)
        return st.unit_key(unit) if unit is not None else None

    def _record_fatal_malformed(self, raw_name, kind, family, exc,
                                raw_paths, duration_s=None, unit=None):
        """The RED chip: ANY failed LLM call — a double contract
        violation, a crashed/timed-out/non-zero CLI, quota — lands in
        the incident trail (operator decision 2026-07-09). The event
        carries whatever raw texts were captured (both attempts for a
        protocol failure; often none for a spawn failure — the error
        text still tells). A worker that honestly returns `blocked` is
        NOT an LLM failure and records nothing here."""
        raw_paths = list(raw_paths or [])
        call = self._matching_busy_call(kind=kind, label=raw_name)
        task_fields = self._task_id_fields(call.get("task_id"))
        dispatches = getattr(exc, "physical_dispatches", None)
        dispatch_identities = (
            {
                (
                    dispatch.get("family"),
                    dispatch.get("model"),
                    dispatch.get("effort"),
                )
                for dispatch in dispatches
                if isinstance(dispatch, dict)
            }
            if isinstance(dispatches, list) else set()
        )
        # A current-state edit can change any part of the repair identity; that
        # exceptional call needs one truthful identity per physical dispatch.
        # A double-malformed call whose full identity is unchanged retains its
        # established single fatal incident and combined failure/accounting.
        if (isinstance(dispatches, list) and len(dispatches) > 1
                and len(dispatch_identities) > 1):
            for index, dispatch in enumerate(dispatches):
                st.append_event(
                    self.state,
                    "worker_malformed",
                    unit=self._worker_event_unit(unit),
                    label=raw_name,
                    kind=kind,
                    family=dispatch.get("family"),
                    model=dispatch.get("model"),
                    effort=dispatch.get("effort"),
                    fatal=index == len(dispatches) - 1,
                    error=str(dispatch.get("error") or exc)[:300],
                    duration_s=dispatch.get("duration_s"),
                    token_usage=copy.deepcopy(
                        dispatch.get("token_usage")
                    ),
                    token_usage_partial=bool(
                        dispatch.get("token_usage_partial", False)
                        or dispatch.get("token_usage") is None
                    ),
                    cost=copy.deepcopy(dispatch.get("cost")),
                    cost_partial=bool(
                        dispatch.get("cost_partial", False)
                        or dispatch.get("cost") is None
                    ),
                    raw_path=(
                        raw_paths[index] if index < len(raw_paths) else None
                    ),
                    raw_path2=None,
                    **self._prompt_set_fallback_fields(dispatch),
                    **task_fields,
                )
            return
        fallback_fields = self._prompt_set_fallback_evidence(exc)
        st.append_event(
            self.state,
            "worker_malformed",
            unit=self._worker_event_unit(unit),
            label=raw_name,
            kind=kind,
            family=family,
            model=(call.get("model")
                   or getattr(exc, "resolved_model", None)),
            effort=(call.get("effort")
                    or getattr(exc, "resolved_effort", None)),
            fatal=True,
            error=str(
                getattr(exc, "incident_error", None) or exc
            )[:300],
            duration_s=(
                duration_s if duration_s is not None
                else getattr(exc, "duration_s", None)
            ),
            token_usage=copy.deepcopy(getattr(exc, "token_usage", None)),
            token_usage_partial=bool(
                getattr(exc, "token_usage_partial", False)
                or getattr(exc, "token_usage", None) is None
            ),
            cost=copy.deepcopy(getattr(exc, "cost", None)),
            cost_partial=bool(
                getattr(exc, "cost_partial", False)
                or getattr(exc, "cost", None) is None
            ),
            raw_path=(raw_paths or [None])[0],
            raw_path2=(raw_paths[1] if len(raw_paths or []) > 1 else None),
            **fallback_fields,
            **task_fields,
        )

    def _consume_stale_marker(self):
        """A driver that died mid-call (Stop, crash, SIGKILL) leaves its
        in-flight marker behind. On startup, use it to repair what the
        death may have dirtied — without ever destroying legitimate work:

        - killed EDIT call with zero completed fixes in the episode, or a
          killed call in a clean-tree phase (rounds/sealing): the
          pre-call worktree was exactly HEAD, so restore_clean is safe;
        - killed fixer mid-loop (legitimate prior fix work is mixed with
          the partial dead work): no destructive action — the next fixer
          gets a KILLED NOTICE instead (killed_fix_notice flag).
        """
        marker = self._read_busy()
        if marker is None:
            return
        calls = list(marker.get("pending_calls") or [])
        calls.append(self._busy_call(marker))
        deduped = []
        seen_ids = set()
        for call in calls:
            if not isinstance(call, dict):
                continue
            call_id = call.get("call_id")
            if call_id and call_id in seen_ids:
                continue
            if call_id:
                seen_ids.add(call_id)
            deduped.append(call)
        calls = deduped
        marker_unit = None
        for call in reversed(calls):
            marker_unit = self._active_task_unit(call.get("task_id"))
            if marker_unit is not None:
                break
        marker_state = marker.get("state_digest")
        current_state = self._state_file_digest()
        has_unfinished_call = any(
            call.get("family") and not call.get("completed")
            for call in calls
        )
        if (
            marker_state is not None
            and current_state is not None
            and marker_state != current_state
            and (marker_unit is None or not has_unfinished_call)
        ):
            self._clear_busy()
            return
        # Preserve every unsaved physical call. Completed parents contribute
        # their known lower bound; the active child remains explicitly
        # partial because the process died before its result was durable.
        accounted = False
        for call in calls:
            if not call.get("family"):
                continue
            unit = (
                self._active_task_unit(call.get("task_id"))
                or marker_unit
                or st.current_unit(self.state)
            )
            usage = (
                copy.deepcopy(call.get("token_usage"))
                if call.get("completed") else None
            )
            st.append_event(
                self.state,
                "worker_interrupted",
                unit=st.unit_key(unit) if unit is not None else None,
                label=call.get("label"),
                kind=call.get("kind"),
                family=call.get("family"),
                model=call.get("model"),
                effort=call.get("effort"),
                duration_s=(
                    call.get("duration_s") if call.get("completed") else None
                ),
                token_usage=usage,
                token_usage_partial=bool(
                    call.get("token_usage_partial", False)
                    or usage is None
                ),
                cost=(
                    copy.deepcopy(call.get("cost"))
                    if call.get("completed") else None
                ),
                cost_partial=bool(
                    call.get("cost_partial", False)
                    or not call.get("completed")
                    or call.get("cost") is None
                ),
                **self._prompt_set_fallback_fields(call),
                **self._task_id_fields(call.get("task_id")),
            )
            accounted = True
        if accounted:
            self._save()
        if not gitops.enabled(self.config):
            self._clear_busy()
            return
        root_call = calls[0] if calls else marker
        kind = root_call.get("kind")
        unit = (
            self._active_task_unit(root_call.get("task_id"))
            or marker_unit
            or st.current_unit(self.state)
        )
        if unit is None or kind in (None, "verification"):
            self._clear_busy()
            return
        try:
            dirty = bool(gitops.worktree_diff(self.workspace).strip())
        except gitops.GitError:
            return
        status = unit["status"]
        clean_tree_phase = status in (
            st.U_ROUNDS, st.U_SEALING, st.U_PRE_SEAL_VERIFY,
            st.U_PRE_REVIEW_VERIFY,
        )
        fresh_episode_fix = (
            kind == contracts.KIND_FIX_FINDINGS
            and status == st.U_FIXING
            and not unit.get("fix_loop_rounds")
            and not (unit.get("fix_source") or {}).get(
                "preserve_dirty_on_killed_fix"
            )
        )
        if dirty and (clean_tree_phase or fresh_episode_fix):
            try:
                gitops.restore_clean(self.workspace)
            except gitops.GitError:
                return
            st.append_event(
                self.state,
                "unclean_stop_restored",
                unit=st.unit_key(unit),
                killed_call=root_call.get("label"),
                kind=kind,
            )
            self._save()
            self._clear_busy()
            return
        if kind == contracts.KIND_FIX_FINDINGS and status in (
            st.U_FIXING, st.U_DELTA_REVIEW
        ):
            unit["killed_fix_notice"] = root_call.get("label") or True
            st.append_event(
                self.state,
                "unclean_stop_noticed",
                unit=st.unit_key(unit),
                killed_call=root_call.get("label"),
            )
            self._save()
        self._clear_busy()

    def _amendments_path(self):
        return os.path.join(self._runtime_dir(), "amendments.json")

    def _parked_candidate_ref(self, unit):
        digest = hashlib.sha256(
            (os.path.abspath(self.state_path) + "\0" + st.unit_key(unit))
            .encode("utf-8", "surrogatepass")
        ).hexdigest()[:24]
        return "refs/orchestrator/parked/%s" % digest

    def _record_amendments_seen(self, amendments):
        if not amendments:
            return
        seen = {
            e.get("amendment_id")
            for e in self.state["events"]
            if e.get("type") == "amendment_seen"
        }
        for amendment in amendments:
            aid = str(amendment.get("id") or "")
            if aid and aid not in seen:
                seen.add(aid)
                st.append_event(
                    self.state,
                    "amendment_seen",
                    amendment_id=aid,
                    text=str(amendment.get("text"))[:300],
                )

    def _amendments_snapshot(
        self, record_seen=True, retain_valid_operator_siblings=False,
        unit=None,
    ):
        """Return amendments plus mutable-file completeness for one read.

        A complete mutable file is authoritative even when its list is empty.
        Any absent, unreadable, or malformed shape is incomplete and therefore
        cannot revoke authority already present in a provider conversation.
        Non-Worker briefings retain the prior tolerant posture by requesting
        otherwise-valid entries from a list with malformed siblings.
        Accepted design amendments come from append-only run state either way.
        """
        operator = []
        operator_complete = False
        try:
            with open(self._amendments_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            raw = data.get("amendments") if isinstance(data, dict) else None
            if not isinstance(raw, list):
                raise ValueError("amendments must be a list")
            operator = []
            for item in raw:
                if (
                    not isinstance(item, dict)
                    or not str(item.get("text") or "").strip()
                ):
                    continue
                amendment = copy.deepcopy(item)
                # Authority comes from the mutable operator file itself, never
                # from an entry's self-description.  Removing a spoofed tier
                # keeps the existing operator payload shape while letting the
                # renderer's absent-authority default classify it correctly.
                amendment.pop("authority", None)
                operator.append(amendment)
            operator_complete = len(operator) == len(raw)
            if not operator_complete and not retain_valid_operator_siblings:
                operator = []
        except (OSError, ValueError, TypeError, UnicodeError):
            operator = []
        if record_seen:
            self._record_amendments_seen(operator)
        design = [
            {
                "id": event.get("amendment_id"),
                "text": event.get("text"),
                "at": event.get("at"),
                # These supported event types are durable design sources. An
                # old migration event may carry ``historical_design_update``;
                # that payload label must not promote it to operator law.
                "authority": "brainstorming_design",
                "session_id": event.get("session_id"),
                "accepted_target_revision": event.get(
                    "accepted_target_revision"
                ),
            }
            for event in self.state.get("events", [])
            if event.get("type") in (
                "brainstorming_design_amendment_adopted",
                "brainstorming_no_implementation_adopted",
                "redoc_wave_migrated_to_design_update",
            )
            and (
                event.get("type")
                != "brainstorming_no_implementation_adopted"
                or (
                    unit is not None
                    and event.get("unit") == st.unit_key(unit)
                )
            )
            and str(event.get("text") or "").strip()
        ]
        return operator + design, operator_complete

    def _amendments(self, record_seen=True, unit=None):
        """Return operator amendments plus accepted design clarifications."""
        return self._amendments_snapshot(
            record_seen=record_seen,
            retain_valid_operator_siblings=True,
            unit=unit,
        )[0]

    def _read_standing_law(self, worker_kind, unit_kind):
        """LIVE read of the project's standing law for one worker call:
        (in-scope enabled policies, reuse-source roles or None), through
        the sealed Slice 3 selection and Slice 2 meta seams. Any fault is
        a _StandingLawError: unlike amendments.json (a lock-free hot-edit
        file whose tolerant read returns nothing on a mid-write race), the
        policy store is a CAS-disciplined KV validated on write — malformed
        content there is corruption, and silently proceeding WITHOUT
        standing law is the one behavior this surface must never exhibit."""
        block = self.state["project"]
        directory, project = block["directory"], block["project"]
        store_dir = os.path.join(directory, project)
        if not os.path.isdir(store_dir):
            # Opening a client would silently recreate an EMPTY store and
            # run the call with no law at all; refuse before that.
            raise _StandingLawError(
                "project %r has no readable store under %s (removed after "
                "init?); repair the store and resume" % (project, directory)
            )
        store_file = os.path.join(store_dir, kvstore.STORE_FILENAME)
        if not os.path.isfile(store_file):
            # The project directory alone is not evidence of standing law:
            # LocalKVClient would treat a missing file as an empty store.
            raise _StandingLawError(
                "project %r has no readable KV file at %s (removed after "
                "init?); repair the store and resume" % (project, store_file)
            )
        try:
            selected = projects.PolicyStore(directory, project).in_scope(
                worker_kind, unit_kind
            )
        except OSError as exc:
            raise _StandingLawError(
                "policy store of project %r is unreadable while selecting "
                "safeguards for (%s, %s): %s; repair the store and resume"
                % (project, worker_kind, unit_kind, exc)
            )
        if not selected.ok:
            raise _StandingLawError(
                "policy store of project %r failed while selecting "
                "safeguards for (%s, %s): %s; repair the store and resume"
                % (project, worker_kind, unit_kind, selected.reason)
            )
        work_area = block["work_area"]
        try:
            record = workareas.WorkAreaStore(directory, project).read_meta(
                work_area
            )
        except (OSError, RuntimeError) as exc:
            raise _StandingLawError(
                "work_area_meta:%s of project %r is unreadable: %s; repair "
                "the store and resume" % (work_area, project, exc)
            )
        if not record["exists?"]:
            # The meta family is optional by Slice 2's design: the map
            # renders without roles.
            return selected.value, None
        try:
            meta = workareas._meta_value(record["value"])
        except ValueError as exc:
            raise _StandingLawError(
                "work_area_meta:%s of project %r is malformed (%s); repair "
                "the store and resume" % (work_area, project, exc)
            )
        return selected.value, meta["reuse_sources"]

    def _record_safeguards_seen(self, policies):
        """`project_safeguard_seen`, mirroring `amendment_seen`: appended
        the first time each (policy id, version) pair enters a prompt of
        this run, with the same 300-character text clip; a version bump
        re-records under the new version (the frozen ledger shape). Runs
        BEFORE the worker call, so a call that later fails still leaves
        what its worker was shown in the persisted ledger."""
        seen = {
            (e.get("policy_id"), e.get("version"))
            for e in self.state["events"]
            if e.get("type") == "project_safeguard_seen"
        }
        recorded = False
        for policy in policies:
            key = (policy["id"], policy["version"])
            if key in seen:
                continue
            seen.add(key)
            recorded = True
            st.append_event(
                self.state,
                "project_safeguard_seen",
                policy_id=policy["id"],
                version=policy["version"],
                text=str(policy["prompt"])[:300],
            )
        return recorded

    def _project_prompt_inputs(self, unit, kind, record_seen=True):
        """Standing project law for one worker call of a project-bound
        run: (project_context, extensions, roots) — the PROJECT CONTEXT
        builder input, the compiled in-scope contract extensions, and the
        grant universe. (None, None, None) for a project-less run, whose
        builders and validation then behave byte-identically to today.

        Selection and meta are read live for every worker call through this
        method. Roots and handles come from the state project block
        recorded at init, never a live resolve: the map always describes
        exactly the universe containment enforces, and a mid-run store
        edit to the work-area record changes neither. Selection, meta,
        and compile faults fail the run, loudly, consuming no worker call
        (Slice 4's non-repairable error split, reused); the same call
        that renders an obligation supplies its compiled extension to
        enforcement — never one without the other."""
        block = self.state.get("project")
        if block is None:
            return None, None, None
        try:
            policies, reuse_sources = self._read_standing_law(
                kind, unit["kind"]
            )
            extensions = verifiers.compile_extensions(policies)
        except (_StandingLawError, verifiers.VerifierError) as exc:
            st.fail_run(
                self.state,
                "project standing law unavailable for the %s call: %s"
                % (kind, exc),
                unit=unit,
            )
            self._save()
            raise StopStep(str(exc))
        if record_seen:
            self._record_safeguards_seen(policies)
        roots = [block["primary"]["path"]] + [
            root["path"] for root in block["additional"]
        ]
        project_context = {
            "project": block["project"],
            "work_area": block["work_area"],
            "primary": block["primary"],
            "additional": block["additional"],
            "reuse_sources": reuse_sources,
            "safeguards": policies,
        }
        return project_context, extensions, roots

    def _worker_episode_authority(self, unit, kind):
        """Take one live authority snapshot for a milestone Worker episode."""
        amendments, operator_complete = self._amendments_snapshot(
            record_seen=False,
            unit=unit,
        )
        project_context, extensions, roots = self._project_prompt_inputs(
            unit, kind, record_seen=False
        )
        return {
            "amendments": amendments,
            "operator_complete": operator_complete,
            "project_context": project_context,
            "extensions": extensions,
            "roots": roots,
        }

    def _activate_worker_episode_authority(self, snapshot):
        """Persist existing seen traces before dispatching this snapshot."""
        before = len(self.state.get("events") or [])
        if snapshot.get("operator_complete"):
            self._record_amendments_seen([
                item for item in snapshot.get("amendments") or []
                if item.get("authority") != "brainstorming_design"
            ])
        project_context = snapshot.get("project_context") or {}
        self._record_safeguards_seen(
            project_context.get("safeguards") or []
        )
        if len(self.state.get("events") or []) != before:
            self._save()

    @staticmethod
    def _worker_episode_prompt(prompt, snapshot):
        return prompts.attach_worker_episode_authority(
            prompt,
            snapshot.get("amendments") or [],
            snapshot.get("project_context"),
            bool(snapshot.get("operator_complete")),
        )

    def _refresh_worker_episode(self, unit, kind, prompt):
        """Refresh and activate one later episode around an immutable prompt."""
        snapshot = self._worker_episode_authority(unit, kind)
        self._activate_worker_episode_authority(snapshot)
        return (
            self._worker_episode_prompt(prompt, snapshot),
            snapshot["extensions"],
            snapshot["roots"],
        )

    def _busy_path(self):
        return os.path.join(self._runtime_dir(), "current.json")

    @staticmethod
    def _busy_call(marker):
        return {
            key: copy.deepcopy(value)
            for key, value in marker.items()
            if key != "pending_calls"
        }

    @staticmethod
    def _task_id_fields(task_id):
        """Return the optional explicit Worker ownership link."""
        if task_id is None:
            return {}
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task_id must be a non-empty string")
        return {"task_id": task_id}

    @staticmethod
    def _prompt_set_fallback_fields(source):
        """Project optional routed-set provenance beside one physical call."""
        fallback = (
            source.get("prompt_set_fallback")
            if isinstance(source, dict)
            else getattr(source, "prompt_set_fallback", None)
        )
        return (
            {"prompt_set_fallback": fallback}
            if fallback is not None else {}
        )

    @classmethod
    def _prompt_set_fallback_evidence(cls, source):
        """Project routed-set provenance without collapsing call attempts."""
        dispatches = (
            source.get("physical_dispatches")
            if isinstance(source, dict)
            else getattr(source, "physical_dispatches", None)
        )
        if isinstance(dispatches, list) and len(dispatches) == 1:
            return cls._prompt_set_fallback_fields(dispatches[0])
        if isinstance(dispatches, list) and len(dispatches) > 1:
            return {
                "physical_dispatches": [
                    cls._prompt_set_fallback_fields(dispatch)
                    for dispatch in dispatches
                ]
            }
        return cls._prompt_set_fallback_fields(source)

    def _task_work_area(self):
        """Freeze the execution context the milestone already resolved."""
        project = self.state.get("project")
        if project is not None:
            return copy.deepcopy(project)
        return {
            "workspace_path": self.workspace,
            "primary": self.workspace,
            "additional": [],
        }

    def _active_worker_task(self, unit, kind):
        reference = unit.get("active_task")
        if reference is None:
            return None
        if (
            not isinstance(reference, dict)
            or set(reference) != {"id", "kind"}
            or reference.get("kind") != kind
        ):
            raise st.IllegalTransition(
                "unit %s has an incompatible active task" % st.unit_key(unit)
            )
        record = tasks.task_record(self.state, reference.get("id"))
        if tasks.stored_task_executor(
            record["order"]["task_executor"]
        ) != "agent_call":
            raise st.IllegalTransition(
                "the active task is not an agent-call task"
            )
        if record["result"] is not None:
            raise st.IllegalTransition("the active agent-call task is terminal")
        return record

    def _active_brainstorming_task(self, unit, kind):
        reference = unit.get("active_task")
        if reference is None:
            return None
        if (
            not isinstance(reference, dict)
            or set(reference) != {"id", "kind"}
            or reference.get("kind") != kind
        ):
            raise st.IllegalTransition(
                "unit %s has an incompatible active task" % st.unit_key(unit)
            )
        record = tasks.task_record(self.state, reference.get("id"))
        if record["order"]["task_executor"] != "brainstorming":
            raise st.IllegalTransition(
                "the active task is not a Brainstorming task"
            )
        if record["result"] is not None:
            raise st.IllegalTransition(
                "the active Brainstorming task is terminal"
            )
        return record

    def _brainstorming_producer_selected(self, unit, kind):
        reference = unit.get("active_task")
        if reference is not None:
            record = tasks.task_record(self.state, reference.get("id"))
            return record["order"]["task_executor"] == "brainstorming"
        selection = tasks.effective_slice_producers(
            self._slice_info(unit["slice_id"])
        )[kind]
        return selection["task_executor"] == "brainstorming"

    def _admit_worker_task(
        self,
        unit,
        kind,
        prompt,
        family,
        model=None,
        effort=None,
        dispatch_resolver=None,
        output_directory=None,
        project_context=None,
        project_safeguards=None,
        validate_opts=None,
        author_coordinates=None,
    ):
        """Durably freeze one Worker scheduling decision before dispatch."""
        active = self._active_worker_task(unit, kind)
        if active is not None:
            return active
        staffing_family, staffing_model, staffing_effort = family, model, effort
        if dispatch_resolver is not None:
            staffing_family, staffing_model, staffing_effort = (
                dispatch_resolver()
            )
        defaults = self._family_defaults(staffing_family)
        staffing_model = staffing_model or defaults[0]
        staffing_effort = staffing_effort or defaults[1]
        context = {
            "task_kind": kind,
            "unit": st.unit_key(unit),
            # These options are the machine-readable half of the admitted
            # prompt contract. A later strategy change may govern successor
            # tasks, but cannot make recovery validate this frozen request
            # against requirements it never carried.
            "worker_validation": json.loads(json.dumps(
                validate_opts or {},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )),
        }
        if kind == contracts.KIND_REVIEW_ROUND:
            # Freeze only the strategy decisions this review consumes after a
            # validated result. Live model-profile dispatch and hot authority
            # retain their separate call-time/episode boundaries.
            context["worker_result_policy"] = self._worker_result_policy(unit)
        if project_context is not None:
            context["project_context"] = copy.deepcopy(project_context)
        elif project_safeguards is not None:
            # Compatibility for callers draining the first Slice 3 shape.
            context["project_safeguards"] = copy.deepcopy(
                project_safeguards
            )
        if author_coordinates is not None:
            context["author_coordinates"] = copy.deepcopy(
                author_coordinates
            )
        request = {
            "work_area": self._task_work_area(),
            "request": prompt,
            "context": context,
            "reference_documents": [],
        }
        if output_directory is not None:
            request["output_directory"] = output_directory
        order = {
            "task_executor": "agent_call",
            "configuration": {},
            "request": request,
        }
        if kind in tasks.PRODUCER_TASK_KINDS:
            order = tasks.producer_order(
                self._slice_info(unit["slice_id"]), kind, request
            )
            if order["task_executor"] != "agent_call":
                raise st.IllegalTransition(
                    "selected production task is not an agent-call task"
                )
        # The milestone owns both of these, and writes them last. The
        # producer channel chooses WHICH executor runs a production step,
        # never which process step the call performs: a `role` an operator
        # or an agent put in a prospective configuration would otherwise
        # staff a milestone dispatch from outside milestone law. The
        # session is the run's one binding, or none while it is unbound.
        order["configuration"] = dict(
            order.get("configuration") or {},
            role=self._order_role(unit, kind),
        )
        order["staffing_session"] = st.staffing_session(self.state)
        record = tasks.admit_task(
            self.state,
            order,
            {
                "agent_call": {
                    "agent": staffing_family,
                    "model": staffing_model,
                    "effort": staffing_effort,
                }
            },
            self.workspace,
        )
        unit["active_task"] = {"id": record["id"], "kind": kind}
        self._save()
        return record

    def _worker_result_policy(self, unit):
        """Project the current strategy decisions owned by one Worker task."""
        threshold = str(self.config.get("p3_defer_max_risk") or "low")
        if threshold not in contracts.DRIFT_RISK_LEVELS:
            threshold = "low"
        return {
            "defer_scope": list(
                interpreter.defer_scope_for(self.state, unit["kind"])
            ),
            "p3_reclassify_debt": bool(
                self.config.get("p3_reclassify_debt")
            ),
            "p3_defer_max_risk": threshold,
            "gap_backstop": bool(interpreter.gap_semantics(self.state)),
        }

    def _worker_task_result_policy(self, record, unit):
        """Recover frozen post-result strategy, with pre-field compatibility."""
        context = ((record.get("order") or {}).get("request") or {}).get(
            "context"
        ) or {}
        frozen = context.get("worker_result_policy")
        if frozen is None:
            return self._worker_result_policy(unit)
        if not isinstance(frozen, dict):
            raise st.IllegalTransition(
                "Worker task has malformed frozen result policy"
            )
        scope = frozen.get("defer_scope")
        threshold = frozen.get("p3_defer_max_risk")
        if (
            not isinstance(scope, list)
            or any(item not in contracts.SEVERITIES for item in scope)
            or threshold not in contracts.DRIFT_RISK_LEVELS
            or not isinstance(frozen.get("p3_reclassify_debt"), bool)
            or not isinstance(frozen.get("gap_backstop"), bool)
        ):
            raise st.IllegalTransition(
                "Worker task has malformed frozen result policy"
            )
        return copy.deepcopy(frozen)

    def _worker_task_project_inputs(
        self, record, project_context=None, extensions=None, roots=None
    ):
        """Recover project prompt and enforcement inputs from task admission."""
        request = record["order"]["request"]
        context = request.get("context") or {}
        frozen_context = context.get("project_context")
        policies = None
        if frozen_context is not None:
            project_context = copy.deepcopy(frozen_context)
            policies = project_context.get("safeguards") or []
        elif "project_safeguards" in context:
            # The first Slice 3 record shape froze policies and roots but not
            # the already-rendered reuse-source projection. Reconstruct the
            # available inherited context without reopening the project store.
            policies = context.get("project_safeguards") or []
            work_area = request.get("work_area") or {}
            project_context = {
                "project": work_area.get("project"),
                "work_area": work_area.get("work_area"),
                "primary": copy.deepcopy(work_area.get("primary")),
                "additional": copy.deepcopy(work_area.get("additional") or []),
                "reuse_sources": None,
                "safeguards": copy.deepcopy(policies),
            }
        if policies is None:
            return project_context, extensions, roots
        work_area = request.get("work_area") or {}
        primary = work_area.get("primary") or {}
        additional = work_area.get("additional") or []
        def root_path(root):
            return root.get("path") if isinstance(root, dict) else root

        frozen_roots = [root_path(primary)] + [
            root_path(root) for root in additional
        ]
        if any(not isinstance(path, str) or not path for path in frozen_roots):
            raise st.IllegalTransition(
                "Worker task has incomplete frozen project roots"
            )
        frozen_extensions = verifiers.compile_extensions(policies)
        if self._record_safeguards_seen(policies):
            # Keep the existing before-dispatch ledger guarantee after moving
            # safeguard authority behind durable task admission.
            self._save()
        return project_context, frozen_extensions, frozen_roots

    def _worker_task_enforcement(self, record, extensions, roots):
        """Recover the validators that accompanied the frozen Worker prompt."""
        _project_context, extensions, roots = (
            self._worker_task_project_inputs(
                record, extensions=extensions, roots=roots
            )
        )
        return extensions, roots

    @staticmethod
    def _worker_task_validate_opts(record, fallback=None):
        """Recover prompt-aligned validation frozen at task admission.

        Records admitted by the first Slice 3 implementation did not carry
        this internal context member. Keep those historical records usable by
        retaining their prior fallback behavior; every new task freezes the
        value, including an explicit empty option set.
        """
        context = ((record.get("order") or {}).get("request") or {}).get(
            "context"
        ) or {}
        if "worker_validation" not in context:
            return copy.deepcopy(fallback)
        frozen = context["worker_validation"]
        if not isinstance(frozen, dict):
            raise st.IllegalTransition(
                "Worker task has invalid frozen validation options"
            )
        return copy.deepcopy(frozen) or None

    def _terminalize_worker_task(
        self,
        unit,
        native_result,
        result=None,
        status="success",
        reason=None,
        task_id=None,
    ):
        """Record one accepted outcome without changing legacy unstamped work."""
        if task_id is None:
            task_id = getattr(result, "task_id", None)
        if task_id is None:
            return None
        if status == "failure":
            origin_signal = getattr(result, "origin_rethink_signal", None)
            if origin_signal is not None:
                native_result = origin_signal
        envelope = tasks.worker_result(
            self.state,
            task_id,
            copy.deepcopy(native_result),
            status=status,
            reason=reason,
            prompt_set_fallback=getattr(
                result, "prompt_set_fallback", None
            ),
        )
        record = tasks.record_task_result(self.state, task_id, envelope)
        reference = unit.get("active_task")
        if isinstance(reference, dict) and reference.get("id") == task_id:
            unit.pop("active_task", None)
        return record

    def _fail_waiting_worker_task(self, unit, wait, reason):
        origin = wait.get("origin") or {}
        return self._fail_worker_task_if_open(
            unit,
            wait.get("signal"),
            task_id=origin.get("task_id"),
            reason=reason,
        )

    def _fail_worker_task_if_open(
        self, unit, native_result, reason, result=None, task_id=None
    ):
        if task_id is None:
            task_id = getattr(result, "task_id", None)
        if task_id is None:
            return None
        record = tasks.task_record(self.state, task_id)
        if record["result"] is not None:
            return record
        return self._terminalize_worker_task(
            unit,
            native_result,
            result=result,
            status="failure",
            reason=reason,
            task_id=task_id,
        )

    def _worker_task_fields(self, kind=None, family=None, label=None,
                            result=None):
        """Read ownership only from a carried result or durable marker."""
        task_id = getattr(result, "task_id", None)
        if task_id is None:
            task_id = self._matching_busy_call(
                kind=kind, family=family, label=label
            ).get("task_id")
        return self._task_id_fields(task_id)

    @classmethod
    def _retain_task_id(cls, call, task_id):
        if task_id is not None:
            call.task_id = cls._task_id_fields(task_id)["task_id"]

    def _matching_busy_call(self, kind=None, family=None, label=None):
        """Find the durable ordinary call identity for an incident."""
        marker = self._read_busy()
        if marker is None:
            return {}
        calls = list(marker.get("pending_calls") or [])
        calls.append(self._busy_call(marker))
        for call in reversed(calls):
            if not isinstance(call, dict):
                continue
            if kind is not None and call.get("kind") != kind:
                continue
            if family is not None and call.get("family") != family:
                continue
            if label is not None and call.get("label") != label:
                continue
            return copy.deepcopy(call)
        return {}

    def _active_task_unit(self, task_id):
        """Resolve a durable Worker task to its still-open owning unit."""
        if not isinstance(task_id, str) or not task_id:
            return None
        for unit in self.state.get("units", []):
            active = unit.get("active_task")
            if isinstance(active, dict) and active.get("id") == task_id:
                return unit
        return None

    @staticmethod
    def _retain_call_identity(call, model, effort, family=None):
        """Keep generic staffing available after the busy marker is gone."""
        if getattr(call, "resolved_family", None) is None:
            call.resolved_family = family
        if getattr(call, "resolved_model", None) is None:
            call.resolved_model = model
        if getattr(call, "resolved_effort", None) is None:
            call.resolved_effort = effort

    def _read_busy(self):
        try:
            with open(self._busy_path(), "r", encoding="utf-8") as fh:
                marker = json.load(fh)
        except (OSError, ValueError):
            return None
        return marker if isinstance(marker, dict) else None

    def _write_busy(self, marker):
        try:
            os.makedirs(os.path.dirname(self._busy_path()), exist_ok=True)
            tmp = self._busy_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(marker, fh)
            os.replace(tmp, self._busy_path())
            return True
        except OSError:
            return False

    def _mark_busy(self, label, kind, family, model=None, effort=None,
                   nested=False, task_id=None, staffing_fallback=None):
        """Durable in-flight marker, with any unsaved parent calls.

        The top-level fields remain the panel's active-call projection.
        Nested classifiers retain the completed parent in ``pending_calls``
        until the enclosing step saves all accounting together.

        ``staffing_fallback`` says the staffing was resolved on the default
        document because an input could not be read. It is bookkeeping and
        additive — absent on an ordinary call — and losing it changes no
        acceptance, seal or result.
        """
        with self._busy_lock:
            state_digest = self._state_file_digest()
            pending = []
            if nested:
                previous = self._read_busy()
                if (
                    previous is not None
                    and previous.get("state_digest") == state_digest
                ):
                    pending = list(previous.get("pending_calls") or [])
                    pending.append(self._busy_call(previous))
            marker = {
                "label": label,
                "kind": kind,
                "family": family,
                "model": model,
                "effort": effort,
                "started_at": time.time(),
                "call_id": str(uuid.uuid4()),
                "state_digest": state_digest,
            }
            marker.update(self._task_id_fields(task_id))
            if staffing_fallback:
                marker["staffing_fallback"] = staffing_fallback
            if pending:
                marker["pending_calls"] = pending
            return self._write_busy(marker)

    def _retarget_busy(self, label, kind, family, model, effort,
                       staffing_fallback=None, prompt_set_fallback=None):
        """Keep the generic in-flight marker aligned with the next call.

        Including the fallback note: the marker says what the LAST physical
        dispatch actually ran on, so a call that no longer falls back loses
        the note the previous attempt left.
        """
        with self._busy_lock:
            marker = self._read_busy()
            if (
                marker is None
                or marker.get("label") != label
                or marker.get("kind") != kind
            ):
                raise RuntimeError(
                    "%s call lost its accounting marker before dispatch"
                    % kind
                )
            marker.update({
                "family": family,
                "model": model,
                "effort": effort,
                "started_at": time.time(),
            })
            if staffing_fallback:
                marker["staffing_fallback"] = staffing_fallback
            else:
                marker.pop("staffing_fallback", None)
            if prompt_set_fallback is not None:
                marker["prompt_set_fallback"] = prompt_set_fallback
            else:
                marker.pop("prompt_set_fallback", None)
            if not self._write_busy(marker):
                raise RuntimeError(
                    "%s call could not update its accounting marker"
                    % kind
                )

    def _price_call(self, family, model, call, include_repair=False):
        """Price one completed call and hang the answer on it.

        Mirrors token_usage exactly: a dict when the cost is known, absent
        plus a `partial` flag when it is not. Unknown is never rendered as
        zero — zero is what a subscription seat genuinely costs, and the two
        must stay distinguishable.
        """
        is_dict = isinstance(call, dict)
        own = (
            call.get("cost_payloads") if is_dict
            else getattr(call, "cost_payloads", None)
        )
        # An attempt that ran and reported nothing is unknown, not free — the
        # same explicit None runners.merged_cost_payloads appends.
        payloads = list(own) if own else ([None] if call is not None else [])
        if include_repair:
            repair = (
                call.get("repair") if is_dict
                else getattr(call, "repair", None)
            )
            if isinstance(repair, dict):
                strike = repair.get("cost_payloads")
                payloads.extend(list(strike) if strike else [None])
        # No already-settled branch: a carrier that ran always yields at
        # least the explicit None above, so `payloads` is empty only when
        # there is no carrier at all — and then there is nothing to read a
        # previous figure from either.
        configured = self.config.get("billing")
        billing = (
            configured.get(family) if isinstance(configured, dict) else None
        )
        quoted = pricing.quote_many(family, model, payloads, billing=billing)
        # Both readings or nothing: a stored half-known cost passes the
        # record-level partial check while every aggregation drops it.
        if quoted.api_usd is None or quoted.real_usd is None:
            return None
        return quoted.as_dict()

    def _quote_call(self, family, model, call):
        """Price ONE physical call and hang the answer on it.

        Deliberately excludes a repair's first strike: that attempt is
        recorded on its own malformed event, the same split duration and
        token usage already follow. Only the crash sentinel wants both.
        """
        cost = self._price_call(family, model, call)
        if isinstance(call, dict):
            call["cost"] = cost
            call["cost_partial"] = cost is None
        else:
            call.cost = cost
            call.cost_partial = cost is None
        return cost

    def _update_busy_accounting(self, call, duration_s=None):
        """Attach a completed physical call's known cost to its sentinel."""
        with self._busy_lock:
            marker = self._read_busy()
            if marker is None:
                return False
            final_family, final_model, final_effort = self._result_identity(
                call,
                marker.get("family"),
                marker.get("model"),
                marker.get("effort"),
            )
            marker.update({
                "family": final_family,
                "model": final_model,
                "effort": final_effort,
            })
            duration, usage, partial = self._call_accounting(call)
            # Every completed physical call passes through here, successful or
            # not, and the marker already records WHICH model actually ran —
            # so this is the one place a price has to be struck.
            # The call object gets its OWN price (final attempt only);
            # the sentinel separately gets the whole logical call, repair
            # included, because crash recovery reasons about the call as one.
            physical_dispatches = getattr(
                call, "physical_dispatches", None
            )
            if isinstance(physical_dispatches, list):
                costs = [
                    self._quote_call(
                        item.get("family") or final_family,
                        item.get("model") or final_model,
                        item,
                    )
                    for item in physical_dispatches
                ]
            else:
                final_cost = self._quote_call(
                    final_family, final_model, call
                )
                costs = [final_cost]
                repair = getattr(call, "repair", None)
                if isinstance(repair, dict):
                    costs.append(self._price_call(
                        repair.get("family") or final_family,
                        repair.get("model") or final_model,
                        repair,
                    ))
            sentinel_cost = None
            if costs and all(isinstance(cost, dict) for cost in costs):
                sentinel_cost = {
                    "api_usd": sum(cost["api_usd"] for cost in costs),
                    "real_usd": sum(cost["real_usd"] for cost in costs),
                }
            if isinstance(physical_dispatches, list):
                call.cost = copy.deepcopy(sentinel_cost)
                call.cost_partial = sentinel_cost is None
            marker["cost"] = copy.deepcopy(sentinel_cost)
            marker["cost_partial"] = sentinel_cost is None
            marker["completed"] = True
            marker["duration_s"] = (
                duration_s if duration_s is not None else duration
            )
            marker["token_usage"] = copy.deepcopy(usage)
            marker["token_usage_partial"] = bool(
                partial or usage is None
            )
            # In-call control may have durably changed state while the
            # provider was running (the controlled-cutoff write-ahead marker).
            # This completed result is not in that state yet, so bind the
            # sentinel to the current digest before any raw/state persistence.
            marker["state_digest"] = self._state_file_digest()
            return self._write_busy(marker)

    @staticmethod
    def _call_accounting(call):
        """Return the complete duration and usage of one logical worker call.

        A contract repair is a second physical provider call.  Its successful
        result carries the first attempt in ``repair``; count both so the
        permanent record matches the live timer.
        """
        if isinstance(call, dict):
            usage = call.get("token_usage")
            partial = call.get("token_usage_partial", False)
            duration = call.get("duration_s")
            repair = None
        else:
            usage = getattr(call, "token_usage", None)
            partial = getattr(call, "token_usage_partial", False)
            duration = getattr(call, "duration_s", None)
            repair = getattr(call, "repair", None)
        final_usage_missing = usage is None
        if isinstance(repair, dict):
            repair_usage = repair.get("token_usage")
            usage = runners.add_token_usage(usage, repair_usage)
            partial = bool(
                partial
                or final_usage_missing
                or repair.get("token_usage_partial", False)
                or repair_usage is None
            )
            repair_duration = repair.get("duration_s")
            if (
                isinstance(duration, (int, float))
                and not isinstance(duration, bool)
                and isinstance(repair_duration, (int, float))
                and not isinstance(repair_duration, bool)
            ):
                duration += repair_duration
        return duration, usage, bool(partial or usage is None)

    def _require_busy_accounting(self, kind, family, label, call,
                                 duration_s=None, parent_call=None,
                                 task_id=None, unit=None):
        """Do not continue after losing the only crash-safe call marker."""
        self._retain_task_id(call, task_id)
        if self._update_busy_accounting(call, duration_s=duration_s):
            return
        unit = unit if unit is not None else st.current_unit(self.state)
        self._record_worker_unaccepted(
            unit, kind, family, call,
            "%s completed but its accounting marker could not be updated"
            % label,
        )
        if parent_call is not None:
            self._record_worker_unaccepted(
                unit, parent_call[0], parent_call[1], parent_call[2],
                "parent call could not safely start nested accounting",
            )
        st.fail_run(
            self.state,
            "%s completed but its accounting marker could not be updated"
            % kind,
            unit=unit,
            type_="orchestrator",
        )
        self._save()
        self._clear_busy()
        raise StopStep("worker accounting marker unavailable")

    def _clear_busy(self):
        with self._busy_lock:
            try:
                os.unlink(self._busy_path())
            except OSError:
                pass

    def _call(self, family, prompt, kind, raw_name, model=None, effort=None,
              extensions=None, roots=None, validate_opts=None,
              start_session=False, session_ref=None, active_control=None,
              repeat_protocol=False, dispatch_resolver=None,
              continuation_family=None, task_id=None, prepare_call=None,
              episode_unit=None, cutoff_marker=None):
        """Validated worker call; on protocol/runner failure, fail the run
        with the explanation recorded, then re-raise as StopStep.

        extensions/roots: the in-scope compiled project contract
        extensions and the run's grant universe (_project_prompt_inputs).
        Absent, validation is exactly the base kind contract.
        validate_opts: extra validation kwargs (require_plain,
        battery_questions) threaded into runners.call_worker.
        episode_unit keeps accounting on the admitted call owner when an
        accepted plan edit makes another unit current before validation."""
        call_unit = (
            episode_unit
            if episode_unit is not None else st.current_unit(self.state)
        )
        dm, de = self._family_defaults(family)
        model = model or dm
        effort = effort or de
        retries = self.config.get("infra_retry_backoff_s")
        if retries is None:
            retries = [10, 30]
        attempt = 0
        while True:
            call_family, call_model, call_effort = family, model, effort
            if dispatch_resolver is not None:
                call_family, call_model, call_effort = dispatch_resolver()
            if not self._mark_busy(
                raw_name, kind, call_family,
                model=call_model, effort=call_effort, task_id=task_id,
                staffing_fallback=getattr(
                    dispatch_resolver, "staffing_fallback", None
                ),
            ):
                st.fail_run(
                    self.state,
                    "%s call could not create its accounting marker" % kind,
                    unit=call_unit,
                    type_="orchestrator",
                )
                self._save()
                raise StopStep("worker accounting marker unavailable")
            physical_started = time.time()
            try:
                call_control = (
                    active_control
                    if attempt == 0 or active_control is None
                    else active_control.renew()
                )
                output, result = runners.call_worker(
                    self.runner, call_family, prompt, kind, self.workspace,
                    model=call_model, effort=call_effort,
                    extensions=extensions, roots=roots,
                    validate_opts=validate_opts,
                    start_session=start_session, session_ref=session_ref,
                    active_control=call_control,
                    resolve_dispatch=dispatch_resolver,
                    continuation_family=continuation_family,
                    on_dispatch=lambda f, m, e, prompt_fallback: (
                        self._retarget_busy(
                            raw_name,
                            kind,
                            f,
                            m,
                            e,
                            staffing_fallback=getattr(
                                dispatch_resolver, "staffing_fallback", None
                            ),
                            prompt_set_fallback=prompt_fallback,
                        )
                    ),
                    prepare_call=prepare_call,
                )
                actual_family, actual_model, actual_effort = (
                    self._result_identity(
                        result, call_family, call_model, call_effort
                    )
                )
                self._retain_call_identity(
                    result, actual_model, actual_effort, actual_family
                )
                self._require_busy_accounting(
                    kind, actual_family, raw_name, result, task_id=task_id,
                    unit=call_unit,
                )
            except StopStep as exc:
                if getattr(
                    exc, "completed_attempt_before_dispatch_failure", False
                ):
                    actual_family, actual_model, actual_effort = (
                        self._result_identity(
                            exc, call_family, call_model, call_effort
                        )
                    )
                    self._retain_call_identity(
                        exc, actual_model, actual_effort, actual_family
                    )
                    self._require_busy_accounting(
                        kind, actual_family, raw_name, exc, task_id=task_id,
                        unit=call_unit,
                    )
                    proto_paths = self._save_protocol_raws(raw_name, exc)
                    self._record_fatal_malformed(
                        raw_name, kind, actual_family, exc, proto_paths,
                        unit=call_unit,
                    )
                    self._save()
                self._clear_busy()
                raise
            except verifiers.VerifierError as exc:
                actual_family, actual_model, actual_effort = (
                    self._result_identity(
                        exc, call_family, call_model, call_effort
                    )
                )
                self._retain_call_identity(
                    exc, actual_model, actual_effort, actual_family
                )
                has_physical_attempt = bool(
                    getattr(exc, "physical_dispatches", None)
                    or getattr(exc, "provider_dispatch_started", False)
                )
                if has_physical_attempt:
                    self._require_busy_accounting(
                        kind, actual_family, raw_name, exc, task_id=task_id,
                        unit=call_unit,
                    )
                # Slice 4's non-repairable family (the operator's policy or
                # the environment, e.g. a missing reuse-source directory —
                # never the worker): a recorded run failure the operator
                # repairs and resumes; no repair retry is burned.
                if has_physical_attempt:
                    self._record_worker_unaccepted(
                        call_unit, kind, actual_family, exc,
                        "project standing-law fault",
                    )
                st.fail_run(
                    self.state,
                    "%s call: project standing-law fault (never the "
                    "worker's): %s" % (kind, exc),
                    unit=call_unit,
                    type_="orchestrator",
                )
                self._save()
                self._clear_busy()
                raise StopStep(str(exc))
            except (runners.RunnerError, runners.WorkerProtocolError) as exc:
                failed_duration_s = time.time() - physical_started
                actual_family, actual_model, actual_effort = (
                    self._result_identity(
                        exc, call_family, call_model, call_effort
                    )
                )
                self._retain_call_identity(
                    exc, actual_model, actual_effort, actual_family
                )
                if (
                    isinstance(exc, runners.PromptPreparationError)
                    and not getattr(exc, "provider_dispatch_started", False)
                ):
                    completed_attempt = getattr(
                        exc,
                        "completed_attempt_before_dispatch_failure",
                        False,
                    )
                    if completed_attempt:
                        self._require_busy_accounting(
                            kind,
                            actual_family,
                            raw_name,
                            exc,
                            duration_s=failed_duration_s,
                            task_id=task_id,
                            unit=call_unit,
                        )
                        proto_paths = self._save_protocol_raws(raw_name, exc)
                        self._record_fatal_malformed(
                            raw_name,
                            kind,
                            actual_family,
                            exc,
                            proto_paths,
                            duration_s=failed_duration_s,
                            unit=call_unit,
                        )
                    boundary_failure = getattr(
                        exc, "call_boundary_failure", False
                    )
                    st.fail_run(
                        self.state,
                        (
                            "%s dispatch blocked before the worker started: %s"
                            if boundary_failure else
                            "%s prompt preparation failed before dispatch: %s"
                        ) % (kind, exc),
                        unit=call_unit,
                        type_=(
                            "canonical_plan_boundary"
                            if boundary_failure else "orchestrator"
                        ),
                    )
                    self._save()
                    self._clear_busy()
                    raise StopStep(str(exc))
                if (
                    getattr(exc, "call_boundary_failure", False)
                    and not getattr(exc, "provider_dispatch_started", False)
                    and not getattr(
                        exc,
                        "completed_attempt_before_dispatch_failure",
                        False,
                    )
                ):
                    st.fail_run(
                        self.state,
                        "%s dispatch blocked before the worker started: %s"
                        % (kind, exc),
                        unit=call_unit,
                        type_="canonical_plan_boundary",
                    )
                    self._save()
                    self._clear_busy()
                    raise StopStep(str(exc))
                self._require_busy_accounting(
                    kind, actual_family, raw_name, exc,
                    duration_s=failed_duration_s,
                    task_id=task_id,
                    unit=call_unit,
                )
                proto_paths = self._save_protocol_raws(raw_name, exc)
                if getattr(exc, "call_boundary_failure", False):
                    # Repository rejection is terminal for this physical
                    # call even when the transport already accepted a size
                    # interrupt. The rejected work was restored, so it must
                    # never be handed to cutoff stabilization.
                    if cutoff_marker is not None:
                        self._clear_rejected_implementation_stabilization(
                            cutoff_marker, unit=call_unit
                        )
                    self._record_fatal_malformed(
                        raw_name, kind, actual_family, exc, proto_paths,
                        duration_s=failed_duration_s,
                        unit=call_unit,
                    )
                    st.fail_run(
                        self.state,
                        "%s call rejected at the canonical plan boundary: %s"
                        % (kind, exc),
                        unit=call_unit,
                        type_="canonical_plan_boundary",
                    )
                    self._save()
                    self._clear_busy()
                    raise StopStep(str(exc))
                if call_control is not None and call_control.interrupted:
                    # The transport accepted the hard stop. A late transport
                    # or parsing error cannot turn that boundary back into an
                    # initial-draft retry or a run failure: hand the accepted
                    # interruption to the ordinary stabilizer path.
                    st.append_event(
                        self.state,
                        "worker_malformed",
                        unit=self._worker_event_unit(call_unit),
                        label=raw_name,
                        kind=kind,
                        family=actual_family,
                        model=actual_model,
                        effort=actual_effort,
                        fatal=False,
                        controlled_interruption=True,
                        error=str(exc)[:300],
                        duration_s=None,
                        raw_path=(proto_paths or [None])[0],
                        raw_path2=(
                            proto_paths[1]
                            if len(proto_paths) > 1 else None
                        ),
                        **self._prompt_set_fallback_evidence(exc),
                        **self._worker_task_fields(
                            kind=kind, label=raw_name, result=exc
                        ),
                    )
                    raw_texts = list(
                        getattr(exc, "raw_texts", []) or []
                    )
                    result = runners.ControlledInterruptionResult(
                        raw_texts[-1] if raw_texts else "",
                        1,
                        time.time() - physical_started,
                        call_control.interrupt_reason,
                        token_usage=getattr(exc, "token_usage", None),
                        cost_payloads=getattr(exc, "cost_payloads", None),
                    )
                    result.token_usage_partial = bool(
                        getattr(exc, "token_usage_partial", False)
                        or getattr(exc, "token_usage", None) is None
                    )
                    result.cost = getattr(exc, "cost", None)
                    result.cost_partial = bool(
                        getattr(exc, "cost_partial", False)
                        or result.cost is None
                    )
                    result.prompt_set_fallback = getattr(
                        exc, "prompt_set_fallback", None
                    )
                    self._retain_call_identity(
                        result, actual_model, actual_effort, actual_family
                    )
                    break
                if (
                    repeat_protocol
                    and isinstance(exc, runners.WorkerProtocolError)
                ):
                    # A cutoff stabilizer owns an already-interrupted delivery.
                    # A malformed handoff cannot safely open review, but it is
                    # also not a reason to abandon the preserved work. Record
                    # the strike and retry in a fresh provider session until a
                    # valid ordinary implementation envelope is delivered.
                    st.append_event(
                        self.state,
                        "worker_malformed",
                        unit=self._worker_event_unit(call_unit),
                        label=raw_name,
                        kind=kind,
                        family=actual_family,
                        model=actual_model,
                        effort=actual_effort,
                        fatal=False,
                        stabilizer_retry=True,
                        error=str(exc)[:300],
                        duration_s=failed_duration_s,
                        token_usage=copy.deepcopy(
                            getattr(exc, "token_usage", None)
                        ),
                        token_usage_partial=bool(
                            getattr(exc, "token_usage_partial", False)
                            or getattr(exc, "token_usage", None) is None
                        ),
                        cost=copy.deepcopy(getattr(exc, "cost", None)),
                        cost_partial=bool(
                            getattr(exc, "cost_partial", False)
                            or getattr(exc, "cost", None) is None
                        ),
                        raw_path=(proto_paths or [None])[0],
                        raw_path2=(
                            proto_paths[1] if len(proto_paths) > 1 else None
                        ),
                        **self._prompt_set_fallback_evidence(exc),
                        **self._worker_task_fields(
                            kind=kind, label=raw_name, result=exc
                        ),
                    )
                    self._save()
                    # A repeated stabilization is a new worker, not another
                    # continuation of the session that already failed twice.
                    if session_ref is not None:
                        session_ref = None
                        start_session = True
                    continue
                etype, resume_at, evidence = self._classify_failure(
                    actual_family, exc, raw_name=raw_name, unit=call_unit
                )
                if etype in ("network", "busy") and attempt < len(retries):
                    # Short in-place retries BEFORE failing: transient
                    # blips should not cost a run failure + resume cycle.
                    incident = {
                        "unit": self._worker_event_unit(call_unit),
                        "label": raw_name,
                        "kind": kind,
                        "family": actual_family,
                        "model": actual_model,
                        "effort": actual_effort,
                        "fatal": False,
                        "infra_retry": True,
                        "error": str(exc)[:300],
                        "duration_s": failed_duration_s,
                        "token_usage": copy.deepcopy(
                            getattr(exc, "token_usage", None)
                        ),
                        "token_usage_partial": bool(
                            getattr(exc, "token_usage_partial", False)
                            or getattr(exc, "token_usage", None) is None
                        ),
                        "cost": copy.deepcopy(getattr(exc, "cost", None)),
                        "cost_partial": bool(
                            getattr(exc, "cost_partial", False)
                            or getattr(exc, "cost", None) is None
                        ),
                        "raw_path": (proto_paths or [None])[0],
                        "raw_path2": (
                            proto_paths[1]
                            if len(proto_paths) > 1 else None
                        ),
                    }
                    if repeat_protocol:
                        incident["stabilizer_retry"] = True
                    incident.update(self._prompt_set_fallback_evidence(exc))
                    incident.update(self._worker_task_fields(
                        kind=kind, label=raw_name, result=exc
                    ))
                    st.append_event(
                        self.state, "worker_malformed", **incident
                    )
                    st.append_event(
                        self.state, "infra_retry", kind=kind,
                        family=actual_family,
                        failure_type=etype, attempt=attempt + 1,
                        wait_s=retries[attempt],
                    )
                    self._save()
                    self._clear_busy()
                    time.sleep(retries[attempt])
                    attempt += 1
                    continue
                # The call is now definitively FAILING the run: the red
                # incident chip. An absorbed infrastructure blip above gets a
                # non-fatal incident even when the provider exposed no raw
                # bytes, so every retry remains visible and truthful.
                self._record_fatal_malformed(
                    raw_name, kind, actual_family, exc, proto_paths,
                    duration_s=failed_duration_s,
                    unit=call_unit,
                )
                resume_at = errclass.normalize_resume_at(resume_at)
                if etype in errclass.AUTO_RESUMABLE and not resume_at:
                    fallback_min = (
                        30 if etype == "quota"
                        else errclass.TRANSIENT_BACKOFF_MIN
                    )
                    resume_at = errclass.parse_resume_at(
                        "in %d minutes" % fallback_min
                    )
                st.fail_run(
                    self.state,
                    "%s call failed: %s" % (kind, exc),
                    unit=call_unit,
                    type_=etype,
                    resume_at=resume_at,
                    evidence=evidence,
                )
                self._save()
                self._clear_busy()
                raise StopStep(str(exc))
            break
        self._retain_task_id(result, task_id)
        if isinstance(result, runners.ControlledInterruptionResult):
            raw_text = getattr(result, "transport_text", None)
            if not isinstance(raw_text, str) or not raw_text:
                raw_text = result.text
            raw_path = self._save_raw_noclobber(
                raw_name + "-controlled-interruption", raw_text
            )
            actual_family, _actual_model, _actual_effort = (
                self._result_identity(result, call_family, call_model, call_effort)
            )
            self._record_repair(
                raw_name, kind, actual_family, result, unit=call_unit
            )
            result.raw_path = raw_path
            return None, result, raw_path
        raw_path = (
            self._save_raw_noclobber(raw_name, result.text)
            if kind in contracts.REPORT_KINDS
            else self._save_raw(raw_name, result.text)
        )
        actual_family, _actual_model, _actual_effort = self._result_identity(
            result, call_family, call_model, call_effort
        )
        self._record_repair(
            raw_name, kind, actual_family, result, unit=call_unit
        )
        return output, result, raw_path

    def _record_repair(self, raw_name, kind, family, result, unit=None):
        """Permanent trace of a repaired first strike: a worker whose first
        output violated the contract and whose single repair retry then
        validated used to be invisible (no event, no raw, its duration
        unrecorded — the panel's '7 min' call that took 20). The malformed
        text lands in raw/ and a worker_malformed event carries the error,
        the wasted duration, and the raw path — the panel surfaces it as a
        chip; prompt/contract tuning needs these strikes visible."""
        call = self._matching_busy_call(kind, family, raw_name)
        task_fields = self._task_id_fields(call.get("task_id"))
        # BOTH channels, never `or`: a repair retry that itself needed
        # delimiter recovery produced two distinct strikes, and reporting
        # only the first would hide the second.
        for attr in ("repair", "recovered"):
            rep = getattr(result, attr, None)
            if not rep:
                continue
            raw_path = self._save_raw_noclobber(
                "%s-malformed%s"
                % (raw_name, "" if attr == "repair" else "-tail"),
                rep["raw_text"],
            )
            marker = self._read_busy() or {}
            strike_family = rep.get("family") or family
            strike_model = rep.get("model") or marker.get("model")
            strike_effort = rep.get("effort") or call.get("effort")
            strike_cost = self._price_call(
                strike_family, strike_model, rep
            )
            st.append_event(
                self.state,
                "worker_malformed",
                unit=self._worker_event_unit(unit),
                label=raw_name,
                kind=kind,
                family=strike_family,
                model=strike_model,
                effort=strike_effort,
                error=str(rep["error"])[:300],
                # A delimiter recovery costs no retry, so it wasted no
                # time — it still reports as malformed because the output
                # WAS, and the model dropping its brace must stay visible.
                duration_s=rep.get("duration_s"),
                cost=copy.deepcopy(strike_cost),
                # A recovery channel strike made no extra call, so an absent
                # price is "nothing to price", not "could not price it".
                cost_partial=bool(strike_cost is None and attr == "repair"),
                token_usage=copy.deepcopy(rep.get("token_usage")),
                token_usage_partial=bool(
                    rep.get("token_usage_partial", False)
                    or rep.get("token_usage") is None
                ),
                raw_path=raw_path,
                **self._prompt_set_fallback_fields(rep),
                **task_fields,
            )

    def _classify_failure(self, family, exc, raw_name=None, unit=None):
        """Type a failed worker call: deterministic patterns over the raw
        outputs (and the exception text), opposite-family LLM classifier
        as a non-blocking fallback (config error_classifier).

        When the LLM stage runs, its prompt+response (or the error, if the
        classifier call itself failed) are persisted as a
        <raw_name>-classify-<family>.txt artifact so an "unknown" verdict is
        auditable after the fact.

        A surfaced staffing condition met at the classifier's own dispatch is
        DELIBERATELY not promoted to the run's failure. The classifier never
        worsens the failure it is diagnosing (errclass.llm_classify): the run
        keeps naming the primary call that actually failed, with its own
        recovery type, and the condition travels verbatim as that failure's
        `classify_evidence` — which the panel prints on the same failure card
        ("classified via: ..."). Replacing the reason would hide the real
        cause and swap a transient, auto-resumable type for a stop."""
        if self.model_profiles_home is not None:
            # The classifier is a `classify` seat like the debt rater: which
            # family types a failure is the document's choice, not a
            # structural derivation off the family that failed.
            #
            # Resolved by the dispatch hook and NOWHERE else: the LLM stage
            # is a fallback behind the deterministic patterns and behind
            # `error_classifier`, so most failures never reach a classifier
            # call at all. Asking the router here would let a surfaced
            # condition stop a call that was never going to be made — and
            # bury the failure the run actually has under it.
            resolver = self._dispatch_for_role("classify")
            classifier = cls_model = cls_effort = None
        else:
            classifier = self._opposite(family)
            cls_model, cls_effort = self._family_defaults(classifier)
            resolver = self._structural_dispatch(
                classifier, cls_model, cls_effort
            )
        task_id = self._matching_busy_call(label=raw_name).get("task_id")
        return errclass.classify_worker_failure(
            exc,
            runner=self.runner,
            opposite_family=classifier,
            workspace=self.workspace,
            use_llm=bool(self.config.get("error_classifier", True)),
            on_llm_raw=self._classify_raw_saver(raw_name),
            classifier_model=cls_model,
            classifier_effort=cls_effort,
            on_llm_call=self._classify_call_recorder(
                raw_name, task_id, unit=unit
            ),
            on_llm_start=self._classify_call_starter(
                raw_name, task_id, resolver=resolver
            ),
            resolve_dispatch=resolver,
        )

    def _classify_call_starter(self, raw_name, task_id=None, resolver=None):
        """Mark the optional classifier only when its LLM call starts."""
        def _start(call):
            if not self._mark_busy(
                raw_name or "error-classifier",
                "error_classifier",
                call.get("family"),
                model=call.get("model"),
                effort=call.get("effort"),
                nested=True,
                task_id=task_id,
                staffing_fallback=getattr(
                    resolver, "staffing_fallback", None
                ),
            ):
                raise RuntimeError(
                    "classifier accounting marker is unavailable"
                )

        return _start

    def _classify_call_recorder(self, raw_name, task_id=None, unit=None):
        """Own the cost of the optional opposite-family classifier call."""
        def _record(call):
            self._update_busy_accounting(call)
            st.append_event(
                self.state,
                "error_classifier_call",
                unit=self._worker_event_unit(unit),
                label=raw_name,
                family=call.get("family"),
                model=call.get("model"),
                effort=call.get("effort"),
                status=call.get("status"),
                failure_type=call.get("failure_type"),
                error=call.get("error"),
                duration_s=call.get("duration_s"),
                token_usage=copy.deepcopy(call.get("token_usage")),
                token_usage_partial=bool(
                    call.get("token_usage_partial", False)
                    or call.get("token_usage") is None
                ),
                cost=copy.deepcopy(call.get("cost")),
                cost_partial=bool(
                    call.get("cost_partial", False)
                    or call.get("cost") is None
                ),
                prompt_path=call.get("prompt_path"),
                **self._task_id_fields(task_id),
            )

        return _record

    def _classify_raw_saver(self, raw_name):
        """A best-effort sink that persists the failure classifier's I/O.
        Returns None when there is no raw_name to key the artifact on."""
        if not raw_name:
            return None

        def _save(classifier_family, prompt, raw):
            # The family is unknown only when the dispatch never resolved
            # one; the artifact still has to land, since it carries WHY.
            self._save_raw(
                "%s-classify-%s" % (raw_name, classifier_family
                                    or "unresolved"),
                "CLASSIFIER PROMPT\n=================\n%s\n\n"
                "CLASSIFIER RESPONSE\n===================\n%s\n"
                % (prompt, raw if raw is not None else "(no response)"),
            )

        return _save

    def _builders_desc(self):
        """One line naming the run's REAL downstream builders for the
        drift-risk rater: 'who builds on this artifact' is a fact of the
        run, not a hypothetical junior — a fable-5-at-max implementer reads
        an ambiguity very differently than the rater's imagined worst case.

        Homed, those builders are the session's `draft` and `implement`
        seats, so this asks the router: the debt rating is a driver-made
        worker call, and after the cutover no profile, act sidecar or
        config act may decide any part of one or stop it. This is PROMPT
        TEXT for a call whose own staffing resolved above, so a condition
        surfaced on a seat this call does not dispatch withholds its line
        instead of stopping the rating — only `classify`'s own resolution
        may do that. A home-less run keeps today's act derivation, family
        defaults filled in, byte-identical."""
        parts = []
        for role, act, label in (
            ("draft", "drafter", "slice docs drafted by"),
            ("implement", "implementer", "implementation built by"),
        ):
            if self.model_profiles_home is not None:
                try:
                    answer = staffing.resolve(
                        self.model_profiles_home,
                        st.staffing_session(self.state),
                        role,
                        families=list(self.config["families_order"]),
                    ).answer
                except staffing.StaffingConditionError:
                    continue
                fam, model, effort = (
                    answer["agent"], answer["model"], answer["effort"]
                )
            else:
                fam, model, effort = self._act_profile(act)
                dm, de = self._family_defaults(fam)
                model, effort = model or dm, effort or de
            parts.append("%s %s (%s, %s effort)" % (label, fam, model, effort))
        return "; ".join(parts)

    def _enforce_sealed_artifacts(
        self,
        raw_name,
        editable_sealed=None,
        preserve_canonical_plan=False,
    ):
        """SEALED units' doc artifacts are read-only for every edit-kind
        call (found live 2026-07-10: a fixer materially REWROTE the
        sealed slice-02 note to legalize behaviors the sealed version
        forbade, then self-declared the note in its expected files — 50
        rounds of review judged a moving target). After every edit-kind
        call, each sealed unit's artifact must byte-match the run's
        NEWEST gate commit (not HEAD: the amend discipline folds
        tampering into the wip commit, so HEAD can already be tainted;
        and not each unit's OWN gate: sealed docs carry legal post-seal
        drift — pre-guard-era `prevention` edits reviewed and folded
        into later gates, and repair reseals — so the last gate, a
        deterministically sealed checkpoint of the WHOLE tree, is the canonical
        baseline; baselining on the own gate fired three false restores
        on 2026-07-10, each regressing a legally amended note). A
        mismatch is restored from that gate, the illegal bytes land in
        raw/ for forensics, and a sealed_artifact_restored event records
        the violation. Runs without git have no canonical source and
        skip (their sealed docs are protected by the prompt rule only).
        A unit under legitimate repair is not SEALED while it is being
        repaired, so its own repair episode is naturally exempt."""
        if not gitops.enabled(self.config):
            return []
        editable_sealed = set(editable_sealed or ())
        last_gate = gitops.newest_commit(
            self.workspace,
            [u.get("gate_commit") for u in self.state["units"]],
        )
        restored = []
        for u in self.state["units"]:
            if u["status"] != st.U_SEALED:
                continue
            gate, art = u.get("gate_commit"), u.get("artifact")
            if not gate or not art:
                continue
            if art in editable_sealed:
                continue
            canonical = gitops.show_file(
                self.workspace, last_gate or gate, art
            )
            if canonical is None:
                # The artifact is unreadable at the newest gate (e.g. a
                # foreign-history edge): fall back to the unit's own gate.
                canonical = gitops.show_file(self.workspace, gate, art)
            if canonical is None:
                continue  # unreadable gate/path: nothing to enforce against
            if preserve_canonical_plan:
                anchor = self.state["milestone"].get(
                    canonical_plan.ANCHOR_KEY
                ) or {}
                if art == anchor.get("path"):
                    accepted = gitops.show_file(
                        self.workspace, anchor.get("revision"), art
                    )
                    if accepted is None:
                        raise canonical_plan.CanonicalPlanError(
                            "accepted canonical-plan anchor is unreadable"
                        )
                    canonical = canonical_plan.preserve_canonical_block(
                        canonical, accepted
                    )
            path = os.path.join(self.workspace, art)
            try:
                with open(path, "rb") as fh:
                    current = fh.read()
            except OSError:
                current = None  # deleted: also a violation
            if current == canonical:
                continue
            safe = st.unit_key(u).replace("/", "_")
            raw = self._save_raw(
                "%s-sealed-violation-%s" % (raw_name, safe),
                (current if current is not None else b"(file deleted)")
                .decode("utf-8", "replace"),
            )
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(canonical)
            st.append_event(
                self.state, "sealed_artifact_restored",
                unit=st.unit_key(u), artifact=art, during=raw_name,
                raw_path=raw,
            )
            restored.append(art)
        return restored

    @staticmethod
    def _safe_design_path(value):
        if not isinstance(value, str) or not value.strip():
            return None
        value = os.path.normpath(value.strip())
        if os.path.isabs(value) or value in (".", "..") \
                or value.startswith(".." + os.sep):
            return None
        return value

    def _design_correction_offer(self, unit):
        """One-shot semantic exception for a normal implementation fixer."""
        if (
            unit.get("kind") != st.UNIT_SLICE_IMPL
            or unit.get("under_repair")
            or unit.get("design_correction")
            or unit.get("design_correction_attempted")
            or self.state.get("redoc_wave")
            or not interpreter.gap_semantics(self.state)
            or not gitops.enabled(self.config)
        ):
            return None
        note = self._find_unit(st.UNIT_SLICE_DOC, unit.get("slice_id"))
        if note is None or note.get("status") != st.U_SEALED \
                or not note.get("gate_commit"):
            return None
        return {
            "mode": "offer",
            "artifact": note.get("artifact")
            or self._slice_note_artifact(unit["slice_id"]),
            "note_unit": st.unit_key(note),
            "authority_gate": note["gate_commit"],
        }

    def _design_correction_context(self, unit):
        correction = unit.get("design_correction") or {}
        if correction.get("phase") == "proposed":
            return {"mode": "active", **correction}
        return self._design_correction_offer(unit)

    def _workspace_bytes(self, relpath):
        try:
            with open(os.path.join(self.workspace, relpath), "rb") as fh:
                return fh.read()
        except OSError:
            return None

    def _start_design_correction(
        self, unit, declaration, files_changed, offer,
        pre_refs, pre_sym, pre_head, pre_tree, pre_worktree_tree, pre_stash,
        brainstorming_handoff=None,
    ):
        """Validate the mechanical envelope; semantic judgment is next."""
        baseline = {
            "refs": pre_refs,
            "sym": pre_sym,
            "head": pre_head,
            "tree": pre_worktree_tree,
            "index_tree": pre_tree,
            "stash": pre_stash,
        }
        candidate = {
            "phase": "proposed",
            "baseline": baseline,
            "original_fix_queue": copy.deepcopy(unit.get("fix_queue") or []),
            "original_fix_source": copy.deepcopy(unit.get("fix_source")),
            "original_fix_loop_rounds": int(unit.get("fix_loop_rounds") or 0),
        }
        if offer is None or offer.get("mode") != "offer":
            return candidate, "the one-shot correction envelope is not open"
        if any(value is None for value in (
            pre_refs, pre_sym, pre_head, pre_tree, pre_worktree_tree,
        )):
            return candidate, "the normal pre-fix Git snapshot is unavailable"
        artifact = self._safe_design_path(declaration.get("artifact"))
        authority = self._safe_design_path(declaration.get("authority_artifact"))
        brainstorming_authority = declaration.get("brainstorming_authority")
        expected = self._safe_design_path(offer.get("artifact"))
        if artifact != expected:
            return candidate, "only the implementation's own slice note is editable"
        changed = {
            self._safe_design_path(path) for path in (files_changed or [])
        }
        if artifact not in changed:
            return candidate, "the corrected note is absent from files_changed"
        note_before = gitops.show_file(self.workspace, pre_head, artifact)
        note_after = self._workspace_bytes(artifact)
        if note_before is None or note_after is None or note_before == note_after:
            return candidate, "the proposed correction did not change its note"

        if brainstorming_authority is not None:
            handoff = brainstorming_handoff or {}
            expected_authority = {
                "session_id": handoff.get("session_id"),
                "accepted_target_revision": handoff.get(
                    "accepted_target_revision"
                ),
            }
            if not brainstorming._same_json_value(
                brainstorming_authority, expected_authority
            ):
                return candidate, (
                    "Brainstorming authority does not match the recorded handoff"
                )
            try:
                authority_record = brainstorming_milestone.retained_revision(
                    self.state,
                    brainstorming_authority["session_id"],
                    brainstorming_authority["accepted_target_revision"],
                    active_home=self.model_profiles_home,
                )
                checked_record = brainstorming.validate_target_revision(
                    authority_record
                )
                authority_exists, authority_before = (
                    brainstorming.target_revision_content(checked_record)
                )
            except Exception:
                authority_exists, authority_before = False, None
            if not authority_exists or authority_before is None:
                return candidate, (
                    "the recorded Brainstorming authority has no proposal content"
                )
            authority = (handoff.get("result") or {}).get("target_ref")
            candidate["brainstorming_authority"] = copy.deepcopy(
                brainstorming_authority
            )
        else:
            if authority is None or authority == artifact:
                return candidate, (
                    "authority must be one different pre-existing artifact"
                )
            authority_gate = offer.get("authority_gate")
            authority_before = gitops.show_file(
                self.workspace, authority_gate, authority
            )
            if authority_before is None:
                return candidate, (
                    "the cited authority did not predate the sealed note"
                )
            if (
                gitops.show_file(self.workspace, pre_head, authority)
                != authority_before
                or self._workspace_bytes(authority) != authority_before
            ):
                return candidate, (
                    "the cited authority is not unchanged and pre-existing"
                )
        candidate.update({
            "artifact": artifact,
            "note_unit": offer["note_unit"],
            "authority_artifact": authority,
            "authority_sha256": hashlib.sha256(authority_before).hexdigest(),
            "original_note_sha256": hashlib.sha256(note_before).hexdigest(),
            "contradiction": declaration["contradiction"],
            "resolution": declaration["resolution"],
        })
        unit["design_correction"] = candidate
        unit["design_correction_attempted"] = True
        st.append_event(
            self.state,
            "design_correction_proposed",
            unit=st.unit_key(unit),
            artifact=artifact,
            authority_artifact=authority,
        )
        return candidate, None

    def _design_correction_integrity_error(self, correction):
        brainstorming_authority = (correction or {}).get(
            "brainstorming_authority"
        )
        if brainstorming_authority is not None:
            try:
                authority_record = brainstorming_milestone.retained_revision(
                    self.state,
                    brainstorming_authority["session_id"],
                    brainstorming_authority["accepted_target_revision"],
                    active_home=self.model_profiles_home,
                )
                exists, content = brainstorming.target_revision_content(
                    authority_record
                )
            except Exception:
                exists, content = False, None
            if (
                not exists
                or content is None
                or hashlib.sha256(content).hexdigest()
                != (correction or {}).get("authority_sha256")
            ):
                return (
                    "the retained Brainstorming authority changed or became "
                    "unavailable while the correction was provisional"
                )
            return None
        authority = self._safe_design_path(
            (correction or {}).get("authority_artifact")
        )
        content = self._workspace_bytes(authority) if authority else None
        if content is None or hashlib.sha256(content).hexdigest() != (
            correction or {}
        ).get("authority_sha256"):
            return "the cited authority changed while the correction was provisional"
        return None

    def _design_correction_review_context(self, correction):
        """Expose retained Brainstorming authority only to the review prompt."""
        context = copy.deepcopy(correction)
        authority = context.get("brainstorming_authority")
        if authority is None:
            return context
        record = brainstorming_milestone.retained_revision(
            self.state,
            authority["session_id"],
            authority["accepted_target_revision"],
            active_home=self.model_profiles_home,
        )
        exists, content = brainstorming.target_revision_content(record)
        if not exists:
            raise brainstorming_milestone.AdapterError(
                "the retained Brainstorming authority is absent"
            )
        try:
            context["retained_authority_content"] = content.decode("utf-8")
            context["retained_authority_encoding"] = "utf-8"
        except UnicodeDecodeError:
            context["retained_authority_content"] = base64.b64encode(
                content
            ).decode("ascii")
            context["retained_authority_encoding"] = "base64"
        return context

    def _rollback_design_correction(
        self, unit, reason, correction=None, abandon_active_task=False
    ):
        """Discard the provisional fixer delta and retry without authority."""
        correction = correction or unit.get("design_correction") or {}
        if abandon_active_task:
            reference = unit.get("active_task")
            if isinstance(reference, dict):
                task_id = reference.get("id")
                native_result = None
                resume = unit.get("brainstorming_resume")
                if (
                    isinstance(resume, dict)
                    and resume.get("kind") == reference.get("kind")
                    and resume.get("task_id") in (None, task_id)
                ):
                    if resume.get("task_id") == task_id:
                        native_result = copy.deepcopy(
                            resume.get("origin_rethink_signal")
                        )
                        # The continuation call completed and its accounting
                        # is durable only in this carrier until ordinary
                        # consumption records a draft/round.  Abandonment is
                        # that carrier's terminal consumer, so move the known
                        # charge into the existing unaccepted-call home before
                        # deleting it.  Task and unit/run projections then see
                        # the same underlying call once.
                        self._record_worker_unaccepted(
                            unit,
                            resume["kind"],
                            resume.get("family"),
                            self._resume_result(resume),
                            "completed continuation abandoned because "
                            "provisional design authority became unusable",
                        )
                    unit.pop("brainstorming_resume", None)
                self._fail_worker_task_if_open(
                    unit,
                    native_result,
                    task_id=task_id,
                    reason=(
                        "provisional design authority became unusable before "
                        "the Worker invocation completed: %s" % reason
                    ),
                )
        baseline = correction.get("baseline") or {}
        try:
            gitops.restore_to_snapshot(
                self.workspace,
                baseline["refs"],
                baseline["sym"],
                baseline["head"],
                baseline["tree"],
                stash=baseline.get("stash"),
            )
            gitops.restore_index_tree(
                self.workspace, baseline.get("index_tree") or baseline["tree"]
            )
        except (KeyError, TypeError, gitops.GitError) as exc:
            st.fail_run(
                self.state,
                "design correction rollback failed: %s" % exc,
                unit=unit,
                type_="gap_cleanup",
            )
            self._save()
            raise StopStep("design correction rollback failed")
        unit["design_correction"] = None
        unit["design_correction_attempted"] = True
        unit["fix_queue"] = copy.deepcopy(
            correction.get("original_fix_queue") or []
        )
        unit["fix_source"] = copy.deepcopy(
            correction.get("original_fix_source")
        )
        unit["fix_loop_rounds"] = int(
            correction.get("original_fix_loop_rounds") or 0
        )
        if unit.get("status") != st.U_FIXING:
            st.transition_unit(
                self.state, unit, st.U_FIXING,
                reason="design correction rejected; retry without exception",
            )
        st.append_event(
            self.state,
            "design_correction_rolled_back",
            unit=st.unit_key(unit),
            reason=str(reason or "")[:300],
        )
        return "design correction rejected; fixer retries without exception"

    @staticmethod
    def _design_correction_gap(correction, decision, reason):
        return {
            "classification": (
                contracts.CLASSIFY_NEEDS_OPERATOR
                if decision == "needs_operator"
                else contracts.CLASSIFY_FITS_REMODEL
            ),
            "missing_or_conflict": correction.get("contradiction"),
            "where": correction.get("artifact"),
            "forced_decision": reason,
            "plain": correction.get("contradiction"),
            "example": correction.get("resolution"),
            "proposal": correction.get("resolution"),
        }

    def _ratify_design_correction(self, unit, correction, verdict, return_to):
        note = self._unit_by_key(correction.get("note_unit"))
        content = self._workspace_bytes(correction.get("artifact"))
        if note is None or content is None:
            st.fail_run(
                self.state, "ratified design correction lost its note", unit=unit
            )
            self._save()
            raise StopStep("ratified correction note missing")
        if hashlib.sha256(content).hexdigest() == correction.get(
            "original_note_sha256"
        ):
            return self._rollback_design_correction(
                unit,
                "the correction reviewer ratified an unchanged governing note",
                correction,
            )
        try:
            note_sha, sha = gitops.ratify_note_correction(
                self.workspace,
                correction["artifact"],
                note["gate_commit"],
                "Ratify slice %02d note correction" % unit["slice_id"],
            )
        except gitops.GitError as exc:
            st.fail_run(self.state, "ratification failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        correction["phase"] = "ratified"
        correction["approved_sha256"] = hashlib.sha256(content).hexdigest()
        correction["ratified_commit"] = note_sha
        correction["verdict_reason"] = verdict.get("reason")
        for key in (
            "baseline", "original_fix_queue", "original_fix_source",
            "original_fix_loop_rounds",
        ):
            correction.pop(key, None)
        note["gate_commit"] = note_sha
        st.append_event(self.state, "amended", unit=st.unit_key(unit), sha=sha)
        st.append_event(
            self.state,
            "design_correction_ratified",
            unit=st.unit_key(unit),
            artifact=correction.get("artifact"),
            sha=sha,
            note_sha=note_sha,
            reason=str(verdict.get("reason") or "")[:300],
        )
        unit["fix_queue"] = []
        unit["fix_source"] = None
        unit.pop("phantom_retried", None)
        st.restart_reviews_after_candidate_change(
            self.state, unit, "ratified design correction changed bytes"
        )
        return_to = st.U_PRE_REVIEW_VERIFY
        st.transition_unit(
            self.state, unit, return_to,
            reason="own-note correction independently ratified",
        )
        return "design correction ratified; amended (%s)" % sha

    def _maybe_update_slices(self, unit, output):
        """Keep a legitimately edited skeleton table aligned with state."""
        slices = output.get("slices")
        if not slices or (
            unit["kind"] != st.UNIT_SKELETON
            and not unit.get("design_update")
        ):
            return False
        slices = copy.deepcopy(slices)
        contracts.validate_slices(slices, "replacement slice plan")
        if unit["kind"] != st.UNIT_SKELETON:
            before = list(self.state["milestone"]["slices"])
            old_ids = [item["id"] for item in before]
            new_ids = [item["id"] for item in slices]
            if [value for value in new_ids if value in old_ids] != old_ids:
                reason = (
                    "a lightweight design update may insert future slices, "
                    "but may not remove, renumber, or reorder existing ones"
                )
                st.fail_run(self.state, reason, unit=unit)
                self._save()
                raise StopStep(reason)
            current_id = unit.get("slice_id")
            if current_id in new_ids:
                current_index = new_ids.index(current_id)
                additions_before_current = [
                    value for value in new_ids[:current_index]
                    if value not in old_ids
                ]
                if additions_before_current:
                    reason = (
                        "a lightweight design update may not insert work "
                        "before the slice currently being completed"
                    )
                    st.fail_run(self.state, reason, unit=unit)
                    self._save()
                    raise StopStep(reason)
        if slices != self.state["milestone"]["slices"]:
            self.state["milestone"]["slices"] = [dict(sl) for sl in slices]
            st.append_event(
                self.state,
                "slices_updated",
                unit=st.unit_key(unit),
                slices=copy.deepcopy(self.state["milestone"]["slices"]),
            )
            return True
        return False

    def _brainstorming_references(self, unit, signal):
        return brainstorming_milestone.stable_references(
            self.state,
            [
                ledgers.goal_path(self.state),
                self._skeleton_artifact(),
                self._governing(unit),
                unit.get("artifact"),
            ],
            signal["target_path"],
        )

    @staticmethod
    def _rethink_requests_design_amendment(signal):
        return (
            signal.get("result_mode")
            == contracts.RETHINK_RESULT_DESIGN_AMENDMENT
        )

    def _adopt_brainstorming_design_amendment(
        self, unit, wait, handoff
    ):
        """Persist one accepted, bounded amendment in the append-only ledger."""
        for event in self.state.get("events", []):
            if (
                event.get("type")
                == "brainstorming_design_amendment_adopted"
                and event.get("session_id") == handoff.get("session_id")
                and event.get("accepted_target_revision")
                == handoff.get("accepted_target_revision")
            ):
                return event
        retained = handoff.get("retained_target") or {}
        content = retained.get("content")
        if (
            retained.get("exists") is not True
            or retained.get("encoding") != "utf-8"
            or not isinstance(content, str)
        ):
            raise brainstorming_milestone.AdapterError(
                "an accepted design amendment must be one UTF-8 text artifact"
            )
        text = content
        if (
            not text.strip()
            or any(
                placeholder.strip() in text
                for placeholder in (
                    brainstorming_milestone.DESIGN_AMENDMENT_PLACEHOLDERS
                )
            )
        ):
            raise brainstorming_milestone.AdapterError(
                "the accepted design amendment still contains only its "
                "placeholder"
            )
        if "\x00" in text:
            raise brainstorming_milestone.AdapterError(
                "the accepted design amendment must be UTF-8 text without "
                "NUL bytes"
            )
        number = 1 + sum(
            event.get("type") == "brainstorming_design_amendment_adopted"
            for event in self.state.get("events", [])
        )
        source = wait["signal"].get("finding") or {}
        event = st.append_event(
            self.state,
            "brainstorming_design_amendment_adopted",
            unit=st.unit_key(unit),
            amendment_id="B%d" % number,
            text=text,
            session_id=handoff["session_id"],
            accepted_target_revision=handoff["accepted_target_revision"],
            source_finding_id=source.get("id"),
            target_path=wait["signal"].get("target_path"),
        )
        if unit.get("rounds"):
            st.restart_reviews_after_candidate_change(
                self.state, unit, "accepted Brainstorming design amendment"
            )
        return event

    def _design_document_paths(self):
        """Existing worker-authored design documents, in plan order."""
        paths = []
        by_key = {
            (candidate["kind"], candidate["slice_id"]): candidate
            for candidate in self.state.get("units") or []
        }
        for kind, slice_id in st.planned_units(self.state):
            if kind not in (st.UNIT_SKELETON, st.UNIT_SLICE_DOC):
                continue
            candidate = by_key.get((kind, slice_id))
            path = (candidate or {}).get("artifact")
            if not path:
                path = (
                    ledgers.skeleton_path(self.state)
                    if kind == st.UNIT_SKELETON
                    else ledgers.slice_note_path(self.state, slice_id)
                )
            if os.path.isfile(os.path.join(self.workspace, path)):
                paths.append(path)
        return paths

    def _activate_design_update(self, unit, handoff, amendment_event):
        """Authorize ordinary reviewable document edits after agreement."""
        previous = unit.get("design_update") or {}
        editable_paths = list(previous.get("editable_paths") or [])
        for path in self._design_document_paths():
            if path not in editable_paths:
                editable_paths.append(path)
        update = {
            "session_id": handoff["session_id"],
            "accepted_target_revision": handoff[
                "accepted_target_revision"
            ],
            "amendment_id": amendment_event.get("amendment_id"),
            "amendment": amendment_event.get("text"),
            "editable_paths": editable_paths,
        }
        if previous.get("changed_paths"):
            update["changed_paths"] = list(previous["changed_paths"])
        unit["design_update"] = update
        st.append_event(
            self.state,
            "brainstorming_design_update_authorized",
            unit=st.unit_key(unit),
            session_id=update["session_id"],
            accepted_target_revision=update["accepted_target_revision"],
            editable_paths=list(update["editable_paths"]),
        )
        return update

    @staticmethod
    def _editable_design_paths(unit):
        update = unit.get("design_update") or {}
        return list(update.get("editable_paths") or [])

    @staticmethod
    def _design_review_paths(unit):
        update = unit.get("design_update") or {}
        return list(update.get("changed_paths") or [])

    def _record_design_changes(self, unit, changed_paths):
        update = unit.get("design_update") or {}
        allowed = set(update.get("editable_paths") or [])
        changed = [path for path in changed_paths if path in allowed]
        if not changed:
            return
        merged = list(update.get("changed_paths") or [])
        for path in changed:
            if path not in merged:
                merged.append(path)
        update["changed_paths"] = merged
        unit["design_update"] = update

    def _design_amendment_finding_id(self, result):
        handoff = getattr(result, "brainstorming_handoff", None) or {}
        for event in reversed(self.state.get("events", [])):
            if (
                event.get("type")
                == "brainstorming_design_amendment_adopted"
                and event.get("session_id") == handoff.get("session_id")
                and event.get("accepted_target_revision")
                == handoff.get("accepted_target_revision")
            ):
                return event.get("source_finding_id")
        return None

    def _start_rethink(
        self,
        unit,
        kind,
        family,
        model,
        effort,
        signal,
        result,
        raw_path,
        raw_name,
        pre_snapshot=None,
    ):
        """Attach one non-completing worker signal to an independent session."""
        st.append_event(
            self.state,
            "brainstorming_origin_recorded",
            unit=st.unit_key(unit),
            kind=kind,
            family=family,
            model=model,
            effort=effort,
            raw_path=raw_path,
            duration_s=result.duration_s,
            token_usage=copy.deepcopy(getattr(result, "token_usage", None)),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=copy.deepcopy(getattr(result, "cost", None)),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            **self._prompt_set_fallback_fields(result),
            **self._worker_task_fields(
                kind=kind, family=family, label=raw_name, result=result
            ),
        )
        try:
            checked = brainstorming_milestone.validate_origin_signal(
                signal,
                kind,
                queued_findings=unit.get("fix_queue") or [],
            )
            if kind in contracts.REPORT_KINDS:
                self._validate_contests(
                    unit,
                    {"findings": [copy.deepcopy(checked["finding"])]},
                    kind,
                )
                self._terminalize_worker_task(
                    unit,
                    signal,
                    result=result,
                    status="failure",
                    reason=(
                        "%s requested design help instead of returning its "
                        "contracted review" % kind
                    ),
                )
                # A review origin is terminal before the independent discussion
                # is attached. Later review work must admit a fresh task.
        except StopStep:
            self._fail_worker_task_if_open(
                unit,
                signal,
                result=result,
                reason="need_rethink attachment failed",
            )
            self._save()
            raise
        except Exception as exc:
            self._fail_worker_task_if_open(
                unit,
                signal,
                result=result,
                reason="need_rethink attachment failed: %s" % exc,
            )
            st.fail_run(
                self.state,
                "need_rethink could not create its independent session: %s"
                % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming session creation failed")

        # The paid origin call is complete before session creation begins.
        # Persist its accounting now so a crash in the independent-session
        # handoff cannot erase it. A non-continuable review's failed task result
        # is part of this same write: no restart may reuse that task id merely
        # because the discussion was not attached yet.
        self._save()
        try:
            provider_ref = getattr(result, "session_ref", None)
            if (
                kind in contracts.RETHINK_CONTINUATION_KINDS
                and (
                    not isinstance(provider_ref, str)
                    or not provider_ref.strip()
                )
            ):
                raise brainstorming_milestone.AdapterError(
                    "the origin provider exposed no explicit session reference"
                )
            references = self._brainstorming_references(unit, checked)
            authority_context = {
                "amendments": self._amendments(
                    record_seen=False, unit=unit
                ),
            }
            if self._rethink_requests_design_amendment(checked):
                # The attached discussion is independent non-Worker activity.
                # Its briefing reads project law when the session starts; the
                # origin task's frozen context governs only Worker execution.
                project_context, _extensions, _roots = (
                    self._project_prompt_inputs(
                        unit, kind, record_seen=False
                    )
                )
                authority_context.update({
                    "goal": self.state.get("goal"),
                    "project_context": project_context,
                })
            staffing_selection = self._brainstorming_staffing()
            lead_profile = counterpart_profile = None
            if staffing_selection is None:
                lead_profile, counterpart_profile = (
                    self._brainstorming_profiles()
                )
            created = brainstorming_milestone.create_session(
                self.state,
                self.config,
                st.unit_key(unit),
                checked,
                references,
                authority_context=authority_context,
                lead_profile=lead_profile,
                counterpart_profile=counterpart_profile,
                staffing_selection=staffing_selection,
                active_home=self.model_profiles_home,
            )
            progress = brainstorming.coordination_projection(created["state"])
            if (
                progress is None
                or progress["accepted_target_revision"] is not None
                or not progress["recovery_baseline_revision"]
            ):
                raise brainstorming_milestone.AdapterError(
                    "Brainstorming creation did not expose an unaccepted "
                    "recovery baseline"
                )
        except StopStep:
            # The origin call was already recorded above. Persist only the
            # structural failure here; report/fix callers instead add their
            # worker_unaccepted accounting before their single save.
            self._fail_worker_task_if_open(
                unit,
                signal,
                result=result,
                reason="need_rethink attachment failed",
            )
            self._save()
            raise
        except Exception as exc:
            self._fail_worker_task_if_open(
                unit,
                signal,
                result=result,
                reason="need_rethink attachment failed: %s" % exc,
            )
            st.fail_run(
                self.state,
                "need_rethink could not create its independent session: %s"
                % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming session creation failed")

        unit["brainstorming_wait"] = {
            "session_id": created["id"],
            "signal": copy.deepcopy(checked),
            "references": list(references),
            "origin": {
                "unit": st.unit_key(unit),
                "kind": kind,
                "family": family,
                "model": model,
                "effort": effort,
                "provider_session_ref": provider_ref,
                "provider_session_token_usage": copy.deepcopy(
                    getattr(result, "session_token_usage", None)
                ),
                # The raw CUMULATIVE snapshot, so a continuation after a
                # restart can still subtract instead of pricing as unknown.
                # It must be the session twin, not cost_payloads[-1]: that
                # list is rewritten to the per-turn delta, and persisting a
                # delta as a baseline re-charges the whole session on resume.
                # Codex only -- nothing else consumes it, and Claude's payload
                # is a whole worker envelope.
                "provider_session_cost_payload": copy.deepcopy(
                    getattr(result, "session_cost_payload", None)
                    if family == "codex" else None
                ),
                "raw_path": raw_path,
                "raw_name": raw_name,
                "duration_s": result.duration_s,
                "pre_snapshot": copy.deepcopy(pre_snapshot),
                **self._prompt_set_fallback_fields(result),
                **self._worker_task_fields(
                    kind=kind, family=family, label=raw_name, result=result
                ),
            },
        }
        st.append_event(
            self.state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind=kind,
            family=family,
            session_id=created["id"],
            target_path=checked["target_path"],
        )
        # The independent process is already live. Persist its attachment
        # before returning to the outer step so a later crash cannot leave a
        # successfully launched session invisible to its milestone.
        self._save()
        return "started Brainstorming session %s" % created["id"]

    @staticmethod
    def _resume_result(record):
        result = runners.RunnerResult(
            record.get("text", ""),
            0,
            record.get("duration_s", 0),
            token_usage=record.get("token_usage"),
        )
        result.token_usage_partial = bool(
            record.get("token_usage_partial", False)
            or record.get("token_usage") is None
        )
        result.cost = record.get("cost")
        result.cost_partial = bool(
            record.get("cost_partial", False) or result.cost is None
        )
        result.session_ref = record.get("provider_session_ref")
        result.brainstorming_handoff = copy.deepcopy(record.get("handoff"))
        result.origin_family = record.get("family")
        result.origin_model = record.get("model")
        result.origin_effort = record.get("effort")
        result.origin_pre_snapshot = copy.deepcopy(record.get("pre_snapshot"))
        result.prompt_set_fallback = record.get("prompt_set_fallback")
        if record.get("origin_rethink_signal") is not None:
            result.origin_rethink_signal = copy.deepcopy(
                record["origin_rethink_signal"]
            )
        result.brainstorming_workspace_changed = bool(
            record.get("workspace_changed")
        )
        result.brainstorming_baseline_fingerprint = record.get(
            "baseline_fingerprint"
        )
        if record.get("task_id") is not None:
            result.task_id = record["task_id"]
        return result

    def _take_brainstorming_resume(self, unit, kind):
        record = unit.get("brainstorming_resume")
        if not record:
            return None
        if record.get("kind") != kind:
            raise st.IllegalTransition(
                "Brainstorming continuation kind does not match current action"
            )
        unit.pop("brainstorming_resume", None)
        return (
            copy.deepcopy(record["output"]),
            self._resume_result(record),
            record["raw_path"],
        )

    def _brainstorming_application_handoff(self, unit):
        record = self._fixer_brainstorming_agreement(unit)
        if not record or record.get("applied"):
            return None
        handoff = brainstorming_milestone.prompt_handoff(
            self.state,
            record["handoff"],
            active_home=self.model_profiles_home,
        )
        handoff["source_finding"] = copy.deepcopy(
            record["source_finding"]
        )
        return handoff

    @staticmethod
    def _fixer_brainstorming_agreement(unit, result=None):
        record = (unit.get("fix_source") or {}).get(
            "brainstorming_agreement"
        )
        if record:
            return record
        handoff = getattr(result, "brainstorming_handoff", None)
        signal = getattr(result, "origin_rethink_signal", None)
        if handoff and isinstance(signal, dict) and signal.get("finding"):
            agreement = {
                "origin_kind": contracts.KIND_FIX_FINDINGS,
                "target_path": signal.get("target_path"),
                "handoff": handoff,
                "source_finding": signal["finding"],
                "continuation": True,
                "baseline_fingerprint": getattr(
                    result, "brainstorming_baseline_fingerprint", None
                ),
            }
            source = unit.get("fix_source")
            if isinstance(source, dict):
                source["brainstorming_agreement"] = agreement
            return agreement
        return None

    def _validate_brainstorming_application_claim(
        self, unit, output, result, workspace_changed
    ):
        claim = output.get("brainstorming_application")
        if claim is None:
            return None
        agreement = self._fixer_brainstorming_agreement(unit, result)
        if not agreement or agreement.get("applied"):
            raise contracts.ContractError(
                "brainstorming_application requires one pending accepted "
                "Brainstorming result"
            )
        source_id = (agreement.get("source_finding") or {}).get("id")
        if claim.get("finding_id") != source_id:
            raise contracts.ContractError(
                "brainstorming_application.finding_id must name the source "
                "finding %r" % source_id
            )
        matching = [
            finding for finding in output.get("findings") or []
            if finding.get("id") == source_id
        ]
        if (
            len(matching) != 1
            or matching[0].get("disposition") not in (
                "fixed", "rejected", "rejected_adjudicated"
            )
        ):
            raise contracts.ContractError(
                "brainstorming_application without implementation requires "
                "a completed disposition for the source finding"
            )
        other_implemented = any(
            finding.get("id") != source_id
            and (
                finding.get("disposition") == "fixed"
                or finding.get("prevention")
            )
            for finding in output.get("findings") or []
        )
        source_state_claim = bool(
            output.get("suite_command_finding_id") == source_id
            or (
                ("slices" in output or "design_correction" in output)
                and not other_implemented
            )
        )
        if matching[0].get("prevention") or source_state_claim or (
            (workspace_changed or output.get("files_changed"))
            and not other_implemented
        ):
            raise contracts.ContractError(
                "brainstorming_application says implementation_required "
                "false but the fixer attributed workspace or milestone state "
                "changes to its source finding"
            )
        return source_id

    def _adopt_brainstorming_no_implementation_resolution(
        self, unit, output, result, finding_id
    ):
        """Persist a valid finding resolved by agreement without workspace work."""
        if finding_id is None:
            return None
        agreement = self._fixer_brainstorming_agreement(unit, result)
        handoff = agreement["handoff"]
        session_id = handoff.get("session_id")
        revision = handoff.get("accepted_target_revision")
        for event in self.state.get("events") or []:
            if (
                event.get("type")
                == "brainstorming_no_implementation_adopted"
                and event.get("session_id") == session_id
                and event.get("accepted_target_revision") == revision
                and event.get("source_finding_id") == finding_id
            ):
                return event
        source = agreement.get("source_finding") or {}
        claim = output["brainstorming_application"]
        number = 1 + sum(
            event.get("type")
            == "brainstorming_no_implementation_adopted"
            for event in self.state.get("events") or []
        )
        text = (
            "Finding %s (%s) is settled by the accepted Brainstorming "
            "result without workspace implementation: %s Do not report "
            "the absence of an implementation as a defect unless new "
            "evidence changes this decision."
            % (
                finding_id,
                str(source.get("summary") or "accepted decision").strip(),
                claim["reason"].strip(),
            )
        )
        return st.append_event(
            self.state,
            "brainstorming_no_implementation_adopted",
            unit=st.unit_key(unit),
            amendment_id="BSR-%d" % number,
            text=text,
            session_id=session_id,
            accepted_target_revision=revision,
            source_finding_id=finding_id,
        )

    def _mark_brainstorming_application_applied(
        self, unit, output, result=None, workspace_changed=False,
        state_changed=False,
    ):
        """Stop reissuing an agreement once its fixer honestly completes it."""
        agreement = self._fixer_brainstorming_agreement(unit, result)
        if not agreement or agreement.get("applied"):
            return
        source_id = (agreement.get("source_finding") or {}).get("id")
        finding_result = next(
            (
                finding for finding in output.get("findings") or []
                if finding.get("id") == source_id
            ),
            None,
        )
        implemented = bool(
            finding_result
            and finding_result.get("disposition") == "fixed"
            and (workspace_changed or state_changed)
        )
        prevention_applied = bool(
            finding_result
            and finding_result.get("disposition") in (
                "rejected", "rejected_adjudicated"
            )
            and finding_result.get("prevention")
            and workspace_changed
        )
        completed_state_task = bool(
            state_changed and finding_result is None
        )
        no_implementation = bool(
            (output.get("brainstorming_application") or {}).get(
                "finding_id"
            ) == source_id
        )
        if not (
            implemented
            or prevention_applied
            or completed_state_task
            or no_implementation
        ):
            return
        self._retire_unused_brainstorming_target_authorization(
            unit, agreement
        )
        agreement["applied"] = True
        st.append_event(
            self.state,
            "brainstorming_implementation_applied",
            unit=st.unit_key(unit),
            session_id=agreement["handoff"].get("session_id"),
            accepted_target_revision=agreement["handoff"].get(
                "accepted_target_revision"
            ),
            workspace_changed=bool(workspace_changed),
            state_changed=bool(state_changed),
            no_workspace_change=bool(
                no_implementation
            ),
        )

    @staticmethod
    def _consume_persisted_review_handoff(unit):
        record = unit.get("brainstorming_review_handoff")
        if not record:
            return
        reserved = record.get("reserved_handoff")
        if reserved is None:
            unit.pop("brainstorming_review_handoff", None)
        else:
            unit["brainstorming_review_handoff"] = copy.deepcopy(reserved)

    def _fixer_gap_enabled(self, unit):
        """One shared eligibility gate for advertised and routed fixer gaps."""
        return (
            self._legacy_gap_enabled()
            and gitops.enabled(self.config)
            and not unit.get("under_repair")
            and unit["kind"] != st.UNIT_SKELETON
        )

    @staticmethod
    def _rethink_finding_for_fix(finding):
        return copy.deepcopy(finding)

    def _route_rethink_report_failure(self, unit, wait):
        kind = wait["origin"]["kind"]
        self._enter_rethink_report_fix(
            unit,
            kind,
            wait["origin"].get("family"),
            wait["session_id"],
            wait["signal"]["finding"],
        )

    def _enter_rethink_report_fix(
        self, unit, kind, family, session_id, finding
    ):
        """Enter the ordinary fixer while preserving a delta's return edge."""
        old_source = copy.deepcopy(unit.get("fix_source") or {})
        old_fix_loop_rounds = int(unit.get("fix_loop_rounds") or 0)
        source_type = {
            contracts.KIND_REVIEW_ROUND: "round",
            contracts.KIND_DELTA_REVIEW: "delta",
        }[kind]
        return_to = {
            contracts.KIND_REVIEW_ROUND: st.U_ROUNDS,
            contracts.KIND_DELTA_REVIEW: (
                old_source.get("return_to") or st.U_PRE_REVIEW_VERIFY
            ),
        }[kind]
        st.enter_fix_episode(
            self.state,
            unit,
            [self._rethink_finding_for_fix(finding)],
            source_type,
            family,
            "brainstorming:%s" % session_id,
            return_to,
        )
        if kind == contracts.KIND_DELTA_REVIEW and old_source:
            unit["fix_source"]["origin_type"] = old_source.get(
                "origin_type", old_source.get("type", "delta")
            )
            try:
                max_fix_loops = int(self.config.get("max_fix_loops", 6))
            except (TypeError, ValueError):
                max_fix_loops = 6
            preserved_rounds = max(old_fix_loop_rounds, 1)
            if max_fix_loops > 0:
                preserved_rounds = min(
                    preserved_rounds, max_fix_loops - 1
                )
            unit["fix_loop_rounds"] = preserved_rounds
            unit["fix_source"]["preserve_dirty_on_killed_fix"] = True

    def _authorize_brainstorming_application_target(
        self, unit, target_path, handoff
    ):
        """Make only an agreed design target editable for this unit."""
        if (
            not target_path
            or target_path == unit.get("artifact")
            or target_path not in self._design_document_paths()
        ):
            return None
        previous = unit.get("design_update")
        update = copy.deepcopy(previous or {})
        editable = list(update.get("editable_paths") or [])
        if target_path in editable:
            return None
        authorization = {
            "target_path": target_path,
            "created_update": previous is None,
            "added_session_id": "session_id" not in update,
            "added_accepted_target_revision": (
                "accepted_target_revision" not in update
            ),
        }
        editable.append(target_path)
        update["editable_paths"] = editable
        update.setdefault("session_id", handoff["session_id"])
        update.setdefault(
            "accepted_target_revision",
            handoff["accepted_target_revision"],
        )
        unit["design_update"] = update
        st.append_event(
            self.state,
            "brainstorming_application_target_authorized",
            unit=st.unit_key(unit),
            session_id=handoff["session_id"],
            accepted_target_revision=handoff[
                "accepted_target_revision"
            ],
            target_path=target_path,
        )
        return authorization

    @staticmethod
    def _retire_unused_brainstorming_target_authorization(unit, agreement):
        authorization = agreement.pop("design_target_authorization", None)
        if not authorization:
            return
        update = copy.deepcopy(unit.get("design_update") or {})
        target_path = authorization["target_path"]
        if target_path in (update.get("changed_paths") or []):
            agreement["design_target_authorization"] = authorization
            return
        update["editable_paths"] = [
            path for path in update.get("editable_paths") or []
            if path != target_path
        ]
        if authorization.get("added_session_id"):
            update.pop("session_id", None)
        if authorization.get("added_accepted_target_revision"):
            update.pop("accepted_target_revision", None)
        if authorization.get("created_update"):
            unit.pop("design_update", None)
        else:
            unit["design_update"] = update

    def _queue_brainstorming_application(self, unit, wait, handoff):
        """Route an accepted report-origin result straight to a fixer."""
        origin_kind = wait["origin"]["kind"]
        kind = origin_kind
        if kind == RETIRED_SEAL_WORKER_KIND:
            self._restart_from_retired_seal_rethink(
                unit, "retired seal Brainstorming succeeded"
            )
            kind = contracts.KIND_REVIEW_ROUND
        self._enter_rethink_report_fix(
            unit,
            kind,
            wait["origin"].get("family"),
            wait["session_id"],
            wait["signal"]["finding"],
        )
        target_path = wait["signal"].get("target_path")
        unit["fix_source"]["brainstorming_agreement"] = {
            "origin_kind": origin_kind,
            "target_path": target_path,
            "handoff": copy.deepcopy(handoff),
            "source_finding": copy.deepcopy(wait["signal"]["finding"]),
            "baseline_fingerprint": self._candidate_fingerprint(),
        }
        authorization = self._authorize_brainstorming_application_target(
            unit, target_path, handoff
        )
        if authorization is not None:
            unit["fix_source"]["brainstorming_agreement"][
                "design_target_authorization"
            ] = authorization
        st.append_event(
            self.state,
            "brainstorming_implementation_queued",
            unit=st.unit_key(unit),
            kind=kind,
            origin_kind=origin_kind,
            session_id=wait["session_id"],
            accepted_target_revision=handoff[
                "accepted_target_revision"
            ],
            target_path=target_path,
        )
        return "Brainstorming succeeded; implementation queued"

    def _restart_from_retired_seal_rethink(self, unit, reason):
        """Migrate an in-flight pre-derived-seal discussion to reviews."""
        st.restart_reviews_after_candidate_change(self.state, unit, reason)
        if unit["status"] in (st.U_SEALING, st.U_PRE_SEAL_VERIFY):
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="retired seal discussion migrated to ordinary reviews",
            )
            return
        if unit["status"] not in (
            st.U_PRE_REVIEW_VERIFY,
            st.U_FIXING,
            st.U_DELTA_REVIEW,
        ):
            raise st.IllegalTransition(
                "retired seal discussion cannot migrate from status %s"
                % unit["status"]
            )

    def _migrate_persisted_review_handoff(self, unit):
        """Turn a pre-cutover fresh-review handoff into an application."""
        record = copy.deepcopy(unit.get("brainstorming_review_handoff") or {})
        pending_agreement = (unit.get("fix_source") or {}).get(
            "brainstorming_agreement"
        )
        if pending_agreement and not pending_agreement.get("applied"):
            return False
        status = unit.get("status")
        if not record or unit.get("status") not in (
            st.U_PRE_REVIEW_VERIFY,
            st.U_ROUNDS,
            st.U_FIXING,
            st.U_DELTA_REVIEW,
            st.U_PRE_SEAL_VERIFY,
            st.U_SEALING,
        ):
            return False
        origin_kind = record.get("kind")
        kind = origin_kind
        if kind == RETIRED_SEAL_WORKER_KIND:
            self._restart_from_retired_seal_rethink(
                unit,
                "persisted retired seal Brainstorming handoff migrated",
            )
            kind = contracts.KIND_REVIEW_ROUND
        elif unit.get("status") == st.U_SEALING:
            self._restart_from_retired_seal_rethink(
                unit,
                "persisted Brainstorming handoff migrated before sealing",
            )
        if kind not in contracts.REPORT_KINDS:
            raise st.IllegalTransition(
                "persisted Brainstorming review handoff has unknown kind %r"
                % origin_kind
            )
        handoff = record["handoff"]
        session_id = handoff["session_id"]
        application_finding = self._rethink_finding_for_fix(
            record["source_finding"]
        )
        origin_event = next(
            (
                event for event in reversed(self.state.get("events") or [])
                if event.get("type") == "brainstorming_wait_started"
                and event.get("session_id") == session_id
            ),
            {},
        )
        target_path = origin_event.get("target_path")
        source_family = (
            origin_event.get("family")
            or (unit.get("fix_source") or {}).get("family")
        )
        active = unit.get("active_task")
        if active is not None:
            allowed_active_kinds = (
                {contracts.KIND_FIX_FINDINGS}
                if status == st.U_FIXING else contracts.REPORT_KINDS
            )
            if (
                not isinstance(active, dict)
                or active.get("kind") not in allowed_active_kinds
                or not active.get("id")
            ):
                raise st.IllegalTransition(
                    "persisted Brainstorming handoff has an incompatible "
                    "active task"
                )
            self._fail_worker_task_if_open(
                unit,
                None,
                task_id=active["id"],
                reason=(
                    "accepted Brainstorming result must be applied before "
                    "the pending worker continues"
                ),
            )
        self._consume_persisted_review_handoff(unit)
        deferred_dirty = False
        if status == st.U_FIXING:
            unit["deferred_fix_episode"] = {
                "fix_queue": copy.deepcopy(unit.get("fix_queue") or []),
                "fix_source": copy.deepcopy(unit.get("fix_source")),
                "fix_loop_rounds": int(unit.get("fix_loop_rounds") or 0),
                "phantom_retried": bool(unit.get("phantom_retried")),
            }
            if gitops.enabled(self.config):
                try:
                    deferred_dirty = bool(
                        gitops.worktree_diff(self.workspace).strip()
                    )
                except gitops.GitError:
                    pass
        if status == st.U_FIXING:
            deferred_source = (
                unit["deferred_fix_episode"].get("fix_source") or {}
            )
            source_type = (
                "delta"
                if kind == contracts.KIND_DELTA_REVIEW else "round"
            )
            return_to = (
                deferred_source.get("return_to")
                or (
                    st.U_PRE_REVIEW_VERIFY
                    if kind == contracts.KIND_DELTA_REVIEW
                    else st.U_ROUNDS
                )
            )
            unit["fix_queue"] = [copy.deepcopy(application_finding)]
            unit["fix_source"] = {
                "type": source_type,
                "origin_type": source_type,
                "family": source_family,
                "source_round_id": "brainstorming:%s" % session_id,
                "return_to": return_to,
            }
            unit["fix_loop_rounds"] = 0
            unit.pop("phantom_retried", None)
            st.append_event(
                self.state,
                "brainstorming_application_preempted_fix",
                unit=st.unit_key(unit),
                session_id=session_id,
            )
        else:
            self._enter_rethink_report_fix(
                unit,
                kind,
                source_family,
                session_id,
                application_finding,
            )
        if deferred_dirty:
            unit["fix_source"]["preserve_dirty_on_killed_fix"] = True
            unit["deferred_fix_episode"]["fix_source"][
                "preserve_dirty_on_killed_fix"
            ] = True
        unit["fix_source"]["brainstorming_agreement"] = {
            "origin_kind": origin_kind,
            "target_path": target_path,
            "handoff": copy.deepcopy(handoff),
            "source_finding": copy.deepcopy(application_finding),
            "baseline_fingerprint": self._candidate_fingerprint(),
        }
        authorization = self._authorize_brainstorming_application_target(
            unit, target_path, handoff
        )
        if authorization is not None:
            unit["fix_source"]["brainstorming_agreement"][
                "design_target_authorization"
            ] = authorization
        st.append_event(
            self.state,
            "brainstorming_review_handoff_migrated_to_implementation",
            unit=st.unit_key(unit),
            from_kind=origin_kind,
            to_kind=contracts.KIND_FIX_FINDINGS,
            session_id=session_id,
            accepted_target_revision=handoff.get(
                "accepted_target_revision"
            ),
        )
        return True

    @staticmethod
    def _restore_deferred_fix_episode(unit, candidate_changed=False):
        deferred = unit.pop("deferred_fix_episode", None)
        if not deferred:
            return False
        unit["fix_queue"] = copy.deepcopy(deferred["fix_queue"])
        unit["fix_source"] = copy.deepcopy(deferred["fix_source"])
        unit["fix_loop_rounds"] = int(
            deferred.get("fix_loop_rounds") or 0
        )
        if deferred.get("phantom_retried"):
            unit["phantom_retried"] = True
        else:
            unit.pop("phantom_retried", None)
        source = unit.get("fix_source") or {}
        if candidate_changed and source.get("type") == "verification":
            source["deferred_candidate_changed"] = True
            unit["fix_source"] = source
        return True

    def _guarantee_calibration_config(self):
        value = self.config.get("guarantee_calibration")
        if not isinstance(value, dict) or value.get("enabled") is not True:
            return None
        rounds = value.get(
            "max_rounds",
            contracts.MILESTONE_BRAINSTORMING_ROUNDS,
        )
        if isinstance(rounds, bool) or not isinstance(rounds, int) \
                or rounds <= 0:
            rounds = contracts.MILESTONE_BRAINSTORMING_ROUNDS
        return {"max_rounds": rounds}

    def _start_guarantee_calibration(self, unit):
        """Hold a drafted skeleton for one focused guarantee discussion."""
        settings = self._guarantee_calibration_config()
        if settings is None:
            return self._finish_draft(unit, "drafted")
        skeleton_path = unit.get("artifact") or self._skeleton_artifact()
        staffing_selection = self._brainstorming_staffing()
        lead_profile = counterpart_profile = None
        if staffing_selection is None:
            lead_profile, counterpart_profile = self._brainstorming_profiles()
        project_context, _extensions, _roots = self._project_prompt_inputs(
            unit, contracts.KIND_DRAFT_SKELETON, record_seen=False
        )
        references = brainstorming_milestone.stable_references(
            self.state,
            [skeleton_path, ledgers.goal_path(self.state)],
            skeleton_path,
        )
        try:
            created = (
                brainstorming_milestone.create_guarantee_calibration_session(
                    self.state,
                    self.config,
                    st.unit_key(unit),
                    skeleton_path,
                    lead_profile,
                    counterpart_profile,
                    references=references,
                    authority_context={
                        "amendments": self._amendments(
                            record_seen=False, unit=unit
                        ),
                        "project_context": project_context,
                    },
                    max_rounds=settings["max_rounds"],
                    staffing_selection=staffing_selection,
                    active_home=self.model_profiles_home,
                )
            )
        except Exception as exc:
            unit["guarantee_calibration"] = {
                "status": "failed",
                "reason": str(exc)[:500],
            }
            st.fail_run(
                self.state,
                "guarantee calibration could not start: %s" % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("guarantee calibration creation failed")
        unit["guarantee_calibration"] = {
            "status": "running",
            "session_id": created["id"],
        }
        origin = {
            "unit": st.unit_key(unit),
            "kind": "guarantee_calibration",
            "raw_name": "%s-guarantee-calibration" % st.unit_key(unit),
        }
        if lead_profile is not None:
            origin.update({
                "family": lead_profile["agent"],
                "model": lead_profile["model"],
                "effort": lead_profile["effort"],
            })
        unit["brainstorming_wait"] = {
            "session_id": created["id"],
            "signal": None,
            "references": list(references),
            "origin": origin,
        }
        st.append_event(
            self.state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind="guarantee_calibration",
            session_id=created["id"],
            target_path=skeleton_path,
            **(
                {"family": lead_profile["agent"]}
                if lead_profile is not None else {}
            ),
        )
        return "skeleton drafted; guarantee calibration started"

    def _complete_guarantee_calibration(self, unit, wait, handoff):
        expanded = brainstorming_milestone.prompt_handoff(
            self.state,
            handoff,
            active_home=self.model_profiles_home,
        )
        retained = expanded.get("retained_target") or {}
        content = retained.get("content")
        if (
            retained.get("exists") is not True
            or retained.get("encoding") != "utf-8"
            or not isinstance(content, str)
            or not content.strip()
            or "\x00" in content
        ):
            raise brainstorming_milestone.AdapterError(
                "guarantee calibration did not retain one complete UTF-8 "
                "skeleton"
            )
        relpath = unit.get("artifact") or self._skeleton_artifact()
        path = os.path.join(self.workspace, relpath)
        with open(path, "r", encoding="utf-8") as handle:
            before = handle.read()
        changed = before != content
        if changed:
            tmp = path + ".guarantee-calibration.tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp, path)
        unit.pop("brainstorming_wait", None)
        unit["guarantee_calibration"] = {
            "status": "complete",
            "session_id": handoff["session_id"],
            "accepted_target_revision": handoff[
                "accepted_target_revision"
            ],
            "changed": changed,
        }
        st.append_event(
            self.state,
            "guarantee_calibration_completed",
            unit=st.unit_key(unit),
            session_id=handoff["session_id"],
            accepted_target_revision=handoff[
                "accepted_target_revision"
            ],
            changed=changed,
        )
        return self._finish_draft(unit, "guarantees calibrated")

    def _finish_draft(self, unit, reason):
        if gitops.enabled(self.config):
            try:
                pending = unit.get("pending_wip")
                if pending is None:
                    pending = {
                        "parent": gitops.head_full_sha(self.workspace),
                        "tree": gitops.snapshot_worktree_tree(self.workspace),
                        "message": "wip: %s" % st.display_unit_key(unit),
                        "reason": reason,
                    }
                    unit["pending_wip"] = pending
                    self._save()
                return self._complete_pending_wip(unit)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state, "wip commit failed: %s" % exc, unit=unit
                )
                self._save()
                raise StopStep(str(exc))
        st.transition_unit(
            self.state, unit, st.U_PRE_REVIEW_VERIFY, reason=reason
        )
        unit.pop("implementation_attempt_snapshot", None)
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    def _brainstorming_production_request(self, unit, kind):
        """Freeze one target-free milestone brief for the selected producer."""
        from orchestrator import brainstorming_tasks

        slice_info = self._slice_info(unit["slice_id"])
        project_context, _extensions, _roots = self._project_prompt_inputs(
            unit, kind
        )
        governing = (
            self._skeleton_artifact()
            if kind == contracts.KIND_DRAFT_SLICE_NOTE
            else self._slice_note_artifact(unit["slice_id"])
        )
        skeleton_path = self._skeleton_artifact()
        remodeled = (
            kind == contracts.KIND_IMPLEMENT
            and (
                bool(unit.get("has_gap_remodel"))
                or self._note_predates_skeleton(unit["slice_id"])
            )
        )
        prompt = prompts.build_brainstorming_production(
            kind,
            self.workspace,
            self._goal_for(unit),
            slice_info,
            governing,
            amendments=self._amendments(unit=unit),
            project_context=project_context,
            implementation_scope=(
                self._implementation_scope(unit)
                if kind == contracts.KIND_IMPLEMENT else None
            ),
            skeleton_path=skeleton_path,
            remodeled=remodeled,
            two_register=(
                kind == contracts.KIND_DRAFT_SLICE_NOTE
                and interpreter.doc_register(self.state) == "lay+hard-table"
            ),
            battery=(
                interpreter.battery_questions(self.state, unit["kind"])
                if kind == contracts.KIND_DRAFT_SLICE_NOTE else None
            ),
        )
        context = {
            "task_kind": kind,
            "unit": st.unit_key(unit),
        }
        if project_context is not None:
            context["project_context"] = copy.deepcopy(project_context)
        references = [governing]
        if remodeled and skeleton_path not in references:
            references.append(skeleton_path)
        request = {
            "work_area": self._task_work_area(),
            "request": prompt,
            "context": context,
            "reference_documents": references,
        }
        planned_path = None
        if kind == contracts.KIND_DRAFT_SLICE_NOTE:
            planned_path = ledgers.slice_note_path(
                self.state, unit["slice_id"]
            )
            request["context"]["planned_slice_note_path"] = planned_path
            request = brainstorming_tasks.prepare_slice_note_request(
                request, planned_path
            )
        return request, planned_path

    def _admit_brainstorming_production(self, unit, kind):
        """Reuse or admit the one Brainstorming task owned by this unit."""
        from orchestrator import brainstorming_tasks

        active = self._active_brainstorming_task(unit, kind)
        if active is not None:
            planned = active["order"]["request"].get("context", {}).get(
                "planned_slice_note_path"
            )
            return active, planned
        request, planned = self._brainstorming_production_request(unit, kind)
        order = tasks.producer_order(
            self._slice_info(unit["slice_id"]), kind, request
        )
        if order["task_executor"] != "brainstorming":
            raise st.IllegalTransition(
                "selected production task is not a Brainstorming task"
            )
        # The same inherited context every other milestone order records.
        # The discussion's own calls resolve through the selection below,
        # which is where slice 6 put that authority; this key keeps the
        # order honest about the session the work belongs to rather than
        # letting the validator's default say it belongs to none.
        order["staffing_session"] = st.staffing_session(self.state)
        try:
            record = brainstorming_tasks.admit_task(
                self.state,
                order,
                self.config,
                self.workspace,
                staffing_selection=self._brainstorming_staffing(order),
            )
        except tasks.TaskRequestError as exc:
            reason = "Brainstorming producer admission failed: %s" % exc.code
            st.fail_run(
                self.state,
                reason,
                unit=unit,
                type_="brainstorming_production",
            )
            self._save()
            raise StopStep(reason)
        unit["active_task"] = {"id": record["id"], "kind": kind}
        self._save()
        return record, planned

    def _fail_brainstorming_production(self, unit, record, session_id=None):
        result = record.get("result") or {}
        wait = unit.get("brainstorming_wait") or {}
        self._record_brainstorming_work(
            unit,
            session_id or wait.get("session_id"),
            result.get("duration_s"),
            result.get("token_usage"),
            result.get("token_usage_partial", False),
            cost=result.get("cost"),
            cost_partial=result.get("cost_partial", False),
            task_id=record.get("id"),
        )
        self._enforce_sealed_artifacts(
            "%s-brainstorming-production" % st.unit_key(unit)
        )
        unit.pop("brainstorming_wait", None)
        reference = unit.get("active_task") or {}
        if reference.get("id") == record.get("id"):
            unit.pop("active_task", None)
        reason = result.get("reason") or "Brainstorming production failed"
        st.fail_run(
            self.state,
            reason,
            unit=unit,
            type_="brainstorming_production",
        )
        self._save()
        raise StopStep(reason)

    def _start_brainstorming_production(self, unit, kind):
        from orchestrator import brainstorming_tasks

        record, planned = self._admit_brainstorming_production(unit, kind)
        home = brainstorming_milestone.service_home(
            self.state, active_home=self.model_profiles_home
        )
        try:
            projection = brainstorming_tasks.start_task(
                self.state,
                record["id"],
                self.config,
                home,
                staffing_selection=self._brainstorming_staffing(
                    record["order"]
                ),
            )
        except brainstorming_lifecycle.PublicLifecycleError as exc:
            if exc.code == brainstorming_lifecycle.STOP_INCOMPLETE:
                return "waiting for Brainstorming producer recovery"
            st.fail_run(
                self.state,
                "Brainstorming producer could not be started: %s" % exc.code,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming producer start failed")
        record = tasks.task_record(self.state, record["id"])
        if record["result"] is not None:
            return self._fail_brainstorming_production(
                unit, record, session_id=(projection or {}).get("id")
            )
        session_id = (projection or {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            st.fail_run(
                self.state,
                "Brainstorming producer exposed no session identity",
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming producer start failed")
        unit["brainstorming_wait"] = {
            "session_id": session_id,
            "origin": {
                "unit": st.unit_key(unit),
                "kind": kind,
                "task_executor": "brainstorming",
                "task_id": record["id"],
                **(
                    {"planned_slice_note_path": planned}
                    if planned is not None else {}
                ),
            },
        }
        st.append_event(
            self.state,
            "brainstorming_wait_started",
            unit=st.unit_key(unit),
            kind=kind,
            session_id=session_id,
            task_id=record["id"],
        )
        return "waiting for Brainstorming producer %s" % session_id

    def _do_brainstorming_production_wait(self, unit, wait):
        from orchestrator import brainstorming_tasks

        origin = wait.get("origin") or {}
        kind = origin.get("kind")
        task_id = origin.get("task_id")
        active = self._active_brainstorming_task(unit, kind)
        if active is None or active["id"] != task_id:
            raise st.IllegalTransition(
                "Brainstorming production wait has no matching open task"
            )
        home = brainstorming_milestone.service_home(
            self.state, active_home=self.model_profiles_home
        )
        dispatch_authority = (active.get("resolved_staffing") or {}).get(
            "dispatch_authority"
        )
        staffing_selection = (
            self._brainstorming_staffing(active["order"])
            if dispatch_authority == "current_profile"
            else None
        )
        try:
            terminal = self._with_inspection_retry(
                lambda: brainstorming_tasks.finish_task(
                    self.state,
                    task_id,
                    home,
                    wait["session_id"],
                    lambda effect_request:
                        brainstorming_tasks.apply_agreed_effects(
                            home,
                            wait["session_id"],
                            task_id,
                            effect_request,
                            dispatch_authority=dispatch_authority,
                            staffing_selection=staffing_selection,
                        ),
                )
            )
        except Exception as exc:
            # Inspection and recoverable service faults leave the task and its
            # wait intact. Explicit Resume re-enters this same identity.
            self._enforce_sealed_artifacts(
                "%s-brainstorming-production" % st.unit_key(unit)
            )
            st.fail_run(
                self.state,
                "Brainstorming producer could not be inspected: %s" % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming producer inspection failed")
        if terminal is None:
            return "waiting for Brainstorming producer %s" % wait["session_id"]
        if terminal["result"]["status"] != "success":
            return self._fail_brainstorming_production(unit, terminal)

        self._enforce_sealed_artifacts(
            "%s-brainstorming-production" % st.unit_key(unit)
        )
        result = terminal["result"]
        native = copy.deepcopy(result.get("native_result"))
        if not isinstance(native, dict):
            raise st.IllegalTransition("Brainstorming result is unavailable")
        st.record_draft(
            self.state,
            unit,
            kind,
            native,
            family=None,
            duration=result["duration_s"],
            token_usage=result.get("token_usage"),
            token_usage_partial=result.get("token_usage_partial", False),
            cost=result.get("cost"),
            cost_partial=result.get("cost_partial", False),
            task_id=task_id,
        )
        if kind == contracts.KIND_DRAFT_SLICE_NOTE:
            planned = origin.get("planned_slice_note_path")
            brainstorming_tasks.record_slice_note_handoff(
                unit, terminal, planned
            )
        unit.pop("brainstorming_wait", None)
        unit.pop("active_task", None)
        return self._finish_draft(unit, "Brainstorming production completed")

    def _complete_pending_wip(self, unit):
        """Create or adopt exactly one durable WIP before reviews open."""
        pending = unit.get("pending_wip")
        if not isinstance(pending, dict):
            raise st.IllegalTransition("pending WIP metadata is missing")
        parent = pending.get("parent")
        tree = pending.get("tree")
        message = pending.get("message")
        reason = pending.get("reason") or "drafted"
        try:
            head = gitops.head_full_sha(self.workspace)
            if head == parent:
                if gitops.snapshot_worktree_tree(self.workspace) != tree:
                    raise gitops.GitError(
                        "the pending WIP candidate changed before recovery"
                    )
                sha = gitops.commit_wip(self.workspace, message)
            elif gitops.head_matches_wip(
                self.workspace, parent, tree, message
            ):
                sha = gitops.head_sha(self.workspace)
            else:
                raise gitops.GitError(
                    "HEAD no longer matches the pending WIP parent or its "
                    "already-created commit"
                )
        except gitops.GitError as exc:
            st.fail_run(
                self.state,
                "wip commit failed: %s" % exc,
                unit=unit,
                type_="wip_recovery",
            )
            self._save()
            raise StopStep(str(exc))
        st.append_event(
            self.state, "wip_commit", unit=st.unit_key(unit), sha=sha
        )
        unit.pop("pending_wip", None)
        unit.pop("implementation_attempt_snapshot", None)
        st.transition_unit(
            self.state, unit, st.U_PRE_REVIEW_VERIFY, reason=reason
        )
        return "drafted %s" % (unit["artifact"] or "(implementation)")

    def _record_brainstorming_work(self, unit, session_id, duration_s,
                                   token_usage=None,
                                   token_usage_partial=False,
                                   cost=None, cost_partial=False,
                                   task_id=None):
        """Attach one independent session's consumed LLM work exactly once."""
        if duration_s is None and token_usage is None and cost is None:
            return
        if any(
            event.get("type") == "brainstorming_work_recorded"
            and (
                event.get("task_id") == task_id
                if task_id is not None
                else event.get("session_id") == session_id
            )
            for event in self.state.get("events", [])
        ):
            return
        st.append_event(
            self.state,
            "brainstorming_work_recorded",
            unit=st.unit_key(unit),
            session_id=session_id,
            duration_s=duration_s,
            token_usage=copy.deepcopy(token_usage),
            token_usage_partial=bool(token_usage_partial),
            cost=copy.deepcopy(cost),
            cost_partial=bool(cost_partial),
            **({"task_id": task_id} if task_id is not None else {}),
        )

    _INSPECTION_ATTEMPTS = 3
    _INSPECTION_RETRY_DELAY_S = 2.0

    def _with_inspection_retry(self, call):
        """Retry one lifecycle read briefly before treating it as fatal.

        An UNAVAILABLE projection is routinely transient — the shared session
        store may be mid-write by another session's executor — and a run must
        not die for a read that succeeds seconds later. Every other error
        keeps its meaning and its first-raise timing.
        """
        for _ in range(self._INSPECTION_ATTEMPTS - 1):
            try:
                return call()
            except brainstorming_lifecycle.PublicLifecycleError as exc:
                if exc.code != brainstorming_lifecycle.UNAVAILABLE:
                    raise
                time.sleep(self._INSPECTION_RETRY_DELAY_S)
        return call()

    def _do_brainstorming_wait(self):
        unit = st.current_unit(self.state)
        wait = copy.deepcopy(unit.get("brainstorming_wait") or {})
        session_id = wait.get("session_id")
        if not session_id:
            raise st.IllegalTransition(
                "brainstorming wait action has no recorded session"
            )
        if (wait.get("origin") or {}).get("unit") != st.unit_key(unit):
            raise st.IllegalTransition(
                "brainstorming wait origin does not match its attached unit"
            )
        if (wait.get("origin") or {}).get("task_executor") == "brainstorming":
            return self._do_brainstorming_production_wait(unit, wait)
        try:
            handoff = self._with_inspection_retry(
                lambda: brainstorming_milestone.terminal_handoff(
                    self.state,
                    session_id,
                    active_home=self.model_profiles_home,
                )
            )
        except brainstorming_lifecycle.PublicLifecycleError as exc:
            if exc.code != brainstorming_lifecycle.UNKNOWN_SESSION:
                st.fail_run(
                    self.state,
                    "recorded Brainstorming session could not be inspected: %s"
                    % exc,
                    unit=unit,
                    type_="brainstorming_operational",
                )
                self._save()
                raise StopStep("Brainstorming inspection failed")
            unit.pop("brainstorming_wait", None)
            origin_kind = (wait.get("origin") or {}).get("kind")
            if origin_kind in contracts.RETHINK_CONTINUATION_KINDS:
                self._fail_waiting_worker_task(
                    unit,
                    wait,
                    "attached Brainstorming session is missing",
                )
            st.append_event(
                self.state,
                "brainstorming_missing_detached",
                unit=st.unit_key(unit),
                kind=origin_kind,
                session_id=session_id,
            )
            if origin_kind == "guarantee_calibration":
                unit["guarantee_calibration"] = {
                    "status": "discarded",
                    "session_id": session_id,
                }
                return self._finish_draft(
                    unit, "discarded missing guarantee calibration"
                )
            return (
                "discarded missing Brainstorming session %s; "
                "originating action resumed" % session_id
            )
        except brainstorming_milestone.OperationalTerminalError as exc:
            # The terminal session remains retained evidence, but it must no
            # longer monopolize the unit's next action. Operator resume now
            # retries the unchanged originating milestone call.
            self._record_brainstorming_work(
                unit, session_id, exc.work_duration_s,
                exc.work_token_usage,
                exc.work_token_usage_partial,
                cost=getattr(exc, "work_cost", None),
                cost_partial=getattr(exc, "work_cost_partial", False),
            )
            unit.pop("brainstorming_wait", None)
            if (wait.get("origin") or {}).get("kind") \
                    in contracts.RETHINK_CONTINUATION_KINDS:
                self._fail_waiting_worker_task(
                    unit,
                    wait,
                    "attached Brainstorming session ended operationally: %s"
                    % exc,
                )
            if (wait.get("origin") or {}).get("kind") \
                    == "guarantee_calibration":
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": str(exc)[:500],
                }
            st.append_event(
                self.state,
                "brainstorming_operational_detached",
                unit=st.unit_key(unit),
                kind=(wait.get("origin") or {}).get("kind"),
                session_id=session_id,
            )
            st.fail_run(
                self.state,
                "recorded Brainstorming session ended operationally: %s" % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming execution failed")
        except Exception as exc:
            st.fail_run(
                self.state,
                "recorded Brainstorming session could not be inspected: %s"
                % exc,
                unit=unit,
                type_="brainstorming_operational",
            )
            self._save()
            raise StopStep("Brainstorming inspection failed")
        if handoff is None:
            return "waiting for Brainstorming session %s" % session_id

        self._record_brainstorming_work(
            unit, session_id, handoff.get("work_duration_s"),
            handoff.get("work_token_usage"),
            handoff.get("work_token_usage_partial", False),
            cost=handoff.get("work_cost"),
            cost_partial=handoff.get("work_cost_partial", False),
        )

        origin = wait["origin"]
        kind = origin["kind"]
        if kind == "guarantee_calibration":
            if handoff["result"]["outcome"] == "failure":
                unit.pop("brainstorming_wait", None)
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": "the participants did not agree",
                }
                st.append_event(
                    self.state,
                    "guarantee_calibration_failed",
                    unit=st.unit_key(unit),
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "guarantee calibration ended without agreement",
                    unit=unit,
                    type_="guarantee_calibration",
                )
                self._save()
                raise StopStep("guarantee calibration did not agree")
            try:
                return self._complete_guarantee_calibration(
                    unit, wait, handoff
                )
            except Exception as exc:
                unit.pop("brainstorming_wait", None)
                unit["guarantee_calibration"] = {
                    "status": "failed",
                    "session_id": session_id,
                    "reason": str(exc)[:500],
                }
                st.append_event(
                    self.state,
                    "guarantee_calibration_failed",
                    unit=st.unit_key(unit),
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "accepted guarantee calibration could not be applied: "
                    "%s" % exc,
                    unit=unit,
                    type_="brainstorming_operational",
                )
                self._save()
                raise StopStep("guarantee calibration adoption failed")
        if handoff["result"]["outcome"] == "failure":
            if self._modern_design_updates():
                unit.pop("brainstorming_wait", None)
                if kind in contracts.RETHINK_CONTINUATION_KINDS:
                    self._fail_waiting_worker_task(
                        unit,
                        wait,
                        "focused design discussion ended without agreement",
                    )
                st.append_event(
                    self.state,
                    "brainstorming_failure_routed",
                    unit=st.unit_key(unit),
                    kind=kind,
                    session_id=session_id,
                )
                st.fail_run(
                    self.state,
                    "focused design discussion ended without agreement; "
                    "the original work and candidate are preserved",
                    unit=unit,
                    type_="brainstorming_no_agreement",
                )
                self._save()
                raise StopStep("Brainstorming ended without agreement")
            if (
                kind == contracts.KIND_FIX_FINDINGS
                and not self._fixer_gap_enabled(unit)
            ):
                # A discussion failure cannot broaden the ordinary fixer-gap
                # route. Preserve the fix episode and stop before any unwind.
                unit.pop("brainstorming_wait", None)
                self._fail_waiting_worker_task(
                    unit,
                    wait,
                    "focused design discussion could not be adopted by the "
                    "fixer route",
                )
                st.fail_run(
                    self.state,
                    "Brainstorming failed for a fixer outside the supported "
                    "gap envelope; the existing fix episode is preserved for "
                    "operator intervention",
                    unit=unit,
                    type_="worker_blocked",
                )
                self._save()
                raise StopStep(
                    "Brainstorming fixer failure outside gap envelope"
                )
            unit.pop("brainstorming_wait", None)
            if kind in contracts.RETHINK_CONTINUATION_KINDS:
                self._fail_waiting_worker_task(
                    unit,
                    wait,
                    "focused design discussion routed the work elsewhere",
                )
            st.append_event(
                self.state,
                "brainstorming_failure_routed",
                unit=st.unit_key(unit),
                kind=kind,
                session_id=session_id,
            )
            if kind in contracts.RETHINK_CONTINUATION_KINDS:
                failure_gap = wait["signal"].get("failure_gap")
                if not isinstance(failure_gap, dict):
                    st.fail_run(
                        self.state,
                        "a historical Brainstorming continuation has no "
                        "failure_gap for its no-agreement route",
                        unit=unit,
                        type_="worker_protocol",
                    )
                    self._save()
                    raise StopStep("missing legacy failure gap")
                pre = origin.get("pre_snapshot") or {}
                return self._handle_gap(
                    unit,
                    {"gaps": [copy.deepcopy(failure_gap)]},
                    None,
                    pre_tree=pre.get("tree"),
                    pre_head=pre.get("head"),
                    pre_sym=pre.get("sym"),
                    pre_refs=pre.get("refs"),
                    pre_stash=pre.get("stash"),
                    pre_worktree_tree=pre.get("worktree_tree"),
                    from_fixer=kind == contracts.KIND_FIX_FINDINGS,
                )
            if kind == RETIRED_SEAL_WORKER_KIND:
                self._restart_from_retired_seal_rethink(
                    unit, "retired seal Brainstorming failed"
                )
                st.enter_fix_episode(
                    self.state,
                    unit,
                    [self._rethink_finding_for_fix(
                        wait["signal"]["finding"]
                    )],
                    "round",
                    origin.get("family"),
                    "brainstorming:%s" % session_id,
                    st.U_ROUNDS,
                )
                return (
                    "Brainstorming failed; retired seal finding queued and "
                    "ordinary reviews restarted"
                )
            self._route_rethink_report_failure(unit, wait)
            return "Brainstorming failed; source finding queued for fixing"

        if kind in contracts.RETHINK_CONTINUATION_KINDS:
            amendment_mode = self._rethink_requests_design_amendment(
                wait["signal"]
            )
            if amendment_mode:
                try:
                    amendment_event = self._adopt_brainstorming_design_amendment(
                        unit, wait, handoff
                    )
                    if self._modern_design_updates():
                        self._activate_design_update(
                            unit, handoff, amendment_event
                        )
                except brainstorming_milestone.AdapterError as exc:
                    unit.pop("brainstorming_wait", None)
                    self._fail_waiting_worker_task(
                        unit,
                        wait,
                        "accepted design amendment could not be adopted: %s"
                        % exc,
                    )
                    st.fail_run(
                        self.state,
                        "accepted Brainstorming amendment could not be "
                        "adopted: %s" % exc,
                        unit=unit,
                        type_="brainstorming_operational",
                    )
                    self._save()
                    raise StopStep("Brainstorming amendment adoption failed")
            if kind == contracts.KIND_FIX_FINDINGS:
                source = unit.get("fix_source")
                if not isinstance(source, dict):
                    source = {
                        "type": "round",
                        "origin_type": "round",
                        "family": origin.get("family"),
                        "source_round_id": "brainstorming:%s" % session_id,
                        "return_to": st.U_ROUNDS,
                    }
                    unit["fix_source"] = source
                agreement = source.get("brainstorming_agreement")
                if (
                    not isinstance(agreement, dict)
                    or (agreement.get("handoff") or {}).get("session_id")
                    != session_id
                ):
                    agreement = {
                        "origin_kind": kind,
                        "target_path": wait["signal"].get("target_path"),
                        "handoff": copy.deepcopy(handoff),
                        "source_finding": copy.deepcopy(
                            wait["signal"]["finding"]
                        ),
                        "baseline_fingerprint": (
                            self._candidate_fingerprint()
                        ),
                    }
                    source["brainstorming_agreement"] = agreement
                    authorization = (
                        self._authorize_brainstorming_application_target(
                            unit,
                            agreement["target_path"],
                            handoff,
                        )
                    )
                    if authorization is not None:
                        agreement["design_target_authorization"] = (
                            authorization
                        )
            elif "application_target_authorization" not in wait:
                authorization = self._authorize_brainstorming_application_target(
                    unit,
                    wait["signal"].get("target_path"),
                    handoff,
                )
                if authorization is not None:
                    wait["application_target_authorization"] = authorization
                    unit["brainstorming_wait"][
                        "application_target_authorization"
                    ] = copy.deepcopy(authorization)
            family = origin["family"]
            design_context = (
                self._design_correction_context(unit)
                if (
                    kind == contracts.KIND_FIX_FINDINGS
                    and (not self._modern_design_updates()
                         or unit.get("design_correction"))
                )
                else None
            )
            task_id = origin.get("task_id")
            task = (
                tasks.task_record(self.state, task_id)
                if task_id is not None else None
            )
            authority = self._worker_episode_authority(unit, kind)
            episode_authority = prompts.worker_episode_authority_block(
                authority["amendments"],
                authority["project_context"],
                authority["operator_complete"],
            )
            if task is not None:
                # Keep strategy and the admitted request frozen, while the
                # continuation itself is a new live-authority episode.
                validate_opts = self._worker_task_validate_opts(task)
                project_context = authority["project_context"]
                extensions = authority["extensions"]
                roots = authority["roots"]
                original_request = task["order"]["request"]["request"]
                amendments = None
            else:
                # Compatibility for a pre-task retained wait.
                amendments = None
                current_battery = (
                    interpreter.battery_questions(self.state, unit["kind"])
                    if kind == contracts.KIND_DRAFT_SLICE_NOTE
                    else None
                )
                current_verification_repair = (
                    kind == contracts.KIND_FIX_FINDINGS
                    and (unit.get("fix_source") or {}).get("type")
                    == "verification"
                )
                validate_opts = {
                    **(
                        {"allow_design_correction": True}
                        if design_context
                        and design_context.get("mode") == "offer"
                        else {}
                    ),
                    **(
                        {"battery_questions": current_battery}
                        if current_battery else {}
                    ),
                    **(
                        {"require_failure_gap": True}
                        if self._legacy_failure_gap_required(unit, kind)
                        else {}
                    ),
                    **(
                        {"verification_repair": True}
                        if current_verification_repair else {}
                    ),
                } or None
                project_context = authority["project_context"]
                extensions = authority["extensions"]
                roots = authority["roots"]
                original_request = None
            validation = validate_opts or {}
            battery = validation.get("battery_questions")
            verification_repair = bool(
                validation.get("verification_repair")
            )
            verification_commands = (
                self._verification_commands(unit)
                if verification_repair and original_request is None else None
            )
            prompt = prompts.build_rethink_continuation(
                kind,
                family,
                self.workspace,
                brainstorming_milestone.prompt_handoff(
                    self.state,
                    handoff,
                    active_home=self.model_profiles_home,
                ),
                allow_design_correction=bool(
                    validation.get("allow_design_correction")
                ),
                amendments=amendments,
                project_context=project_context,
                battery=battery,
                accepted_design_amendment=amendment_mode,
                editable_design_paths=(
                    self._editable_design_paths(unit)
                    if (
                        self._modern_design_updates()
                        and (
                            amendment_mode
                            or kind == contracts.KIND_FIX_FINDINGS
                        )
                    )
                    else None
                ),
                verification_repair=verification_repair,
                verification_commands=verification_commands,
                verification_signal=(
                    wait.get("signal", {}).get("finding")
                    if verification_repair else None
                ),
                unit_kind=unit["kind"],
                gap_enabled=(
                    self._fixer_gap_enabled(unit)
                    if verification_repair and original_request is None
                    else False
                ),
                original_request=original_request,
                episode_authority=episode_authority,
                producer_planning=self._continuation_may_plan_slices(unit),
                materials=self._planning_materials(),
            )
            durable_stabilization_size = None
            if kind == contracts.KIND_IMPLEMENT:
                durable_stabilization = unit.get(
                    "implementation_stabilization"
                )
                if durable_stabilization is not None:
                    durable_stabilization_size = (
                        copy.deepcopy(durable_stabilization.get(
                            "implementation_size"
                        ))
                        if isinstance(durable_stabilization, dict)
                        and isinstance(durable_stabilization.get(
                            "implementation_size"
                        ), dict)
                        else None
                    )
                    if durable_stabilization_size is None:
                        st.fail_run(
                            self.state,
                            "implementation stabilization metadata is "
                            "incomplete",
                            unit=unit,
                            type_="orchestrator",
                        )
                        self._save()
                        raise StopStep(
                            "implementation stabilization metadata incomplete"
                        )
                    self._ensure_implementation_stabilization_events(
                        unit, durable_stabilization_size
                    )
                    # The unit marker is current process truth. Brainstorming's
                    # origin snapshot is retained history and may predate a
                    # cutoff or a crash; it cannot reopen the size-monitored
                    # draft or drop the stabilizer's closing instruction.
                    prompt = self._implementation_stabilizer_prompt(
                        prompt, durable_stabilization_size
                    )
            self._activate_worker_episode_authority(authority)
            raw_name = "%s-rethink-return" % origin["raw_name"]
            application_before = self._snapshot()
            design_before = (
                self._snapshot() if unit.get("design_update") else None
            )
            implementation_size = None
            implementation_stabilized = False
            seed_usage = getattr(
                getattr(self, "runner", None),
                "seed_codex_session_usage",
                None,
            )
            if family == "codex" and callable(seed_usage):
                seed_usage(
                    origin["provider_session_ref"],
                    origin.get("provider_session_token_usage"),
                    origin.get("provider_session_cost_payload"),
                )
            if kind == contracts.KIND_IMPLEMENT:
                origin_pre_snapshot = origin.get("pre_snapshot") or {}
                fresh_stabilizer_session = bool(
                    durable_stabilization_size is not None
                    and not origin_pre_snapshot.get(
                        "implementation_stabilized"
                    )
                )
                (
                    output,
                    result,
                    raw_path,
                    implementation_size,
                    implementation_stabilized,
                ) = self._call_implementation(
                    family,
                    prompt,
                    raw_name,
                    origin.get("model"),
                    origin.get("effort"),
                    extensions,
                    roots,
                    validate_opts,
                    fresh_stabilizer_session,
                    (
                        unit.get("implementation_attempt_snapshot") or {}
                    ).get("tree")
                    or origin_pre_snapshot.get("tree"),
                    session_ref=(
                        None if fresh_stabilizer_session
                        else origin["provider_session_ref"]
                    ),
                    stabilizing=bool(
                        durable_stabilization_size is not None
                        or origin_pre_snapshot.get(
                            "implementation_stabilized"
                        )
                    ),
                    dispatch_resolver=self._dispatch_for_worker_kind(
                        unit, kind
                    ),
                    continuation_family=origin["family"],
                    task_id=origin.get("task_id"),
                    episode_refresher=lambda next_prompt: (
                        self._refresh_worker_episode(
                            unit, kind, next_prompt
                        )
                    ),
                )
                if durable_stabilization_size is not None:
                    implementation_size = durable_stabilization_size
                    implementation_stabilized = True
            else:
                output, result, raw_path = self._call(
                    family,
                    prompt,
                    kind,
                    raw_name,
                    model=origin.get("model"),
                    effort=origin.get("effort"),
                    extensions=extensions,
                    roots=roots,
                    validate_opts=validate_opts,
                    session_ref=origin["provider_session_ref"],
                    dispatch_resolver=self._dispatch_for_worker_kind(
                        unit,
                        kind,
                        origin_family=(unit.get("fix_source") or {}).get(
                            "family"
                        ),
                    ),
                    continuation_family=origin["family"],
                    task_id=origin.get("task_id"),
                )
            family, current_model, current_effort = self._result_identity(
                result,
                family,
                origin.get("model"),
                origin.get("effort"),
            )
            continued_pre_snapshot = copy.deepcopy(
                origin.get("pre_snapshot") or {}
            )
            if kind == contracts.KIND_IMPLEMENT:
                if (
                    implementation_size
                    and (
                        implementation_size.get("steer_delivered")
                        or implementation_size.get("interrupt_lines")
                    )
                ) or "implementation_size" not in continued_pre_snapshot:
                    continued_pre_snapshot["implementation_size"] = (
                        copy.deepcopy(implementation_size)
                    )
                continued_pre_snapshot["implementation_stabilized"] = bool(
                    continued_pre_snapshot.get("implementation_stabilized")
                    or implementation_stabilized
                )
            if design_before is not None:
                self._record_design_changes(
                    unit,
                    self._snapshot_diff(design_before, self._snapshot()),
                )
            application_workspace_changed = bool(
                self._snapshot_diff(application_before, self._snapshot())
            )
            if output.get("status") != "ok":
                durable_origin = unit["brainstorming_wait"]["origin"]
                durable_origin["provider_session_ref"] = (
                    getattr(result, "session_ref", None)
                    or durable_origin.get("provider_session_ref")
                )
                session_usage = getattr(
                    result, "session_token_usage", None
                )
                if session_usage is not None:
                    durable_origin["provider_session_token_usage"] = (
                        copy.deepcopy(session_usage)
                    )
                session_cost = getattr(
                    result, "session_cost_payload", None
                )
                if family == "codex" and session_cost is not None:
                    durable_origin["provider_session_cost_payload"] = (
                        copy.deepcopy(session_cost)
                    )
                self._enforce_sealed_artifacts(
                    raw_name,
                    editable_sealed=self._editable_design_paths(unit),
                )
                reason = (
                    "%s worker did not complete the accepted Brainstorming "
                    "application (status %s); the same agreement remains "
                    "pending"
                    % (kind, output.get("status"))
                )
                self._record_worker_unaccepted(
                    unit, kind, family, result, reason
                )
                st.fail_run(
                    self.state,
                    reason,
                    unit=unit,
                    type_=(
                        "worker_protocol"
                        if output.get("status") == "need_rethink"
                        else "unknown"
                        if output.get("status") == "retry"
                        else "worker_blocked"
                    ),
                )
                self._save()
                raise StopStep(reason)
            if kind != contracts.KIND_FIX_FINDINGS:
                authorization = wait.pop(
                    "application_target_authorization", None
                )
                if authorization is not None:
                    self._retire_unused_brainstorming_target_authorization(
                        unit,
                        {"design_target_authorization": authorization},
                    )
            unit.pop("brainstorming_wait", None)
            unit["brainstorming_resume"] = {
                "kind": kind,
                "output": copy.deepcopy(output),
                "raw_path": raw_path,
                "duration_s": result.duration_s,
                "token_usage": copy.deepcopy(
                    getattr(result, "token_usage", None)
                ),
                "token_usage_partial": bool(
                    getattr(result, "token_usage_partial", False)
                    or getattr(result, "token_usage", None) is None
                ),
                "cost": copy.deepcopy(getattr(result, "cost", None)),
                "cost_partial": bool(
                    getattr(result, "cost_partial", False)
                    or getattr(result, "cost", None) is None
                ),
                "text": result.text,
                "provider_session_ref": (
                    getattr(result, "session_ref", None)
                    or origin["provider_session_ref"]
                ),
                "handoff": copy.deepcopy(handoff),
                "family": family,
                "model": current_model,
                "effort": current_effort,
                "pre_snapshot": continued_pre_snapshot,
                "origin_rethink_signal": copy.deepcopy(wait["signal"]),
                "workspace_changed": application_workspace_changed,
                "baseline_fingerprint": self._candidate_fingerprint(
                    application_before
                ),
                **self._prompt_set_fallback_fields(result),
                **(
                    {"task_id": origin["task_id"]}
                    if origin.get("task_id") is not None else {}
                ),
            }
            st.append_event(
                self.state,
                "brainstorming_builder_continued",
                unit=st.unit_key(unit),
                kind=kind,
                session_id=session_id,
                accepted_target_revision=handoff[
                    "accepted_target_revision"
                ],
            )
            return "Brainstorming succeeded; origin conversation continued"

        unit.pop("brainstorming_wait", None)
        return self._queue_brainstorming_application(unit, wait, handoff)

    def _record_worker_unaccepted(self, unit, kind, family, result, reason):
        call = self._matching_busy_call(kind=kind, family=family)
        fallback_fields = self._prompt_set_fallback_evidence(result)
        st.append_event(
            self.state,
            "worker_unaccepted",
            unit=st.unit_key(unit) if unit is not None else None,
            label=call.get("label"),
            kind=kind,
            family=family,
            model=(call.get("model")
                   or getattr(result, "resolved_model", None)
                   or getattr(result, "origin_model", None)),
            effort=(call.get("effort")
                    or getattr(result, "resolved_effort", None)
                    or getattr(result, "origin_effort", None)),
            reason=str(reason or "")[:300],
            duration_s=getattr(result, "duration_s", None),
            token_usage=copy.deepcopy(getattr(result, "token_usage", None)),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=copy.deepcopy(getattr(result, "cost", None)),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            **fallback_fields,
            **self._worker_task_fields(
                kind=kind, family=family, result=result
            ),
        )

    def _check_worker_blocked(self, unit, output, kind, family, result):

        if output["status"] == "retry":
            self._record_worker_unaccepted(
                unit, kind, family, result, "worker requested retry"
            )
            # A fixer could not complete its mandatory opposite-family
            # consultation. This is neither a finding disposition nor an
            # operator decision: fail through the established `unknown`
            # lane so the service guard restores failed_from=U_FIXING and
            # retries the same queue after its 15-minute emergency interval.
            # Preserve any partial delta for the next fixer to inspect, just
            # like a killed fixer call; sealed-doc tampering was already
            # restored by _enforce_sealed_artifacts before this check.
            unit["killed_fix_notice"] = "consultation unavailable"
            detail = str(output.get("notes") or "").strip()
            reason = (
                "%s consultation unavailable; transient retry requested"
                % kind
            )
            if detail:
                reason += ": %s" % detail[:500]
            self._terminalize_worker_task(
                unit,
                output,
                result=result,
                status="failure",
                reason=reason,
            )
            st.fail_run(
                self.state,
                reason,
                unit=unit,
                type_="unknown",
                evidence="worker reported consultation_unavailable",
            )
            self._save()
            raise StopStep("consultation unavailable")
        # type_="worker_blocked": a blocked worker is an OPERATOR-gated
        # stop (like goal_gap/gap_stall), not an unclassified transient —
        # left untyped it defaults to "unknown" and the service guard
        # emergency-resumes it every 15 minutes forever, re-running the
        # worker against the very decision it stopped to ask for. Found
        # live (2026-07-10, LPC rich-content): blocked findings that
        # needed a sealed-note repair were auto-resumed 16 minutes later.
        if output["status"] == "blocked":
            self._record_worker_unaccepted(
                unit, kind, family, result, "worker reported blocked"
            )
            reason = "%s worker blocked: %s" % (
                kind,
                output.get("blocked_reason"),
            )
            self._terminalize_worker_task(
                unit,
                output,
                result=result,
                status="failure",
                reason=reason,
            )
            st.fail_run(
                self.state,
                reason,
                unit=unit, type_="worker_blocked",
            )
            self._save()
            raise StopStep(output.get("blocked_reason"))
        blocked = contracts.blocking_findings(output)
        if blocked:
            self._record_worker_unaccepted(
                unit, kind, family, result, "worker reported blocking findings"
            )
            reason = "%s reported blocked findings needing the operator: %s" % (
                kind,
                "; ".join(f["summary"] for f in blocked),
            )
            self._terminalize_worker_task(
                unit,
                output,
                result=result,
                status="failure",
                reason=reason,
            )
            st.fail_run(
                self.state,
                reason,
                unit=unit, type_="worker_blocked",
            )
            self._save()
            raise StopStep("blocked findings")

    # -- action executors --------------------------------------------------

    def _decide_at_strategy_boundary(self):
        """Apply a pending strategy replacement before deciding an action."""
        try:
            if self._apply_profile_swap():
                # Persist the transition before any newly governed worker
                # dispatch. A killed call cannot erase or duplicate it.
                self._save()
            unit = st.current_unit(self.state)
            if (
                unit is not None
                and self.state.get("failure") is None
                and not unit.get("brainstorming_wait")
                and self._migrate_persisted_review_handoff(unit)
            ):
                # Persist the application order before dispatching its fixer.
                # An upgraded run must never fall back to reviewing an
                # accepted result that has not reached the workspace.
                self._save()
        except profiles.ProfileError as exc:
            st.fail_run(
                self.state,
                "strategy profile change invalid: %s" % exc,
                unit=st.current_unit(self.state),
                type_="orchestrator",
            )
            self._save()
            return (
                Action(A_FAILED, reason=str(exc)),
                "run failed: %s" % exc,
            )
        try:
            return decide(self.state), None
        except st.IllegalTransition as exc:
            unit = st.current_unit(self.state)
            events = self.state.get("events") or []
            changed_profile_governs = any(
                event.get("type") == "profile_changed"
                for event in reversed(events)
            )
            if (
                not changed_profile_governs
                or unit is None
                or unit.get("status") != st.U_ROUNDS
                or interpreter.rounds_loop(self.state)
                == interpreter.FAMILY_UNTIL_CLEAN
            ):
                raise
            st.fail_run(
                self.state,
                "strategy profile change is not interpretable: %s" % exc,
                unit=unit,
                type_="orchestrator",
            )
            self._save()
            return (
                Action(A_FAILED, reason=str(exc)),
                "run failed: %s" % exc,
            )

    def step(self):
        """Execute exactly one action. Returns (action, note).

        Worker calls have at-least-once semantics: records are saved only
        after the handler completes, so a crash mid-handler re-executes the
        same call on resume (see README, "Operational semantics")."""
        with self._exclusive():
            self._assert_not_stale()
            action, boundary_note = self._decide_at_strategy_boundary()
            if action.type in (A_DONE, A_FAILED):
                return action, boundary_note
            handler = {
                A_DRAFT: self._do_draft,
                A_VERIFY: self._do_verify,
                A_REVIEW_ROUND: self._do_review_round,
                A_FIX: self._do_fix,
                A_DELTA_REVIEW: self._do_delta_review,
                A_SEAL_ATTEMPT: self._do_seal_attempt,
                A_BRAINSTORM_WAIT: self._do_brainstorming_wait,
            }[action.type]
            waiting_session = (
                self._brainstorming_wait_session()
                if action.type == A_BRAINSTORM_WAIT else None
            )
            try:
                note = handler()
            except StopStep as exc:
                return action, "run failed: %s" % exc
            if (
                action.type == A_BRAINSTORM_WAIT
                and self._brainstorming_wait_session() == waiting_session
            ):
                return action, note
            self._save()
            self._clear_busy()
            return action, note

    def _brainstorming_wait_session(self):
        unit = st.current_unit(self.state)
        if unit is None:
            return None
        return (unit.get("brainstorming_wait") or {}).get("session_id")

    def run(self, max_steps=1000):
        steps = 0
        while True:
            unit = st.current_unit(self.state)
            waiting = bool(unit and unit.get("brainstorming_wait"))
            waiting_session = self._brainstorming_wait_session()
            if steps >= max_steps and not waiting:
                with self._exclusive(adopt_producer_handoff=True):
                    self._assert_not_stale()
                    action, _note = self._decide_at_strategy_boundary()
                if action.type not in (A_DONE, A_FAILED):
                    return 3
            else:
                sealed_before = self._sealed_keys()
                previous_handoff = self._allow_producer_handoff
                self._allow_producer_handoff = True
                try:
                    action, _note = self.step()
                finally:
                    self._allow_producer_handoff = previous_handoff
            if action.type == A_DONE:
                if st.current_unit(self.state) is None:
                    with self._exclusive(adopt_producer_handoff=True):
                        self._assert_not_stale()
                        st.maybe_close_milestone(self.state)
                        self._save()
                return 0
            if action.type == A_FAILED:
                return 2
            if (
                action.type == A_BRAINSTORM_WAIT
                and self._brainstorming_wait_session() == waiting_session
            ):
                time.sleep(BRAINSTORMING_POLL_INTERVAL_S)
                continue
            steps += 1
            newly_sealed = self._sealed_keys() - sealed_before
            if newly_sealed and self._control().get("stop_after_seal"):
                # Operator-ordered safe pause: a seal is the one point
                # where worktree == HEAD == reviewed (the seal predicate),
                # so stopping here leaves the repo committed and clean for
                # an out-of-band build. One-shot: the flag clears on
                # honoring; a plain start resumes exactly where paused.
                with self._exclusive(adopt_producer_handoff=True):
                    self._assert_not_stale()
                    st.append_event(
                        self.state, "paused_after_seal",
                        units=sorted(newly_sealed),
                        note="operator-ordered safe pause at a sealed "
                             "point (worktree == HEAD == reviewed)",
                    )
                    self._save()
                self._clear_stop_after_seal()
                return 4
        return 3

    def _goal_for(self, unit):
        """The GOAL block a unit's prompts carry.

        Reform runs preserve the operator's goal as generated goal.md before
        the skeleton call. The skeleton consumes the goal inline when small;
        a LARGE goal (config goal_inline_max) rides as that ledger with an
        ordered full read instead of
        inline text: instructions must dominate a prompt (a 60K goal
        drowns the altitude rules and the output contract), and a file
        survives the worker's own context compaction where inline prose
        does not — the worker can re-read ground truth at any point.

        Reform runs, later units consume the current reviewed skeleton
        (spec §2's chain of consumption) — operator planning prose stops
        riding every downstream call, and downstream workers judge scope
        against that reviewed boundary rather than a raw brainstorm's
        non-binding sketches; goal.md stays one read away.

        Legacy and profile-less runs keep the full goal inline
        everywhere (bit-identical)."""
        if not interpreter.reform_active(self.state):
            return self.state["goal"]
        if unit["kind"] == st.UNIT_SKELETON:
            self._ensure_goal_ledger()
            limit = self.config.get("goal_inline_max")
            if not isinstance(limit, int) or limit <= 0:
                limit = 8000
            if len(self.state["goal"]) <= limit:
                return self.state["goal"]
            return (
                "the operator's goal document is preserved VERBATIM at "
                "%s (generated snapshot, frozen at launch — the live "
                "original may drift; this file is the mandate). Read it "
                "IN FULL before working: every requirement in it binds "
                "exactly as if it were printed here."
                % ledgers.goal_path(self.state)
            )
        self._ensure_goal_ledger()
        return (
            "the current reviewed skeleton at %s is the operative "
            "restatement of "
            "the goal — the milestone boundary; judge scope against IT. "
            "The operator's full original goal text is preserved at %s "
            "(generated snapshot); read it only to trace intent the "
            "skeleton does not settle."
            % (ledgers.skeleton_path(self.state),
               ledgers.goal_path(self.state))
        )

    def _producer_review_context(self, unit):
        """Expose the producer plan when a review must judge its visibility."""
        skeleton = next(
            (
                candidate for candidate in self.state.get("units", [])
                if candidate.get("kind") == st.UNIT_SKELETON
            ),
            None,
        )
        skeleton_path = (
            (skeleton or {}).get("artifact")
            or ledgers.skeleton_path(self.state)
        )
        if (
            unit["kind"] != st.UNIT_SKELETON
            and skeleton_path not in self._design_review_paths(unit)
            # An active design update may replace the structured slice plan
            # without changing a design-document path. Reuse that durable
            # authority so already-open updates need no marker or migration.
            and not unit.get("design_update")
        ):
            return None
        return {
            "producer_task_executor_by_slice": tasks.effective_slice_plan(
                self.state["milestone"]["slices"]
            ),
            "explicit_operator_overrides": (
                tasks.operator_producer_overrides(self.state)
            ),
            # The material an authorized caller wrote after the current plan
            # was installed. Same rule as a producer override and the same
            # cutoff: it supersedes the document's own column without
            # requiring the reviewed artifact to be rewritten.
            "explicit_operator_material_overrides": (
                tasks.operator_material_overrides(self.state)
            ),
        }

    def _ensure_goal_ledger(self):
        """Idempotent write of the goal.md snapshot ledger, for prompts
        that reference it before the first gate regeneration lands it
        (the skeleton draft of a large goal precedes every gate). Always
        called on the main thread during prompt assembly — before any
        report-call tamper snapshot, so the write is never attributed to
        a reviewer."""
        rel = ledgers.goal_path(self.state)
        path = os.path.join(self.workspace, rel)
        content = ledgers.render_goal(self.state)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                if fh.read() == content:
                    return
        except OSError:
            pass
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)

    def _resume_preserved_candidate(self, unit):
        """Replay a parked implementation only when its slice is due again."""
        marker = unit.get("preserved_candidate") or {}
        tree = marker.get("tree")
        refname = marker.get("ref")
        base = marker.get("base")
        if not (tree and refname and base) or not gitops.enabled(self.config):
            st.fail_run(
                self.state,
                "preserved candidate metadata is incomplete; refusing to "
                "rebuild or discard it",
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep("preserved candidate metadata incomplete")
        resume_base = marker.get("resume_base")
        merged_tree = marker.get("merged_tree")
        if resume_base is None or merged_tree is None:
            if gitops.parked_candidate_tree(self.workspace, refname) != tree:
                st.fail_run(
                    self.state,
                    "parked candidate ref is missing or changed; refusing to "
                    "rebuild or discard the saved implementation",
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep("parked candidate ref unavailable")
            resume_base = gitops.head_full_sha(self.workspace)
            try:
                merged_tree, conflicts = gitops.merge_candidate_tree(
                    self.workspace, base, resume_base, tree
                )
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "could not prepare preserved candidate replay: %s" % exc,
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep(str(exc))
            if conflicts:
                marker["conflicts"] = conflicts
                st.fail_run(
                    self.state,
                    "preserved candidate overlaps repaired or newly inserted "
                    "work at %s; the candidate remains parked for explicit "
                    "resolution" % ", ".join(conflicts[:20]),
                    unit=unit,
                    type_="candidate_replay",
                )
                self._save()
                raise StopStep("preserved candidate replay conflicts")
            marker["resume_base"] = resume_base
            marker["merged_tree"] = merged_tree
            st.append_event(
                self.state,
                "candidate_replay_prepared",
                unit=st.unit_key(unit),
                base=resume_base,
                merged_tree=merged_tree,
            )
            return "preserved candidate replay prepared"
        try:
            sha = gitops.restore_parked_candidate(
                self.workspace,
                resume_base,
                merged_tree,
                "wip: %s (preserved after design repair)" % st.unit_key(unit),
            )
            gitops.delete_parked_candidate(self.workspace, refname)
        except gitops.GitError as exc:
            st.fail_run(
                self.state,
                "could not restore preserved candidate: %s" % exc,
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep(str(exc))
        unit.pop("preserved_candidate", None)
        st.append_event(
            self.state,
            "candidate_replayed_after_redoc",
            unit=st.unit_key(unit),
            sha=sha,
            tree=merged_tree,
        )
        return None

    def _do_draft(self):
        unit = _current_author_unit(self.state)
        if unit.get("preserved_candidate"):
            prepared = self._resume_preserved_candidate(unit)
            if prepared is not None:
                return prepared
        if unit.get("draft") is not None:
            if unit.get("pending_wip"):
                return self._complete_pending_wip(unit)
            if (
                unit["kind"] == st.UNIT_SLICE_IMPL
                and unit.get("implementation_attempt_snapshot")
                and gitops.enabled(self.config)
            ):
                # The WIP-intent snapshot itself may have failed before its
                # marker was saved.  New size-controlled implementations
                # retain their attempt baseline, so retry WIP preparation;
                # never fall through to the historical no-marker shortcut.
                return self._finish_draft(
                    unit, "recovered implementation draft"
                )
            if (
                unit["kind"] == st.UNIT_SKELETON
                and self._guarantee_calibration_config() is not None
                and (unit.get("guarantee_calibration") or {}).get("status")
                != "complete"
            ):
                return self._start_guarantee_calibration(unit)
            # Defensive compatibility for a persisted post-draft unit whose
            # status was left pending by an older/crashed driver. The work is
            # already present; never call the implementer twice or livelock
            # trying to establish a pre-work baseline after the fact.
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="recovered pending unit with recorded draft",
            )
            return "recorded draft recovered; review cycle opened"
        kind = {
            st.UNIT_SKELETON: contracts.KIND_DRAFT_SKELETON,
            st.UNIT_SLICE_DOC: contracts.KIND_DRAFT_SLICE_NOTE,
            st.UNIT_SLICE_IMPL: contracts.KIND_IMPLEMENT,
        }[unit["kind"]]
        if self._ensure_author_plan(unit, kind):
            return "canonical plan established; work order refreshed"
        if (
            kind in tasks.PRODUCER_TASK_KINDS
            and self._brainstorming_producer_selected(unit, kind)
        ):
            return self._start_brainstorming_production(unit, kind)
        active_task = self._active_worker_task(unit, kind)
        carrier = unit.get("brainstorming_resume") or {}
        has_validated_carrier = bool(carrier)
        # A synchronously validated carrier already records the physical call's
        # identity.  Consume that evidence before consulting current staffing;
        # profile availability is relevant only when another dispatch may run.
        if has_validated_carrier:
            family = (
                carrier.get("family")
                or self.config["families_order"][0]
            )
            model = carrier.get("model")
            effort = carrier.get("effort")
            dispatch_resolver = None
        else:
            # The unit's own seat: `plan` for the skeleton, `draft` for a
            # slice note, `implement` for an implementation. Only its
            # reviews use the review seats.
            if self.model_profiles_home is not None:
                family, model, effort = self._worker_staffing(unit, kind)
            elif unit["kind"] == st.UNIT_SKELETON:
                family, model, effort = self._skeletoner_profile()
            else:
                act = (
                    "implementer"
                    if unit["kind"] == st.UNIT_SLICE_IMPL else "drafter"
                )
                family, model, effort = self._act_profile(act)
            dispatch_resolver = self._dispatch_for_worker_kind(unit, kind)
        authority = None
        if not has_validated_carrier:
            authority = self._worker_episode_authority(unit, kind)
            project_context = authority["project_context"]
            extensions = authority["extensions"]
            roots = authority["roots"]
        else:
            project_context = extensions = roots = None
        battery = None
        resume_context = (
            "RESUMED AUTHOR EPISODE\n"
            "Continue the already-admitted author work from the current "
            "repository bytes; do not rely on text from an earlier provider "
            "attempt."
            if active_task is not None else None
        )
        material = self._author_material(unit, kind, active_task)
        author_coordinates = self._author_coordinates(
            unit, kind, active_task
        )
        if active_task is not None:
            prompt = active_task["order"]["request"]["request"]
        else:
            preview_meter = None
            if (
                kind == contracts.KIND_IMPLEMENT
                and gitops.enabled(self.config)
                and unit.get("implementation_stabilization") is None
            ):
                preview_meter = self._implementation_size_settings()
            prompt = self._prepare_author_package(
                unit,
                kind,
                material,
                authority,
                recovery=resume_context,
                meter=preview_meter,
                author_coordinates=author_coordinates,
            ).prompt
        # The reviewed baseline as it stands BEFORE the builder runs: the local
        # ref map, HEAD's branch identity and commit tip, and the index tree
        # (== HEAD, or an adopted repo's staged pre-run edits). If the builder
        # gaps, these handles restore exactly this — undoing its scratch work
        # even if it staged, committed, switched or deleted branches — without
        # reverting the baseline.
        pre_refs = pre_sym = pre_head = pre_tree = pre_stash = None
        if gitops.enabled(self.config):
            try:
                pre_refs = gitops.snapshot_refs(self.workspace)
                pre_sym = gitops.head_symbolic_ref(self.workspace)
                pre_head = gitops.head_full_sha(self.workspace)
                pre_tree = gitops.snapshot_index_tree(self.workspace)
                pre_stash = gitops.snapshot_stash(self.workspace)
            except gitops.GitError:
                pre_refs = pre_sym = pre_head = pre_tree = pre_stash = None
        implementation_attempt = unit.get("implementation_attempt_snapshot")
        if kind == contracts.KIND_IMPLEMENT and gitops.enabled(self.config):
            # One implementation attempt may span provider failure, Resume,
            # Brainstorming, contract repair and cutoff recovery.  Freeze its
            # original Git baseline before the first worker call; never let
            # staged scratch from a dead worker become the next call's zero.
            if not implementation_attempt:
                queued = unit.get("brainstorming_resume") or {}
                queued_pre = queued.get("pre_snapshot") or {}
                source = queued_pre if queued_pre.get("tree") else {
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "stash": pre_stash,
                }
                if (
                    source.get("refs") is not None
                    and source.get("sym") is not None
                    and source.get("head") is not None
                    and source.get("tree") is not None
                ):
                    implementation_attempt = {
                        key: copy.deepcopy(source.get(key))
                        for key in ("refs", "sym", "head", "tree", "stash")
                    }
                    unit["implementation_attempt_snapshot"] = (
                        implementation_attempt
                    )
                    st.append_event(
                        self.state,
                        "implementation_size_baseline_recorded",
                        unit=st.unit_key(unit),
                        tree=implementation_attempt["tree"],
                    )
                    self._save()
            if implementation_attempt:
                pre_refs = copy.deepcopy(implementation_attempt.get("refs"))
                pre_sym = implementation_attempt.get("sym")
                pre_head = implementation_attempt.get("head")
                pre_tree = implementation_attempt.get("tree")
                pre_stash = copy.deepcopy(implementation_attempt.get("stash"))
        raw_name = "%s-draft" % st.unit_key(unit)
        stabilization = (
            unit.get("implementation_stabilization")
            if kind == contracts.KIND_IMPLEMENT else None
        )
        stabilization_size = (
            copy.deepcopy(stabilization.get("implementation_size"))
            if isinstance(stabilization, dict)
            and isinstance(stabilization.get("implementation_size"), dict)
            else None
        )
        if stabilization is not None and stabilization_size is None:
            st.fail_run(
                self.state,
                "implementation stabilization metadata is incomplete",
                unit=unit,
                type_="orchestrator",
            )
            self._save()
            raise StopStep("implementation stabilization metadata incomplete")
        if stabilization_size is not None:
            self._ensure_implementation_stabilization_events(
                unit, stabilization_size
            )
            raw_name += "-stabilize"
        resumed = self._take_brainstorming_resume(unit, kind)
        implementation_size = None
        implementation_stabilized = False
        design_before = None
        if resumed is not None:
            output, result, raw_path = resumed
            family = result.origin_family or family
            model = result.origin_model or model
            effort = result.origin_effort or effort
            original_pre = result.origin_pre_snapshot or {}
            pre_refs = original_pre.get("refs")
            pre_sym = original_pre.get("sym")
            pre_head = original_pre.get("head")
            pre_tree = original_pre.get("tree")
            pre_stash = original_pre.get("stash")
            implementation_size = copy.deepcopy(
                original_pre.get("implementation_size")
            )
            implementation_stabilized = bool(
                original_pre.get("implementation_stabilized")
            )
        else:
            if unit.get("design_update"):
                design_before = self._snapshot()
            validate_opts = {
                **(
                    {"battery_questions": battery}
                    if battery else {}
                ),
                **(
                    {"require_failure_gap": True}
                    if self._legacy_failure_gap_required(unit, kind)
                    else {}
                ),
            } or None
            start_session = kind in contracts.RETHINK_CONTINUATION_KINDS
            task = self._admit_worker_task(
                unit,
                kind,
                prompt,
                family,
                model=model,
                effort=effort,
                dispatch_resolver=dispatch_resolver,
                project_context=project_context,
                validate_opts=validate_opts,
                author_coordinates=author_coordinates,
            )
            self._activate_worker_episode_authority(authority)
            validate_opts = self._worker_task_validate_opts(
                task, validate_opts
            )
            material = self._author_material(unit, kind, task)
            if kind == contracts.KIND_IMPLEMENT:
                def dispatch(request):
                    # The admitted order is immutable scheduling history. A
                    # later Worker episode decorates this physical call
                    # without rewriting the frozen request in that order.
                    call_prompt = prompt
                    return self._call_implementation(
                        family,
                        call_prompt,
                        raw_name,
                        model,
                        effort,
                        extensions,
                        roots,
                        validate_opts,
                        start_session,
                        (implementation_attempt or {}).get("tree") or pre_tree,
                        stabilizing=stabilization_size is not None,
                        dispatch_resolver=dispatch_resolver,
                        task_id=task["id"],
                        episode_refresher=lambda next_prompt: (
                            self._refresh_worker_episode(
                                unit, kind, next_prompt
                            )
                        ),
                        prepare_author=lambda recovery, meter: (
                            self._author_prepare_call(
                                unit,
                                kind,
                                material,
                                raw_name,
                                recovery=recovery,
                                meter=meter,
                                author_coordinates=author_coordinates,
                            )
                        ),
                        author_recovery=resume_context,
                        episode_unit=unit,
                    )

                (
                    output,
                    result,
                    raw_path,
                    implementation_size,
                    implementation_stabilized,
                ) = tasks.execute_worker(
                    task,
                    dispatch,
                )
                if stabilization_size is not None:
                    implementation_size = stabilization_size
            else:
                output, result, raw_path = tasks.execute_worker(
                    task,
                    lambda _request: self._call(
                        family,
                        prompt,
                        kind,
                        raw_name,
                        model=model,
                        effort=effort,
                        extensions=extensions,
                        roots=roots,
                        validate_opts=validate_opts,
                        start_session=start_session,
                        dispatch_resolver=dispatch_resolver,
                        task_id=task["id"],
                        prepare_call=self._author_prepare_call(
                            unit,
                            kind,
                            material,
                            raw_name,
                            recovery=resume_context,
                            author_coordinates=author_coordinates,
                        ),
                        episode_unit=unit,
                    ),
                )
            family, model, effort = self._result_identity(
                result, family, model, effort
            )
        if design_before is not None:
            self._record_design_changes(
                unit,
                self._snapshot_diff(design_before, self._snapshot()),
            )
        if output.get("status") == "need_rethink":
            self._enforce_sealed_artifacts(
                raw_name,
                editable_sealed=self._editable_design_paths(unit),
                preserve_canonical_plan=True,
            )
            return self._start_rethink(
                unit,
                kind,
                family,
                model,
                effort,
                output,
                result,
                raw_path,
                raw_name,
                pre_snapshot={
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "stash": pre_stash,
                    "implementation_size": copy.deepcopy(
                        implementation_size
                    ),
                    "implementation_stabilized": bool(
                        implementation_stabilized
                    ),
                },
            )
        if output.get("status") == "gap":
            # The builder met a build-changing hole/conflict and stopped
            # (reform §3). Route it upstream (repair) or to the operator
            # (goal). The unit finished NOTHING and stays pending; it
            # re-drafts after the repair reseals.
            return self._handle_gap(unit, output, result.duration_s,
                                    token_usage=getattr(result, "token_usage", None),
                                    token_usage_partial=getattr(
                                        result, "token_usage_partial", False
                                    ),
                                    cost=getattr(result, "cost", None),
                                    cost_partial=getattr(
                                        result, "cost_partial", False
                                    ),
                                    task_id=getattr(result, "task_id", None),
                                    result=result,
                                    pre_tree=pre_tree, pre_head=pre_head,
                                    pre_sym=pre_sym, pre_refs=pre_refs,
                                    pre_stash=pre_stash)
        self._enforce_sealed_artifacts(
            raw_name,
            editable_sealed=self._editable_design_paths(unit),
            preserve_canonical_plan=True,
        )
        self._check_worker_blocked(unit, output, kind, family, result)
        implementation_cut = output.get("implementation_cut")
        if implementation_cut is not None:
            st.record_implementation_cut(
                self.state,
                unit,
                implementation_cut["cut_scope"],
                implementation_cut["remaining_scope"],
                steer_lines=(implementation_size or {}).get("steer_lines"),
                interrupt_lines=(implementation_size or {}).get(
                    "interrupt_lines"
                ),
            )
        if kind == contracts.KIND_IMPLEMENT:
            unit.pop("implementation_stabilization", None)
        st.record_draft(self.state, unit, kind, output, raw_path,
                        family=family, duration=result.duration_s,
                        model=model, effort=effort,
                        token_usage=getattr(result, "token_usage", None),
                        token_usage_partial=bool(
                            getattr(result, "token_usage_partial", False)
                            or getattr(result, "token_usage", None) is None
                        ),
                        cost=getattr(result, "cost", None),
                        cost_partial=bool(
                            getattr(result, "cost_partial", False)
                            or getattr(result, "cost", None) is None
                        ),
                        task_id=getattr(result, "task_id", None),
                        prompt_set_fallback=getattr(
                            result, "prompt_set_fallback", None
                        ))
        self._terminalize_worker_task(unit, output, result=result)
        if kind == contracts.KIND_IMPLEMENT and output.get("suite_command"):
            st.set_discovered_suite(self.state, output["suite_command"])
        if (
            unit["kind"] == st.UNIT_SKELETON
            and self._guarantee_calibration_config() is not None
        ):
            unit["guarantee_calibration"] = {"status": "pending"}
            return self._start_guarantee_calibration(unit)
        return self._finish_draft(unit, "drafted")

    # -- gap routing (reform §3: stop-report-repair-resume) -----------------

    def _find_unit(self, kind, slice_id):
        for u in self.state["units"]:
            if u["kind"] == kind and u["slice_id"] == slice_id:
                return u
        return None

    def _last_sealed_seq(self, unit_key):
        """Event seq of the unit's LAST transition to sealed, or -1. The
        ledger seq is the run's total order — unlike second-resolution
        timestamps, it cannot tie (same-second seals) or run backwards
        (DST rollback)."""
        last = -1
        for e in self.state["events"]:
            if e.get("type") == "unit_transition" \
                    and e.get("to_status") == st.U_SEALED \
                    and e.get("unit") == unit_key:
                last = e.get("seq", -1)
        return last

    @staticmethod
    def _last_seal_at(unit):
        for rec in reversed((unit or {}).get("seals") or []):
            if rec.get("passed"):
                return rec.get("at") or ""
        return ""

    def _note_predates_skeleton(self, slice_id):
        """True when the governing slice note sealed BEFORE the skeleton's
        latest reseal — i.e. a remodel happened after the note was written.
        The implementer must then read the CURRENT skeleton: a remodel may
        assign this slice work its (stale) note never mentions, and only
        the gap REPORTER carries has_gap_remodel — a PRODUCER slice whose
        note sealed pre-remodel would otherwise build from the stale note
        and force the reporter to gap again. Ordered by ledger seq (total,
        clock-proof); operator hand-seals may lack transition events, so
        the second-resolution seal timestamps remain as fallback."""
        skeleton = self._find_unit(st.UNIT_SKELETON, None)
        note = self._find_unit(st.UNIT_SLICE_DOC, slice_id)
        sk_seq = self._last_sealed_seq(st.UNIT_SKELETON)
        note_seq = self._last_sealed_seq(st.unit_key(note)) if note else -1
        if sk_seq >= 0 and note_seq >= 0:
            return sk_seq > note_seq
        sk_at, note_at = self._last_seal_at(skeleton), self._last_seal_at(note)
        return bool(sk_at and note_at and sk_at > note_at)

    def _gap_to_finding(self, gap, i, reporter_key):
        """A fits_remodel gap becomes a P1 repair OBJECTIVE for the skeleton
        fixer — a documentary target ("the design under-specifies X; update it
        so a NOT-YET-BUILT step produces X before the reporter needs it"),
        never orchestration vocabulary. Steps run in the slice TABLE's row
        order and the reporter re-drafts after the remodel, so the producer
        may be the reporter itself or any unbuilt step placed before it —
        including a NEW slice inserted in the table (current_unit follows
        table order, so an inserted step genuinely runs first). A sealed
        step is not rerun and its historical episode is not reopened, but it
        does not permanently own the files or code it introduced: the
        reporting or newly inserted slice may modify them when the revised
        skeleton assigns that work. Its proposal, when present, is carried
        as CONTEXT and marked as a proposal — the fixer verifies it against
        the sources, never adopts it on trust (reform decision 6)."""
        summary = (
            "REMODEL OBJECTIVE (a step downstream cannot proceed): %s. "
            "Update the skeleton design so this is resolved: specify which "
            "NOT-YET-BUILT step produces/records what is missing within its "
            "own scope — %s itself (the step that reported this and will "
            "re-draft against the remodel), or a step placed BEFORE it in "
            "the slice table (steps run in table order; a new slice inserted "
            "there runs first). Do not rerun or assign new work to an "
            "already-sealed step; instead assign the correction to one of "
            "those unbuilt steps. That implementing step may modify code "
            "first introduced by a sealed step when the revised scope "
            "requires it; historical seals stay closed. "
            "Resolve: %s."
        ) % (
            gap.get("missing_or_conflict", ""), reporter_key,
            gap.get("forced_decision", "")
        )
        if gap.get("proposal"):
            summary += (
                " Proposal (a PROPOSAL — verify independently against the "
                "sources, do not adopt on trust): %s" % gap["proposal"]
            )
        finding = {"id": "GAP%d" % (i + 1), "severity": "P1",
                   "summary": summary,
                   "validity": {
                       "permitted_baseline": (
                           "the goal is represented by a coherent skeleton "
                           "that assigns every required implementation"
                       ),
                       "actual_outcome": gap.get("missing_or_conflict", ""),
                       "incremental_harm": (
                           "the reporting step cannot implement the goal "
                           "until the design assigns the missing work"
                       ),
                       "exceeds_baseline": True,
                   }}
        if gap.get("plain"):
            finding["plain"] = gap["plain"]
        if gap.get("example"):
            finding["example"] = gap["example"]
        return finding

    def _handle_gap(self, unit, output, duration_s=None, token_usage=None,
                    token_usage_partial=False, cost=None, cost_partial=False,
                    pre_tree=None,
                    pre_head=None, pre_sym=None, pre_refs=None, pre_stash=None,
                    pre_worktree_tree=None, from_fixer=False, task_id=None,
                    result=None):
        gaps = output.get("gaps", [])
        st.append_event(
            self.state, "gap_reported", unit=st.unit_key(unit),
            duration_s=duration_s,
            token_usage=copy.deepcopy(token_usage),
            token_usage_partial=bool(
                token_usage_partial or token_usage is None
            ),
            cost=copy.deepcopy(cost),
            cost_partial=bool(cost_partial or cost is None),
            count=len(gaps),
            from_fixer=from_fixer,
            gaps=[{k: g.get(k)
                   for k in ("classification", "forced_decision", "plain")}
                  for g in gaps],
            **self._prompt_set_fallback_fields(result),
            **self._task_id_fields(task_id),
        )
        self._terminalize_worker_task(
            unit,
            output,
            status="failure",
            reason="Worker routed the scheduling decision to gap handling",
            task_id=task_id,
            result=result,
        )
        # Persist the validated gap BEFORE any cleanup or routing. From the
        # moment the worker returns a gap, a crash must RE-ROUTE it on restart,
        # never let the reporter silently re-draft: a divergent re-draft would
        # bury the design hole — drift through the back door, exactly what the
        # gap exit exists to prevent. The pre-call baseline snapshot rides along
        # so recovery can still clean the worktree deterministically.
        self.state["pending_gap"] = {
            "reporter": st.unit_key(unit),
            "gaps": gaps,
            "pre_tree": pre_tree,
            "pre_head": pre_head,
            "pre_sym": pre_sym,
            "pre_refs": pre_refs,
            "pre_stash": pre_stash,
            "pre_worktree_tree": pre_worktree_tree,
            # A FIXER gap is mid-episode, not a "finished nothing" builder:
            # its reporter already committed a draft wip and may hold prior
            # fix work, so the builder scratch-cleanup (restore to the
            # pre-CALL snapshot) misfires. _route_pending_gap branches on this.
            "from_fixer": from_fixer,
            **self._task_id_fields(task_id),
        }
        self._save()
        return self._route_pending_gap()

    def _park_fixer_candidate(self, unit, baseline, tree, refname):
        """Pause a built slice for redoc without erasing its implementation."""
        prior = unit["status"]
        unit["preserved_candidate"] = {
            "base": baseline,
            "tree": tree,
            "ref": refname,
        }
        unit["fix_queue"] = []
        unit["fix_source"] = None
        unit.pop("phantom_retried", None)
        unit.pop("baseline_verification", None)
        unit.pop("baseline_unstable_runs", None)
        unit.pop("brainstorming_resume", None)
        unit["fix_loop_rounds"] = 0
        unit["verify_fix_attempts"] = {"pre_review": 0, "pre_seal": 0}
        unit["rounds_amnesty"] = len(unit.get("rounds") or [])
        st.restart_reviews_after_candidate_change(
            self.state, unit, "candidate parked for sealed-design repair"
        )
        # Like reset_for_redraft, this is an intentional backward process
        # edge outside transition_unit. Unlike it, draft/artifact stay intact:
        # _do_draft's recovery branch reopens reviews without another builder.
        unit["status"] = st.U_PENDING
        st.append_event(
            self.state,
            "candidate_parked_for_redoc",
            unit=st.unit_key(unit),
            from_status=prior,
            base=baseline,
            tree=tree,
            ref=refname,
        )

    def _route_pending_gap(self):
        """Clean the worktree and route the recorded gap. Both the fresh path
        and the restart path come here, so it is rerunnable after a crash at
        any point: cleanup restores the recorded pre-call snapshot, and the
        fits_remodel reopen reuses an already-made repair commit and skips an
        already-applied reopen. Clears `pending_gap` once the gap reaches a
        durable terminal (an operator-gated failure, or the reopen applied)."""
        pending = self.state.get("pending_gap")
        if not pending:
            return "no pending gap"
        unit = self._unit_by_key(pending["reporter"])
        if unit is None:
            self.state["pending_gap"] = None
            self._save()
            return "pending gap has no reporter; cleared"
        gaps = pending["gaps"]
        # A BUILDER gap FINISHES NOTHING (contract: no artifact, no file
        # changes). A builder that touched the repo before deciding to gap
        # leaves that behind; left in place a later commit (the repair commit
        # below, or — after the operator amends and resumes — the next
        # successful draft's `git add -A`) would adopt it, and a junk commit
        # the builder made itself would become the repair commit's parent. Undo
        # it all now, BEFORE routing, back to the pre-call snapshot. A FIXER gap
        # is different: its pre-call worktree is the valuable slice candidate.
        # Its dedicated branch below restores that exact tree (discarding only
        # the gapping call's scratch), then either keeps it in place for an
        # operator goal decision or parks it outside the redoc checkout.
        if not pending.get("from_fixer") and gitops.enabled(self.config):
            pre_tree = pending.get("pre_tree")
            pre_head = pending.get("pre_head")
            pre_sym = pending.get("pre_sym")
            pre_refs = pending.get("pre_refs")
            pre_stash = pending.get("pre_stash")
            if (pre_tree is None or pre_head is None or pre_sym is None
                    or pre_refs is None):
                # No pre-call snapshot (rare: the pre-draft git reads failed).
                # Committed or staged-only junk, a branch switch, or a deleted
                # branch is unrecoverable without it, so never route the gap
                # over a repo we cannot restore. (pre_sym == "" is a valid
                # DETACHED snapshot, not a missing one — only None means
                # missing.)
                st.fail_run(
                    self.state,
                    "cannot clean the repo after a gap from %s: the pre-draft "
                    "baseline snapshot is missing, so a builder's scratch work "
                    "cannot be safely discarded — operator inspection required"
                    % st.unit_key(unit),
                    unit=unit, type_="gap_cleanup",
                )
                self._save()
                raise StopStep("gap cleanup: no baseline snapshot")

            def _stash_shas():
                return [e[0] for e in gitops.snapshot_stash(self.workspace)]

            stash_want = ([e[0] for e in pre_stash]
                          if pre_stash is not None else None)

            def _diverges():
                return (
                    gitops.snapshot_refs(self.workspace) != pre_refs
                    or gitops.head_symbolic_ref(self.workspace) != pre_sym
                    or gitops.head_full_sha(self.workspace) != pre_head
                    or gitops.snapshot_index_tree(self.workspace) != pre_tree
                    or gitops.has_builder_edits(self.workspace)
                    or (stash_want is not None
                        and _stash_shas() != stash_want)
                )
            try:
                if _diverges():
                    gitops.restore_to_snapshot(
                        self.workspace, pre_refs, pre_sym, pre_head, pre_tree,
                        stash=pre_stash,
                    )
                    st.append_event(
                        self.state, "gap_edits_discarded",
                        unit=st.unit_key(unit),
                    )
                # Prove the repo is actually back to the snapshot; if anything
                # resisted cleanup (e.g. a stubborn nested repo), FAIL rather
                # than commit over it.
                if _diverges():
                    raise gitops.GitError(
                        "repo still diverges from the baseline after restore"
                    )
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "could not clean the repo after a gap from %s (%s): the "
                    "builder's scratch work cannot be safely discarded — "
                    "operator inspection required"
                    % (st.unit_key(unit), exc),
                    unit=unit, type_="gap_cleanup",
                )
                self._save()
                raise StopStep("gap cleanup failed")
        if not pending.get("from_fixer"):
            # Cleanup proved that this builder attempt has been abandoned.
            # A later re-draft must establish a fresh size baseline.
            unit.pop("implementation_attempt_snapshot", None)
            unit.pop("implementation_stabilization", None)
        operator_gaps = [
            g for g in gaps
            if g.get("classification") == contracts.CLASSIFY_NEEDS_OPERATOR
        ]
        if (
            not operator_gaps
            and self._modern_design_updates()
            and not gitops.enabled(self.config)
        ):
            # Only an already-running historical worker can still return this
            # retired result. Without Git there is no exact pre-call snapshot,
            # so retrying could adopt its abandoned scratch. Stop safely; never
            # fall through to the old re-documentation route.
            self.state["pending_gap"] = None
            st.fail_run(
                self.state,
                "cannot retry the retired in-goal gap from %s without an "
                "exact Git snapshot; inspect the preserved workspace and "
                "resume explicitly"
                % pending.get("reporter"),
                unit=unit,
                type_="gap_cleanup",
            )
            self._save()
            raise StopStep("retired gap has no restorable snapshot")
        if (
            not pending.get("from_fixer")
            and not operator_gaps
            and self._modern_design_updates()
        ):
            if int(unit.get("retired_gap_retries") or 0) >= 1:
                self.state["pending_gap"] = None
                st.fail_run(
                    self.state,
                    "%s repeated the retired in-goal gap route; use "
                    "need_rethink for the same design contradiction"
                    % pending.get("reporter"),
                    unit=unit,
                    type_="worker_protocol",
                )
                self._save()
                raise StopStep("retired in-goal gap route repeated")
            unit["retired_gap_retries"] = int(
                unit.get("retired_gap_retries") or 0
            ) + 1
            self.state["pending_gap"] = None
            st.append_event(
                self.state,
                "legacy_gap_retried_as_rethink",
                unit=st.unit_key(unit),
                from_fixer=False,
            )
            self._save()
            return (
                "retired in-goal gap cleared; the same draft retries with "
                "the rethink contract"
            )
        # A fixer gap is taken AFTER the slice already has a candidate. Restore
        # the exact PRE-FIXER worktree tree: this discards only the gapping
        # call's scratch while retaining the implementation and any earlier
        # accepted/pending fixes. A goal gap stops on those bytes. An in-goal
        # remodel parks the tree behind a durable ref, resets only the checkout
        # used by the documentation wave, and later replays the candidate over
        # the repaired/possibly-expanded history.
        if pending.get("from_fixer"):
            if gitops.enabled(self.config):
                pre_refs = pending.get("pre_refs")
                pre_sym = pending.get("pre_sym")
                pre_head = pending.get("pre_head")
                pre_tree = pending.get("pre_tree")
                candidate_tree = pending.get("pre_worktree_tree")
                baseline = gitops.newest_commit(
                    self.workspace,
                    [u.get("gate_commit") for u in self.state["units"]
                     if u.get("gate_commit")],
                )
                if (baseline is None or pre_refs is None or pre_sym is None
                        or pre_head is None or pre_tree is None
                        or candidate_tree is None):
                    self.state["pending_gap"] = None
                    st.fail_run(
                        self.state,
                        "cannot preserve fixer-gap reporter %s: missing its "
                        "exact pre-call candidate or sealed base — operator "
                        "inspection required" % st.unit_key(unit),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep("fixer-gap preservation: no baseline")
                try:
                    gitops.restore_to_snapshot(
                        self.workspace, pre_refs, pre_sym, pre_head,
                        candidate_tree,
                        stash=pending.get("pre_stash"),
                    )
                    if (
                        gitops.snapshot_index_tree(self.workspace)
                        != candidate_tree
                        or gitops.has_builder_edits(self.workspace)
                    ):
                        raise gitops.GitError(
                            "pre-fixer candidate tree did not restore exactly"
                        )
                except gitops.GitError as exc:
                    st.fail_run(
                        self.state,
                        "could not restore fixer-gap reporter %s before "
                        "routing (%s): candidate preserved for operator "
                        "inspection" % (st.unit_key(unit), exc),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep(str(exc))
                st.append_event(
                    self.state, "gap_edits_discarded", unit=st.unit_key(unit),
                    scope="gapping fixer scratch only",
                )
                if not operator_gaps and self._modern_design_updates():
                    if int(unit.get("retired_gap_retries") or 0) >= 1:
                        self.state["pending_gap"] = None
                        st.fail_run(
                            self.state,
                            "%s repeated the retired in-goal gap route; use "
                            "need_rethink for the same design contradiction"
                            % pending.get("reporter"),
                            unit=unit,
                            type_="worker_protocol",
                        )
                        self._save()
                        raise StopStep("retired fixer gap route repeated")
                    unit["retired_gap_retries"] = int(
                        unit.get("retired_gap_retries") or 0
                    ) + 1
                    self.state["pending_gap"] = None
                    st.append_event(
                        self.state,
                        "legacy_gap_retried_as_rethink",
                        unit=st.unit_key(unit),
                        from_fixer=True,
                    )
                    self._save()
                    return (
                        "retired fixer gap cleared; the same fix retries with "
                        "the rethink contract"
                    )
                if operator_gaps:
                    return self._route_goal_gap(unit, operator_gaps[0])
                refname = self._parked_candidate_ref(unit)
                try:
                    gitops.park_candidate_tree(
                        self.workspace, refname, candidate_tree
                    )
                    gitops.reset_hard(self.workspace, baseline)
                except gitops.GitError as exc:
                    st.fail_run(
                        self.state,
                        "could not park fixer-gap reporter %s for design "
                        "repair (%s) — operator inspection required"
                        % (st.unit_key(unit), exc),
                        unit=unit, type_="gap_cleanup",
                    )
                    self._save()
                    raise StopStep(str(exc))
                self._park_fixer_candidate(
                    unit, baseline, candidate_tree, refname
                )
        # The worker classified; the machine routes. needs_operator OUTRANKS
        # fits_remodel: a goal-level issue must reach the operator even if it
        # arrived alongside in-goal remodels. Everything else (all
        # fits_remodel) reopens the skeleton — the design authority — toward
        # the gaps as an objective; the design is remodelled and the pointer
        # continues, never touching the operator.
        if operator_gaps:
            return self._route_goal_gap(unit, operator_gaps[0])
        skeleton = self._find_unit(st.UNIT_SKELETON, None)
        if skeleton is None or skeleton is unit \
                or skeleton["status"] != st.U_SEALED:
            # A fits_remodel needs a sealed skeleton to remodel; a skeleton
            # builder cannot remodel itself. That is a routing impossibility,
            # not an operator decision — fail loudly rather than loop.
            self.state["pending_gap"] = None
            st.fail_run(
                self.state,
                "fits_remodel gap from %s has no sealed skeleton to remodel"
                % st.unit_key(unit),
                unit=unit, type_="gap_route",
            )
            self._save()
            raise StopStep("fits_remodel gap with no sealed skeleton")
        return self._reopen_and_repair(unit, skeleton, gaps, gaps[0])

    def _route_goal_gap(self, unit, primary):
        """A gap targeting the goal routes to the OPERATOR — the goal is
        operator-authored and only its author repairs it. The operator
        resolves by amending the goal (the existing amendment mechanism
        binds from the next call) and resuming; the fresh draft then sees
        the amendment. Operator-gated failure: not auto- or emergency-
        resumed (re-drafting would just re-report the same gap)."""
        st.append_event(
            self.state, "goal_gap_reported", unit=st.unit_key(unit),
            forced_decision=str(primary.get("forced_decision", ""))[:400],
            plain=str(primary.get("plain", ""))[:400],
            example=str(primary.get("example", ""))[:400],
        )
        st.fail_run(
            self.state,
            "goal gap: %s — resolve by amending the goal, then resume "
            "(the goal is operator-authored; only its author repairs it)"
            % primary.get("forced_decision", ""),
            unit=unit, type_="goal_gap",
        )
        # Escalated: the operator-gated failure is now the durable record, so
        # the pending-gap intent is discharged.
        self.state["pending_gap"] = None
        self._save()
        raise StopStep("goal gap reported to the operator")

    def _commit_repair_wip(self, message):
        """Open the fresh repair commit atomically: snapshot the repo state
        immediately before committing, and on ANY GitError roll back to it —
        a commit hook that dirties the tree then fails, or a commit that lands
        but whose sha lookup fails, must not leave partial state the resumed
        run would fold in. Re-raises for the caller to fail the run."""
        snap = (
            gitops.snapshot_refs(self.workspace),
            gitops.head_symbolic_ref(self.workspace),
            gitops.head_full_sha(self.workspace),
            gitops.snapshot_index_tree(self.workspace),
        )
        try:
            return gitops.commit_wip(self.workspace, message)
        except gitops.GitError:
            try:
                gitops.restore_to_snapshot(self.workspace, *snap)
            except gitops.GitError:
                pass  # best effort; the caller fails the run regardless
            raise

    def _unit_by_key(self, key):
        for u in self.state["units"]:
            if st.unit_key(u) == key:
                return u
        return None

    def _reopen_and_repair(self, unit, target_unit, gaps, primary):
        target_key = st.unit_key(target_unit)
        reporter_key = st.unit_key(unit)
        # Idempotent restart: if the reopen already applied before a crash, the
        # pending-gap intent just needs discharging.
        if target_unit.get("under_repair"):
            self.state["pending_gap"] = None
            self._save()
            return "gap repair already applied; intent cleared"
        cap = int(self.config.get("max_gap_repairs", 3))
        n = int(unit.get("gap_repairs", 0)) + 1
        if n > cap:
            unit["gap_repairs"] = n
            self.state["pending_gap"] = None  # terminal failure; discharge it
            st.fail_run(
                self.state,
                "design remodel not converging after %d attempts on %s: the "
                "skeleton keeps being reopened for the same objective without "
                "clearing it — the objective may be malformed or the "
                "downstream builder keeps re-reporting; needs a look"
                % (cap, st.unit_key(unit)),
                unit=unit, type_="gap_stall",
            )
            self._save()
            raise StopStep("gap-repair cap exceeded")
        # Every fits_remodel gap routes to the skeleton (the design
        # authority), so all reported gaps become objectives for it, each
        # pinned to the reporting unit's own scope.
        repair_findings = [self._gap_to_finding(g, i, reporter_key)
                           for i, g in enumerate(gaps)]
        # The reopened design unit's own commit is buried under every unit
        # sealed since (HEAD is the latest sealed unit's commit); its repair
        # amends HEAD, so a fresh commit it owns keeps that amend from
        # rewriting a later sealed unit's commit. Always open a FRESH commit:
        # the whole gap transaction is durable (pending_gap was persisted
        # before routing), and on a crash-retry _route_pending_gap's cleanup
        # already reset the branch to the recorded pre-call HEAD — undoing any
        # stray repair commit a prior attempt made — so nothing is reused and
        # nothing stacks. (Reusing by commit shape could grab an unrelated
        # same-named commit and let the amend rewrite it.)
        sha = None
        if gitops.enabled(self.config):
            try:
                sha = self._commit_repair_wip("wip-repair: %s" % target_key)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state,
                    "repair reopen commit failed: %s" % exc, unit=target_unit,
                )
                self._save()
                raise StopStep(str(exc))
        unit["gap_repairs"] = n
        # A DURABLE record that this slice's design was remodelled, distinct
        # from gap_repairs (a convergence cap the operator's resume resets to
        # 0): the re-draft's REMODEL ASSIGNMENT block gates on this, so a
        # post-resume draft still reads the remodelled skeleton instead of
        # silently following its stale sealed note.
        unit["has_gap_remodel"] = True
        # RE-DOCUMENTATION WAVE: the remodel reopens the WHOLE documentation
        # set — the skeleton (anchor) plus every sealed slice note. Whatever
        # the gap NAMED only orients the objective; it never bounds the edit
        # scope: the re-documenter has free rein under the GOAL to leave the
        # documentation coherent and continuable (restricting the set to the
        # named docs could leave an unnamed note incoherent and re-loop).
        # The notes wait in U_REPAIRING while the anchor's episode runs (its
        # fixer may edit them; the sealed-artifact guard only polices SEALED
        # units) and reseal via close_redoc_wave when the anchor's wave seal
        # passes. Docs reopen BEFORE the anchor so a crash mid-loop resumes
        # through the normal path (anchor still sealed -> re-route re-runs;
        # already-repairing docs are skipped).
        wave_docs = []
        for u in self.state["units"]:
            if u["kind"] != st.UNIT_SLICE_DOC:
                continue
            if u is target_unit or u is unit:
                continue
            if u.get("under_repair"):
                wave_docs.append(st.unit_key(u))  # resume: already reopened
                continue
            if u["status"] != st.U_SEALED:
                continue
            st.reopen_for_repair(
                self.state, u, primary,
                reason="re-documentation wave (gap from %s)" % reporter_key,
                reported_by=reporter_key,
            )
            wave_docs.append(st.unit_key(u))
        st.reopen_for_repair(
            self.state, target_unit, primary,
            reason="downstream %s reported a gap" % reporter_key,
            reported_by=reporter_key,
        )
        self.state["redoc_wave"] = {
            "anchor": target_key,
            "docs": wave_docs,
            "reporter": reporter_key,
        }
        if sha is not None:
            st.append_event(
                self.state, "wip_commit", unit=target_key, sha=sha
            )
        st.enter_fix_episode(
            self.state, target_unit, repair_findings, "repair", None,
            "%s-gap-repair" % target_key, st.U_PRE_SEAL_VERIFY,
        )
        # The reopen is applied and durable: discharge the intent.
        self.state["pending_gap"] = None
        self._save()
        return (
            "gap on %s -> re-documentation wave: reopened %s + %d slice "
            "note(s) (%d repair finding(s)); the set reseals, then %s %s"
            % (reporter_key, target_key, len(wave_docs),
               len(repair_findings), reporter_key,
               ("resumes its preserved candidate"
                if unit.get("preserved_candidate") else "re-drafts"))
        )

    def _pre_clean_pending_gap(self):
        """Best-effort worktree restore for a persisted-but-unrouted gap, run
        BEFORE repo validation so worker junk (e.g. a nested repo) cannot make
        ensure_repo reject the workspace and deadlock every resume. Silent on
        any error — a genuinely broken repo surfaces through ensure_repo, and
        _route_pending_gap re-verifies the cleanup before routing anyway.

        A FIXER gap runs this too (it must — its worker may have left a nested
        repo that would deadlock ensure_repo on every resume). For that branch
        the restore uses the exact pre-call WORKTREE tree, not merely its index,
        so accumulated legitimate fixes survive while gapping-call scratch is
        removed."""
        pending = self.state.get("pending_gap")
        if not pending or not gitops.enabled(self.config):
            return
        pre_refs = pending.get("pre_refs")
        pre_sym = pending.get("pre_sym")
        pre_head = pending.get("pre_head")
        pre_tree = pending.get("pre_tree")
        restore_tree = (
            pending.get("pre_worktree_tree")
            if pending.get("from_fixer") else pre_tree
        )
        pre_stash = pending.get("pre_stash")
        if pre_refs is None or pre_sym is None or pre_head is None \
                or restore_tree is None:
            return
        # Under the run lock, so it cannot race a concurrent invocation's
        # recovery; skips on contention (the lock holder restores) and on any
        # git error (a genuinely broken repo surfaces through ensure_repo).
        try:
            with self._exclusive():
                gitops.restore_to_snapshot(
                    self.workspace, pre_refs, pre_sym, pre_head, restore_tree,
                    stash=pre_stash,
                )
        except (ConcurrentRunError, gitops.GitError):
            pass

    def _consume_pending_gap(self):
        """A driver that died mid gap transaction (the validated gap recorded,
        not yet fully routed) re-routes it on startup, so the gap is never lost
        to a re-draft of the reporter. Idempotent: no intent is a no-op, an
        already-applied reopen just discharges the intent. Skipped while the
        run is failed — resume clears the failure first, then this runs.

        Runs UNDER the exclusive run lock, reloading fresh state so a second
        concurrent invocation cannot restore refs while this one is opening the
        repair commit; on lock contention it simply skips — the invocation that
        holds the lock does the (idempotent) recovery."""
        if not self.state.get("pending_gap") or self.state.get("failure"):
            return
        try:
            with self._exclusive():
                self.state = st.load(self.state_path)
                if not self.state.get("pending_gap") \
                        or self.state.get("failure"):
                    return
                self._route_pending_gap()
        except ConcurrentRunError:
            return
        except StopStep:
            pass  # a routing failure recorded a run failure; leave it be

    def _migrate_active_redoc_wave(self):
        """Retire an in-flight historical redocumentation wave.

        The current anchor keeps its ordinary fix/review position. Co-opened
        notes return to their prior terminal state, while every existing design
        document remains editable through one normal ``design_update`` owned by
        the anchor. Any active Brainstorming attachment and any parked
        implementation candidate are left untouched. The anchor's eventual
        ordinary gate binds the actually changed design paths.
        """
        if not self.state.get("redoc_wave"):
            return
        try:
            with self._exclusive():
                self.state = st.load(self.state_path)
                wave = self.state.get("redoc_wave")
                if not wave:
                    return
                anchor = self._unit_by_key(wave.get("anchor"))
                if anchor is None:
                    return
                anchor_sealed = anchor.get("status") == st.U_SEALED
                by_key = {
                    st.unit_key(unit): unit
                    for unit in self.state.get("units") or []
                }
                docs = [
                    by_key.get(key) for key in wave.get("docs") or []
                ]
                if any(
                    doc is None
                    or doc.get("status") not in (st.U_REPAIRING, st.U_SEALED)
                    for doc in docs
                ):
                    return

                editable_paths = self._design_document_paths()
                changed_paths = []
                candidates = [anchor] + [doc for doc in docs if doc is not None]
                for candidate in candidates:
                    artifact = candidate.get("artifact")
                    if not artifact or artifact not in editable_paths:
                        continue
                    changed = True
                    if gitops.enabled(self.config) and candidate.get("gate_commit"):
                        baseline = gitops.show_file(
                            self.workspace,
                            candidate["gate_commit"],
                            artifact,
                        )
                        changed = baseline != self._workspace_bytes(artifact)
                    if changed and artifact not in changed_paths:
                        changed_paths.append(artifact)

                for doc in docs:
                    if doc["status"] == st.U_REPAIRING:
                        st.transition_unit(
                            self.state,
                            doc,
                            st.U_SEALED,
                            reason=(
                                "historical redocumentation retired; changes "
                                "moved to the anchor's ordinary review"
                            ),
                        )

                trigger = next(
                    (
                        event for event in reversed(self.state.get("events") or [])
                        if event.get("type") == "reopened_for_repair"
                        and event.get("unit") == st.unit_key(anchor)
                    ),
                    {},
                )
                subject = (
                    trigger.get("plain")
                    or trigger.get("forced_decision")
                    or "the reported in-goal design contradiction"
                )
                text = (
                    "Apply the smallest coherent in-goal design update needed "
                    "for: %s. Preserve completed implementation and review the "
                    "changed design with the current unit's ordinary cycle."
                    % subject
                )
                amendment_id = "legacy-redoc-%d" % (
                    1
                    + sum(
                        event.get("type")
                        == "redoc_wave_migrated_to_design_update"
                        for event in self.state.get("events") or []
                    )
                )
                previous = anchor.get("design_update") or {}
                merged_editable = list(previous.get("editable_paths") or [])
                for path in editable_paths:
                    if path not in merged_editable:
                        merged_editable.append(path)
                merged_changed = list(previous.get("changed_paths") or [])
                for path in changed_paths:
                    if path not in merged_changed:
                        merged_changed.append(path)
                if not anchor_sealed:
                    anchor["design_update"] = {
                        **previous,
                        "amendment_id": amendment_id,
                        "amendment": text,
                        "editable_paths": merged_editable,
                        "changed_paths": merged_changed,
                    }
                anchor.pop("under_repair", None)
                self.state["redoc_wave"] = None
                st.append_event(
                    self.state,
                    (
                        "redoc_wave_retired_after_review"
                        if anchor_sealed
                        else "redoc_wave_migrated_to_design_update"
                    ),
                    unit=st.unit_key(anchor),
                    reporter=wave.get("reporter"),
                    amendment_id=amendment_id,
                    text=text,
                    authority="historical_design_update",
                    editable_paths=merged_editable,
                    changed_paths=merged_changed,
                )
                if anchor_sealed:
                    # The anchor's ordinary reviews already covered these
                    # bytes. Recover its post-review gate only when the crash
                    # occurred before that gate; never manufacture per-note
                    # review/seal records.
                    anchor_key = st.unit_key(anchor)
                    sealed_seq = gate_seq = -1
                    for event in self.state.get("events") or []:
                        if event.get("unit") != anchor_key:
                            continue
                        if (
                            event.get("type") == "unit_transition"
                            and event.get("to_status") == st.U_SEALED
                        ):
                            sealed_seq = event.get("seq", -1)
                        elif event.get("type") == "gate_commit":
                            gate_seq = event.get("seq", -1)
                    if gitops.enabled(self.config) and gate_seq < sealed_seq:
                        self.state["retired_redoc_docs_pending_gate"] = {
                            "anchor": anchor_key,
                            "docs": [st.unit_key(doc) for doc in docs],
                        }
                        self._gate_commit(anchor)
                    gate_sha = anchor.get("gate_commit")
                    if gate_sha:
                        for doc in docs:
                            doc["gate_commit"] = gate_sha
                    self._guard_unplanned_preserved_candidates()
                self._save()
        except ConcurrentRunError:
            return
        except StopStep:
            pass  # gate recovery recorded the failure and remains resumable

    def _slice_info(self, slice_id):
        for sl in self.state["milestone"]["slices"]:
            if sl["id"] == slice_id:
                return sl
        raise st.IllegalTransition("unknown slice id %r" % slice_id)

    def _guard_unplanned_preserved_candidates(self):
        """Never let a redoc row deletion silently destroy parked work."""
        planned = set(st.planned_units(self.state))
        for unit in self.state.get("units", []):
            marker = unit.get("preserved_candidate")
            if not marker or (unit["kind"], unit["slice_id"]) in planned:
                continue
            st.append_event(
                self.state,
                "preserved_candidate_lost_plan_assignment",
                unit=st.unit_key(unit),
                tree=marker.get("tree"),
                ref=marker.get("ref"),
            )
            st.fail_run(
                self.state,
                "repaired skeleton removed %s while its implementation "
                "candidate is parked at %s; refusing to discard or silently "
                "orphan that work" % (st.unit_key(unit), marker.get("ref")),
                unit=unit,
                type_="candidate_replay",
            )
            self._save()
            raise StopStep("preserved candidate lost its slice assignment")

    def _skeleton_artifact(self):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SKELETON:
                return u["artifact"] or ledgers.skeleton_path(self.state)
        return ledgers.skeleton_path(self.state)

    def _slice_note_artifact(self, slice_id):
        for u in self.state["units"]:
            if u["kind"] == st.UNIT_SLICE_DOC and u["slice_id"] == slice_id:
                return u["artifact"] or ledgers.slice_note_path(
                    self.state, slice_id
                )
        return ledgers.slice_note_path(self.state, slice_id)


    # -- review/fix separation machinery ------------------------------------

    def _registry(self):
        return st.adjudicated_rejections(self.state)

    def _debt(self, unit):
        return list(st.active_debt(self.state, unit))

    # -- staffing: the run's one session decides every driver-made call -----
    #
    # A driver with a catalogue home asks the router and nothing else. A
    # `Driver` built WITHOUT one has no document store to read, so it keeps
    # today's configuration-act resolution: it is a library and test
    # construction, not a channel an operator or a product can reach — the
    # service and every CLI entry point supply the home.
    #
    # WHICH read decides. One worker call reads the router more than once,
    # exactly as it read profiles before: `_worker_staffing` for the family
    # the PROMPT is built with, `_admit_worker_task` for the order's
    # best-effort `resolved_staffing`, `_call` to seed the in-flight marker,
    # and `runners`' dispatch hook. Only the LAST one staffs the call: the
    # earlier answers are prompt text and bookkeeping, are never cached
    # forward, and are overwritten by the hook's own retarget. "Do not
    # resolve at order time" is about AUTHORITY — no order-time answer may
    # decide a dispatch — not about the count of reads, since the prompt
    # cannot be written without a family and `resolved_staffing` is out of
    # this slice's scope.
    #
    # WHEN it is read. A seat is asked for only where a dispatch is really
    # due. The `classify` seat is the one that is often NOT: the debt
    # rater's single-family gate withholds the rating before any call, and
    # the failure classifier's LLM stage sits behind the deterministic
    # patterns and behind `error_classifier`. Resolving those speculatively
    # would let a surfaced condition stop a call nobody was going to make.

    def _derive_staffing_session(self):
        """Amendment A2: give a run that has none a session, once.

        The session REFERENCES the document named by the run's model-profile
        selection at that selection's rigor — `default` at `medium` when
        there is no selection, and `default` when no document carries that
        name — with the run's own configured families. NOTHING else is
        derived: the run's `acts.json` literals are not carried and no
        override is written from them; the document's own numbers apply from
        the next call, and the operator edits the session to change it.

        It reads `model_profile.json` and the stored document NAMES, and no
        other file, and writes only the session and the run's one key: no
        document, profile file or act sidecar is created, edited or deleted.
        Resume is NEVER failed or blocked for it — every step of the
        derivation, the catalogue listing included, leaves the run unbound
        on failure, and an unbound run sends every call to the resolver's
        visible default-document fallback.
        """
        if st.staffing_session(self.state):
            return
        try:
            selection = read_current_model_profile_selection(self.state_path)
        except model_profiles.ModelProfileError:
            selection = None
        selection = selection or {}
        name = selection.get("name")
        try:
            # Reading the catalogue to answer "does that name exist?" is
            # part of the derivation and fails like the rest of it: an
            # unreadable documents directory leaves the run UNBOUND rather
            # than escaping this method, which would raise out of the
            # constructor and block the resume A2 promises never to block.
            # Unbound is also the honest answer — binding `default` on a
            # read fault would write a once-only binding derived from a
            # fault, silently, where the resolver's fallback already gives
            # the same document with the marker's `staffing_fallback` note
            # and the next resume can still derive properly.
            document = (
                name
                if name in staffing.document_names(self.model_profiles_home)
                else staffing.DEFAULT_DOCUMENT_NAME
            )
            # `self.state` IS the record it binds, so the id is in force for
            # this process even when the save below is what failed.
            open_run_staffing_session(
                self.state_path,
                self.model_profiles_home,
                document,
                selection.get("rigor") or staffing.FALLBACK_RIGOR,
                run_state=self.state,
                derived=True,
            )
        except (staffing.StaffingError, OSError, st.HistoryRewriteError):
            return

    def _fail_staffing(self, exc, episode_unit=None):
        """Stop this dispatch through ordinary run recovery.

        The reason carries the surfaced condition's own token, which is the
        whole of what a consumer switches on. These are the ONLY two
        conditions that stop a driver call: everything else the router meets
        — an unreadable session or document, an unbound family, an
        out-of-range rank, an unknown material, an unassigned seat — has an
        answer.
        """
        reason = "staffing refused this call (%s): %s" % (exc.code, exc)
        if self.state.get("failure") is None:
            st.fail_run(
                self.state,
                reason,
                unit=(episode_unit or st.current_unit(self.state)),
                type_="orchestrator",
            )
            self._save()
        raise StopStep(reason)

    def _staffing_resolution(self, role, index=1, round=1, material=None,
                             episode_unit=None):
        """One router answer, read live from the run's session."""
        try:
            return staffing.resolve(
                self.model_profiles_home,
                st.staffing_session(self.state),
                role,
                index=index,
                round=round,
                material=material,
                families=list(self.config["families_order"]),
            )
        except staffing.StaffingConditionError as exc:
            self._fail_staffing(exc, episode_unit=episode_unit)

    def _continuation_may_plan_slices(self, unit):
        """Whether a resumed worker task may still author the slice plan.

        Keyed to what this driver can INSTALL from the continuation's result
        (`_maybe_update_slices`), never to the discussion's result mode: a
        skeleton fixer edits its own artifact's slice table under any mode,
        and a unit already carrying the skeleton among its editable design
        paths keeps that authority when its discussion returned a proposal
        rather than an amendment. Either one is a plan-authoring prompt and
        needs the pair read at THIS boundary, because the catalogue quoted
        inside its frozen request is the one its first call was dispatched
        with — a document edited since is otherwise invisible to it, and the
        retired vocabulary reads as current. This only widens the condition:
        every amendment case that carried the pair still does.
        """
        return (
            unit["kind"] == st.UNIT_SKELETON
            or self._skeleton_artifact() in self._editable_design_paths(unit)
        )

    def _planning_materials(self):
        """The material vocabulary a plan-authoring prompt shows, live.

        The `materials` of the document this run's session REFERENCES, read
        at the prompt boundary through the same validated session and
        document reads every dispatch uses. Guidance only: it names no
        agent, model or effort and decides no call, so an unreadable
        session or document leaves it empty and planning continues. That
        deliberately does NOT borrow the resolver's mandatory fallback — a
        catalogue from a document this run does not name would be a
        vocabulary nobody wrote for it, and inventing one is worse than
        asking for no proposal at all.
        """
        if self.model_profiles_home is None:
            return {}
        session = st.staffing_session(self.state)
        if not session:
            return {}
        try:
            record = staffing.read_session(self.model_profiles_home, session)
            document = staffing.load(
                self.model_profiles_home, record["document"]
            )
        except (staffing.StaffingError, OSError):
            return {}
        # Whether the prompt can CARRY a name is the prompt's own question,
        # not a reason to read less: a document that loads supplies every
        # name it validated, and `prompts._material_catalogue_json` decides
        # how to quote one no UTF-8 encoder emits.
        return copy.deepcopy(document["materials"])

    def _staff(self, role, index=1, round=1, material=None,
               episode_unit=None):
        """(family, model, effort) for one driver-made call."""
        answer = self._staffing_resolution(
            role, index, round, material=material,
            episode_unit=episode_unit,
        ).answer
        return answer["agent"], answer["model"], answer["effort"]

    def _dispatch_for_role(self, role, index=1, round=1, material=None,
                           episode_unit=None):
        """A fresh router resolution for every physical provider dispatch."""
        return _RoleDispatch(
            self, role, index=index, round=round, material=material,
            episode_unit=episode_unit,
        )

    # -- the review cycle IS the document's `review` seats ------------------
    #
    # Which families review a unit comes from the seats the run's session
    # document assigns to `review`, in index order, read live — not from the
    # run's configured family order. Rotation, the round cap, cycle
    # restarts, resume amnesty and the seal predicate keep exactly their
    # present shape; only the list they walk changes, so nothing about what
    # a review round means, about convergence or about sealing moves here.
    # A `Driver` with no catalogue home has no document to read and keeps
    # reviewing in the configured order.

    def _review_seats(self):
        """The `review` seat indices this run's document assigns, live.

        Never empty: every stored document assigns index 1 to every role
        (`staffing._validate_seats`), a session override only ADDS seats,
        and an unreadable session or document falls back to the default
        document, which assigns two. A family slot the document carries but
        assigns to no `review` seat adds no seat, because this reads the
        assignment and not the family table.
        """
        return staffing.session_seats(
            self.model_profiles_home,
            st.staffing_session(self.state),
            "review",
            families=list(self.config["families_order"]),
        )

    def _review_families(self):
        """The family each assigned `review` seat runs on, in seat order.

        The run's review cycle, as the rotation, the cap and the seal
        predicate read it. Describing the cycle DISPATCHES nothing, so it
        is a read and not a call: the router answers it from one reading of
        one document, and a `review` role whose declared split this session
        cannot honour comes back described rather than refused.
        `distinct_families_unsatisfiable` keeps the placement it is given —
        an affected review dispatch, and nothing else — because a read that
        stopped here would fail a run that called nobody, discard a clean
        cycle it has no authority over, and then buy every one of its
        rounds again after the repair.

        `staffing_unavailable` still raises: with no family available there
        is no cycle to describe, and an empty list is not the honest
        substitute, since the seal predicate reads it as a cycle with no
        seat left to review and would open a seal on no reviews at all.
        """
        if self.model_profiles_home is None:
            return list(self.config["families_order"])
        return staffing.session_seat_families(
            self.model_profiles_home,
            st.staffing_session(self.state),
            "review",
            families=list(self.config["families_order"]),
        )

    def _seal_reviews(self, unit, current_fingerprint=None):
        """The seal predicate over the CURRENTLY assigned review seats.

        Reading the cycle is not dispatching one, so a document whose
        `review` role declares a split this session cannot honour still
        seals here on the rounds its currently assigned seats have already
        earned — the same pre-seal path a shrunken seat list takes, which
        seals on the current seats or restarts because one is not clean.
        `staffing_unavailable` leaves no cycle to describe and takes its
        own declared route through ordinary recovery naming its token.
        """
        try:
            families = self._review_families()
        except staffing.StaffingConditionError as exc:
            self._fail_staffing(exc)
        return st.seal_predicate_reviews(
            unit, families, current_fingerprint=current_fingerprint
        )

    def _current_review_family(self, unit):
        """The family standing at the unit's review-cycle index, or None.

        Its one consumer is a bookkeeping field on the `delta_checkpoint`
        event, so a run with nobody to call leaves the field empty rather
        than stopping a step that has already restarted the cycle and has
        no other record of having done so.
        """
        try:
            families = self._review_families()
        except staffing.StaffingConditionError:
            return None
        return st.current_family(self.state, unit, families=families)

    def _advance_review_cycle(self, unit, last_result=None, deferred=False):
        """Move the cycle to the next assigned seat, or to pre-seal.

        Advancing reads the cycle to know its length and to name the seat
        the round that just finished ran on; it dispatches nothing, so a
        declared split this session cannot honour is described here and the
        clean round that just landed stands. `staffing_unavailable` stops
        the run with its token — but the move itself happens first, because
        it is bookkeeping over a round the ledger already holds. Nobody to
        call leaves no family to NAME, and nothing else: the cycle still
        has one entry per assigned seat, which the seat read answers on its
        own, and the `family_clean` label is left empty exactly as the
        checkpoint's current-family field is. Stopping before the move
        would leave the cycle standing on a seat whose clean round is
        already recorded, and nothing skips a seat already clean, so the
        repaired run would buy that round a second time.
        """
        stopping = None
        try:
            families = self._review_families()
        except staffing.StaffingConditionError as exc:
            families = [None] * len(self._review_seats())
            stopping = exc
        if deferred:
            st.advance_family_deferred(self.state, unit, families=families)
        else:
            st.advance_family_if_clean(
                self.state, unit, last_result, families=families
            )
        if stopping is not None:
            self._fail_staffing(stopping)

    def _settled_review_seat(self, unit, seat):
        """One coherent (round, resolution) for a `review` seat, read live.

        A `review` request carries the count of review rounds that seat's
        family already has in the current cycle, plus one — the count the
        round cap itself takes — so the round needs the family, while the
        family comes from a resolution the round is an input to. Ask,
        derive, and ask again until a resolution's family still wants the
        round it was asked at: then the answer, its round and the count the
        cap takes are one reading of the document. A stable document
        settles on the second ask, since `round` feeds `step_up` alone and
        cannot itself move the family. Only a document rewritten under
        consecutive asks spends the bound, and the last ask is then made at
        the round this returns, so what RUNS is always the document's
        answer FOR that round — a spent bound can leave the round itself
        one reading behind the family that answers, never the `step_up`
        rung behind the round beside it. Spending it takes three completed
        writes, one in each gap between the four asks: one write always
        settles by the third ask, and two leave the last two asks reading
        the same document. That residual costs at most the rung this one
        call runs on — the cap is taken at the dispatch on the family this
        returns, and no round is recorded from here — and no finite retry
        closes it, since one more ask only moves the gap the next write
        lands in. Only freezing the document for the dispatch would, which
        live uncached reads exclude. Resolving is also the split-family
        check for this dispatch: the router's own refusal stops the run
        with its own token.
        """
        round_number = 1
        for _ in range(_REVIEW_SEAT_SETTLE_READS):
            resolution = self._staffing_resolution("review", seat,
                                                   round_number)
            wanted = 1 + _review_rounds_done(unit, resolution.answer["agent"])
            if wanted == round_number:
                return round_number, resolution
            round_number = wanted
        return round_number, self._staffing_resolution(
            "review", seat, round_number)

    def _review_seat_staffing(self, unit, seat):
        """(family, model, effort) a review at *seat* is prepared under.

        What the prompt, the raw name and the round record start from; the
        dispatch settles the seat again and is what actually runs.
        """
        _round, resolution = self._settled_review_seat(unit, seat)
        answer = resolution.answer
        return answer["agent"], answer["model"], answer["effort"]

    def _enforce_review_round_cap(self, unit, family):
        """Stop the run when *family* has spent this cycle's review rounds.

        Taken twice for one round: once as the cycle prepares it, so a run
        with nothing left to spend stops before building a prompt, and once
        at each physical dispatch, which is where the family the cap must
        bind is finally known — a dispatch resolves live and may land on a
        different family than the preparing read named.
        """
        cap = self.config["max_rounds_per_family"]
        if _review_rounds_done(unit, family) < cap:
            return
        st.fail_run(
            self.state,
            "family %s reached max_rounds_per_family=%d on %s without a "
            "clean round" % (family, cap, st.unit_key(unit)),
            unit=unit,
        )
        self._save()
        raise StopStep("round cap")

    def _review_dispatch(self, unit, index, capped=False):
        """A review dispatch that re-derives its round when it resolves."""
        return _ReviewSeatDispatch(self, unit, index=index, capped=capped)

    def _delta_review_staffing(self, unit, fixer_family):
        """(seat, family, model, effort) for one delta review.

        A delta review is a review, so it chooses among the seats the
        document assigns to `review` and nowhere else: the lowest-index
        seat whose resolved family is the latest fixer's, and the lowest
        assigned seat when none is. Walking the seats resolves them, which
        is this dispatch's split-family check as well.
        """
        chosen = None
        for seat in self._review_seats():
            family, _model, _effort = self._staff("review", index=seat)
            if chosen is None:
                chosen = seat
            if fixer_family and family == fixer_family:
                chosen = seat
                break
        return (chosen,) + self._review_seat_staffing(unit, chosen)

    @staticmethod
    def _worker_role(unit, kind):
        """The (role, round) one worker call resolves under.

        Round is 1 for every role but `fix`, which carries the unit's
        active-episode fixer iteration count plus one — the counter the fix
        loop already keeps — so a `step_up` rule written for a stuck fixer
        can see how long it has been stuck. A fix on the SKELETON is the
        skeleton's own seat (`plan`), exactly as it is today.
        """
        if kind == contracts.KIND_DRAFT_SKELETON:
            return "plan", 1
        if kind == contracts.KIND_DRAFT_SLICE_NOTE:
            return "draft", 1
        if kind == contracts.KIND_IMPLEMENT:
            return "implement", 1
        if kind == contracts.KIND_FIX_FINDINGS:
            if unit["kind"] == st.UNIT_SKELETON:
                return "plan", 1
            return "fix", 1 + int(unit.get("fix_loop_rounds") or 0)
        return None, None

    def _worker_staffing(self, unit, kind):
        """(family, model, effort) for one worker call, from the router."""
        role, round_number = self._worker_role(unit, kind)
        return self._staff(
            role,
            round=round_number,
            material=self._worker_staffing_material(unit, kind),
            episode_unit=unit,
        )

    def _worker_staffing_material(self, unit, kind):
        """The admitted production material, or the value about to be admitted.

        Recovery reads the active task's immutable order.  Only a task with no
        admitted record yet consults the prospective slice plan.
        """
        if kind not in tasks.PRODUCER_TASK_KINDS:
            return None
        active = self._active_worker_task(unit, kind)
        if active is not None:
            return tasks.order_staffing_material(active["order"])
        return tasks.slice_material(self._slice_info(unit["slice_id"]))

    def _order_role(self, unit, kind):
        """The process step one admitted agent-call order records.

        The same seat the call will actually resolve under, written into
        the durable order so a reader can see which step bought it. A
        report-only round is a `review` however many rounds it has had:
        the order records the ROLE, and the seat and round the cycle is on
        stay the dispatch's own facts.
        """
        if kind in contracts.REPORT_KINDS:
            return "review"
        role, _round = self._worker_role(unit, kind)
        if role is None:
            raise st.IllegalTransition(
                "task kind %r has no staffing role" % (kind,)
            )
        return role

    def _acts_overlay(self):
        """Read the one current per-run override map beside state."""
        try:
            return read_current_acts_overlay(
                self.state_path,
                strict=self.model_profiles_home is not None,
            )
        except model_profiles.ModelProfileError as exc:
            self._fail_model_profile_resolution(str(exc))

    def _fail_model_profile_resolution(self, reason):
        """Fail through ordinary run recovery before any provider dispatch."""
        if self.state.get("failure") is None:
            st.fail_run(
                self.state,
                "model-profile resolution failed: %s" % reason,
                unit=st.current_unit(self.state),
                type_="orchestrator",
            )
            self._save()
        raise StopStep("model-profile resolution failed: %s" % reason)

    def _act_profile(self, act, origin_family=None, default_family=None,
                     include_explicit=False):
        """Resolve one act from CURRENT state, with whole-act precedence.

        Current override > current saved profile > existing config/structural
        rules. Nothing is cached, bound to a unit, or copied into history.
        """
        try:
            return resolve_current_act(
                self.state_path,
                self.config,
                self.model_profiles_home,
                act,
                origin_family=origin_family,
                default_family=default_family,
                include_explicit=include_explicit,
            )
        except model_profiles.ModelProfileError as exc:
            self._fail_model_profile_resolution(str(exc))

    def _dispatch_for_act(self, act, origin_family=None,
                          default_family=None, fixed_family=None,
                          skeleton=False):
        """Return a fresh resolver for every physical provider dispatch."""
        def resolve():
            if skeleton:
                family, model, effort = self._skeletoner_profile(
                    origin_family
                )
            else:
                family, model, effort = self._act_profile(
                    act,
                    origin_family=origin_family,
                    default_family=(fixed_family or default_family),
                )
            if fixed_family is not None:
                family = fixed_family
            default_model, default_effort = self._family_defaults(family)
            return (
                family,
                model or default_model,
                effort or default_effort,
            )

        return resolve

    def _structural_dispatch(self, family, model=None, effort=None):
        """Validate current profile state, then apply a non-profile act."""
        def resolve():
            if self.model_profiles_home is not None:
                try:
                    _read_current_profile_layers(
                        self.state_path, self.model_profiles_home
                    )
                except model_profiles.ModelProfileError as exc:
                    self._fail_model_profile_resolution(str(exc))
            default_model, default_effort = self._family_defaults(family)
            return (
                family,
                model or default_model,
                effort or default_effort,
            )

        return resolve

    def _dispatch_for_worker_kind(self, unit, kind, origin_family=None):
        if self.model_profiles_home is not None:
            role, round_number = self._worker_role(unit, kind)
            if role is None:
                return None
            return self._dispatch_for_role(
                role,
                round=round_number,
                material=self._worker_staffing_material(unit, kind),
                episode_unit=unit,
            )
        if kind == contracts.KIND_DRAFT_SKELETON:
            return self._dispatch_for_act(
                "skeletoner", origin_family=origin_family, skeleton=True
            )
        if kind == contracts.KIND_DRAFT_SLICE_NOTE:
            return self._dispatch_for_act("drafter")
        if kind == contracts.KIND_IMPLEMENT:
            return self._dispatch_for_act("implementer")
        if kind == contracts.KIND_FIX_FINDINGS:
            if unit["kind"] == st.UNIT_SKELETON:
                return self._dispatch_for_act(
                    "skeletoner", origin_family=origin_family, skeleton=True
                )
            return self._dispatch_for_act(
                "fixer",
                origin_family=origin_family,
                default_family="codex",
            )
        return None

    @staticmethod
    def _result_identity(call, family=None, model=None, effort=None):
        return (
            getattr(call, "resolved_family", None) or family,
            getattr(call, "resolved_model", None) or model,
            getattr(call, "resolved_effort", None) or effort,
        )

    def _skeletoner_profile(self, origin_family=None):
        """(family, model, effort) for the `skeletoner` act, with the
        skeleton's OWN defaults re-asserted.

        The skeleton's declared defaults live in
        DEFAULT_CONFIG["acts"]["skeletoner"] (claude / claude-fable-5 / max),
        but merge_config replaces a whole act entry on a partial override —
        so a panel that customizes only the model drops the agent and
        effort. Left to the generic fallback, a model-only override would
        silently resolve to the codex fix-family (breaking: the codex CLI
        cannot run a claude model) and to claude's family effort instead of
        the skeleton's max. Re-assert the skeleton's family and effort here.
        The model stays None so _call fills it from the RESOLVED family's
        defaults — correct whichever family wins, whereas the skeleton's
        default model belongs only to its default family.
        """
        defaults = DEFAULT_CONFIG["acts"]["skeletoner"]
        family, model, effort = self._act_profile(
            "skeletoner", origin_family,
            default_family=defaults.get("agent"),
        )
        return family, model, effort or defaults.get("effort")

    def _validate_billing(self):
        """Refuse a payment mode we cannot honour.

        An unrecognized mode leaves real money unknown, which correctly
        degrades every call of that family to unpriced -- but silently, and
        the panel then shows a permanently partial run with no explanation.
        Say it once, at startup, where it can be acted on.
        """
        configured = self.config.get("billing")
        if configured is None:
            return
        if not isinstance(configured, dict):
            raise ValueError(
                "config billing must be a mapping of family -> %s"
                % "|".join(pricing.BILLING_MODES)
            )
        for family, mode in configured.items():
            if mode not in pricing.BILLING_MODES:
                raise ValueError(
                    "config billing[%r] is %r; expected one of %s"
                    % (family, mode, "|".join(pricing.BILLING_MODES))
                )

    def _family_defaults(self, family):
        d = (self.config.get("model_defaults") or {}).get(family) or {}
        return d.get("model"), d.get("effort")

    def _brainstorming_profiles(self):
        """Resolve the two voices for non-profile-aware library callers."""
        family, model, effort = self._act_profile("implementer")
        default_model, default_effort = self._family_defaults(family)
        lead = {
            "agent": family,
            "model": model or default_model,
            "effort": effort or default_effort,
        }

        # In a milestone the counterpart ALWAYS argues from the other
        # family — an opponent drawn from the lead's own family is not an
        # opposition — and it inherits the lead's effort, because a second
        # voice argued at lower weight than the proposal is not a second
        # opinion either. A same-family pin is therefore not honored here
        # (only a single-family configuration can still fall back), and a
        # model pinned for that other family goes with it; effort survives.
        opposite = self._opposite(lead["agent"])
        pinned_family, model, effort = self._act_profile(
            "brainstorming_counterpart",
            origin_family=lead["agent"],
            default_family=opposite,
        )
        if pinned_family != opposite:
            model = None
        default_model, _default_effort = self._family_defaults(opposite)
        counterpart = {
            "agent": opposite,
            "model": model or default_model,
            "effort": effort or lead["effort"],
        }
        return lead, counterpart

    def _brainstorming_staffing(self, order=None):
        """The run's one staffing session, for a discussion it owns.

        A discussion the milestone starts is staffed by the same session
        every other call of this run is staffed by: the reference travels as
        inherited context, never as a copied document or a second staffing
        value, and each of the discussion's own calls resolves it afresh.

        A selection carrying no session is that same answer for a run that
        holds none — the A2 derivation faulted and left it unbound — and it
        is not a missing one: every call this run makes meanwhile resolves
        through the visible default-document fallback, so the discussion is
        staffed exactly as its owner is. Inheritance happens once, at
        creation: the record it writes is its own authority, and this run
        binding a session at a later resume does not reach back into a
        discussion already created.

        For a selected production order the same mapping also carries that
        order's admitted optional material. It is request context, not a
        copied staffing answer: every physical call still resolves the live
        session and document.

        `None` — no selection at all — only for a `Driver` built without a
        catalogue home, which has no document store to read and keeps
        today's configuration-act seats.
        """
        if self.model_profiles_home is None:
            return None
        selection = {"session": st.staffing_session(self.state)}
        if order is not None:
            # Production discussions inherit the task order's admitted
            # material, including an explicit absence.  Other discussions
            # have no slice-material source and keep the selection's old shape.
            selection["material"] = tasks.order_staffing_material(order)
        return selection

    def _modern_design_updates(self):
        # Compatibility must never restore retired redocumentation machinery.
        # Persisted runs with a missing or false historical flag use the same
        # lightweight rethink/design-update path as newly created runs.
        return True

    def _legacy_gap_enabled(self):
        return (
            interpreter.gap_semantics(self.state)
            and not self._modern_design_updates()
        )

    def _legacy_failure_gap_required(self, unit, kind):
        if (
            not self._legacy_gap_enabled()
            or kind not in contracts.RETHINK_CONTINUATION_KINDS
        ):
            return False
        return (
            kind != contracts.KIND_FIX_FINDINGS
            or self._fixer_gap_enabled(unit)
        )

    def _review_profile(self, family):
        """Effective model/effort for a fixed review family.

        Review leadership remains family-rotated: an accidental/manual
        `agent` field on the act cannot turn the Codex half into Claude or
        vice versa. Only model and effort are operator-tunable.
        """
        _ignored_family, model, effort = self._act_profile(
            "review_%s" % family,
            origin_family=family,
            default_family=family,
        )
        default_model, default_effort = self._family_defaults(family)
        return model or default_model, effort or default_effort

    def _delta_review_profile(self, fixer_family):
        """Use the fixer's family and that family's Review profile.

        Older frozen configs may still contain a `delta_review` act. It is
        deliberately ignored: the delta judge has no independent family or
        model dial, so it cannot drift away from the fixer it is checking.
        """
        family = fixer_family or self._fix_family()
        model, effort = self._review_profile(family)
        return family, model, effort

    def _resolve_act(self, act, origin_family):
        """Family-only view of _act_profile (legacy call sites/tests)."""
        fam, _m, _e = self._act_profile(
            act, origin_family,
            default_family="codex" if act == "fixer" else None,
        )
        return fam

    def _validate_contests(self, unit, output, kind):
        """Structural check: a finding's contests.rejection_id must exist in
        the milestone registry — adjudicated rejections OR tracked debt,
        the two ways a finding gets dispatched without a fix. A bad
        reference is a protocol violation and fails the run with the
        explanation."""
        known = st.registry_ids(self.state) | st.debt_ids(self.state)
        for f in output.get("findings", []):
            contests = f.get("contests")
            if contests and contests.get("rejection_id") not in known:
                st.fail_run(
                    self.state,
                    "%s finding %s contests unknown adjudication %r "
                    "(known: %s)"
                    % (kind, f.get("id"), contests.get("rejection_id"),
                       sorted(known) or "none"),
                    unit=unit,
                )
                raise StopStep("bad contests reference")

    def _validate_adjudication_refs(self, unit, output):
        known = st.registry_ids(self.state)
        for f in output.get("findings", []):
            if f.get("disposition") == "rejected_adjudicated":
                ref = f.get("adjudication_ref")
                if ref not in known:
                    st.fail_run(
                        self.state,
                        "fixer marked %s rejected_adjudicated with unknown "
                        "registry ref %r (known: %s)"
                        % (f.get("id"), ref, sorted(known) or "none"),
                        unit=unit,
                    )
                    raise StopStep("bad adjudication reference")

    def _validate_contested_dispositions(self, unit, output):
        """A queued finding carrying `contests` re-opened that adjudication
        with structurally validated new evidence; the fixer must weigh it
        on the merits — fix, or reject with a FRESH consultation (the
        prompt contract: a CONTESTS finding "re-opens that adjudication").
        Disposing it rejected_adjudicated — killing the new evidence by
        pointer, typically citing the very adjudication under contest — is
        a protocol violation, enforced structurally, not by prompt text."""
        contested = {
            f["id"]: (f.get("contests") or {}).get("rejection_id")
            for f in (unit.get("fix_queue") or [])
            if f.get("contests")
        }
        for f in output.get("findings", []):
            if (f.get("disposition") == "rejected_adjudicated"
                    and f.get("id") in contested):
                st.fail_run(
                    self.state,
                    "fixer disposed finding %s as rejected_adjudicated "
                    "(ref %r), but that finding CONTESTS adjudication %r "
                    "with new evidence: a contested adjudication is "
                    "re-opened and must be fixed or rejected with a fresh "
                    "consultation, never killed by pointer"
                    % (f.get("id"), f.get("adjudication_ref"),
                       contested[f.get("id")]),
                    unit=unit,
                )
                raise StopStep("contested finding killed by pointer")

    def _report_call(self, unit, family, prompt, kind, raw_name,
                     extensions=None, roots=None, validate_opts=None,
                     model=None, effort=None, dispatch_resolver=None,
                     task_id=None, output_directory=None,
                     project_context=None,
                     project_safeguards=None):
        """Run a report-only call.

        Report-only remains the CONTRACT — reviewers are told not to edit,
        and their envelopes carry no dispositions or file changes — but it
        is no longer re-verified by snapshotting the workspace around the
        call. Operator decision, on the evidence: across 6,326 recorded
        report-only rounds the check never once caught a reviewer editing
        code, while its false positives (artifact churn a reviewer's own
        build or test run wrote) repeatedly discarded good reviews."""
        task = None
        if task_id is None:
            task = self._admit_worker_task(
                unit,
                kind,
                prompt,
                family,
                model=model,
                effort=effort,
                dispatch_resolver=dispatch_resolver,
                output_directory=output_directory,
                project_context=project_context,
                project_safeguards=project_safeguards,
                validate_opts=validate_opts,
            )
            task_id = task["id"]
        else:
            task = tasks.task_record(self.state, task_id)
        validate_opts = self._worker_task_validate_opts(task, validate_opts)

        def dispatch(_request):
            return self._call(
                family,
                prompt,
                kind,
                raw_name,
                model=model,
                effort=effort,
                extensions=extensions,
                roots=roots,
                validate_opts=validate_opts,
                dispatch_resolver=dispatch_resolver,
                task_id=task_id,
            )

        output, result, raw_path = tasks.execute_worker(task, dispatch)
        return output, result, raw_path

    def _do_fix(self):
        unit = st.current_unit(self.state)
        source = unit.get("fix_source") or {}
        verification_repair = source.get("type") == "verification"
        verification_commands = (
            self._verification_commands(unit) if verification_repair else None
        )
        max_loops = self.config.get("max_fix_loops", 6)
        cap_agreement = (source.get("brainstorming_agreement") or {})
        mandatory_application_retry = bool(
            cap_agreement.get("application_retry_issued")
            and not cap_agreement.get("applied")
        )
        if (
            unit.get("fix_loop_rounds", 0) >= max_loops
            and not mandatory_application_retry
        ):
            st.fail_run(
                self.state,
                "fix episode on %s did not converge after %d fixer+delta "
                "loops (source: %s)"
                % (st.unit_key(unit), max_loops, source.get("type")),
                unit=unit,
            )
            self._save()
            raise StopStep("fix loop cap")
        active_task = self._active_worker_task(
            unit, contracts.KIND_FIX_FINDINGS
        )
        carrier = unit.get("brainstorming_resume") or {}
        has_validated_carrier = bool(carrier)
        if has_validated_carrier:
            family = (
                carrier.get("family")
                or source.get("family")
                or self.config["families_order"][0]
            )
            fix_model = carrier.get("model")
            fix_effort = carrier.get("effort")
            dispatch_resolver = None
            consultation_family = family
            consultation_cmd = None
        elif self.model_profiles_home is not None:
            family, fix_model, fix_effort = self._worker_staffing(
                unit, contracts.KIND_FIX_FINDINGS
            )
            dispatch_resolver = self._dispatch_for_worker_kind(
                unit, contracts.KIND_FIX_FINDINGS
            )
            # The prompt names the family the `consult` seat resolves to now;
            # the command line resolves it again when the fixer runs it. An
            # ALREADY ADMITTED fixer reuses its frozen prompt and builds no
            # consultation text below, so its call uses no `consult` answer
            # and none is asked for: a seat no call uses is never resolved,
            # and a `consult` role this machine cannot split therefore stops
            # a resumed fixer no more than an unsatisfiable `classify` stops
            # a failure the classifier never sees.
            consultation_family = consultation_cmd = None
            if active_task is None:
                consultation_family, _cm, _ce = self._staff("consult")
                consultation_cmd = self._consultation_command(
                    consultation_family, None
                )
        else:
            if unit["kind"] == st.UNIT_SKELETON:
                # Skeleton content uses the operator-selected `skeletoner`;
                # only its reviews use the review families.
                family, fix_model, fix_effort = self._skeletoner_profile(
                    source.get("family")
                )
            else:
                family, fix_model, fix_effort = self._act_profile(
                    "fixer", source.get("family"), default_family="codex"
                )
            dispatch_resolver = self._dispatch_for_worker_kind(
                unit,
                contracts.KIND_FIX_FINDINGS,
                origin_family=source.get("family"),
            )
            consultation_family = self._resolve_act("consultation", family)
            # Consultation uses the fixer's effort, or its family default.
            _fixer_model, fixer_family_effort = self._family_defaults(family)
            consultation_cmd = self._consultation_command(
                consultation_family,
                fix_effort or fixer_family_effort,
            )
        authority = None
        if not has_validated_carrier:
            authority = self._worker_episode_authority(
                unit, contracts.KIND_FIX_FINDINGS
            )
            project_context = authority["project_context"]
            extensions = authority["extensions"]
            roots = authority["roots"]
        else:
            project_context = extensions = roots = None
        # New runs amend design through need_rethink and the ordinary review
        # cycle. Keep the old one-note envelope only for an already-persisted
        # correction episode.
        design_context = (
            self._design_correction_context(unit)
            if (not self._modern_design_updates()
                or unit.get("design_correction"))
            else None
        )
        legacy_design_process = (
            not self._modern_design_updates()
            or bool(unit.get("under_repair"))
            or design_context is not None
        )
        if (
            design_context
            and design_context.get("mode") == "active"
            and design_context.get("brainstorming_authority") is not None
        ):
            correction_error = self._design_correction_integrity_error(
                design_context
            )
            if correction_error:
                return self._rollback_design_correction(
                    unit,
                    correction_error,
                    design_context,
                    abandon_active_task=True,
                )
            try:
                design_context = self._design_correction_review_context(
                    design_context
                )
            except Exception as exc:
                return self._rollback_design_correction(
                    unit,
                    "the retained Brainstorming authority could not be read: "
                    "%s" % exc,
                    design_context,
                    abandon_active_task=True,
                )
        killed_notice = bool(unit.get("killed_fix_notice"))
        if active_task is not None:
            prompt = active_task["order"]["request"]["request"]
            if authority is not None:
                prompt = self._worker_episode_prompt(prompt, authority)
        elif has_validated_carrier:
            prompt = ""
        else:
            editable_design_paths = self._editable_design_paths(unit)
            prompt = prompts.build_fix_findings(
            family,
            self.workspace,
            self._goal_for(unit),
            self._unit_desc(unit),
            unit.get("fix_queue") or [],
            self._registry(),
            consultation_family,
            consultation_cmd,
            unit_kind=unit["kind"],
            amendments=(authority or {}).get("amendments"),
            phantom_retry=bool(unit.get("phantom_retried")),
            killed_notice=killed_notice,
            project_context=project_context,
            debt=self._debt(unit),
            repair_artifact=(
                # The editability declaration follows the unit's repair
                # CYCLE (under_repair: reopen -> ... -> reseal), not the
                # queue's source type: a delta-loop fix round inside a
                # repair re-queues with source "delta_review", and keying
                # off the source dropped the line there — the fixer then
                # refused to edit its own under-repair artifact.
                unit.get("artifact")
                if (source.get("type") == "repair"
                    or unit.get("under_repair"))
                else None
            ),
            repair_wave_docs=self._wave_doc_paths(unit),
            # The fixer earns the gap exit under the same reform gate as the
            # builders — but SCOPED to its primary case: a NORMAL slice fixer
            # (a doc/impl being built) that meets a queued finding unfixable in
            # scope because the sealed set contradicts itself. Excluded, keeping
            # the existing `blocked`->operator path:
            #  - git OFF: the candidate cannot be parked/replayed safely
            #    (production is git on; this only affects pure-CLI/test runs).
            #  - an UNDER_REPAIR reporter (a wave's co-reopened note): it is
            #    already inside a repair episode; a nested remodel is out of
            #    scope, and its worktree is the repair wip, not a slice draft.
            #  - the SKELETON: it cannot remodel itself.
            gap_enabled=(
                self._fixer_gap_enabled(unit)
            ),
            legacy_design_process=legacy_design_process,
            design_correction=design_context,
            editable_design_paths=editable_design_paths,
            verification_repair=verification_repair,
            verification_commands=verification_commands,
            implementation_scope=self._implementation_scope(unit),
            producer_planning=(
                unit["kind"] != st.UNIT_SKELETON
                and self._skeleton_artifact() in editable_design_paths
            ),
            materials=self._planning_materials(),
            )
            application_handoff = self._brainstorming_application_handoff(
                unit
            )
            if application_handoff is not None:
                prompt = prompts.attach_brainstorming_application_order(
                    prompt, application_handoff
                )
        n_fix = 1 + len(
            [r for r in unit["rounds"] if r["kind"] == contracts.KIND_FIX_FINDINGS]
        )
        # Pre-call snapshot, exactly as the builder captures before its draft:
        # if the fixer GAPS (a queued finding is valid but unfixable in scope —
        # the sealed doc set contradicts itself), the gap FINISHES NOTHING and
        # the worktree-tree handle preserves the candidate, including earlier
        # pending fixes, while excluding scratch written by the gapping call.
        # The wave runs from the sealed base; the candidate is replayed later.
        pre_refs = pre_sym = pre_head = pre_tree = pre_worktree_tree = None
        pre_stash = None
        if gitops.enabled(self.config):
            try:
                pre_refs = gitops.snapshot_refs(self.workspace)
                pre_sym = gitops.head_symbolic_ref(self.workspace)
                pre_head = gitops.head_full_sha(self.workspace)
                pre_tree = gitops.snapshot_index_tree(self.workspace)
                # A persisted worker from an older driver may still return the
                # retired gap result even though current prompts never offer
                # it. Always retain the exact candidate so recovery cannot
                # discard fixes accumulated in earlier rounds.
                pre_worktree_tree = gitops.snapshot_worktree_tree(
                    self.workspace
                )
                pre_stash = gitops.snapshot_stash(self.workspace)
            except gitops.GitError:
                pre_refs = pre_sym = pre_head = pre_tree = None
                pre_worktree_tree = pre_stash = None
        raw_name = "%s-fix%d" % (st.unit_key(unit), n_fix)
        fix_workspace_before = self._snapshot()
        resumed = self._take_brainstorming_resume(
            unit, contracts.KIND_FIX_FINDINGS
        )
        if resumed is not None:
            output, result, raw_path = resumed
            family = result.origin_family or family
            fix_model = result.origin_model or fix_model
            fix_effort = result.origin_effort or fix_effort
            original_pre = result.origin_pre_snapshot or {}
            pre_refs = original_pre.get("refs")
            pre_sym = original_pre.get("sym")
            pre_head = original_pre.get("head")
            pre_tree = original_pre.get("tree")
            pre_worktree_tree = original_pre.get("worktree_tree")
            pre_stash = original_pre.get("stash")
        else:
            validate_opts = (
                {
                    **(
                        {"allow_design_correction": True}
                        if design_context
                        and design_context.get("mode") == "offer"
                        else {}
                    ),
                    **(
                        {"require_failure_gap": True}
                        if self._legacy_failure_gap_required(
                            unit, contracts.KIND_FIX_FINDINGS
                        )
                        else {}
                    ),
                    **(
                        {"verification_repair": True}
                        if verification_repair else {}
                    ),
                } or None
            )
            task = self._admit_worker_task(
                unit,
                contracts.KIND_FIX_FINDINGS,
                prompt,
                family,
                model=fix_model,
                effort=fix_effort,
                dispatch_resolver=dispatch_resolver,
                project_context=project_context,
                validate_opts=validate_opts,
            )
            self._activate_worker_episode_authority(authority)
            validate_opts = self._worker_task_validate_opts(
                task, validate_opts
            )
            def dispatch(_request):
                call_prompt = prompt
                if killed_notice:
                    call_prompt = prompts.attach_killed_call_notice(
                        call_prompt
                    )
                return self._call(
                    family,
                    call_prompt,
                    contracts.KIND_FIX_FINDINGS,
                    raw_name,
                    model=fix_model,
                    effort=fix_effort,
                    extensions=extensions,
                    roots=roots,
                    validate_opts=validate_opts,
                    start_session=True,
                    dispatch_resolver=dispatch_resolver,
                    task_id=task["id"],
                )

            output, result, raw_path = tasks.execute_worker(
                task,
                dispatch,
            )
            if killed_notice:
                unit.pop("killed_fix_notice", None)
            family, fix_model, fix_effort = self._result_identity(
                result, family, fix_model, fix_effort
            )
        # The sealed-artifact guard runs on EVERY outcome (gap or not, in
        # envelope or not) BEFORE any branch returns: a fixer that tampered with
        # a sealed doc and then gapped must still be caught and restored — the
        # gap must never be a side door around tamper detection.
        declaration = output.get("design_correction")
        active_correction = unit.get("design_correction") or {}
        editable_note = None
        if active_correction.get("phase") == "proposed":
            editable_note = active_correction.get("artifact")
        elif declaration is not None and design_context:
            editable_note = design_context.get("artifact")
        editable_documents = self._editable_design_paths(unit)
        if editable_note:
            editable_documents.append(editable_note)
        restored = self._enforce_sealed_artifacts(
            raw_name,
            editable_sealed=editable_documents,
        )
        post_guard_snapshot = self._snapshot()
        fix_workspace_delta = self._snapshot_diff(
            fix_workspace_before, post_guard_snapshot
        )
        pending_agreement = self._fixer_brainstorming_agreement(unit, result)
        if pending_agreement and not pending_agreement.get("applied"):
            baseline_fingerprint = pending_agreement.get(
                "baseline_fingerprint"
            )
            if baseline_fingerprint is None and resumed is not None:
                baseline_fingerprint = getattr(
                    result, "brainstorming_baseline_fingerprint", None
                )
            fix_workspace_changed = bool(
                self._candidate_fingerprint(post_guard_snapshot)
                != baseline_fingerprint
                if baseline_fingerprint is not None
                else (
                    fix_workspace_delta
                    if resumed is None
                    else getattr(
                        result, "brainstorming_workspace_changed", False
                    ) and not restored
                )
            )
        else:
            fix_workspace_changed = bool(fix_workspace_delta)
        if verification_repair and source.get("deferred_candidate_changed"):
            fix_workspace_changed = True
        folded_commits = None
        self._record_design_changes(unit, fix_workspace_delta)
        if output.get("status") == "need_rethink":
            pending_agreement = self._fixer_brainstorming_agreement(
                unit, result
            )
            pending_legacy_handoff = bool(
                unit.get("brainstorming_review_handoff")
            )
            if (
                pending_agreement and not pending_agreement.get("applied")
                or pending_legacy_handoff
            ):
                reason = (
                    "fixer tried to open another Brainstorming before "
                    "applying the accepted result"
                )
                self._record_worker_unaccepted(
                    unit,
                    contracts.KIND_FIX_FINDINGS,
                    family,
                    result,
                    reason,
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=reason
                )
                st.fail_run(
                    self.state,
                    reason,
                    unit=unit,
                    type_="worker_protocol",
                )
                self._save()
                raise StopStep(reason)
            if restored:
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result,
                    "rethink requester modified protected artifacts",
                )
                self._fail_worker_task_if_open(
                    unit,
                    output,
                    result=result,
                    reason="rethink requester modified protected artifacts",
                )
                st.fail_run(
                    self.state,
                    "fixer requested Brainstorming after modifying sealed "
                    "artifacts: %s" % ", ".join(restored),
                    unit=unit,
                    type_="worker_blocked",
                )
                self._save()
                raise StopStep("rethink requester modified sealed artifacts")
            return self._start_rethink(
                unit,
                contracts.KIND_FIX_FINDINGS,
                family,
                fix_model,
                fix_effort,
                output,
                result,
                raw_path,
                raw_name,
                pre_snapshot={
                    "refs": pre_refs,
                    "sym": pre_sym,
                    "head": pre_head,
                    "tree": pre_tree,
                    "worktree_tree": pre_worktree_tree,
                    "stash": pre_stash,
                },
            )
        if output.get("status") == "gap":
            pending_agreement = self._fixer_brainstorming_agreement(
                unit, result
            )
            if pending_agreement and not pending_agreement.get("applied"):
                reason = (
                    "fixer returned a gap before applying the accepted "
                    "Brainstorming result"
                )
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result, reason
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=reason
                )
                st.fail_run(
                    self.state, reason, unit=unit, type_="worker_blocked"
                )
                self._save()
                raise StopStep(reason)
            # The fixer met an insoluble-in-scope contradiction: a queued
            # finding is valid, but the only repair rewrites a sealed doc this
            # call may not touch. Rather than dead-end at `blocked` (operator),
            # it classifies the contradiction and the machine routes it exactly
            # like a builder gap — fits_remodel reopens the whole doc set as a
            # re-documentation wave (full dosage: re-document -> delta ->
            # reseal), needs_operator stops for the operator. The fix episode
            # finishes NOTHING; its sound findings are re-surfaced and re-fixed
            # after the design is made coherent.
            #
            # In-goal fixer gaps are retired in favor of need_rethink. A
            # persisted needs_operator gap remains recoverable so an old
            # in-flight call cannot lose a genuine operator decision.
            has_operator_gap = any(
                gap.get("classification")
                == contracts.CLASSIFY_NEEDS_OPERATOR
                for gap in output.get("gaps") or []
            )
            recoverable_retired_gap = (
                self._modern_design_updates() and gitops.enabled(self.config)
            )
            if (
                not self._fixer_gap_enabled(unit)
                and not has_operator_gap
                and not recoverable_retired_gap
            ):
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result,
                    "fixer gap outside supported envelope",
                )
                self._fail_worker_task_if_open(
                    unit,
                    output,
                    result=result,
                    reason="fixer gap was outside the supported envelope",
                )
                st.fail_run(
                    self.state,
                    "%s returned a contradiction gap outside the supported "
                    "envelope (needs a reform profile, git on, a normal slice, "
                    "not under repair) — resolve as an operator-reopened repair"
                    % contracts.KIND_FIX_FINDINGS,
                    unit=unit, type_="worker_blocked",
                )
                self._save()
                raise StopStep("fixer gap outside supported envelope")
            if active_correction.get("phase") == "proposed":
                baseline = active_correction.get("baseline") or {}
                self._rollback_design_correction(
                    unit, "fixer chose the normal gap exit",
                    active_correction,
                )
                pre_refs = baseline.get("refs")
                pre_sym = baseline.get("sym")
                pre_head = baseline.get("head")
                pre_tree = baseline.get("index_tree")
                pre_worktree_tree = baseline.get("tree")
                pre_stash = baseline.get("stash")
            return self._handle_gap(unit, output, result.duration_s,
                                    token_usage=getattr(result, "token_usage", None),
                                    token_usage_partial=getattr(
                                        result, "token_usage_partial", False
                                    ),
                                    cost=getattr(result, "cost", None),
                                    cost_partial=getattr(
                                        result, "cost_partial", False
                                    ),
                                    task_id=getattr(result, "task_id", None),
                                    result=result,
                                    pre_tree=pre_tree, pre_head=pre_head,
                                    pre_sym=pre_sym, pre_refs=pre_refs,
                                    pre_stash=pre_stash,
                                    pre_worktree_tree=pre_worktree_tree,
                                    from_fixer=True)
        if (
            gitops.enabled(self.config)
            and pre_refs is not None
            and pre_sym is not None
            and pre_head is not None
            and pre_tree is not None
        ):
            try:
                folded_commits = gitops.fold_worker_commits_to_delta(
                    self.workspace,
                    pre_refs,
                    pre_sym,
                    pre_head,
                    pre_tree,
                    pre_stash,
                )
            except gitops.GitError as exc:
                reason = "fixer left an unsupported git mutation: %s" % exc
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result, reason
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=reason
                )
                st.fail_run(
                    self.state, reason, unit=unit,
                    type_="worker_git_mutation",
                )
                self._save()
                raise StopStep(reason)
            if folded_commits:
                st.append_event(
                    self.state,
                    "fixer_commits_folded",
                    unit=st.unit_key(unit),
                    baseline_head=folded_commits["baseline_head"],
                    worker_head=folded_commits["worker_head"],
                    commit_count=folded_commits["commit_count"],
                )
        self._check_worker_blocked(
            unit, output, contracts.KIND_FIX_FINDINGS, family, result
        )
        brainstorming_no_implementation_finding_id = None
        if verification_repair:
            if output.get("findings") != []:
                reason = (
                    "verification repair must return an empty findings list; "
                    "its ok status certifies the live full suite"
                )
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result, reason
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=reason
                )
                st.fail_run(
                    self.state, reason, unit=unit, type_="worker_protocol"
                )
                self._save()
                raise StopStep(reason)
        else:
            try:
                contracts.validate_fix_coverage(
                    output, unit.get("fix_queue") or []
                )
                brainstorming_no_implementation_finding_id = (
                    self._validate_brainstorming_application_claim(
                        unit,
                        output,
                        result,
                        bool(fix_workspace_changed),
                    )
                )
            except contracts.ContractError as exc:
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result, exc
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=str(exc)
                )
                st.fail_run(self.state, str(exc), unit=unit)
                self._save()
                raise StopStep(str(exc))
            try:
                self._validate_adjudication_refs(unit, output)
                self._validate_contested_dispositions(unit, output)
            except StopStep as exc:
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result, exc
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=str(exc)
                )
                self._save()
                raise
        if active_correction.get("phase") == "proposed":
            correction_error = self._design_correction_integrity_error(
                active_correction
            )
            if restored:
                correction_error = (
                    "the provisional correction touched other sealed "
                    "artifacts: %s" % ", ".join(restored)
                )
            if correction_error:
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result,
                    correction_error,
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=correction_error
                )
                return self._rollback_design_correction(
                    unit, correction_error, active_correction
                )
        elif declaration is not None:
            candidate, correction_error = self._start_design_correction(
                unit,
                declaration,
                output.get("files_changed") or [],
                design_context,
                pre_refs,
                pre_sym,
                pre_head,
                pre_tree,
                pre_worktree_tree,
                pre_stash,
                brainstorming_handoff=getattr(
                    result, "brainstorming_handoff", None
                ),
            )
            if restored:
                correction_error = (
                    "the correction touched other sealed artifacts: %s"
                    % ", ".join(restored)
                )
            if correction_error:
                unit["design_correction_attempted"] = True
                self._record_worker_unaccepted(
                    unit, contracts.KIND_FIX_FINDINGS, family, result,
                    correction_error,
                )
                self._fail_worker_task_if_open(
                    unit, output, result=result, reason=correction_error
                )
                return self._rollback_design_correction(
                    unit, correction_error, candidate
                )
        suite_corrected = False
        if (
            isinstance(output.get("suite_command"), str)
            and output["suite_command"].strip()
        ):
            # A queued finding may expose a missing OR narrowed suite from a
            # verification failure or review round. Correcting that run
            # state is a real fix even with zero file edits. The command is
            # part of review evidence, so changed commands invalidate prior
            # approvals and execute at the next scheduled checkpoint.
            command = output["suite_command"].strip()
            effective_before = self._verification_commands(unit)
            suite_state_changed = st.set_discovered_suite(
                self.state, output["suite_command"], replace=True
            )
            suite_corrected = bool(
                unit.get("suite_verification_pending")
                or (
                    bool(self.config.get("verification") or [])
                    and effective_before != [command]
                )
                # With no explicit verification, changing stored state is
                # the correction.  A documentation unit intentionally has
                # no effective gate, so merely repeating the already stored
                # command must not earn state-fix credit.
                or (
                    not bool(self.config.get("verification") or [])
                    and suite_state_changed
                )
            )
            if suite_corrected:
                unit["suite_verification_pending"] = True
        design_amendment_finding_id = self._design_amendment_finding_id(
            result
        )
        self._adopt_brainstorming_no_implementation_resolution(
            unit,
            output,
            result,
            brainstorming_no_implementation_finding_id,
        )
        slices_changed = self._maybe_update_slices(unit, output)
        fixed_slice_candidates = [
            finding.get("id")
            for finding in output.get("findings") or []
            if finding.get("disposition") == "fixed"
            and finding.get("id")
        ] if slices_changed else []
        slices_changed_finding_ids = []
        if fixed_slice_candidates:
            agreement_for_round = self._fixer_brainstorming_agreement(
                unit, result
            )
            source_id = (
                (agreement_for_round.get("source_finding") or {}).get("id")
                if agreement_for_round else None
            )
            if brainstorming_no_implementation_finding_id == source_id:
                siblings = [
                    finding_id for finding_id in fixed_slice_candidates
                    if finding_id != source_id
                ]
                if len(siblings) == 1:
                    slices_changed_finding_ids = siblings
            elif source_id in fixed_slice_candidates:
                slices_changed_finding_ids = [source_id]
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_FIX_FINDINGS,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
            token_usage=getattr(result, "token_usage", None),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=getattr(result, "cost", None),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            task_id=getattr(result, "task_id", None),
            # `queued` preserves what the fixer was actually asked to triage
            # — including any contests links — in the immutable history;
            # state.adjudicated_rejections() derives overturned
            # adjudications (a contested finding conceded as 'fixed') from
            # it. model/effort record which experiment produced this fix.
            meta={
                "source_round_id": source.get("source_round_id"),
                "queued": copy.deepcopy(unit.get("fix_queue") or []),
                **(
                    {"model": fix_model, "effort": fix_effort}
                    if (fix_model or fix_effort)
                    else {}
                ),
                **({"suite_corrected": True} if suite_corrected else {}),
                **(
                    {
                        "brainstorming_no_implementation_finding_id":
                        brainstorming_no_implementation_finding_id,
                    }
                    if brainstorming_no_implementation_finding_id else {}
                ),
                **(
                    {
                        "design_amendment_finding_id":
                        design_amendment_finding_id,
                    }
                    if design_amendment_finding_id else {}
                ),
                **(
                    {
                        "slices_changed_finding_ids":
                        slices_changed_finding_ids,
                    }
                    if slices_changed_finding_ids else {}
                ),
            },
        )
        self._terminalize_worker_task(unit, output, result=result)
        if verification_repair:
            # The fixer owns the complete suite in this episode. Its `ok`
            # certifies the final workspace bytes; bind that assertion to the
            # exact candidate and commands so any later edit invalidates it.
            certified_fingerprint = self._verification_candidate_fingerprint()
            st.append_event(
                self.state,
                "verification",
                unit=st.unit_key(unit),
                stage="fixer",
                boundary="final",
                cadence=self._full_verification_cadence(unit),
                ok=True,
                commands=list(verification_commands or []),
                candidate_before=certified_fingerprint,
                candidate_after=certified_fingerprint,
                stable=True,
                vacuous=not bool(verification_commands),
                fixer_certified=True,
                raw_path=raw_path,
                output_tail="(fixer reported the configured full suite green)",
            )
            unit.pop("last_verification_output", None)
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            unit["verify_fix_attempts"]["pre_seal"] = 0
        self._mark_brainstorming_application_applied(
            unit,
            output,
            result=result,
            workspace_changed=fix_workspace_changed,
            state_changed=bool(
                suite_corrected
                or verification_repair
                or design_amendment_finding_id
                or slices_changed
            ),
        )
        unit["fix_loop_rounds"] = unit.get("fix_loop_rounds", 0) + 1
        agreement = (unit.get("fix_source") or {}).get(
            "brainstorming_agreement"
        )
        if agreement and not agreement.get("applied"):
            reason = (
                "fixer completed without applying the accepted "
                "Brainstorming result"
            )
            if not agreement.get("application_retry_issued"):
                agreement["application_retry_issued"] = True
                st.append_event(
                    self.state,
                    "brainstorming_application_retry",
                    unit=st.unit_key(unit),
                    session_id=agreement["handoff"].get("session_id"),
                    accepted_target_revision=agreement["handoff"].get(
                        "accepted_target_revision"
                    ),
                    reason=reason,
                )
                return reason + "; fixer retries before review"
            st.fail_run(
                self.state,
                reason + " after its mandatory retry",
                unit=unit,
                type_="phantom_fix",
            )
            self._save()
            raise StopStep(reason)
        if (
            agreement
            and agreement.get("applied")
            and self._restore_deferred_fix_episode(
                unit, candidate_changed=fix_workspace_changed
            )
        ):
            st.append_event(
                self.state,
                "brainstorming_deferred_fix_restored",
                unit=st.unit_key(unit),
                session_id=agreement["handoff"].get("session_id"),
                candidate_changed=bool(fix_workspace_changed),
            )
            return "Brainstorming result applied; deferred fixer restored"
        # A suite repair that did not touch the tests is taken at its word.
        # The old condition only skipped ahead when the fixer changed
        # NOTHING — the case where the shortcut is least needed — so every
        # real repair fell into a delta review whose findings forced more
        # edits, and those edits invalidated the certification the episode
        # had just earned, sending the unit back to re-verify. That is the
        # loop: certify green, get edited, re-verify, repeat.
        #
        # What actually decides whether the certification can be trusted is
        # whether the tests themselves were altered to obtain it, and only
        # the fixer knows that: a test can live in its own file, beside the
        # code, or inside it, differently in every language. So it declares,
        # and the declaration routes — reviewed when it says yes, accepted
        # when it says no.
        certified_without_touching_tests = (
            verification_repair
            and not bool(output.get("tests_modified"))
            and not folded_commits
        )
        if certified_without_touching_tests:
            if fix_workspace_changed:
                # Skip the REVIEW, never the commit discipline. Folding the
                # repair into the wip commit needs git; invalidating stale
                # approvals does not — the candidate changed either way, and
                # a git-disabled run inheriting a whole-artifact approval of
                # bytes that no longer exist is exactly the seal this guard
                # is here to prevent.
                if gitops.enabled(self.config):
                    try:
                        sha = gitops.amend(self.workspace)
                    except gitops.GitError as exc:
                        st.fail_run(
                            self.state,
                            "suite repair amend failed: %s" % exc,
                            unit=unit,
                        )
                        self._save()
                        raise StopStep(str(exc))
                    st.append_event(
                        self.state, "amended", unit=st.unit_key(unit), sha=sha
                    )
                st.restart_reviews_after_candidate_change(
                    self.state, unit, "suite repair changed bytes"
                )
            target = source.get("return_to") or st.U_PRE_SEAL_VERIFY
            if (
                target == st.U_PRE_SEAL_VERIFY
                and self._seal_reviews(
                    unit,
                    current_fingerprint=self._review_evidence_fingerprint(unit),
                ) is None
            ):
                target = st.U_PRE_REVIEW_VERIFY
            unit["fix_queue"] = []
            unit["fix_source"] = None
            unit.pop("phantom_retried", None)
            st.transition_unit(
                self.state,
                unit,
                target,
                reason=(
                    "full suite certified by fixer; tests untouched"
                    if fix_workspace_changed
                    else "full suite certified by fixer; no candidate delta"
                ),
            )
            return "full suite green; continuing without re-verification"
        if gitops.enabled(self.config):
            st.transition_unit(
                self.state, unit, st.U_DELTA_REVIEW, reason="fix applied"
            )
            return "fix call done (%d finding(s) triaged); delta review next" % len(
                output.get("findings", [])
            )
        # Without git there is no delta to review or amend: return directly.
        target = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        if fix_workspace_changed:
            st.restart_reviews_after_candidate_change(
                self.state, unit, "git-disabled fixer changed bytes"
            )
            target = st.U_PRE_REVIEW_VERIFY
        elif suite_corrected and target == st.U_ROUNDS:
            target = st.U_PRE_REVIEW_VERIFY
        elif (target == st.U_PRE_SEAL_VERIFY
              and self._seal_reviews(
                  unit,
                  current_fingerprint=self._review_evidence_fingerprint(unit),
              ) is None):
            target = st.U_PRE_REVIEW_VERIFY
        source.pop("brainstorming_agreement", None)
        st.transition_unit(self.state, unit, target, reason="fix applied (no git)")
        return "fix call done; continuing (git disabled)"

    def _phantom_edit_claims(self, unit):
        """Edit claims made by the unit's LAST fix call: any 'fixed'
        disposition, any prevention edit, or a non-empty files_changed
        (entries under .orchestrator/ are ignored — consultation
        transcripts are bookkeeping, excluded from diffs by design).
        Cross-checked against an empty worktree delta in _do_delta_review."""
        last_fix = None
        for r in reversed(unit["rounds"]):
            if r["kind"] == contracts.KIND_FIX_FINDINGS:
                last_fix = r
                break
        if last_fix is None:
            return []
        result = last_fix["result"]
        design_amendment_finding_id = last_fix.get(
            "design_amendment_finding_id"
        )
        brainstorming_no_implementation_finding_id = last_fix.get(
            "brainstorming_no_implementation_finding_id"
        )
        slices_changed_finding_ids = set(
            last_fix.get("slices_changed_finding_ids") or []
        )
        suite_corrected = bool(
            last_fix.get("suite_corrected")
            # Resume compatibility for a state saved by the earlier
            # suite-arming implementation between fix and delta review.
            or unit.pop("suite_armed_by_fix", None)
        )
        suite_finding_id = result.get("suite_command_finding_id")
        if suite_corrected and not suite_finding_id:
            # Old states predate the explicit binding.  Their arming fix was
            # safe only in the historical single-fixed-finding shape.
            fixed_ids = [
                finding.get("id") for finding in result.get("findings", [])
                if finding.get("disposition") == "fixed"
            ]
            if len(fixed_ids) == 1:
                suite_finding_id = fixed_ids[0]
        claims = []
        changed = []
        for p in result.get("files_changed") or []:
            norm = os.path.normpath(str(p))
            # Runtime-bookkeeping paths (either layout) are not real edits.
            if any(seg in (".orchestrator", ".run")
                   for seg in norm.split(os.sep)):
                continue
            changed.append(p)
        if changed:
            claims.append("files_changed=%s" % (changed,))
        for f in result.get("findings", []):
            if f.get("disposition") == "fixed":
                if not (
                    suite_corrected and f.get("id") == suite_finding_id
                    or design_amendment_finding_id
                    and f.get("id") == design_amendment_finding_id
                    or brainstorming_no_implementation_finding_id
                    and f.get("id")
                    == brainstorming_no_implementation_finding_id
                    or f.get("id") in slices_changed_finding_ids
                ):
                    # Only the explicitly bound finding earns state-fix
                    # credit; unrelated fixed claims still require real edits.
                    claims.append(
                        "finding %s disposed 'fixed'" % f.get("id")
                    )
            if f.get("prevention"):
                claims.append(
                    "finding %s claims a prevention edit in %s"
                    % (f.get("id"),
                       (f.get("prevention") or {}).get("documented_in"))
                )
        return claims

    def _do_delta_review(self):
        unit = st.current_unit(self.state)
        correction = unit.get("design_correction") or {}
        provisional = (
            correction if correction.get("phase") == "proposed" else None
        )
        review_correction = provisional
        if provisional:
            correction_error = self._design_correction_integrity_error(
                provisional
            )
            if correction_error:
                return self._rollback_design_correction(
                    unit,
                    correction_error,
                    provisional,
                    abandon_active_task=True,
                )
            try:
                review_correction = self._design_correction_review_context(
                    provisional
                )
            except Exception as exc:
                return self._rollback_design_correction(
                    unit,
                    "the retained Brainstorming authority could not be read: "
                    "%s" % exc,
                    provisional,
                    abandon_active_task=True,
                )
        source = unit.get("fix_source") or {}
        # The delta convergence checkpoint (delta_full_review_after_fixes)
        # escalates a review finding's fix loop to a full re-review after N
        # fixes. It is keyed off the episode's origin, not return_to, because
        # a pending suite re-verification may rewrite the latter.
        origin_type = st.active_fix_origin_type(self.state, unit)
        checkpoint_source = origin_type == "round"
        return_to = source.get("return_to") or st.U_PRE_REVIEW_VERIFY
        suite_verification_pending = bool(
            unit.get("suite_verification_pending")
            or unit.get("suite_armed_by_fix")
        )
        if suite_verification_pending and return_to == st.U_ROUNDS:
            return_to = st.U_PRE_REVIEW_VERIFY
        try:
            delta = gitops.worktree_diff(self.workspace)
        except gitops.GitError as exc:
            st.fail_run(self.state, "git diff failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        if not delta.strip():
            empty_delta_reason = (
                "the proposed correction left no delta to ratify"
                if provisional
                else "delta review was abandoned because no pending delta remained"
            )
            active_task = self._active_worker_task(
                unit, contracts.KIND_DELTA_REVIEW
            )
            if active_task is not None:
                self._fail_worker_task_if_open(
                    unit,
                    None,
                    task_id=active_task["id"],
                    reason=empty_delta_reason,
                )
            if provisional:
                return self._rollback_design_correction(
                    unit,
                    empty_delta_reason,
                    provisional,
                )
            # An all-rejections episode leaves no delta: nothing to amend.
            # But the fixer's claims must agree with that: a 'fixed'
            # disposition, a non-empty files_changed, or a prevention edit
            # with an EMPTY worktree delta means the fixer reported work it
            # never did — a phantom fix would close the finding unfixed,
            # and a phantom prevention pointer would enter the adjudication
            # registry and suppress re-detection in every later review
            # prompt ("Settled findings stay settled" is a structural rule,
            # so the prevention edit must structurally exist).
            claims = self._phantom_edit_claims(unit)
            if claims:
                if not unit.get("phantom_retried"):
                    # First offense: the phantom round stays on the record
                    # (invalid evidence) but does not kill the run —
                    # re-run the fixer once with the same queue, exactly
                    # like the JSON repair retry. A second phantom is a
                    # typed failure whose resume restores to FIXING.
                    unit["phantom_retried"] = True
                    st.append_event(
                        self.state,
                        "phantom_fix_retry",
                        unit=st.unit_key(unit),
                        claims="; ".join(claims)[:300],
                    )
                    st.transition_unit(
                        self.state, unit, st.U_FIXING,
                        reason="phantom fix (claims with empty delta); "
                               "retrying fixer",
                    )
                    self._save()
                    return "phantom fix discarded; retrying fixer once"
                st.fail_run(
                    self.state,
                    "fixer on %s claimed edits but the worktree delta is "
                    "empty (nothing was actually changed), twice in a row: "
                    "%s" % (st.unit_key(unit), "; ".join(claims)),
                    unit=unit,
                    type_="phantom_fix",
                )
                self._save()
                raise StopStep("fixer claimed edits with an empty delta")
            unit.pop("phantom_retried", None)
            unit["fix_queue"] = []
            unit["fix_source"] = None
            if (return_to == st.U_PRE_SEAL_VERIFY
                    and self._seal_reviews(
                        unit,
                        current_fingerprint=(
                            self._review_evidence_fingerprint(unit)
                        ),
                    ) is None):
                return_to = st.U_PRE_REVIEW_VERIFY
            st.transition_unit(
                self.state, unit, return_to, reason="no delta (fix episode green)"
            )
            return "no pending delta; episode closed"
        try:
            checkpoint_after = int(self.config.get(
                "delta_full_review_after_fixes",
                DEFAULT_CONFIG["delta_full_review_after_fixes"],
            ))
        except (TypeError, ValueError):
            checkpoint_after = DEFAULT_CONFIG[
                "delta_full_review_after_fixes"
            ]
        checkpoint_after = max(0, checkpoint_after)
        dirty_deltas = st.active_fix_dirty_deltas(self.state, unit)
        # One fix is currently pending plus one already-applied fix for every
        # accepted dirty delta in this episode.  Deriving this from immutable
        # history makes Stop/Start and Resume unable to restart the budget;
        # phantom attempts do not count because they produced no dirty delta.
        fix_number = 1 + dirty_deltas
        if (not provisional
                and checkpoint_source
                and checkpoint_after
                and fix_number >= checkpoint_after):
            # The fifth fix has already incorporated the previous delta's
            # known findings.  At this point another diff-only review would
            # inspect a large cumulative patch with less context than a full
            # re-review.  Checkpoint the WIP and follow the exact clean-delta
            # return edge. The accepted candidate changed, so every prior
            # whole-artifact approval is stale and review restarts at family
            # zero after verification.
            try:
                sha = gitops.amend(self.workspace)
            except gitops.GitError as exc:
                st.fail_run(
                    self.state, "delta checkpoint amend failed: %s" % exc,
                    unit=unit,
                )
                self._save()
                raise StopStep(str(exc))
            st.append_event(
                self.state, "amended", unit=st.unit_key(unit), sha=sha
            )
            st.restart_reviews_after_candidate_change(
                self.state, unit, "delta checkpoint changed bytes"
            )
            return_to = st.U_PRE_REVIEW_VERIFY
            st.append_event(
                self.state,
                "delta_checkpoint",
                unit=st.unit_key(unit),
                sha=sha,
                fixes=fix_number,
                dirty_deltas=dirty_deltas,
                return_to=return_to,
                review_family=self._current_review_family(unit),
            )
            unit["fix_queue"] = []
            unit["fix_source"] = None
            unit.pop("phantom_retried", None)
            st.transition_unit(
                self.state,
                unit,
                return_to,
                reason="delta checkpoint after %d fixes; full review resumes"
                % fix_number,
            )
            return (
                "delta checkpoint after %d fixes; amended (%s); continuing"
                % (fix_number, sha)
            )
        fixer_family = None
        for r in reversed(unit["rounds"]):
            if r["kind"] == contracts.KIND_FIX_FINDINGS:
                fixer_family = r["family"]
                break
        delta_seat = None
        if self.model_profiles_home is not None:
            (
                delta_seat,
                family,
                delta_model,
                delta_effort,
            ) = self._delta_review_staffing(unit, fixer_family)
        else:
            family, delta_model, delta_effort = self._delta_review_profile(
                fixer_family
            )
        active_task = self._active_worker_task(
            unit, contracts.KIND_DELTA_REVIEW
        )
        authority = self._worker_episode_authority(
            unit, contracts.KIND_DELTA_REVIEW
        )
        project_context = authority["project_context"]
        extensions = authority["extensions"]
        roots = authority["roots"]
        producer_review_context = self._producer_review_context(unit)
        if active_task is None:
            prompt = prompts.build_delta_review(
                family,
                self.workspace,
                self._goal_for(unit),
                self._unit_desc(unit),
                self._registry(),
                unit_kind=unit["kind"],
                governing=self._governing(unit),
                amendments=authority["amendments"],
                project_context=project_context,
                debt=self._debt(unit),
                wave_docs=self._wave_doc_paths(unit),
                gap_enabled=self._legacy_gap_enabled(),
                design_correction=review_correction,
                editable_design_paths=self._design_review_paths(unit),
                implementation_scope=self._implementation_scope(unit),
                producer_review_context=producer_review_context,
            )
        else:
            prompt = self._worker_episode_prompt(
                active_task["order"]["request"]["request"], authority
            )
        n_delta = 1 + len(
            [r for r in unit["rounds"] if r["kind"] == contracts.KIND_DELTA_REVIEW]
        )
        self._activate_worker_episode_authority(authority)
        output, result, raw_path = self._report_call(
            unit,
            family,
            prompt,
            contracts.KIND_DELTA_REVIEW,
            "%s-delta%d" % (st.unit_key(unit), n_delta),
            extensions=extensions,
            roots=roots,
            # Reform runs hard-require plain/example on every finding;
            # the delta prompt itself is NOT battery-aware (diff-scoped).
            validate_opts={
                **(
                    {"require_plain": True}
                    if interpreter.reform_active(self.state) else {}
                ),
                **(
                    {"require_design_correction_verdict": True}
                    if provisional else {}
                ),
            } or None,
            model=delta_model,
            effort=delta_effort,
            dispatch_resolver=(
                self._review_dispatch(unit, delta_seat)
                if delta_seat is not None
                else self._dispatch_for_act(
                    "review_%s" % family,
                    origin_family=family,
                    fixed_family=family,
                )
            ),
            task_id=(active_task or {}).get("id"),
            project_context=project_context,
        )
        family, delta_model, delta_effort = self._result_identity(
            result, family, delta_model, delta_effort
        )
        if output.get("status") == "need_rethink":
            return self._start_rethink(
                unit,
                contracts.KIND_DELTA_REVIEW,
                family,
                delta_model,
                delta_effort,
                output,
                result,
                raw_path,
                "%s-delta%d" % (st.unit_key(unit), n_delta),
            )
        self._check_worker_blocked(
            unit, output, contracts.KIND_DELTA_REVIEW, family, result
        )
        try:
            self._validate_contests(
                unit, output, contracts.KIND_DELTA_REVIEW
            )
        except StopStep as exc:
            self._record_worker_unaccepted(
                unit, contracts.KIND_DELTA_REVIEW, family, result, exc
            )
            self._fail_worker_task_if_open(
                unit, output, result=result, reason=str(exc)
            )
            self._save()
            raise
        st.record_round(
            self.state,
            unit,
            family,
            contracts.KIND_DELTA_REVIEW,
            output,
            raw_path=raw_path,
            duration=result.duration_s,
            token_usage=getattr(result, "token_usage", None),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=getattr(result, "cost", None),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            meta={"model": delta_model, "effort": delta_effort},
            task_id=getattr(result, "task_id", None),
        )
        self._terminalize_worker_task(unit, output, result=result)
        if provisional:
            verdict = output["design_correction_verdict"]
            decision = verdict["decision"]
            if decision == "ratify":
                correction_error = self._design_correction_integrity_error(
                    provisional
                )
                if correction_error:
                    return self._rollback_design_correction(
                        unit, correction_error, provisional
                    )
                return self._ratify_design_correction(
                    unit, provisional, verdict, return_to
                )
            if decision in ("remodel", "needs_operator"):
                baseline = provisional.get("baseline") or {}
                gap = self._design_correction_gap(
                    provisional, decision, verdict.get("reason")
                )
                self._rollback_design_correction(
                    unit, verdict.get("reason"), provisional
                )
                if decision == "needs_operator":
                    return self._route_goal_gap(unit, gap)
                if self._modern_design_updates():
                    st.append_event(
                        self.state,
                        "legacy_remodel_retried_as_rethink",
                        unit=st.unit_key(unit),
                        reason=str(verdict.get("reason") or "")[:300],
                    )
                    return (
                        "retired remodel verdict cleared; the same fixer "
                        "retries with the rethink contract"
                    )
                return self._handle_gap(
                    unit,
                    {"gaps": [gap]},
                    result.duration_s,
                    token_usage=getattr(result, "token_usage", None),
                    token_usage_partial=getattr(
                        result, "token_usage_partial", False
                    ),
                    cost=getattr(result, "cost", None),
                    cost_partial=getattr(result, "cost_partial", False),
                    pre_tree=baseline.get("index_tree"),
                    pre_head=baseline.get("head"),
                    pre_sym=baseline.get("sym"),
                    pre_refs=baseline.get("refs"),
                    pre_stash=baseline.get("stash"),
                    pre_worktree_tree=baseline.get("tree"),
                    from_fixer=True,
                )
            # retry intentionally falls through to the existing dirty-delta
            # path below; the contract requires actionable findings.
        if contracts.findings_clean(output):
            try:
                sha = gitops.amend(self.workspace)
            except gitops.GitError as exc:
                st.fail_run(self.state, "amend failed: %s" % exc, unit=unit)
                self._save()
                raise StopStep(str(exc))
            st.append_event(
                self.state, "amended", unit=st.unit_key(unit), sha=sha
            )
            st.restart_reviews_after_candidate_change(
                self.state, unit, "accepted delta changed bytes"
            )
            return_to = st.U_PRE_REVIEW_VERIFY
            unit["fix_queue"] = []
            unit["fix_source"] = None
            st.transition_unit(
                self.state, unit, return_to, reason="delta green; amended"
            )
            unit.pop("phantom_retried", None)
            return "delta review clean; amended (%s)" % sha
        # Dirty delta: its findings become the new fix queue (same episode).
        unit["fix_queue"] = [
            {
                "id": f["id"],
                "severity": f["severity"],
                "summary": f["summary"],
                "validity": copy.deepcopy(f["validity"]),
                "contests": f.get("contests"),
            }
            for f in output["findings"]
        ]
        st.reopen_contested_debt(self.state, unit["fix_queue"])
        source["type"] = "delta"
        source["family"] = family
        source["source_round_id"] = st.family_rounds(unit, family)[-1]["id"]
        unit["fix_source"] = source
        st.transition_unit(
            self.state, unit, st.U_FIXING, reason="delta findings queued"
        )
        return "delta review: %d finding(s); back to the fixer" % len(
            output["findings"]
        )

    def _complete_seal_from_reviews(self, unit, verification_event=None):
        """Seal deterministically from current whole-artifact reviews."""
        current_fingerprint = self._review_evidence_fingerprint(unit)
        cite = self._seal_reviews(
            unit, current_fingerprint=current_fingerprint
        )
        if cite is None:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "seal boundary did not match cited review bytes",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="seal evidence stale; ordinary reviews restarted",
            )
            return "%s review cycle restarted before seal" % st.unit_key(unit)
        if unit["status"] == st.U_PRE_SEAL_VERIFY:
            st.transition_unit(
                self.state, unit, st.U_SEALING,
                reason=(
                    "verification passed; review predicate satisfied"
                    if verification_event is not None
                    else "review predicate satisfied; full verification "
                    "not due"
                ),
            )
        st.record_seal_attempt(
            self.state,
            unit,
            {},
            True,
            reviews=list(cite),
            verification_event_seq=(
                verification_event.get("seq")
                if verification_event is not None else None
            ),
        )
        seal_event = {"unit": st.unit_key(unit), "reviews": list(cite)}
        if verification_event is not None:
            seal_event["verification_event_seq"] = verification_event["seq"]
        st.append_event(self.state, "seal_satisfied", **seal_event)
        st.transition_unit(
            self.state,
            unit,
            st.U_SEALED,
            reason="all reviewers effectively clean on current bytes",
        )
        self._after_seal(unit)
        return "%s sealed from reviews %s" % (
            st.unit_key(unit), ", ".join(cite)
        )

    def _do_verify(self):
        unit = st.current_unit(self.state)
        stage = unit["status"]

        if stage == st.U_PRE_REVIEW_VERIFY:
            # Compatibility waypoint retained for existing states and the
            # many fix/review back-edges. Full suites are scheduled checks,
            # not a tax between review cycles: reviews use focused checks.
            unit.pop("skip_next_verify", None)
            st.append_event(
                self.state,
                "verification_deferred",
                unit=st.unit_key(unit),
                stage=stage,
                boundary="scheduled",
                reason="full suite never runs between review cycles",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_ROUNDS,
                reason="full verification deferred to scheduled checkpoint",
            )
            return "full verification deferred; review cycle opened"
        if stage != st.U_PRE_SEAL_VERIFY:
            raise st.IllegalTransition(
                "verification cannot run from status %s" % stage
            )

        # Compatibility with states persisted by the retired generic
        # gate-reuse shortcut. Only a fixer that explicitly owned the full
        # suite may now certify this boundary without another execution.
        unit.pop("skip_next_verify", None)

        if stage == st.U_PRE_SEAL_VERIFY:
            current_fingerprint = self._review_evidence_fingerprint(unit)
            if self._seal_reviews(
                unit, current_fingerprint=current_fingerprint
            ) is None:
                st.restart_reviews_after_candidate_change(
                    self.state,
                    unit,
                    "pre-seal evidence missing or bound to different bytes",
                )
                st.transition_unit(
                    self.state,
                    unit,
                    st.U_PRE_REVIEW_VERIFY,
                    reason="pre-seal evidence stale; reviews restarted",
                )
                return "pre-seal evidence stale; review cycle restarted"

        cadence = self._full_verification_cadence(unit)
        if cadence is None:
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            st.append_event(
                self.state,
                "verification_deferred",
                unit=st.unit_key(unit),
                stage=stage,
                boundary="slice_checkpoint",
                reason=(
                    "documentation does not run the full suite"
                    if unit["kind"] != st.UNIT_SLICE_IMPL
                    else "full suite runs every four completed logical "
                    "slices and at milestone close"
                ),
            )
            closed = self._complete_seal_from_reviews(unit)
            return "full verification not due; %s" % closed

        commands = self._verification_commands(unit)
        verification_before = self._snapshot()
        candidate_before = self._verification_candidate_fingerprint(
            verification_before
        )
        reusable = self._matching_fixer_verification(
            commands, candidate_before
        )
        if reusable is not None:
            event = st.append_event(
                self.state,
                "verification",
                unit=st.unit_key(unit),
                stage=stage,
                boundary="final",
                cadence=cadence,
                ok=True,
                commands=list(commands),
                candidate_before=candidate_before,
                candidate_after=candidate_before,
                stable=True,
                reused=True,
                reused_from_seq=reusable["seq"],
                fixer_certified=True,
                output_tail=(
                    "(reused: fixer certified these exact bytes and "
                    "commands at event %d)" % reusable["seq"]
                ),
            )
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            unit["verify_fix_attempts"]["pre_seal"] = 0
            closed = self._complete_seal_from_reviews(
                unit, verification_event=event
            )
            return "fixer suite result reused; %s" % closed

        verification_changed = []
        boundary = "final"
        self._mark_busy(
            "verification (%s)" % boundary, "verification", None
        )
        verification_started = time.monotonic()
        try:
            ok, output = run_verification(
                commands,
                self.workspace,
                self.config.get("verification_timeout"),
            )
        finally:
            verification_duration_s = max(
                0.0, time.monotonic() - verification_started
            )
            self._clear_busy()
        verification_after = self._snapshot()
        verification_changed = self._snapshot_diff(
            verification_before, verification_after
        )
        candidate_after = self._verification_candidate_fingerprint(
            verification_after
        )
        verification_event = st.append_event(
            self.state,
            "verification",
            unit=st.unit_key(unit),
            stage=stage,
            boundary=boundary,
            cadence=cadence,
            ok=ok,
            commands=list(commands),
            candidate_before=candidate_before,
            candidate_after=candidate_after,
            stable=not bool(verification_changed),
            vacuous=(not commands) or None,
            duration_s=verification_duration_s,
            output_tail=(output or "")[-2000:],
        )

        if verification_changed:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "verification changed candidate bytes: %s"
                % runners.format_changes(verification_changed),
            )
        if ok:
            # A mechanical pass closes any pending suite-repair episode.
            unit.pop("suite_verification_pending", None)
            unit.pop("suite_armed_by_fix", None)
            unit["verify_fix_attempts"]["pre_seal"] = 0
            if verification_changed and stage == st.U_PRE_SEAL_VERIFY:
                st.transition_unit(
                    self.state,
                    unit,
                    st.U_PRE_REVIEW_VERIFY,
                    reason=("verification changed candidate bytes; "
                            "review approvals invalidated"),
                )
                return (
                    "verification ok but changed candidate bytes; "
                    "review cycle restarted"
                )
            sealed = self._complete_seal_from_reviews(
                unit, verification_event=verification_event
            )
            return "verification ok (%d command(s)); %s" % (
                len(commands), sealed
            )
        unit["verify_fix_attempts"]["pre_seal"] += 1
        unit.pop("last_verification_output", None)
        # Keep a unique source signal solely for durable episode identity and
        # the optional rethink handoff. The fixer receives no parsed failure
        # or output tail; it diagnoses the live suite itself.
        seq = unit.setdefault(
            "verify_episode_seq", {"pre_review": 0, "pre_seal": 0}
        )
        seq.setdefault("pre_seal", 0)
        seq["pre_seal"] += 1
        n_episode = seq["pre_seal"]
        st.enter_fix_episode(
            self.state,
            unit,
            [
                {
                    "id": "V1",
                    "severity": "P1",
                    "summary": "the configured full verification suite is "
                    "not green",
                    "validity": {
                        "permitted_baseline": (
                            "the configured verification suite passes"
                        ),
                        "actual_outcome": (
                            "the configured verification suite failed"
                        ),
                        "incremental_harm": (
                            "the candidate cannot demonstrate its required "
                            "verification gate"
                        ),
                        "exceeds_baseline": True,
                    },
                }
            ],
            "verification",
            None,
            "%s-verify-pre_seal-%d" % (st.unit_key(unit), n_episode),
            (st.U_PRE_REVIEW_VERIFY
             if verification_changed else stage),
        )
        return "verification failed; full-suite repair queued"

    def _preserve_reclassify_parent(self, parent_call, reason):
        """Keep a completed review visible when child admission stops."""
        if parent_call is not None:
            unit = st.current_unit(self.state)
            self._record_worker_unaccepted(
                unit,
                parent_call[0],
                parent_call[1],
                parent_call[2],
                reason,
            )
            self._save()
        self._clear_busy()

    def _partition_defer_candidates(
        self,
        unit,
        items,
        source_round=None,
        parent_call=None,
        defer_threshold=None,
        gap_backstop=None,
    ):
        """Rate candidates independently and split debt from fix work.

        `items` is a list of (finding, raising_family). Returns
        (debt_entries, retained_items). A refused/failed rating retains only
        that finding for the fixer; one serious finding can never drag other,
        independently deferred findings into the fix queue.
        """
        debt = []
        retained = []
        levels = contracts.DRIFT_RISK_LEVELS
        threshold = str(
            defer_threshold
            if defer_threshold is not None
            else self.config.get("p3_defer_max_risk") or "low"
        )
        if threshold not in levels:
            threshold = "low"
        try:
            for finding, raising_family in items:
                rater_dispatch = None
                try:
                    if self.model_profiles_home is not None:
                        # The one machine fact the dispatch has, and the one
                        # the retired derivation read: a run that SUPPLIES a
                        # single family has no second family to rate with,
                        # whatever its document assigns. It decides the gate
                        # BEFORE the router is asked, because a withheld
                        # rating makes no call — and a call nobody makes must
                        # not be stopped by a surfaced condition.
                        explicit = (
                            self._opposite(raising_family) != raising_family
                        )
                        if explicit:
                            # The rater is the `classify` seat the run's
                            # document assigns — the EXPLICIT rater today's
                            # rule already admits as a second look, whichever
                            # family it names.
                            rater_dispatch = self._dispatch_for_role(
                                "classify"
                            )
                            opp, rater_model, rater_effort = self._staff(
                                "classify"
                            )
                        else:
                            # The single family the run supplies is the only
                            # one collapse could ever answer with, so the
                            # gate below closes on it without a resolution.
                            opp = raising_family
                            rater_model = rater_effort = None
                    else:
                        opp, rater_model, rater_effort, explicit = (
                            self._act_profile(
                                "reclassifier", origin_family=raising_family,
                                default_family=self._opposite(raising_family),
                                include_explicit=True,
                            )
                        )
                except StopStep:
                    self._preserve_reclassify_parent(
                        parent_call,
                        "review completed but current model-profile state "
                        "blocked nested reclassification",
                    )
                    raise
                defer_ok, reason = False, "reclassification unavailable"
                risk = None
                damage = None
                duration_s = None
                logical_duration_s = None
                token_usage = None
                token_usage_partial = False
                call_cost = None
                call_cost_partial = False
                effective_model = None
                effective_effort = None
                if opp == raising_family and not explicit:
                    # No independent opposite family (single-family config):
                    # cross-family verification is impossible, so the finding
                    # is never deferred — it takes the normal fix path. An
                    # EXPLICIT fixed/self policy is the operator choosing a
                    # same-family rater on purpose — allowed (a fresh
                    # stateless call is still a second look).
                    reason = "no independent reclassifier (single family)"
                else:
                    # Finding ids are arbitrary reviewer strings; sanitize
                    # the raw-filename component so an id with a path
                    # separator cannot make _save_raw raise.
                    safe_id = "".join(
                        c if (c.isalnum() or c in "_.-") else "_"
                        for c in str(finding.get("id", ""))
                    )[:64] or "f"
                    pc, _rx, _rr = self._project_prompt_inputs(
                        unit, contracts.KIND_RECLASSIFY
                    )
                    # Reform runs: the rater judges for the run's REAL
                    # builders and knows their stop-report-repair exit —
                    # the reform's bargain (tolerate more in docs BECAUSE
                    # the builder can come back), encoded in the judge.
                    # Legacy/profile-less prompts stay byte-identical.
                    builder_desc = None
                    effective_gap_backstop = (
                        bool(gap_backstop)
                        if gap_backstop is not None
                        else interpreter.gap_semantics(self.state)
                    )
                    if effective_gap_backstop:
                        builder_desc = self._builders_desc()
                    prompt = prompts.build_reclassify(
                        opp, self.workspace, finding, self._artifact(unit),
                        unit_kind=unit["kind"],
                        amendments=self._amendments(unit=unit),
                        project_context=pc,
                        builder_desc=builder_desc,
                        gap_backstop=effective_gap_backstop,
                        two_axis=effective_gap_backstop,
                        raising_family=(
                            raising_family
                            if self.model_profiles_home is not None else None
                        ),
                    )
                    raw_name = "%s-reclassify-%s-%s" % (
                        st.unit_key(unit), raising_family, safe_id)
                    try:
                        def resolve_profile_rater():
                            current_opp, current_model, current_effort, current_explicit = (
                                self._act_profile(
                                    "reclassifier",
                                    origin_family=raising_family,
                                    default_family=self._opposite(
                                        raising_family
                                    ),
                                    include_explicit=True,
                                )
                            )
                            if current_opp == raising_family and not current_explicit:
                                raise _NoIndependentReclassifier(
                                    "no independent reclassifier"
                                )
                            current_dm, current_de = self._family_defaults(
                                current_opp
                            )
                            return (
                                current_opp,
                                current_model or current_dm,
                                current_effort or current_de,
                            )

                        # Homed, the router is the whole resolution: the kept
                        # single-family gate reads the run's own families,
                        # which no live edit can change mid-episode, so there
                        # is nothing left for a dispatch to re-derive.
                        resolve_rater = (
                            rater_dispatch if rater_dispatch is not None
                            else resolve_profile_rater
                        )
                        dm, de = self._family_defaults(opp)
                        effective_model = rater_model or dm
                        effective_effort = rater_effort or de
                        if not self._mark_busy(
                            raw_name,
                            contracts.KIND_RECLASSIFY,
                            opp,
                            model=effective_model,
                            effort=effective_effort,
                            nested=True,
                            staffing_fallback=getattr(
                                rater_dispatch, "staffing_fallback", None
                            ),
                        ):
                            if parent_call is not None:
                                self._record_worker_unaccepted(
                                    unit,
                                    parent_call[0],
                                    parent_call[1],
                                    parent_call[2],
                                    "review could not complete its nested "
                                    "reclassification",
                                )
                            st.fail_run(
                                self.state,
                                "reclassify call could not create its "
                                "accounting marker",
                                unit=unit,
                                type_="orchestrator",
                            )
                            self._save()
                            raise StopStep(
                                "worker accounting marker unavailable"
                            )
                        try:
                            output, result = runners.call_worker(
                                self.runner, opp, prompt,
                                contracts.KIND_RECLASSIFY,
                                self.workspace,
                                model=effective_model,
                                effort=effective_effort,
                                validate_opts=(
                                    {"require_drift_damage": True}
                                    if effective_gap_backstop else None
                                ),
                                resolve_dispatch=resolve_rater,
                                on_dispatch=lambda f, m, e, prompt_fallback: (
                                    self._retarget_busy(
                                        raw_name,
                                        contracts.KIND_RECLASSIFY,
                                        f,
                                        m,
                                        e,
                                        staffing_fallback=getattr(
                                            rater_dispatch,
                                            "staffing_fallback",
                                            None,
                                        ),
                                        prompt_set_fallback=prompt_fallback,
                                    )
                                ),
                            )
                        except StopStep:
                            self._preserve_reclassify_parent(
                                parent_call,
                                "review completed but current model-profile "
                                "state blocked nested reclassification",
                            )
                            raise
                        opp, effective_model, effective_effort = (
                            self._result_identity(
                                result, opp, effective_model, effective_effort
                            )
                        )
                        self._require_busy_accounting(
                            contracts.KIND_RECLASSIFY,
                            opp,
                            raw_name,
                            result,
                            parent_call=parent_call,
                        )
                        self._save_raw(raw_name, result.text)
                        duration_s = result.duration_s
                        token_usage = getattr(result, "token_usage", None)
                        token_usage_partial = bool(
                            getattr(result, "token_usage_partial", False)
                            or token_usage is None
                        )
                        call_cost = getattr(result, "cost", None)
                        call_cost_partial = bool(
                            getattr(result, "cost_partial", False)
                            or call_cost is None
                        )
                        logical_duration_s = self._call_accounting(result)[0]
                        self._record_repair(
                            raw_name, contracts.KIND_RECLASSIFY, opp, result
                        )
                        if output.get("status") == "ok":
                            # The worker only RATES; the deterministic
                            # decision is this comparison against the
                            # run's threshold. Reform runs rate TWO axes
                            # and the decision gates on DAMAGE (operator,
                            # 2026-07-09: probability and damage decide
                            # differently — a self-revealing cheap defect
                            # defers even at high probability; a
                            # destructive one is fixed however unlikely).
                            # Legacy keeps the single-axis risk gate.
                            risk = output.get("drift_risk")
                            damage = output.get("drift_damage")
                            reason = str(output.get("reason") or "")[:300]
                            gate = damage if effective_gap_backstop else risk
                            defer_ok = (
                                gate in levels
                                and levels.index(gate)
                                <= levels.index(threshold)
                            )
                        else:
                            reason = "reclassifier blocked"
                    except _NoIndependentReclassifier:
                        self._clear_busy()
                        reason = (
                            "no independent reclassifier (single family)"
                        )
                    except (runners.RunnerError,
                            runners.WorkerProtocolError) as exc:
                        opp, effective_model, effective_effort = (
                            self._result_identity(
                                exc, opp, effective_model, effective_effort
                            )
                        )
                        self._require_busy_accounting(
                            contracts.KIND_RECLASSIFY,
                            opp,
                            raw_name,
                            exc,
                            parent_call=parent_call,
                        )
                        self._record_fatal_malformed(
                            raw_name, contracts.KIND_RECLASSIFY, opp, exc,
                            self._save_protocol_raws(raw_name, exc),
                        )
                        reason = ("reclassify call failed: %s" % exc)[:300]
                st.append_event(
                    self.state, "reclassify_recorded",
                    unit=st.unit_key(unit),
                    source_round=source_round,
                    finding_id="%s-%s" % (raising_family, finding.get("id")),
                    reclassifier=opp, drift_risk=risk,
                    drift_damage=damage, threshold=threshold,
                    defer_ok=defer_ok, reason=reason,
                    model=effective_model,
                    effort=effective_effort,
                    duration_s=duration_s,
                    logical_duration_s=logical_duration_s,
                    token_usage=copy.deepcopy(token_usage),
                    token_usage_partial=token_usage_partial,
                    cost=copy.deepcopy(call_cost),
                    cost_partial=bool(call_cost_partial),
                )
                if defer_ok:
                    debt.append({
                        "id": "%s-%s" % (raising_family, finding["id"]),
                        "severity": finding.get("severity", "P3"),
                        "summary": finding.get("summary", ""),
                        "raised_by": raising_family,
                        "cleared_by": opp,
                        "drift_risk": risk,
                        "drift_damage": damage,
                        "reason": reason,
                    })
                else:
                    retained.append((finding, raising_family))
        finally:
            pass
        return debt, retained

    def _do_review_round(self):
        unit = st.current_unit(self.state)
        review_inputs = self._review_evidence_inputs(unit)
        (
            evidence_fingerprint,
            project_context,
            extensions,
            roots,
            amendments,
        ) = review_inputs[:5]
        operator_complete = (
            bool(review_inputs[5]) if len(review_inputs) > 5 else False
        )
        active_review = self._active_worker_task(
            unit, contracts.KIND_REVIEW_ROUND
        )
        bound_fingerprint = unit.get("review_evidence_fingerprint")
        if (
            bound_fingerprint is None
            and int(unit.get("family_index") or 0) > 0
        ):
            # Supported pre-field schema-2 state can carry review progress
            # without the evidence binding later families need.  Preserve its
            # history, but restart before dispatch so no family is skipped and
            # no unbound round can contribute to sealing.
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "advanced review progress lacked an evidence fingerprint",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="unbound review progress restarted at family zero",
            )
            return "unbound review progress; cycle restarted"
        if bound_fingerprint is None:
            unit["review_evidence_fingerprint"] = evidence_fingerprint
        elif bound_fingerprint != evidence_fingerprint:
            if active_review is not None:
                self._fail_worker_task_if_open(
                    unit,
                    None,
                    task_id=active_review["id"],
                    reason=(
                        "review evidence changed before the review "
                        "invocation completed"
                    ),
                )
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "candidate bytes or frozen execution plan changed between "
                "reviewer calls",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason=("review evidence changed; prior approvals "
                        "invalidated"),
            )
            return "review evidence changed; cycle restarted"
        authority = {
            "amendments": amendments,
            "operator_complete": operator_complete,
            "project_context": project_context,
            "extensions": extensions,
            "roots": roots,
        }
        seat = None
        if self.model_profiles_home is not None:
            seats = self._review_seats()
            index = int(unit.get("family_index") or 0)
            if index >= len(seats):
                # Seats are read live, so the list can SHRINK below the seat
                # this cycle already stands on — an edited document, a
                # session repointed at a smaller one, or the default
                # document answering for an unreadable one. That is not a
                # stopping condition: with no seat left at this index the
                # cycle is exhausted, exactly as it is when the last seat
                # comes back clean, and the ordinary pre-seal path decides
                # between sealing on the currently assigned seats and
                # restarting the cycle because one of them is not clean.
                if active_review is not None:
                    # A review admitted for the seat that just vanished can
                    # never be delivered: `review_round` is not continuable,
                    # and neither continuation dispatches its frozen request
                    # — sealing ends the cycle, and a restart re-opens it at
                    # seat 1. That is an abandonment, so it records the
                    # invocation's failure like every other one. Leaving the
                    # task open would carry an active-task reference onto a
                    # sealed unit, where the supported repair reopen could
                    # admit no successor of its own kind.
                    self._fail_worker_task_if_open(
                        unit,
                        None,
                        task_id=active_review["id"],
                        reason=(
                            "the assigned review seats shrank below the "
                            "seat this review was admitted for"
                        ),
                    )
                st.transition_unit(
                    self.state,
                    unit,
                    st.U_PRE_SEAL_VERIFY,
                    reason=(
                        "review cycle exhausted: the document assigns %d "
                        "review seat(s) and the cycle stands at seat %d"
                        % (len(seats), index + 1)
                    ),
                )
                return (
                    "%s review cycle exhausted at seat %d of %d; pre-seal "
                    "decides" % (st.unit_key(unit), index + 1, len(seats))
                )
            seat = seats[index]
            family, review_model, review_effort = (
                self._review_seat_staffing(unit, seat)
            )
        else:
            family = st.current_family(self.state, unit)
            if family is None:
                raise st.IllegalTransition("rounds status with no family left")
        self._enforce_review_round_cap(unit, family)
        # Reform runs: reviewers of doc units check the question battery
        # (presence and substance, never prose — spec §4) and every
        # finding hard-requires its plain/example lay mirror.
        reform = interpreter.reform_active(self.state)
        if seat is None:
            review_model, review_effort = self._review_profile(family)
        producer_review_context = self._producer_review_context(unit)
        prompt = prompts.build_review_round(
            family,
            self.workspace,
            self._goal_for(unit),
            self._unit_desc(unit),
            self._artifact(unit),
            self._registry(),
            unit_kind=unit["kind"],
            governing=self._governing(unit),
            amendments=amendments,
            project_context=project_context,
            battery=interpreter.battery_questions(self.state, unit["kind"]),
            debt=self._debt(unit),
            gap_enabled=self._legacy_gap_enabled(),
            wave_docs=self._wave_doc_paths(unit),
            editable_design_paths=self._design_review_paths(unit),
            implementation_scope=self._implementation_scope(unit),
            producer_review_context=producer_review_context,
            verification_commands=self._review_verification_commands(unit),
        )
        if active_review is not None:
            prompt = self._worker_episode_prompt(
                active_review["order"]["request"]["request"], authority
            )
        # Raw/label numbering counts ALL history (like fix/delta and the
        # ledger round ids): the amnesty-relative `done` must never make a
        # new raw file reuse — and overwrite — a historical round's name.
        label_no = 1 + len(
            [
                r
                for r in st.family_rounds(unit, family)
                if r["kind"] == contracts.KIND_REVIEW_ROUND
            ]
        )
        self._activate_worker_episode_authority(authority)
        output, result, raw_path = self._report_call(
            unit,
            family,
            prompt,
            contracts.KIND_REVIEW_ROUND,
            "%s-%s-r%d" % (st.unit_key(unit), family, label_no),
            extensions=extensions,
            roots=roots,
            validate_opts={"require_plain": True} if reform else None,
            model=review_model,
            effort=review_effort,
            dispatch_resolver=(
                self._review_dispatch(unit, seat, capped=True)
                if seat is not None
                else self._dispatch_for_act(
                    "review_%s" % family,
                    origin_family=family,
                    fixed_family=family,
                )
            ),
            task_id=(active_review or {}).get("id"),
            project_context=project_context,
        )
        family, review_model, review_effort = self._result_identity(
            result, family, review_model, review_effort
        )
        if output.get("status") == "need_rethink":
            return self._start_rethink(
                unit,
                contracts.KIND_REVIEW_ROUND,
                family,
                review_model,
                review_effort,
                output,
                result,
                raw_path,
                "%s-%s-r%d" % (st.unit_key(unit), family, label_no),
            )
        self._check_worker_blocked(
            unit, output, contracts.KIND_REVIEW_ROUND, family, result
        )
        try:
            self._validate_contests(
                unit, output, contracts.KIND_REVIEW_ROUND
            )
        except StopStep as exc:
            self._record_worker_unaccepted(
                unit, contracts.KIND_REVIEW_ROUND, family, result, exc
            )
            self._fail_worker_task_if_open(
                unit, output, result=result, reason=str(exc)
            )
            self._save()
            raise
        findings = output.get("findings", [])
        review_task = tasks.task_record(
            self.state, getattr(result, "task_id", None)
        )
        result_policy = self._worker_task_result_policy(review_task, unit)
        # Debt deferral: the task's admitted profile/phase chooses the
        # deferrable severity scope. The DOC phase rates P3
        # (legacy) or P2/P3 (reform); the IMPL phase rates P3 only (a code
        # P2 always fixes). P0/P1 always fix. Candidates are rated
        # independently: one serious finding must not drag cheap, accepted
        # debt into the fix queue with it.
        defer_scope = tuple(result_policy["defer_scope"])
        deferred = []
        fix_findings = list(findings)
        if (findings
                and result_policy["p3_reclassify_debt"]
                and defer_scope):
            candidates = [
                (f, family) for f in findings
                if f.get("severity") in defer_scope
                # A contest is evidence-backed escalation of something
                # already dispatched once; re-deferring it would loop the
                # same issue through debt forever. Contests always fix.
                and not f.get("contests")
            ]
            if candidates:
                source_round = "%s-%s-r%d" % (
                    st.unit_key(unit), family,
                    len(st.family_rounds(unit, family)) + 1,
                )
                deferred, retained = self._partition_defer_candidates(
                    unit,
                    candidates,
                    source_round=source_round,
                    parent_call=(
                        contracts.KIND_REVIEW_ROUND, family, result
                    ),
                    defer_threshold=result_policy["p3_defer_max_risk"],
                    gap_backstop=result_policy["gap_backstop"],
                )
                retained_ids = {f.get("id") for f, _family in retained}
                fix_findings = [
                    f for f in findings
                    if (f.get("severity") not in defer_scope
                        or f.get("id") in retained_ids)
                ]
        round_meta = {
            "model": review_model,
            "effort": review_effort,
            "evidence_fingerprint": evidence_fingerprint,
        }
        if deferred and not fix_findings:
            round_meta["deferred_clean"] = True
        rec = st.record_round(
            self.state, unit, family, contracts.KIND_REVIEW_ROUND, output,
            raw_path=raw_path, duration=result.duration_s,
            token_usage=getattr(result, "token_usage", None),
            token_usage_partial=bool(
                getattr(result, "token_usage_partial", False)
                or getattr(result, "token_usage", None) is None
            ),
            cost=getattr(result, "cost", None),
            cost_partial=bool(
                getattr(result, "cost_partial", False)
                or getattr(result, "cost", None) is None
            ),
            meta=round_meta,
            task_id=getattr(result, "task_id", None),
        )
        self._terminalize_worker_task(unit, output, result=result)
        if deferred:
            st.record_debt(self.state, unit, deferred, "round", rec["id"])
        if not findings:
            self._advance_review_cycle(unit, last_result=output)
            return "%s round: clean" % family
        if not fix_findings:
            self._advance_review_cycle(unit, deferred=True)
            return ("%s round: %d finding(s) deferred as debt (verified by %s)"
                    % (family, len(deferred), self._opposite(family)))
        st.enter_fix_episode(
            self.state,
            unit,
            [
                {
                    "id": f["id"],
                    "severity": f["severity"],
                    "summary": f["summary"],
                    "validity": copy.deepcopy(f["validity"]),
                    "contests": f.get("contests"),
                }
                for f in fix_findings
            ],
            "round",
            family,
            rec["id"],
            st.U_ROUNDS,
        )
        return ("%s round: %d finding(s) queued for the fixer; %d deferred"
                % (family, len(fix_findings), len(deferred)))

    def _do_seal_attempt(self):
        """Close a recovered sealing state without launching seal reviewers."""
        unit = st.current_unit(self.state)
        current_fingerprint = self._review_evidence_fingerprint(unit)
        cite = self._seal_reviews(
            unit, current_fingerprint=current_fingerprint
        )
        if cite is None:
            st.restart_reviews_after_candidate_change(
                self.state,
                unit,
                "persisted sealing state lacked current review evidence",
            )
            st.transition_unit(
                self.state,
                unit,
                st.U_PRE_REVIEW_VERIFY,
                reason="seal recovery restarted ordinary reviews",
            )
            return "seal recovery: review cycle restarted"
        return self._complete_seal_from_reviews(unit)

    def _wave_doc_paths(self, unit):
        """Artifact paths of the slice notes co-reopened with `unit` by an
        active re-documentation wave — None unless `unit` is the wave's
        anchor. Feeds the fixer, delta reviewer, and full reviewers the same
        whole-set declaration."""
        wave = self.state.get("redoc_wave")
        if not wave or wave.get("anchor") != st.unit_key(unit):
            return None
        by_key = {st.unit_key(u): u for u in self.state["units"]}
        paths = []
        for key in wave.get("docs") or []:
            u = by_key.get(key)
            if u is not None and u.get("artifact"):
                paths.append(u["artifact"])
        return paths

    def _retire_reviewed_redoc_wave(self, anchor):
        """Close a historical reviewed wave without synthetic approvals."""
        wave = self.state.get("redoc_wave") or {}
        if wave.get("anchor") != st.unit_key(anchor):
            return []
        by_key = {
            st.unit_key(candidate): candidate
            for candidate in self.state.get("units") or []
        }
        docs = [
            by_key[key] for key in wave.get("docs") or []
            if key in by_key
        ]
        for doc in docs:
            if doc.get("status") == st.U_REPAIRING:
                st.transition_unit(
                    self.state,
                    doc,
                    st.U_SEALED,
                    reason="historical redocumentation retired after review",
                )
            doc.pop("under_repair", None)
        if gitops.enabled(self.config):
            self.state["retired_redoc_docs_pending_gate"] = {
                "anchor": st.unit_key(anchor),
                "docs": [st.unit_key(doc) for doc in docs],
            }
        self.state["redoc_wave"] = None
        st.append_event(
            self.state,
            "redoc_wave_retired_after_review",
            unit=st.unit_key(anchor),
            reporter=wave.get("reporter"),
            docs=[st.unit_key(doc) for doc in docs],
            authority="historical_review_evidence",
        )
        return docs

    def _after_seal(self, unit):
        if unit["kind"] == st.UNIT_SLICE_IMPL:
            st.close_slice(self.state, unit)
        # A driver upgraded while a historical wave was still alive may reach
        # this boundary without restarting. Retire it using the reviews that
        # just completed; never synthesize approvals for the co-opened notes.
        is_anchor = bool(
            (self.state.get("redoc_wave") or {}).get("anchor")
            == st.unit_key(unit)
        )
        if is_anchor:
            self._retire_reviewed_redoc_wave(unit)
        self._gate_commit(unit)
        # The gate first attributes every changed design document to this
        # commit; only then may the temporary design authority be retired.
        unit.pop("design_update", None)
        if is_anchor:
            self._guard_unplanned_preserved_candidates()
        # Only materialize a continuation whose predecessors have sealed.
        # Re-sealing an earlier documentation anchor must not pre-open a
        # later implementation part while its predecessor is still active.
        nxt = st.ensure_due_unit(self.state)
        if nxt is None and st.maybe_close_milestone(self.state):
            self._final_commit()

    def _gate_message(self, unit):
        if unit["kind"] == st.UNIT_SKELETON:
            return "Complete review of milestone skeleton"
        if unit["kind"] == st.UNIT_SLICE_DOC:
            return "Complete review of slice %02d note" % unit["slice_id"]
        return "Complete review of slice %s implementation" % st.slice_token(
            unit
        )

    def _consume_pending_closure(self):
        """Finish a reviewed unit's missing Git gate before opening another.

        The explicit marker is written before Git is touched.  This avoids
        guessing from old/synthetic sealed units that legitimately have no
        gate metadata, while ensuring a failed gate is retried before the
        next implementation part can be materialized.
        """
        if not gitops.enabled(self.config):
            return False
        pending = self.state.get("pending_gate_unit")
        if not pending:
            return False
        unit = self._unit_by_key(pending)
        if unit is None or unit.get("status") != st.U_SEALED:
            st.fail_run(
                self.state,
                "cannot recover the pending gate for %s" % pending,
                unit=unit,
                type_="gate_recovery",
            )
            self._save()
            raise StopStep("pending gate unit is unavailable")
        self._gate_commit(unit)
        unit.pop("design_update", None)
        return True

    def _gate_commit(self, unit):
        """The canon's commit-the-sealed-unit rule, executed by code: the
        generated ledgers are folded in and the unit's amended wip commit
        is finalized under the canonical gate message."""
        if not gitops.enabled(self.config):
            return
        self.state["pending_gate_unit"] = st.unit_key(unit)
        self._save()
        try:
            ledgers.generate(self.state, self.workspace)
            sha = gitops.finalize_gate(self.workspace, self._gate_message(unit))
        except (gitops.GitError, ledgers.LedgerError, OSError) as exc:
            # A hostile/malformed index file must become a RECORDED run
            # failure — an unhandled crash here would discard the sealed
            # transition still in memory and livelock re-burning seals.
            st.fail_run(self.state, "gate commit failed: %s" % exc, unit=unit)
            self._save()
            raise StopStep(str(exc))
        unit["gate_commit"] = sha
        self.state.pop("pending_gate_unit", None)
        design_paths = set(self._design_review_paths(unit))
        if design_paths:
            for candidate in self.state.get("units") or []:
                if candidate.get("artifact") in design_paths:
                    candidate["gate_commit"] = sha
        correction = unit.get("design_correction") or {}
        if correction.get("phase") == "ratified":
            note = self._unit_by_key(correction.get("note_unit"))
            if note is not None:
                note["gate_commit"] = sha
        retired = self.state.get("retired_redoc_docs_pending_gate") or {}
        if retired.get("anchor") == st.unit_key(unit):
            for key in retired.get("docs") or []:
                note = self._unit_by_key(key)
                if note is not None:
                    note["gate_commit"] = sha
            self.state.pop("retired_redoc_docs_pending_gate", None)
        st.append_event(
            self.state,
            "gate_commit",
            unit=st.unit_key(unit),
            sha=sha,
            message=self._gate_message(unit),
        )

    def _final_commit(self):
        if not gitops.enabled(self.config):
            self.state.pop("pending_final_commit", None)
            return
        # Persist intent before touching Git. A crash or commit failure can
        # then resume this idempotent close instead of leaving a closed
        # milestone whose final ledger commit was never attempted again.
        self.state["pending_final_commit"] = True
        self._save()
        try:
            ledgers.generate(self.state, self.workspace)
            sha = gitops.commit_plain(self.workspace, "Close milestone")
        except (gitops.GitError, ledgers.LedgerError, OSError) as exc:
            st.fail_run(self.state, "close commit failed: %s" % exc)
            self._save()
            raise StopStep(str(exc))
        if sha:
            st.append_event(self.state, "gate_commit", unit=None, sha=sha,
                            message="Close milestone")
        self.state.pop("pending_final_commit", None)


class StopStep(RuntimeError):
    """Raised by executors after fail_run() has recorded the explanation."""


def run_verification(commands, workspace, timeout):
    """Run every verification command; returns (all_ok, combined_output).

    Commands may be worker-discovered strings (suite_command), so they run
    with the same stop semantics as workers: own session, tracked so the
    driver's SIGTERM handler SIGKILLs the whole group (a TERM-trapping or
    hung suite must not survive the Stop button), stdin closed and CI=1
    set so watch-mode/interactive runners run once and exit. Execution
    assumes the operator already trusts workers with full permissions;
    sandboxed-worker configs must set explicit config verification
    instead of relying on discovery."""
    if not commands:
        return True, "(no verification configured)"
    env = dict(os.environ)
    env.setdefault("CI", "1")
    chunks = []
    for cmd in commands:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            start_new_session=True,
        )
        runners._track_worker(proc)
        try:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                runners._kill_group(proc)
                proc.communicate()
                chunks.append("$ %s\nTIMEOUT after %ss" % (cmd, timeout))
                return False, "\n".join(chunks)
        finally:
            runners._untrack_worker(proc)
        chunks.append(
            "$ %s\nexit=%d\n%s%s" % (cmd, proc.returncode, out, err)
        )
        if proc.returncode != 0:
            return False, "\n".join(chunks)
    return True, "\n".join(chunks)


# ---------------------------------------------------------------------------
# CLI


def default_state_path(workspace, docs_dir=None):
    """Where a run's state (and its sibling runtime: raw/, amendments.json,
    acts.json, current.json) lives.

    New milestones (a per-milestone docs_dir like
    implementation/milestones/<slug>) keep their runtime INSIDE the
    milestone directory, in a gitignored `.run/` subdir — so each milestone
    is self-contained and a new run never collides with a closed one.
    Legacy flat-`docs` runs keep the historical workspace-root
    `.orchestrator/` location. Runtime is always the state file's own
    directory, so both layouts work with the same driver code."""
    if docs_dir and os.path.normpath(docs_dir) not in ("", ".", "docs"):
        return os.path.join(workspace, docs_dir, ".run", "state.json")
    return os.path.join(workspace, ".orchestrator", "state.json")


# Init-specific project refusal causes. Causes raised out of Slice 2's
# validation/read seams reuse the workareas vocabulary verbatim
# (invalid_project, invalid_name, unknown_work_area, malformed_work_area);
# an invalid defaults object reuses projects.INVALID_DEFAULTS. Only the
# causes no store seam owns are minted here — the root-existence ones,
# because the roots are judged against this filesystem rather than read
# out of the record.
WORKSPACE_MISMATCH = "workspace_mismatch"
MISSING_PRIMARY_PATH = "missing_primary_path"
MISSING_ADDITIONAL_ROOT = "missing_additional_root"

_BINDING_REQUIRED_KEYS = ("directory", "project", "work_area")


class ProjectResolutionError(RuntimeError):
    """A project binding handed to init_run could not be resolved. Raised
    BEFORE anything is created — no state file, no directory, no KV write —
    so a refused init leaves nothing to resume or clean up. `cause` carries
    one machine-readable reason (Slice 2's validation/read vocabulary,
    projects.INVALID_DEFAULTS, or the init-specific WORKSPACE_MISMATCH /
    MISSING_PRIMARY_PATH / MISSING_ADDITIONAL_ROOT) so the service
    launcher can map project refusals
    to 400-class API errors without string-matching. Deliberately distinct
    from FileExistsError (state already exists — also unchanged)."""

    def __init__(self, cause, message):
        RuntimeError.__init__(self, message)
        self.cause = cause


def _resolve_project_binding(binding, workspace, config_override):
    """Resolve a (project, work_area) binding through Slice 2's sealed
    read seam (WorkAreaStore.read), READ-ONLY: a successful resolution
    writes no KV entry and creates no directory (the store is not even
    opened until the pure validations pass and its project directory is
    known to exist).

    Readiness is VERIFIED HERE, not consulted: the stored `status` is a
    record of what some launcher once found, so it is never read as a
    permission (a live record of any status resolves). What must hold is
    the filesystem truth, checked at the moment of use because that is the
    only moment it is true — every root in the stored descriptor must
    exist, and a missing one refuses with its OWN cause rather than a
    generic not-ready. Requirements that belong to one kind of launch
    (a milestone's git repository root) are verified by that launch, not
    here: this seam is shared with callers that have no such requirement.

    Returns (workspace, project_block, effective_config):

    - workspace: the resolved work area's primary.path — the repo the
      driver owns and executes in. A caller-supplied workspace must equal
      it EXACTLY (no symlink-resolving or normalizing comparison is
      attempted: ambiguity refuses);
    - project_block: {directory, project, work_area, primary, additional}
      — the state seam Slices 6 and 8 consume, roots verbatim in Slice 2's
      public {path, device} shape;
    - effective_config: DEFAULT_CONFIG <- binding defaults <-
      config_override, each applied with merge_config (the single merge
      source): launch intent wins over standing project defaults, which
      win over built-ins.
    """
    if not isinstance(binding, dict):
        raise ValueError("project binding must be a dict")
    unknown = sorted(set(binding) - set(_BINDING_REQUIRED_KEYS) - {"defaults"})
    if unknown:
        raise ValueError("project binding has unknown keys: %s" % unknown)
    missing = [k for k in _BINDING_REQUIRED_KEYS if k not in binding]
    if missing:
        raise ValueError("project binding is missing keys: %s" % missing)
    directory = binding["directory"]
    if not isinstance(directory, str) or not directory.strip():
        raise ValueError(
            "project binding directory must be a non-empty string"
        )
    directory = os.path.abspath(directory)

    try:
        project = workareas.validate_project_slug(binding["project"])
        work_area = workareas.validate_name(binding["work_area"])
    except workareas.WorkAreaValidationError as exc:
        raise ProjectResolutionError(
            exc.reason, "invalid project binding: %s" % exc.reason
        ) from exc

    # Defaults are validated before any store access so every refusal —
    # this one included — creates nothing (opening the KV would
    # materialize the project directory and its lock file).
    defaults = None
    if "defaults" in binding:
        try:
            if not isinstance(binding["defaults"], dict):
                raise ValueError("defaults must be a JSON object")
            defaults = kvstore.canonical_json_value(binding["defaults"])
        except ValueError as exc:
            raise ProjectResolutionError(
                projects.INVALID_DEFAULTS,
                "project defaults must be a JSON-plain object: %s" % exc,
            ) from exc

    if not os.path.isdir(os.path.join(directory, project)):
        raise ProjectResolutionError(
            workareas.UNKNOWN,
            "project %r has no work-area store under %s"
            % (project, directory),
        )
    resolved = workareas.WorkAreaStore(directory, project).read(work_area)
    if not resolved.ok:
        raise ProjectResolutionError(
            resolved.reason,
            "cannot resolve work area %r of project %r: %s"
            % (work_area, project, resolved.reason),
        )
    primary = resolved.value["primary"]
    additional = resolved.value["additional"]

    if workspace is None:
        workspace = primary["path"]
    elif workspace != primary["path"]:
        raise ProjectResolutionError(
            WORKSPACE_MISMATCH,
            "supplied workspace %r is not work area %r's primary.path %r; "
            "a project-bound run executes in the primary root (omit the "
            "workspace to derive it)" % (workspace, work_area,
                                         primary["path"]),
        )
    if not os.path.isdir(primary["path"]):
        raise ProjectResolutionError(
            MISSING_PRIMARY_PATH,
            "work area %r's primary.path %r is not an existing directory; "
            "init never fabricates the executed repo"
            % (work_area, primary["path"]),
        )
    for root in additional:
        if not os.path.isdir(root["path"]):
            raise ProjectResolutionError(
                MISSING_ADDITIONAL_ROOT,
                "work area %r's additional root %r is not an existing "
                "directory" % (work_area, root["path"]),
            )

    config = load_config(None)
    if defaults is not None:
        merge_config(config, defaults)
    if config_override:
        merge_config(config, config_override)
    project_block = {
        "directory": directory,
        "project": project,
        "work_area": work_area,
        "primary": primary,
        "additional": additional,
    }
    return workspace, project_block, config


_CREATION_ACTS_UNSET = object()


def _creation_act_overrides(layers):
    """Project ordered raw creation layers onto the one live override map.

    The projection follows ``merge_config``'s one-level whole-map behavior.
    A dict updates a lower dict but replaces a lower non-dict value. A final
    non-dict whole-map replacement suppresses every configurable profile act.
    Unknown/legacy keys remain outside this layer and continue in config.
    """
    current = _CREATION_ACTS_UNSET
    for layer in layers:
        if layer is _CREATION_ACTS_UNSET:
            continue
        if isinstance(layer, dict):
            if isinstance(current, dict):
                current.update(copy.deepcopy(layer))
            else:
                current = copy.deepcopy(layer)
        else:
            current = copy.deepcopy(layer)
    if current is _CREATION_ACTS_UNSET:
        overrides = {}
    elif not isinstance(current, dict):
        overrides = {
            act: None for act in model_profiles.PROFILE_ACT_KEYS
        }
    else:
        overrides = {
            act: copy.deepcopy(value)
            for act, value in current.items()
            if act in model_profiles.PROFILE_ACT_KEYS
        }
    for act, value in overrides.items():
        if value in (None, "", {}):
            continue
        try:
            model_profiles.validate_act_entry(
                "creation act overrides", act, value
            )
        except model_profiles.ModelProfileError as exc:
            # Creation-input errors need their own caller-facing posture;
            # catalogue corruption remains a ModelProfileError and therefore
            # is not mistaken for a bad launch request by CLI/service callers.
            raise ValueError(str(exc)) from exc
    return overrides


def _restrict_config_acts_to_shipped(config):
    """Keep shipped surface entries in config; creation entries live outside."""
    if not isinstance(config, dict):
        return
    acts = config.get("acts")
    shipped = DEFAULT_CONFIG["acts"]
    if not isinstance(acts, dict):
        config["acts"] = copy.deepcopy(shipped)
        return
    for act in model_profiles.PROFILE_ACT_KEYS:
        if act in shipped:
            acts[act] = copy.deepcopy(shipped[act])
        else:
            acts.pop(act, None)


def _write_creation_acts(state_path, overrides):
    path = os.path.join(
        os.path.dirname(os.path.abspath(state_path)), "acts.json"
    )
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(overrides, fh, indent=1)
    os.replace(tmp, path)


def _validate_initial_strategy(config):
    """Validate raw retained strategy content before creating run state."""
    if not isinstance(config, dict) or "profile" not in config:
        return
    ref = config.get("profile_ref")
    name = ref.get("name") if isinstance(ref, dict) else None
    try:
        profiles.validate_semantic_content(
            config["profile"], name=name, ctx="initial strategy profile"
        )
    except profiles.ProfileError as exc:
        raise ValueError(str(exc)) from exc


def init_run(goal, workspace=None, config=None, state_path=None, name=None,
             project=None, config_override=None, model_profiles_home=None,
             creation_acts=_CREATION_ACTS_UNSET,
             prompt_set=prompt_sets.DEFAULT_SET_NAME):
    """Create a new run state. `config` is a merged config dict (see
    load_config) or None for defaults. Returns the state path.
    Raises FileExistsError instead of overwriting an existing state; the
    claim is atomic (st.save_new, exclusive hard link), so two concurrent
    inits of the same workspace cannot both win — no exists() TOCTOU.

    When ``model_profiles_home`` is supplied, startup seeds/validates the
    current catalogue and surface acts explicitly supplied at creation are
    projected into ``acts.json`` only. ``creation_acts`` carries the raw CLI or
    project-less service layer; project-bound init derives project-default and
    launch layers directly.

    `project` (optional) binds the run to a (project, work_area) pair:
    {"directory": <service-level store dir>, "project": <slug>,
    "work_area": <name>} plus optional "defaults" (the project record's
    standing config conventions). Resolution happens once, here, read-only
    (see _resolve_project_binding): the run's workspace IS the work area's
    primary.path — which must already exist; a bound init never creates
    the executed repo — the resolved block lands in the state document,
    and the ledger records exactly one project_resolved event. A binding
    that cannot be resolved raises ProjectResolutionError and creates
    nothing. Because project defaults must merge BENEATH per-launch
    intent, a bound init takes the launch's own override separately, as
    `config_override`, never pre-merged into `config`. Without a project
    binding, project resolution remains inert."""
    try:
        prompt_set = prompt_sets.validate_name(prompt_set)
    except prompt_sets.PromptSetError as exc:
        raise ValueError(str(exc)) from exc
    if model_profiles_home is not None:
        model_profiles_home = os.path.abspath(model_profiles_home)
    creation_act_layers = [creation_acts]
    if project is not None:
        if config is not None:
            raise ValueError(
                "project-bound init orders project defaults beneath the "
                "launch's own intent; pass the launch override as "
                "config_override, not a pre-merged config"
            )
        if config_override is not None and not isinstance(
            config_override, dict
        ):
            raise ValueError("config_override must be a dict")
        if creation_acts is not _CREATION_ACTS_UNSET:
            raise ValueError(
                "project-bound init derives creation acts; do not pass "
                "creation_acts"
            )
        workspace, project_block, config = _resolve_project_binding(
            project, workspace, config_override
        )
        defaults = project.get("defaults")
        creation_act_layers = [
            (defaults["acts"] if isinstance(defaults, dict)
             and "acts" in defaults else _CREATION_ACTS_UNSET),
            (config_override["acts"] if isinstance(config_override, dict)
             and "acts" in config_override else _CREATION_ACTS_UNSET),
        ]
    else:
        if config_override is not None:
            raise ValueError(
                "config_override applies only to project-bound init; "
                "merge launch overrides into config instead"
            )
        if workspace is None:
            raise ValueError(
                "workspace is required without a project binding"
            )
        project_block = None
        workspace = os.path.abspath(workspace)
        os.makedirs(workspace, exist_ok=True)
        if config is None:
            config = load_config(None)
    _validate_initial_strategy(config)
    creation_overrides = {}
    if model_profiles_home is not None:
        creation_overrides = _creation_act_overrides(creation_act_layers)
        prompt_sets.ensure_default(model_profiles_home)
        model_profiles.ensure_default(model_profiles_home)
        staffing.ensure_documents(model_profiles_home)
        _restrict_config_acts_to_shipped(config)
    template = (config or {}).get("docs_dir") or "docs"
    slug = None
    if "{slug}" in template:
        # New milestones never write into a previous milestone's sealed
        # directory: uniquify the slug until the resolved dir is free.
        base = st.slugify(name)
        slug = base
        k = 1
        while os.path.exists(
            os.path.join(
                workspace,
                os.path.normpath(
                    template.replace("{slug}", slug)
                ).strip("/"),
            )
        ):
            k += 1
            slug = "%s-%d" % (base, k)
    else:
        fixed = os.path.normpath(template).strip("/")
        if fixed != "docs" and os.path.exists(
            os.path.join(workspace, fixed)
        ):
            raise FileExistsError(
                "docs_dir %r already exists in the workspace — a fixed "
                "docs_dir cannot host two milestones; use a {slug} "
                "template or remove/rename the directory" % fixed
            )
    state = st.new_state(goal, workspace, config, name=name, slug=slug,
                         project=project_block, prompt_set=prompt_set)
    st.append_event(state, "initialized", goal=goal)
    if project_block is not None:
        # Frozen ledger shape: payload exactly {project, work_area}, once
        # per run, at init (project-concept.md:254, fixture I10).
        # Exactly-once needs no guard of its own: this is the only append
        # site, save_new's exclusive claim makes init itself exactly-once,
        # and nothing re-resolves after init.
        st.append_event(
            state,
            "project_resolved",
            project=project_block["project"],
            work_area=project_block["work_area"],
        )
    path = state_path or default_state_path(workspace, state.get("docs_dir"))
    st.save_new(path, state)
    if creation_overrides:
        try:
            _write_creation_acts(path, creation_overrides)
        except OSError:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise
    return path


def cmd_init(args):
    user_cfg = None
    if args.config:
        with open(args.config, "r", encoding="utf-8") as fh:
            user_cfg = json.load(fh)
        if not isinstance(user_cfg, dict):
            raise ValueError("--config must contain a JSON object")
    config = load_config(None)
    if user_cfg is not None:
        merge_config(config, user_cfg)
    try:
        path = init_run(
            args.goal,
            args.workspace,
            config=config,
            state_path=args.state,
            name=(
                args.name
                or os.path.basename(
                    os.path.abspath(args.workspace).rstrip("/")
                )
                or "run"
            ),
            model_profiles_home=getattr(
                args, "model_profiles_home", registry.DEFAULT_HOME
            ),
            creation_acts=(
                user_cfg["acts"]
                if isinstance(user_cfg, dict) and "acts" in user_cfg
                else _CREATION_ACTS_UNSET
            ),
            prompt_set=getattr(
                args, "prompt_set", prompt_sets.DEFAULT_SET_NAME
            ),
        )
    except (FileExistsError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print("initialized: %s" % path)
    return 0


def resolve_workspace_state(workspace):
    """Locate a run's state file given only the workspace root.

    Prefers the legacy <ws>/.orchestrator/state.json; otherwise finds a
    per-milestone <ws>/<...>/.run/state.json. Raises SystemExit(2) when
    there is no run, or more than one (the operator must then pass --state
    to disambiguate, since one repo can now host several milestones)."""
    workspace = os.path.abspath(workspace)
    legacy = default_state_path(workspace)
    if os.path.isfile(legacy):
        return legacy
    prune = (runners.SNAPSHOT_EXCLUDE_DIRS - {".run"}) | {
        "node_modules", "deps", "_build", "target", "vendor", "build"
    }
    found = []
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in prune]
        if os.path.basename(root) == ".run" and "state.json" in files:
            found.append(os.path.join(root, "state.json"))
            dirs[:] = []  # do not descend below a runtime dir
    if len(found) == 1:
        return found[0]
    if not found:
        print("error: no run state found under %s (pass --state PATH)"
              % workspace, file=sys.stderr)
    else:
        print("error: %d runs under %s; pass --state PATH to pick one:\n  %s"
              % (len(found), workspace, "\n  ".join(sorted(found))),
              file=sys.stderr)
    raise SystemExit(2)


def _state_path(args):
    if args.state:
        return args.state
    if args.workspace:
        return resolve_workspace_state(args.workspace)
    print(
        "error: pass --state PATH or --workspace DIR to locate the state file",
        file=sys.stderr,
    )
    raise SystemExit(2)


def cmd_status(args):
    path = _state_path(args)
    state = st.load(path)
    acts_path = os.path.join(os.path.dirname(os.path.abspath(path)),
                             "acts.json")
    try:
        with open(acts_path, "r", encoding="utf-8") as fh:
            acts_overlay = json.load(fh)
    except (OSError, ValueError):
        acts_overlay = {}
    current_review_model = resolve_current_review_model(
        path,
        getattr(args, "model_profiles_home", registry.DEFAULT_HOME),
        run_state=state,
    )
    summ = st.summary(
        state,
        acts_overlay=(acts_overlay if isinstance(acts_overlay, dict) else {}),
        current_review_model=current_review_model,
    )
    if args.json:
        print(json.dumps(summ, indent=2, ensure_ascii=False))
        return 0
    print("goal:      %s" % summ["goal"])
    print("workspace: %s" % summ["workspace"])
    print("milestone: %s" % summ["milestone_status"])
    if summ["failure"]:
        print("FAILED:    %s" % summ["failure"]["reason"])
    for unit in summ["units"]:
        seals = ", ".join(
            "a%d:%s" % (s["attempt"], "pass" if s["passed"] else ("inval" if s["invalidated"] else "fail"))
            for s in unit["seals"]
        )
        print(
            "  %-16s %-18s rounds=%-3d seals=[%s]"
            % (unit["unit"], unit["status"], len(unit["rounds"]), seals)
        )
    nxt = decide(state)
    print("next:      %r" % nxt)
    return 0


def cmd_resume(args):
    path = _state_path(args)
    state = st.load(path)
    try:
        restored = st.resume_run(state)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    st.save(path, state)
    for unit, status in restored.items():
        print("resumed %s -> %s" % (unit, status))
    print("run resumed; relaunch with `run` (or the panel's Start)")
    return 0


def cmd_next(args):
    state = st.load(_state_path(args))
    print(repr(decide(state)))
    return 0


def _install_stop_forwarding():
    """Make SIGTERM (service Stop button, plain `kill`) reach in-flight
    worker CLIs before the driver dies. Workers run in their OWN sessions
    (so timeout kills cannot take the driver down with them), which also
    means a SIGTERM to the driver's group would otherwise orphan a
    full-permission codex/claude process that keeps editing the workspace
    for up to its whole timeout. CLI entry points only; signal handlers can
    only be installed from the main thread."""
    if threading.current_thread() is not threading.main_thread():
        return  # pragma: no cover - embedded use; CLI always hits main thread

    def handler(signum, frame):
        # One breadcrumb before dying signal-silent: a driver that vanishes
        # with an empty log is unattributable (2026-08-21).
        print("DRIVER SIGTERM: killing worker groups and exiting",
              file=sys.stderr, flush=True)
        runners.kill_active_worker_groups()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTERM)  # die with the real signal status

    try:
        signal.signal(signal.SIGTERM, handler)
    except ValueError:  # pragma: no cover - non-main thread race
        pass


def cmd_step(args):
    _install_stop_forwarding()
    driver = Driver(
        _state_path(args),
        model_profiles_home=getattr(
            args, "model_profiles_home", registry.DEFAULT_HOME
        ),
    )
    try:
        action, note = driver.step()
    except ConcurrentRunError as exc:
        print("CONCURRENT RUN REFUSED: %s" % exc, file=sys.stderr)
        return 2
    print("%r -> %s" % (action, note))
    if action.type == A_FAILED:
        return 2
    return 0


def cmd_run(args):
    _install_stop_forwarding()
    driver = Driver(
        _state_path(args),
        model_profiles_home=getattr(
            args, "model_profiles_home", registry.DEFAULT_HOME
        ),
    )
    try:
        code = driver.run(max_steps=args.max_steps)
    except ConcurrentRunError as exc:
        print("CONCURRENT RUN REFUSED: %s" % exc, file=sys.stderr)
        return 2
    summ = st.summary(driver.state)
    if code == 0:
        print("milestone %s" % summ["milestone_status"])
    elif code == 2:
        print("RUN FAILED: %s" % (summ["failure"] or {}).get("reason"))
    elif code == 4:
        print("paused after seal (operator-ordered safe stop); "
              "start again to resume")
    else:
        print("stopped after --max-steps")
    return code


def cmd_serve(args):
    from . import webapp

    return webapp.serve(
        _state_path(args), args.port,
        model_profiles_home=getattr(
            args, "model_profiles_home", registry.DEFAULT_HOME
        ),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a new run state")
    p_init.add_argument("--goal", required=True)
    p_init.add_argument("--name", default=None,
                        help="milestone name (slug feeds docs_dir)")
    p_init.add_argument("--workspace", required=True)
    p_init.add_argument("--config", default=None)
    p_init.add_argument("--state", default=None)
    p_init.add_argument(
        "--prompt-set", default=prompt_sets.DEFAULT_SET_NAME,
        help="named prompt set to bind for the run",
    )
    p_init.add_argument(
        "--model-profiles-home", default=registry.DEFAULT_HOME
    )
    p_init.set_defaults(func=cmd_init)

    for name, func in (
        ("status", cmd_status),
        ("resume", cmd_resume),
        ("next", cmd_next),
        ("step", cmd_step),
        ("run", cmd_run),
        ("serve", cmd_serve),
    ):
        p = sub.add_parser(name)
        p.add_argument("--state", default=None)
        p.add_argument("--workspace", default=None)
        if name == "status":
            p.add_argument("--json", action="store_true")
        if name == "run":
            p.add_argument("--max-steps", type=int, default=1000)
        if name in ("status", "step", "run", "serve"):
            p.add_argument(
                "--model-profiles-home", default=registry.DEFAULT_HOME
            )
        if name == "serve":
            p.add_argument("--port", type=int, default=8765)
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
