"""Exhaustive tests for orchestrator/state.py: the append-only state machine.

Covers: new_state shape (schema v2, the fix-episode unit fields), the full
unit lifecycle for every unit kind under the review/fix separation model
(dirty review -> U_FIXING -> U_DELTA_REVIEW -> loop or return), the complete
legal/illegal transition table, write-once drafts, round-recording guards
(rounds/fixing/delta_review only, meta merge), family ordering,
enter_fix_episode, the milestone-global adjudication registry, the seal gate
(invalidated rounds and non-review kinds never count), seal attempts, slice
and milestone closure, run failure, append-only persistence with the
terminal-unit freeze (post-seal exceptions: closed_record and gate_commit),
atomic rename-based saves, schema v1 rejection, and the summary() shape.

Standard library only; every on-disk workspace is a tempfile.TemporaryDirectory.
"""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import state as st

FAMILIES = ["codex", "claude"]


# ---------------------------------------------------------------------------
# Fixture helpers (every worker-result fixture is validated against the real
# contract so the tests cannot drift from the protocol).


def make_config():
    return {"families_order": list(FAMILIES)}


def make_state(workspace="unused-ws", slices=None):
    state = st.new_state("Build X", workspace, make_config())
    if slices is not None:
        state["milestone"]["slices"] = slices
    return state


def clean_review(kind=contracts.KIND_REVIEW_ROUND):
    obj = {"status": "ok", "kind": kind, "findings": []}
    contracts.validate_worker_output(obj, kind)
    return obj


def dirty_review(kind=contracts.KIND_REVIEW_ROUND, n=1):
    # Reviewer findings carry NO disposition (whoever detects never fixes)
    # and report kinds must not claim file changes.
    findings = [
        {"id": "F%d" % (i + 1), "severity": "P1", "summary": "issue %d" % (i + 1)}
        for i in range(n)
    ]
    obj = {"status": "ok", "kind": kind, "findings": findings}
    contracts.validate_worker_output(obj, kind)
    return obj


def fixed_finding(fid="F1", severity="P1"):
    return {
        "id": fid,
        "severity": severity,
        "summary": "issue %s" % fid,
        "disposition": "fixed",
    }


def rejected_finding(fid="F1", resolution="the artifact is correct",
                     prevention=None, severity="P1", summary=None):
    f = {
        "id": fid,
        "severity": severity,
        "summary": summary or "issue %s" % fid,
        "disposition": "rejected",
        "consultation": {"resolution": resolution},
    }
    if prevention is not None:
        f["prevention"] = prevention
    return f


def adjudicated_finding(fid, ref, severity="P2"):
    return {
        "id": fid,
        "severity": severity,
        "summary": "duplicate of settled finding",
        "disposition": "rejected_adjudicated",
        "adjudication_ref": ref,
    }


def blocked_finding(fid="F1"):
    return {
        "id": fid,
        "severity": "P0",
        "summary": "cannot proceed",
        "disposition": "blocked",
    }


def fix_result(findings=None, files_changed=None):
    obj = {
        "status": "ok",
        "kind": contracts.KIND_FIX_FINDINGS,
        "findings": findings if findings is not None else [fixed_finding("F1")],
        "files_changed": files_changed if files_changed is not None else [],
    }
    contracts.validate_worker_output(obj, contracts.KIND_FIX_FINDINGS)
    return obj


def verification_finding():
    """The synthetic V1 finding the driver queues on a verification failure."""
    return {
        "id": "V1",
        "severity": "P1",
        "summary": "the verification suite failed (see the verification "
        "output in this prompt)",
    }


def queued(finding):
    """The queue entry shape the driver derives from a reviewer finding."""
    return {
        "id": finding["id"],
        "severity": finding["severity"],
        "summary": finding["summary"],
        "contests": finding.get("contests"),
    }


def seal_half_result(n_findings=0):
    findings = [
        {"id": "F%d" % (i + 1), "severity": "P2", "summary": "seal issue"}
        for i in range(n_findings)
    ]
    obj = {"status": "ok", "kind": contracts.KIND_SEAL_HALF, "findings": findings}
    contracts.validate_worker_output(obj, contracts.KIND_SEAL_HALF)
    return obj


def make_halves(codex=0, claude=0):
    return {
        "codex": {
            "result": seal_half_result(codex),
            "raw_path": None,
            "duration_s": 0.1,
            "workspace_modified": False,
        },
        "claude": {
            "result": seal_half_result(claude),
            "raw_path": None,
            "duration_s": 0.1,
            "workspace_modified": False,
        },
    }


def skeleton_draft(n_slices=1):
    obj = {
        "status": "ok",
        "kind": contracts.KIND_DRAFT_SKELETON,
        "artifact": "docs/skeleton.md",
        "slices": [
            {"id": i + 1, "title": "slice %d" % (i + 1)} for i in range(n_slices)
        ],
    }
    contracts.validate_worker_output(obj, contracts.KIND_DRAFT_SKELETON)
    return obj


def default_draft_for(unit):
    if unit["kind"] == st.UNIT_SKELETON:
        return skeleton_draft(1)
    if unit["kind"] == st.UNIT_SLICE_DOC:
        obj = {
            "status": "ok",
            "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "artifact": "docs/slice-%02d.md" % unit["slice_id"],
        }
        contracts.validate_worker_output(obj, contracts.KIND_DRAFT_SLICE_NOTE)
        return obj
    obj = {
        "status": "ok",
        "kind": contracts.KIND_IMPLEMENT,
        "files_changed": ["calc.py"],
    }
    contracts.validate_worker_output(obj, contracts.KIND_IMPLEMENT)
    return obj


def run_reviews_clean(state, unit):
    """One clean review round per configured family, advancing each time."""
    for fam in state["config"]["families_order"]:
        res = clean_review()
        st.record_round(state, unit, fam, contracts.KIND_REVIEW_ROUND, res)
        st.advance_family_if_clean(state, unit, res)


def run_fix_episode_green(state, unit, fix_findings, source_round_id=None):
    """Drive the current fix episode to green exactly like the driver does:
    one fixer call, one clean delta review, return to fix_source.return_to.
    The unit must already be in U_FIXING (enter_fix_episode was called)."""
    if unit["status"] != st.U_FIXING:
        raise AssertionError("helper expects U_FIXING, got %s" % unit["status"])
    st.record_round(
        state, unit, "codex", contracts.KIND_FIX_FINDINGS,
        fix_result(fix_findings),
        meta={"source_round_id": source_round_id
              or unit["fix_source"]["source_round_id"]},
    )
    unit["fix_loop_rounds"] += 1
    st.transition_unit(state, unit, st.U_DELTA_REVIEW, reason="fix applied")
    st.record_round(
        state, unit, "codex", contracts.KIND_DELTA_REVIEW,
        clean_review(contracts.KIND_DELTA_REVIEW),
    )
    st.transition_unit(state, unit, unit["fix_source"]["return_to"],
                       reason="delta green; amended")


def seal_current_unit(state, draft_result=None):
    """Drive the current unit through its full happy path to sealed."""
    unit = st.current_unit(state)
    if unit["draft"] is None:
        if draft_result is None:
            draft_result = default_draft_for(unit)
        st.record_draft(state, unit, draft_result["kind"], draft_result)
        if unit["kind"] == st.UNIT_SKELETON:
            state["milestone"]["slices"] = draft_result["slices"]
    st.transition_unit(state, unit, st.U_PRE_REVIEW_VERIFY)
    st.transition_unit(state, unit, st.U_ROUNDS)
    run_reviews_clean(state, unit)
    if unit["status"] != st.U_PRE_SEAL_VERIFY:
        raise AssertionError("helper expected pre_seal_verify, got %s" % unit["status"])
    st.transition_unit(state, unit, st.U_SEALING)
    st.record_seal_attempt(state, unit, make_halves(), True)
    st.transition_unit(state, unit, st.U_SEALED)
    return unit


def unit_in_status(state, status):
    """Fresh skeleton unit with its status forced (to exercise guards)."""
    unit = state["units"][0]
    unit["status"] = status
    return unit


class TempWorkspaceCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = self._tmp.name


# ---------------------------------------------------------------------------
# new_state shape


class TestNewState(TempWorkspaceCase):
    def test_schema_version_is_2(self):
        self.assertEqual(st.SCHEMA_VERSION, 2)

    def test_top_level_shape(self):
        state = st.new_state("Build X", self.workspace, make_config())
        self.assertEqual(
            set(state.keys()),
            {
                "schema_version",
                "goal",
                "workspace",
                "created_at",
                "milestone",
                "units",
                "events",
                "suite_command",
                "name",
                "docs_dir",
                "orchestrator_rev",
                "failure",
                "config",
            },
        )
        self.assertEqual(state["schema_version"], st.SCHEMA_VERSION)
        self.assertEqual(state["goal"], "Build X")
        self.assertEqual(state["workspace"], self.workspace)
        self.assertEqual(state["milestone"], {"status": st.M_OPEN, "slices": []})
        self.assertEqual(state["events"], [])
        self.assertIsNone(state["failure"])
        self.assertEqual(state["config"], make_config())

    def test_initial_unit_is_pending_skeleton_with_fix_episode_fields(self):
        state = st.new_state("Build X", self.workspace, make_config())
        self.assertEqual(len(state["units"]), 1)
        unit = state["units"][0]
        self.assertEqual(
            unit,
            {
                "kind": st.UNIT_SKELETON,
                "slice_id": None,
                "status": st.U_PENDING,
                "artifact": None,
                "draft": None,
                "family_index": 0,
                "rounds": [],
                "seals": [],
                "verify_fix_attempts": {"pre_review": 0, "pre_seal": 0},
                "verify_episode_seq": {"pre_review": 0, "pre_seal": 0},
                "closed_record": None,
                "gate_commit": None,
                "failed_from": None,
                "rounds_amnesty": 0,
                "seals_amnesty": 0,
                "fix_queue": [],
                "fix_source": None,
                "fix_loop_rounds": 0,
                "debt": [],
            },
        )
        self.assertEqual(st.unit_key(unit), "skeleton")

    def test_status_set(self):
        self.assertEqual(
            st.UNIT_STATUSES,
            (
                st.U_PENDING,
                st.U_PRE_REVIEW_VERIFY,
                st.U_ROUNDS,
                st.U_FIXING,
                st.U_DELTA_REVIEW,
                st.U_PRE_SEAL_VERIFY,
                st.U_SEALING,
                st.U_SEALED,
                st.U_REPAIRING,
                st.U_FAILED,
            ),
        )

    def test_current_unit_and_unit_key(self):
        state = make_state(self.workspace, slices=[{"id": 1, "title": "t"}])
        self.assertIs(st.current_unit(state), state["units"][0])
        doc = st.ensure_next_unit(state)
        self.assertEqual(st.unit_key(doc), "slice_doc-01")
        # first non-sealed unit wins
        self.assertIs(st.current_unit(state), state["units"][0])
        state["units"][0]["status"] = st.U_SEALED
        self.assertIs(st.current_unit(state), doc)


# ---------------------------------------------------------------------------
# Unit lifecycle per kind


class TestUnitLifecycle(TempWorkspaceCase):
    def test_skeleton_happy_path(self):
        state = make_state(self.workspace)
        unit = st.current_unit(state)
        draft = skeleton_draft(1)
        st.record_draft(state, unit, draft["kind"], draft)
        self.assertEqual(unit["status"], st.U_PENDING)  # draft does not transition
        self.assertEqual(unit["artifact"], "docs/skeleton.md")
        state["milestone"]["slices"] = draft["slices"]
        st.transition_unit(state, unit, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, unit, st.U_ROUNDS)
        run_reviews_clean(state, unit)
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, unit, st.U_SEALING)
        st.record_seal_attempt(state, unit, make_halves(), True)
        st.transition_unit(state, unit, st.U_SEALED)
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertIsNone(st.current_unit(state))

    def test_slice_doc_lifecycle_with_verification_fix_episodes(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        doc = st.ensure_next_unit(state)
        self.assertEqual(doc["kind"], st.UNIT_SLICE_DOC)
        st.record_draft(state, doc, contracts.KIND_DRAFT_SLICE_NOTE, default_draft_for(doc))
        st.transition_unit(state, doc, st.U_PRE_REVIEW_VERIFY)
        # pre-review verification fails -> synthetic V1 finding -> fix
        # episode -> clean delta -> back to pre-review verification
        st.enter_fix_episode(
            state, doc, [verification_finding()], "verification", None,
            "slice_doc-01-verify-pre_review-1", st.U_PRE_REVIEW_VERIFY,
        )
        self.assertEqual(doc["status"], st.U_FIXING)
        run_fix_episode_green(state, doc, [fixed_finding("V1")])
        self.assertEqual(doc["status"], st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, doc, st.U_ROUNDS)
        run_reviews_clean(state, doc)
        # pre-seal verification can also fail into a fix episode and return
        self.assertEqual(doc["status"], st.U_PRE_SEAL_VERIFY)
        st.enter_fix_episode(
            state, doc, [verification_finding()], "verification", None,
            "slice_doc-01-verify-pre_seal-1", st.U_PRE_SEAL_VERIFY,
        )
        run_fix_episode_green(state, doc, [fixed_finding("V1")])
        self.assertEqual(doc["status"], st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, doc, st.U_SEALING)
        st.record_seal_attempt(state, doc, make_halves(), True)
        st.transition_unit(state, doc, st.U_SEALED)
        self.assertEqual(doc["status"], st.U_SEALED)

    def test_rounds_fix_episode_with_dirty_delta_loop(self):
        # A dirty review round enters the fix episode; a dirty delta loops
        # back to the fixer within the SAME episode; the green delta returns
        # the unit exactly where the dirty review left off (U_ROUNDS).
        state = make_state(self.workspace)
        unit = st.current_unit(state)
        st.transition_unit(state, unit, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, unit, st.U_ROUNDS)
        dirty = dirty_review()
        rec = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty)
        st.enter_fix_episode(
            state, unit, [queued(f) for f in dirty["findings"]],
            "round", "codex", rec["id"], st.U_ROUNDS,
        )
        self.assertEqual(unit["status"], st.U_FIXING)
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
            meta={"source_round_id": rec["id"]},
        )
        unit["fix_loop_rounds"] += 1
        st.transition_unit(state, unit, st.U_DELTA_REVIEW)
        delta_dirty = dirty_review(contracts.KIND_DELTA_REVIEW)
        drec = st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW, delta_dirty
        )
        # dirty delta: same episode, new queue, back to the fixer
        unit["fix_queue"] = [queued(f) for f in delta_dirty["findings"]]
        unit["fix_source"]["type"] = "delta"
        unit["fix_source"]["family"] = "codex"
        unit["fix_source"]["source_round_id"] = drec["id"]
        st.transition_unit(state, unit, st.U_FIXING)
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
            meta={"source_round_id": drec["id"]},
        )
        unit["fix_loop_rounds"] += 1
        st.transition_unit(state, unit, st.U_DELTA_REVIEW)
        st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            clean_review(contracts.KIND_DELTA_REVIEW),
        )
        st.transition_unit(state, unit, unit["fix_source"]["return_to"])
        self.assertEqual(unit["status"], st.U_ROUNDS)
        # The episode never produced a clean codex REVIEW round: gate closed.
        self.assertFalse(st.can_open_seal(state, unit))

    def test_slice_impl_lifecycle_with_seal_fix_episode(self):
        # Mirrors the demo baseline: seal attempt 1 fails -> fix episode ->
        # re-verify -> attempt 2 passes on the impl unit.
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        st.ensure_next_unit(state)
        seal_current_unit(state)  # slice_doc-01
        impl = st.ensure_next_unit(state)
        self.assertEqual(impl["kind"], st.UNIT_SLICE_IMPL)
        st.record_draft(state, impl, contracts.KIND_IMPLEMENT, default_draft_for(impl))
        st.transition_unit(state, impl, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, impl, st.U_ROUNDS)
        run_reviews_clean(state, impl)
        st.transition_unit(state, impl, st.U_SEALING)
        # attempt 1: claude half finds a problem -> fix episode -> re-verify
        rec1 = st.record_seal_attempt(state, impl, make_halves(claude=1), False)
        self.assertEqual(rec1["attempt"], 1)
        st.enter_fix_episode(
            state, impl,
            [{"id": "claude-F1", "severity": "P2",
              "summary": "[claude seal half] seal issue", "contests": None}],
            "seal", None, "slice_impl-01-seal-a1", st.U_PRE_SEAL_VERIFY,
        )
        run_fix_episode_green(state, impl, [fixed_finding("claude-F1", "P2")])
        self.assertEqual(impl["status"], st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, impl, st.U_SEALING)
        rec2 = st.record_seal_attempt(state, impl, make_halves(), True)
        self.assertEqual(rec2["attempt"], 2)
        st.transition_unit(state, impl, st.U_SEALED)
        st.close_slice(state, impl)
        self.assertEqual(impl["closed_record"]["slice_id"], 1)

    def test_ensure_next_before_seal_helper_order(self):
        # Explicitly verify the helper sequencing used above is legitimate:
        # ensure_next_unit appends doc-01 right after the skeleton seals.
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        doc = st.ensure_next_unit(state)
        self.assertEqual(st.unit_key(doc), "slice_doc-01")
        self.assertIs(st.current_unit(state), doc)


# ---------------------------------------------------------------------------
# Transition table


EXPECTED_ALLOWED = {
    # Review/fix separation: dirty reviews from ANY source (verification, a
    # review round, a seal) enter U_FIXING; the fixer's pending diff is
    # checked in U_DELTA_REVIEW; a dirty delta loops back to U_FIXING; a
    # green delta returns exactly where the dirty review would have gone.
    st.U_PENDING: {st.U_PRE_REVIEW_VERIFY, st.U_FAILED},
    st.U_PRE_REVIEW_VERIFY: {st.U_ROUNDS, st.U_FIXING, st.U_FAILED},
    st.U_ROUNDS: {st.U_ROUNDS, st.U_FIXING, st.U_PRE_SEAL_VERIFY, st.U_FAILED},
    st.U_FIXING: {
        st.U_DELTA_REVIEW, st.U_PRE_REVIEW_VERIFY, st.U_ROUNDS,
        st.U_PRE_SEAL_VERIFY, st.U_FAILED,
    },
    st.U_DELTA_REVIEW: {
        st.U_FIXING, st.U_PRE_REVIEW_VERIFY, st.U_ROUNDS,
        st.U_PRE_SEAL_VERIFY, st.U_FAILED,
    },
    st.U_PRE_SEAL_VERIFY: {st.U_SEALING, st.U_FIXING, st.U_FAILED},
    # U_SEALING stays U_SEALING on an invalidated attempt (workspace
    # restored, attempt retried): no self-loop transition is needed.
    st.U_SEALING: {st.U_SEALED, st.U_FIXING, st.U_FAILED},
    # Sealed is terminal EXCEPT reopen_for_repair (reform §3): sealed ->
    # repairing -> fixing (the repair) -> ... -> resealed.
    st.U_SEALED: {st.U_REPAIRING},
    st.U_REPAIRING: {st.U_FIXING, st.U_FAILED},
    st.U_FAILED: set(),
}


class TestTransitionTable(TempWorkspaceCase):
    def test_table_covers_every_status(self):
        self.assertEqual(set(EXPECTED_ALLOWED), set(st.UNIT_STATUSES))

    def test_every_pair_exhaustively(self):
        for old in st.UNIT_STATUSES:
            for new in st.UNIT_STATUSES:
                state = make_state(self.workspace)
                unit = unit_in_status(state, old)
                events_before = len(state["events"])
                if new in EXPECTED_ALLOWED[old]:
                    st.transition_unit(state, unit, new, reason="test")
                    self.assertEqual(unit["status"], new, "%s->%s" % (old, new))
                    evt = state["events"][-1]
                    self.assertEqual(evt["type"], "unit_transition")
                    self.assertEqual(evt["from_status"], old)
                    self.assertEqual(evt["to_status"], new)
                    self.assertEqual(evt["reason"], "test")
                else:
                    with self.assertRaises(
                        st.IllegalTransition, msg="%s->%s must be illegal" % (old, new)
                    ):
                        st.transition_unit(state, unit, new)
                    self.assertEqual(unit["status"], old)
                    self.assertEqual(len(state["events"]), events_before)

    def test_representative_illegal_transitions(self):
        cases = [
            (st.U_PENDING, st.U_ROUNDS),
            (st.U_PENDING, st.U_FIXING),
            (st.U_PENDING, st.U_SEALING),
            (st.U_ROUNDS, st.U_SEALING),          # must pass pre-seal verify
            (st.U_ROUNDS, st.U_DELTA_REVIEW),     # only a fixer opens a delta
            (st.U_FIXING, st.U_FIXING),
            (st.U_FIXING, st.U_SEALING),
            (st.U_FIXING, st.U_SEALED),
            (st.U_DELTA_REVIEW, st.U_SEALING),
            (st.U_DELTA_REVIEW, st.U_SEALED),
            (st.U_PRE_SEAL_VERIFY, st.U_ROUNDS),
            (st.U_PRE_SEAL_VERIFY, st.U_DELTA_REVIEW),
            (st.U_SEALING, st.U_ROUNDS),
            (st.U_SEALING, st.U_PRE_SEAL_VERIFY),  # invalidated attempts stay
            (st.U_SEALING, st.U_DELTA_REVIEW),
            (st.U_SEALED, st.U_ROUNDS),
            (st.U_SEALED, st.U_PENDING),
            (st.U_SEALED, st.U_FAILED),
            (st.U_FAILED, st.U_PENDING),
        ]
        for old, new in cases:
            state = make_state(self.workspace)
            unit = unit_in_status(state, old)
            with self.assertRaises(
                st.IllegalTransition, msg="%s->%s must be illegal" % (old, new)
            ):
                st.transition_unit(state, unit, new)


# ---------------------------------------------------------------------------
# record_draft


class TestRecordDraft(TempWorkspaceCase):
    def test_records_and_sets_artifact(self):
        state = make_state(self.workspace)
        unit = st.current_unit(state)
        draft = skeleton_draft(2)
        rec = st.record_draft(state, unit, draft["kind"], draft, raw_path="raw/x.txt")
        self.assertEqual(unit["artifact"], "docs/skeleton.md")
        self.assertEqual(rec["kind"], contracts.KIND_DRAFT_SKELETON)
        self.assertEqual(rec["raw_path"], "raw/x.txt")
        self.assertEqual(rec["result"], draft)
        self.assertIsNot(rec["result"], draft)  # deep-copied, not aliased
        self.assertEqual(state["events"][-1]["type"], "draft_recorded")

    def test_write_once(self):
        state = make_state(self.workspace)
        unit = st.current_unit(state)
        draft = skeleton_draft(1)
        st.record_draft(state, unit, draft["kind"], draft)
        with self.assertRaises(st.IllegalTransition):
            st.record_draft(state, unit, draft["kind"], draft)

    def test_only_from_pending(self):
        for status in st.UNIT_STATUSES:
            if status == st.U_PENDING:
                continue
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            with self.assertRaises(st.IllegalTransition, msg=status):
                st.record_draft(state, unit, contracts.KIND_DRAFT_SKELETON, skeleton_draft(1))
            self.assertIsNone(unit["draft"])

    def test_implement_draft_has_no_artifact(self):
        state = make_state(self.workspace, slices=[{"id": 1, "title": "t"}])
        state["units"][0]["status"] = st.U_SEALED
        st.ensure_next_unit(state)["status"] = st.U_SEALED  # doc-01
        impl = st.ensure_next_unit(state)
        st.record_draft(state, impl, contracts.KIND_IMPLEMENT, default_draft_for(impl))
        self.assertIsNone(impl["artifact"])


# ---------------------------------------------------------------------------
# record_round


class TestRecordRound(TempWorkspaceCase):
    ALLOWED = {st.U_ROUNDS, st.U_FIXING, st.U_DELTA_REVIEW}

    def test_status_guards_all_statuses(self):
        for status in st.UNIT_STATUSES:
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            if status in self.ALLOWED:
                rec = st.record_round(
                    state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review()
                )
                self.assertEqual(len(unit["rounds"]), 1)
                self.assertEqual(rec["id"], "skeleton-codex-r1")
                self.assertEqual(state["events"][-1]["type"], "round_recorded")
            else:
                with self.assertRaises(st.IllegalTransition, msg=status):
                    st.record_round(
                        state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review()
                    )
                self.assertEqual(unit["rounds"], [])
                self.assertEqual(state["events"], [])

    def test_round_ids_number_per_family_across_kinds(self):
        # Fixer and delta rounds share the family's numbering: ids count
        # ALL of that family's rounds, whatever their kind.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        r1 = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        unit["status"] = st.U_FIXING
        r2 = st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
        )
        unit["status"] = st.U_DELTA_REVIEW
        r3 = st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            clean_review(contracts.KIND_DELTA_REVIEW),
        )
        unit["status"] = st.U_ROUNDS
        r4 = st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertEqual(
            [r1["id"], r2["id"], r3["id"], r4["id"]],
            ["skeleton-codex-r1", "skeleton-codex-r2", "skeleton-codex-r3",
             "skeleton-claude-r1"],
        )
        self.assertEqual(st.family_rounds(unit, "codex"), [r1, r2, r3])
        self.assertEqual(st.family_rounds(unit, "claude"), [r4])

    def test_result_is_deep_copied(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        res = dirty_review()
        rec = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, res)
        res["findings"].append({"id": "F2", "severity": "P0", "summary": "later edit"})
        self.assertEqual(len(rec["result"]["findings"]), 1)

    def test_meta_merges_into_record(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        rec = st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
            meta={"source_round_id": "skeleton-claude-r1"},
        )
        self.assertEqual(rec["source_round_id"], "skeleton-claude-r1")
        # base record fields survive the merge
        self.assertEqual(rec["id"], "skeleton-codex-r1")
        self.assertEqual(rec["kind"], contracts.KIND_FIX_FINDINGS)

    def test_meta_invalidation_marker(self):
        # The driver records a tampering reviewer as an invalidated round
        # (output discarded, empty findings) via meta.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        rec = st.record_round(
            state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review(),
            meta={"invalidated": "reviewer modified the workspace; "
                  "output discarded, workspace restored"},
        )
        self.assertIn("reviewer modified", rec["invalidated"])

    def test_meta_is_deep_copied(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        meta = {"source_round_id": "skeleton-claude-r1", "extra": {"n": 1}}
        rec = st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]), meta=meta,
        )
        meta["extra"]["n"] = 99
        self.assertEqual(rec["extra"], {"n": 1})


# ---------------------------------------------------------------------------
# advance_family_if_clean


class TestAdvanceFamily(TempWorkspaceCase):
    def _unit_in_rounds(self):
        state = make_state(self.workspace)
        unit = st.current_unit(state)
        st.transition_unit(state, unit, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, unit, st.U_ROUNDS)
        return state, unit

    def test_dirty_round_stays_in_same_family(self):
        state, unit = self._unit_in_rounds()
        res = dirty_review()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, res)
        st.advance_family_if_clean(state, unit, res)
        self.assertEqual(unit["family_index"], 0)
        self.assertEqual(unit["status"], st.U_ROUNDS)
        self.assertEqual(st.current_family(state, unit), "codex")
        self.assertNotEqual(state["events"][-1]["type"], "family_clean")

    def test_clean_round_advances_codex_then_claude(self):
        state, unit = self._unit_in_rounds()
        self.assertEqual(st.current_family(state, unit), "codex")
        res = clean_review()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, res)
        st.advance_family_if_clean(state, unit, res)
        self.assertEqual(unit["family_index"], 1)
        self.assertEqual(unit["status"], st.U_ROUNDS)
        self.assertEqual(st.current_family(state, unit), "claude")
        evt = state["events"][-1]
        self.assertEqual(evt["type"], "family_clean")
        self.assertEqual(evt["next_family"], "claude")

    def test_last_family_clean_moves_to_pre_seal_verify(self):
        state, unit = self._unit_in_rounds()
        run_reviews_clean(state, unit)
        self.assertEqual(unit["family_index"], 2)
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        self.assertIsNone(st.current_family(state, unit))
        evt = state["events"][-1]
        self.assertEqual(evt["type"], "unit_transition")
        self.assertEqual(evt["to_status"], st.U_PRE_SEAL_VERIFY)

    def test_claude_round_never_reopens_codex(self):
        state, unit = self._unit_in_rounds()
        res = clean_review()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, res)
        st.advance_family_if_clean(state, unit, res)
        # two dirty claude rounds: family index must never go backwards
        for _ in range(2):
            dirty = dirty_review()
            st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, dirty)
            st.advance_family_if_clean(state, unit, dirty)
            self.assertEqual(unit["family_index"], 1)
            self.assertEqual(st.current_family(state, unit), "claude")
        clean = clean_review()
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean)
        st.advance_family_if_clean(state, unit, clean)
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        self.assertEqual(unit["family_index"], 2)


# ---------------------------------------------------------------------------
# enter_fix_episode


class TestEnterFixEpisode(TempWorkspaceCase):
    LEGAL_FROM = {
        st.U_PRE_REVIEW_VERIFY,
        st.U_ROUNDS,
        st.U_DELTA_REVIEW,
        st.U_PRE_SEAL_VERIFY,
        st.U_SEALING,
        st.U_REPAIRING,   # reopen_for_repair queues the repair as a fix
    }

    def test_queue_source_counter_and_transition(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        unit["fix_loop_rounds"] = 3  # stale value from a previous episode
        findings = [queued(f) for f in dirty_review(n=2)["findings"]]
        st.enter_fix_episode(
            state, unit, findings, "round", "claude",
            "skeleton-claude-r1", st.U_ROUNDS,
        )
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertEqual(unit["fix_queue"], findings)
        self.assertEqual(
            unit["fix_source"],
            {
                "type": "round",
                "family": "claude",
                "source_round_id": "skeleton-claude-r1",
                "return_to": st.U_ROUNDS,
            },
        )
        self.assertEqual(unit["fix_loop_rounds"], 0)  # reset per episode
        evt = state["events"][-1]
        self.assertEqual(evt["type"], "unit_transition")
        self.assertEqual(evt["from_status"], st.U_ROUNDS)
        self.assertEqual(evt["to_status"], st.U_FIXING)
        self.assertIn("round", evt["reason"])

    def test_queue_is_deep_copied(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        findings = [queued(f) for f in dirty_review()["findings"]]
        st.enter_fix_episode(
            state, unit, findings, "round", "codex",
            "skeleton-codex-r1", st.U_ROUNDS,
        )
        self.assertIsNot(unit["fix_queue"], findings)
        self.assertIsNot(unit["fix_queue"][0], findings[0])
        findings[0]["summary"] = "mutated by the caller"
        self.assertEqual(unit["fix_queue"][0]["summary"], "issue 1")

    def test_verification_source_has_no_family(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_PRE_SEAL_VERIFY)
        st.enter_fix_episode(
            state, unit, [verification_finding()], "verification", None,
            "skeleton-verify-pre_seal-1", st.U_PRE_SEAL_VERIFY,
        )
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertIsNone(unit["fix_source"]["family"])
        self.assertEqual(unit["fix_source"]["return_to"], st.U_PRE_SEAL_VERIFY)

    def test_legal_from_every_dirty_review_source_status(self):
        for status in sorted(self.LEGAL_FROM):
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            st.enter_fix_episode(
                state, unit, [verification_finding()], "verification", None,
                "skeleton-x", status,
            )
            self.assertEqual(unit["status"], st.U_FIXING, msg=status)

    def test_illegal_from_other_statuses(self):
        for status in st.UNIT_STATUSES:
            if status in self.LEGAL_FROM:
                continue
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            with self.assertRaises(st.IllegalTransition, msg=status):
                st.enter_fix_episode(
                    state, unit, [verification_finding()], "verification",
                    None, "skeleton-x", status,
                )
            self.assertEqual(unit["status"], status)


# ---------------------------------------------------------------------------
# Adjudication registry (milestone-global, derived from immutable rounds)


class TestAdjudicationRegistry(TempWorkspaceCase):
    def test_empty_without_fix_rounds(self):
        state = make_state(self.workspace)
        self.assertEqual(st.adjudicated_rejections(state), [])
        self.assertEqual(st.registry_ids(state), set())

    def test_entries_across_multiple_units(self):
        state = make_state(self.workspace, slices=[{"id": 1, "title": "t"}])
        skel = unit_in_status(state, st.U_FIXING)
        prevention = {"documented_in": "docs/skeleton.md",
                      "note": "added the rationale paragraph"}
        st.record_round(
            state, skel, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([
                rejected_finding(
                    "F1", resolution="the skeleton is correct",
                    prevention=prevention, severity="P2",
                    summary="claimed missing slice",
                ),
                fixed_finding("F2"),
            ]),
            meta={"source_round_id": "skeleton-claude-r1"},
        )
        skel["status"] = st.U_SEALED
        doc = st.ensure_next_unit(state)
        doc["status"] = st.U_FIXING
        st.record_round(
            state, doc, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([rejected_finding("F3", resolution="note is right")]),
            meta={"source_round_id": "slice_doc-01-claude-r1"},
        )
        entries = st.adjudicated_rejections(state)
        self.assertEqual(
            [e["id"] for e in entries],
            ["skeleton-claude-r1/F1", "slice_doc-01-claude-r1/F3"],
        )
        self.assertEqual(
            entries[0],
            {
                "id": "skeleton-claude-r1/F1",
                "unit": "skeleton",
                "severity": "P2",
                "summary": "claimed missing slice",
                "rationale": "the skeleton is correct",
                "prevention": prevention,
            },
        )
        self.assertEqual(entries[1]["unit"], "slice_doc-01")
        self.assertEqual(entries[1]["rationale"], "note is right")
        self.assertIsNone(entries[1]["prevention"])
        self.assertEqual(
            st.registry_ids(state),
            {"skeleton-claude-r1/F1", "slice_doc-01-claude-r1/F3"},
        )

    def test_source_round_id_falls_back_to_fix_round_id(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        # no meta at all: source_round_id key absent
        rec1 = st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([rejected_finding("V1")]),
        )
        # meta present but source_round_id is None (verification episodes
        # built by hand): the falsy value falls back too
        rec2 = st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([rejected_finding("V2")]),
            meta={"source_round_id": None},
        )
        ids = [e["id"] for e in st.adjudicated_rejections(state)]
        self.assertEqual(ids, ["%s/V1" % rec1["id"], "%s/V2" % rec2["id"]])
        self.assertEqual(rec1["id"], "skeleton-codex-r1")
        self.assertEqual(rec2["id"], "skeleton-codex-r2")

    def test_only_rejected_disposition_registers(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([
                fixed_finding("F1"),
                rejected_finding("F2"),
                blocked_finding("F4"),
            ]),
            meta={"source_round_id": "skeleton-claude-r1"},
        )
        self.assertEqual(
            st.registry_ids(state), {"skeleton-claude-r1/F2"}
        )
        # a duplicate killed by pointer registers nothing new
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([adjudicated_finding("F5", "skeleton-claude-r1/F2")]),
            meta={"source_round_id": "skeleton-claude-r2"},
        )
        self.assertEqual(
            st.registry_ids(state), {"skeleton-claude-r1/F2"}
        )

    def test_non_fix_rounds_never_register(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        unit["status"] = st.U_DELTA_REVIEW
        st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            dirty_review(contracts.KIND_DELTA_REVIEW),
        )
        self.assertEqual(st.adjudicated_rejections(state), [])

    def test_registry_survives_across_sealed_units(self):
        # The registry is derived from append-only rounds, so it still
        # reports entries of long-sealed units (milestone-global memory).
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([rejected_finding("F1")]),
            meta={"source_round_id": "skeleton-claude-r1"},
        )
        unit["status"] = st.U_SEALED
        self.assertEqual(st.registry_ids(state), {"skeleton-claude-r1/F1"})


# ---------------------------------------------------------------------------
# can_open_seal


class TestCanOpenSeal(TempWorkspaceCase):
    def _unit_in_rounds(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        return state, unit

    def test_false_with_no_rounds(self):
        state, unit = self._unit_in_rounds()
        self.assertFalse(st.can_open_seal(state, unit))

    def test_false_until_every_family_clean(self):
        state, unit = self._unit_in_rounds()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertFalse(st.can_open_seal(state, unit))  # claude missing
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertTrue(st.can_open_seal(state, unit))

    def test_latest_review_round_decides(self):
        state, unit = self._unit_in_rounds()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        # a later dirty codex review round reopens the gate
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        self.assertFalse(st.can_open_seal(state, unit))
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertTrue(st.can_open_seal(state, unit))

    def test_invalidated_rounds_are_ignored(self):
        state, unit = self._unit_in_rounds()
        tamper = {"invalidated": "reviewer modified the workspace"}
        # codex has ONLY an invalidated (discarded, empty-findings) round:
        # it must not count as the clean round the gate requires.
        st.record_round(
            state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review(),
            meta=tamper,
        )
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertFalse(st.can_open_seal(state, unit))
        # a dirty valid round followed by an invalidated one: the last
        # VALID round (dirty) decides, the invalidated round is skipped
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        st.record_round(
            state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review(),
            meta=tamper,
        )
        self.assertFalse(st.can_open_seal(state, unit))
        # only a genuine clean round opens the gate
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertTrue(st.can_open_seal(state, unit))

    def test_clean_non_review_kinds_cannot_substitute(self):
        state, unit = self._unit_in_rounds()
        # codex only has a clean fix round and a clean delta review; that
        # is not a clean REVIEW round, so the gate stays closed.
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
            meta={"source_round_id": "skeleton-claude-r1"},
        )
        st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            clean_review(contracts.KIND_DELTA_REVIEW),
        )
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertFalse(st.can_open_seal(state, unit))

    def test_dirty_non_review_kinds_cannot_reopen(self):
        state, unit = self._unit_in_rounds()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        # later fix/delta activity (e.g. a pre-seal verification episode)
        # does not disturb the recorded clean review rounds
        st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            dirty_review(contracts.KIND_DELTA_REVIEW),
        )
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
        )
        self.assertTrue(st.can_open_seal(state, unit))


# ---------------------------------------------------------------------------
# record_seal_attempt / close_slice / maybe_close_milestone / ensure_next_unit


class TestSealAndClosure(TempWorkspaceCase):
    def test_record_seal_attempt_only_in_sealing(self):
        for status in st.UNIT_STATUSES:
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            if status == st.U_SEALING:
                rec = st.record_seal_attempt(state, unit, make_halves(), True)
                self.assertEqual(rec["attempt"], 1)
                self.assertTrue(rec["passed"])
                self.assertIsNone(rec["invalidated"])
                self.assertEqual(state["events"][-1]["type"], "seal_attempt")
            else:
                with self.assertRaises(st.IllegalTransition, msg=status):
                    st.record_seal_attempt(state, unit, make_halves(), True)
                self.assertEqual(unit["seals"], [])

    def test_seal_attempts_number_and_record_invalidation(self):
        # An invalidated attempt (tampering half) stays in U_SEALING: the
        # workspace is restored and the next attempt just runs.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_SEALING)
        r1 = st.record_seal_attempt(
            state, unit, make_halves(claude=1), False, invalidated=None
        )
        r2 = st.record_seal_attempt(
            state, unit, make_halves(), False, invalidated="half modified workspace"
        )
        self.assertEqual(unit["status"], st.U_SEALING)
        r3 = st.record_seal_attempt(state, unit, make_halves(), True)
        self.assertEqual([r["attempt"] for r in unit["seals"]], [1, 2, 3])
        self.assertFalse(r1["passed"])
        self.assertEqual(r2["invalidated"], "half modified workspace")
        self.assertTrue(r3["passed"])

    def test_close_slice_guards(self):
        state = make_state(self.workspace, slices=[{"id": 1, "title": "t"}])
        state["units"][0]["status"] = st.U_SEALED
        doc = st.ensure_next_unit(state)
        doc["status"] = st.U_SEALED
        with self.assertRaises(st.IllegalTransition):
            st.close_slice(state, doc)  # sealed but wrong kind
        impl = st.ensure_next_unit(state)
        with self.assertRaises(st.IllegalTransition):
            st.close_slice(state, impl)  # right kind but not sealed
        impl["status"] = st.U_SEALED
        st.close_slice(state, impl)
        self.assertEqual(impl["closed_record"]["slice_id"], 1)
        self.assertEqual(impl["closed_record"]["rounds"], 0)
        self.assertEqual(impl["closed_record"]["seal_attempts"], 0)
        self.assertEqual(state["events"][-1]["type"], "slice_closed")

    def test_maybe_close_milestone_one_slice(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        self.assertFalse(st.maybe_close_milestone(state))  # doc/impl missing
        self.assertEqual(state["milestone"]["status"], st.M_OPEN)
        st.ensure_next_unit(state)
        seal_current_unit(state)  # doc-01
        self.assertFalse(st.maybe_close_milestone(state))
        st.ensure_next_unit(state)
        impl = seal_current_unit(state)  # impl-01
        st.close_slice(state, impl)
        self.assertIsNone(st.ensure_next_unit(state))
        self.assertTrue(st.maybe_close_milestone(state))
        self.assertEqual(state["milestone"]["status"], st.M_CLOSED)
        self.assertEqual(state["events"][-1]["type"], "milestone_closed")

    def test_maybe_close_milestone_is_idempotent(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        st.ensure_next_unit(state)
        seal_current_unit(state)
        st.ensure_next_unit(state)
        impl = seal_current_unit(state)
        st.close_slice(state, impl)
        self.assertTrue(st.maybe_close_milestone(state))
        events_after_close = len(state["events"])
        # Repeat calls report closed but never record a second event.
        self.assertTrue(st.maybe_close_milestone(state))
        self.assertTrue(st.maybe_close_milestone(state))
        self.assertEqual(len(state["events"]), events_after_close)
        self.assertEqual(
            [e["type"] for e in state["events"]].count("milestone_closed"), 1
        )

    def test_maybe_close_milestone_two_slices(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(2))
        sealed_units = 1
        while True:
            nxt = st.ensure_next_unit(state)
            if nxt is None:
                break
            self.assertFalse(st.maybe_close_milestone(state))
            unit = seal_current_unit(state)
            sealed_units += 1
            if unit["kind"] == st.UNIT_SLICE_IMPL:
                st.close_slice(state, unit)
        self.assertEqual(sealed_units, 5)  # skeleton + 2*(doc+impl)
        self.assertTrue(st.maybe_close_milestone(state))
        self.assertEqual(state["milestone"]["status"], st.M_CLOSED)

    def test_ensure_next_unit_ordering(self):
        state = make_state(
            self.workspace,
            slices=[{"id": 1, "title": "one"}, {"id": 2, "title": "two"}],
        )
        opened = []
        while True:
            unit = st.ensure_next_unit(state)
            if unit is None:
                break
            self.assertEqual(unit["status"], st.U_PENDING)
            self.assertEqual(state["events"][-1]["type"], "unit_opened")
            opened.append(st.unit_key(unit))
        self.assertEqual(
            opened,
            ["slice_doc-01", "slice_impl-01", "slice_doc-02", "slice_impl-02"],
        )
        self.assertEqual(
            [(u["kind"], u["slice_id"]) for u in state["units"]],
            [
                (st.UNIT_SKELETON, None),
                (st.UNIT_SLICE_DOC, 1),
                (st.UNIT_SLICE_IMPL, 1),
                (st.UNIT_SLICE_DOC, 2),
                (st.UNIT_SLICE_IMPL, 2),
            ],
        )
        self.assertEqual(
            st.planned_units(state),
            [(u["kind"], u["slice_id"]) for u in state["units"]],
        )


# ---------------------------------------------------------------------------
# fail_run


class TestFailRun(TempWorkspaceCase):
    def test_failure_recorded_unit_and_milestone_failed(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        st.fail_run(state, "round cap reached", unit=unit)
        self.assertEqual(state["failure"]["reason"], "round cap reached")
        self.assertEqual(state["failure"]["unit"], "skeleton")
        self.assertIn("at", state["failure"])
        self.assertEqual(unit["status"], st.U_FAILED)
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)
        evt = state["events"][-1]
        self.assertEqual(evt["type"], "run_failed")
        self.assertEqual(evt["reason"], "round cap reached")
        self.assertEqual(evt["unit"], "skeleton")

    def test_fail_run_without_unit(self):
        state = make_state(self.workspace)
        st.fail_run(state, "config broken")
        self.assertIsNone(state["failure"]["unit"])
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)
        # unit untouched
        self.assertEqual(state["units"][0]["status"], st.U_PENDING)

    def test_fail_run_does_not_unseal_a_sealed_unit(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_SEALED)
        st.fail_run(state, "later failure", unit=unit)
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertEqual(state["milestone"]["status"], st.M_FAILED)

    def test_fail_run_from_fix_statuses(self):
        for status in (st.U_FIXING, st.U_DELTA_REVIEW):
            state = make_state(self.workspace)
            unit = unit_in_status(state, status)
            st.fail_run(state, "fix loop cap", unit=unit)
            self.assertEqual(unit["status"], st.U_FAILED, msg=status)


# ---------------------------------------------------------------------------
# Append-only persistence + terminal-unit freeze


class TestAppendOnly(TempWorkspaceCase):
    def setUp(self):
        super(TestAppendOnly, self).setUp()
        self.path = os.path.join(self.workspace, ".orchestrator", "state.json")
        self.state = self._build_rich_state()
        st.save(self.path, self.state)
        with open(self.path, "r", encoding="utf-8") as fh:
            self.disk_before = fh.read()

    def _build_rich_state(self):
        state = make_state(self.workspace)
        st.append_event(state, "initialized", goal="Build X")
        seal_current_unit(state, skeleton_draft(1))  # sealed skeleton w/ rounds+seal
        doc = st.ensure_next_unit(state)
        st.record_draft(state, doc, contracts.KIND_DRAFT_SLICE_NOTE, default_draft_for(doc))
        st.transition_unit(state, doc, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, doc, st.U_ROUNDS)
        st.record_round(state, doc, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        return state

    def _assert_rejected_and_disk_unchanged(self, bad):
        with self.assertRaises(st.HistoryRewriteError):
            st.save(self.path, bad)
        with open(self.path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.disk_before)

    def test_mutating_past_event_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["events"][0]["type"] = "rewritten"
        self._assert_rejected_and_disk_unchanged(bad)

    def test_mutating_round_record_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"][1]["rounds"][0]["result"]["findings"] = []
        self._assert_rejected_and_disk_unchanged(bad)

    def test_mutating_seal_record_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"][0]["seals"][0]["passed"] = False
        self._assert_rejected_and_disk_unchanged(bad)

    def test_shrinking_events_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["events"].pop()
        self._assert_rejected_and_disk_unchanged(bad)

    def test_shrinking_rounds_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"][1]["rounds"] = []
        self._assert_rejected_and_disk_unchanged(bad)

    def test_shrinking_units_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"].pop()
        self._assert_rejected_and_disk_unchanged(bad)

    def test_unit_identity_change_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"][1]["slice_id"] = 2
        self._assert_rejected_and_disk_unchanged(bad)

    def test_altering_sealed_unit_fields_rejected(self):
        for field, value in (
            ("artifact", "docs/other.md"),
            ("family_index", 0),
            ("fix_queue", [{"id": "F9", "severity": "P1", "summary": "x"}]),
            ("fix_source", {"type": "round", "family": "codex",
                            "source_round_id": "skeleton-codex-r1",
                            "return_to": st.U_ROUNDS}),
            ("fix_loop_rounds", 5),
        ):
            bad = copy.deepcopy(self.state)
            bad["units"][0][field] = value
            self._assert_rejected_and_disk_unchanged(bad)

    def test_appending_rounds_to_sealed_unit_rejected(self):
        bad = copy.deepcopy(self.state)
        bad["units"][0]["rounds"].append(
            {"id": "skeleton-codex-r3", "family": "codex",
             "kind": "review_round", "at": "x", "duration_s": None,
             "raw_path": None, "result": clean_review()}
        )
        self._assert_rejected_and_disk_unchanged(bad)

    def test_failed_unit_is_resumable_not_frozen(self):
        """Failed units are deliberately NOT frozen: resume_run (an explicit
        operator action) restores them. Their history lists stay
        append-only regardless."""
        path = os.path.join(self.workspace, ".orchestrator", "state-resume.json")
        state = make_state(self.workspace)
        unit = state["units"][0]
        st.fail_run(state, "transient CLI failure", unit=unit)
        st.save(path, state)
        self.assertEqual(unit["status"], st.U_FAILED)
        self.assertEqual(unit["failed_from"], st.U_PENDING)
        restored = st.resume_run(state)
        self.assertEqual(restored, {"skeleton": st.U_PENDING})
        self.assertIsNone(state["failure"])
        self.assertEqual(state["milestone"]["status"], st.M_OPEN)
        self.assertEqual(state["events"][-1]["type"], "resumed")
        st.save(path, state)  # no HistoryRewriteError
        # nothing to resume twice
        with self.assertRaises(ValueError):
            st.resume_run(state)

    def test_appending_history_is_fine(self):
        st.append_event(self.state, "verification", unit="slice_doc-01", ok=True)
        doc = self.state["units"][1]
        st.record_round(
            self.state, doc, "codex", contracts.KIND_REVIEW_ROUND, clean_review()
        )
        st.save(self.path, self.state)  # must not raise
        reloaded = st.load(self.path)
        self.assertEqual(len(reloaded["units"][1]["rounds"]), 2)
        self.assertEqual(reloaded["events"][-2]["type"], "verification")

    def test_normal_working_mutations_are_fine(self):
        doc = self.state["units"][1]
        res = clean_review()
        st.record_round(self.state, doc, "codex", contracts.KIND_REVIEW_ROUND, res)
        st.advance_family_if_clean(self.state, doc, res)  # family_index moves
        st.save(self.path, self.state)  # non-terminal unit fields may change
        self.assertEqual(st.load(self.path)["units"][1]["family_index"], 1)

    def test_fix_episode_bookkeeping_on_live_unit_is_fine(self):
        # fix_queue/fix_source/fix_loop_rounds are working fields on a
        # non-terminal unit: entering an episode after a save must persist.
        doc = self.state["units"][1]
        rec_id = doc["rounds"][0]["id"]
        st.enter_fix_episode(
            self.state, doc,
            [queued(f) for f in doc["rounds"][0]["result"]["findings"]],
            "round", "codex", rec_id, st.U_ROUNDS,
        )
        st.save(self.path, self.state)  # must not raise
        reloaded = st.load(self.path)
        self.assertEqual(reloaded["units"][1]["status"], st.U_FIXING)
        self.assertEqual(
            reloaded["units"][1]["fix_source"]["source_round_id"], rec_id
        )

    def test_closed_record_on_sealed_slice_impl_is_the_allowed_exception(self):
        # Build a fully sealed impl unit, save, then close_slice afterwards.
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        st.ensure_next_unit(state)
        seal_current_unit(state)  # doc-01
        st.ensure_next_unit(state)
        impl = seal_current_unit(state)  # impl-01, sealed, not yet closed
        path = os.path.join(self.workspace, "impl-state.json")
        st.save(path, state)
        st.close_slice(state, impl)  # mutates a sealed unit's closed_record
        st.save(path, state)  # must not raise
        reloaded = st.load(path)
        self.assertEqual(reloaded["units"][2]["closed_record"]["slice_id"], 1)

    def test_gate_commit_on_sealed_unit_is_the_allowed_exception(self):
        # The driver writes gate_commit right after the terminal transition
        # (state was already saved as sealed by the seal step).
        self.state["units"][0]["gate_commit"] = "abc1234"
        st.append_event(
            self.state, "gate_commit", unit="skeleton", sha="abc1234",
            message="Seal milestone skeleton",
        )
        st.save(self.path, self.state)  # must not raise
        reloaded = st.load(self.path)
        self.assertEqual(reloaded["units"][0]["gate_commit"], "abc1234")


# ---------------------------------------------------------------------------
# save_new() exclusive creation


class TestSaveNew(TempWorkspaceCase):
    def test_creates_then_refuses_overwrite(self):
        path = os.path.join(self.workspace, ".orchestrator", "state.json")
        state = make_state(self.workspace)
        st.save_new(path, state)
        self.assertEqual(st.load(path), state)
        other = make_state(self.workspace)
        other["goal"] = "Different goal"
        with self.assertRaises(FileExistsError):
            st.save_new(path, other)
        # original untouched, no temp leftovers
        self.assertEqual(st.load(path)["goal"], "Build X")
        leftovers = [
            n for n in os.listdir(os.path.dirname(path))
            if n.startswith(".state-")
        ]
        self.assertEqual(leftovers, [])


# ---------------------------------------------------------------------------
# save() atomicity + schema version gate


class TestSaveAtomicity(TempWorkspaceCase):
    def setUp(self):
        super(TestSaveAtomicity, self).setUp()
        self.path = os.path.join(self.workspace, "state.json")

    def _tmp_leftovers(self):
        return [
            name
            for name in os.listdir(os.path.dirname(self.path) or ".")
            if name.startswith(".state-")
        ]

    def test_disk_file_is_valid_json_and_no_temp_leftovers(self):
        state = make_state(self.workspace)
        st.save(self.path, state)
        with open(self.path, "r", encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), state)
        self.assertEqual(self._tmp_leftovers(), [])

    def test_save_writes_via_rename_in_same_directory(self):
        state = make_state(self.workspace)
        real_replace = os.replace
        calls = []

        def spy(src, dst):
            calls.append((src, dst))
            return real_replace(src, dst)

        with mock.patch("orchestrator.state.os.replace", side_effect=spy):
            st.save(self.path, state)
        self.assertEqual(len(calls), 1)
        src, dst = calls[0]
        self.assertEqual(dst, self.path)
        self.assertEqual(os.path.dirname(src), os.path.dirname(os.path.abspath(self.path)))
        self.assertTrue(os.path.basename(src).startswith(".state-"))

    def test_failed_serialization_leaves_previous_state_intact(self):
        state = make_state(self.workspace)
        st.append_event(state, "initialized")
        st.save(self.path, state)
        with open(self.path, "r", encoding="utf-8") as fh:
            before = fh.read()
        # Appended event passes the append-only check but cannot be
        # serialized; the write must fail without corrupting the file.
        state["events"].append(
            {"seq": 1, "at": "now", "type": "bad", "payload": {1, 2}}
        )
        with self.assertRaises(TypeError):
            st.save(self.path, state)
        with open(self.path, "r", encoding="utf-8") as fh:
            after = fh.read()
        self.assertEqual(after, before)
        json.loads(after)  # still valid JSON
        self.assertEqual(self._tmp_leftovers(), [])

    def test_rejected_rewrite_leaves_disk_untouched(self):
        state = make_state(self.workspace)
        st.append_event(state, "initialized")
        st.save(self.path, state)
        with open(self.path, "r", encoding="utf-8") as fh:
            before = fh.read()
        bad = copy.deepcopy(state)
        bad["events"][0]["type"] = "rewritten"
        with self.assertRaises(st.HistoryRewriteError):
            st.save(self.path, bad)
        with open(self.path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(self._tmp_leftovers(), [])

    def test_load_rejects_wrong_schema_versions(self):
        # v1 (pre-redesign) states and anything else non-v2 are refused:
        # there is no migration path; the operator starts a fresh run.
        for version in (0, 1, 3, "2", None):
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump({"schema_version": version}, fh)
            with self.assertRaises(RuntimeError, msg=repr(version)):
                st.load(self.path)

    def test_load_rejects_v1_shaped_state(self):
        # A realistic schema-v1 file (old statuses, old unit fields) must
        # be rejected outright by the version gate.
        v1_state = {
            "schema_version": 1,
            "goal": "Build X",
            "workspace": self.workspace,
            "milestone": {"status": "open", "slices": []},
            "units": [
                {
                    "kind": "skeleton",
                    "slice_id": None,
                    "status": "micro_review",
                    "return_to": "rounds",
                    "micro_rounds_in_loop": 1,
                }
            ],
            "events": [],
            "failure": None,
            "config": make_config(),
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(v1_state, fh)
        with self.assertRaises(RuntimeError):
            st.load(self.path)


# ---------------------------------------------------------------------------
# summary()


class TestSummary(TempWorkspaceCase):
    def test_shape_with_units_rounds_seals_and_failure(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        doc = st.ensure_next_unit(state)
        st.record_draft(state, doc, contracts.KIND_DRAFT_SLICE_NOTE, default_draft_for(doc))
        st.transition_unit(state, doc, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, doc, st.U_ROUNDS)
        st.record_round(state, doc, "codex", contracts.KIND_REVIEW_ROUND, dirty_review(n=2))
        st.fail_run(state, "round cap", unit=doc)

        summ = st.summary(state)
        self.assertEqual(
            set(summ.keys()),
            {
                "goal",
                "workspace",
                "milestone_status",
                "slices",
                "current_unit",
                "current_unit_status",
                "current_family",
                "current_model",
                "created_epoch",
                "last_event_epoch",
                "suite_command",
                "name",
                "docs_dir",
                "failure",
                "units",
                "events_total",
                "last_events",
                "malformed",
                "acts_config",
                "model_defaults",
            },
        )
        self.assertEqual(summ["goal"], "Build X")
        self.assertEqual(summ["workspace"], self.workspace)
        self.assertEqual(summ["milestone_status"], st.M_FAILED)
        self.assertEqual(summ["slices"], [{"id": 1, "title": "slice 1"}])
        self.assertEqual(summ["current_unit"], "slice_doc-01")
        self.assertEqual(summ["current_unit_status"], st.U_FAILED)
        self.assertEqual(summ["failure"]["reason"], "round cap")
        self.assertEqual(summ["events_total"], len(state["events"]))
        self.assertLessEqual(len(summ["last_events"]), 30)
        self.assertEqual(summ["last_events"], state["events"][-30:])

        self.assertEqual(len(summ["units"]), 2)
        skel_view, doc_view = summ["units"]
        self.assertEqual(
            set(skel_view.keys()),
            {"unit", "status", "artifact", "gate_sha", "wip_sha", "draft",
             "rounds", "seals", "opened_epoch", "closed_epoch", "debt",
             "reclassify"},
        )
        # The draft chip data: write-once record surfaced for the panel.
        self.assertEqual(
            set(skel_view["draft"].keys()),
            {"kind", "family", "model", "effort", "duration_s", "at"},
        )
        self.assertEqual(skel_view["unit"], "skeleton")
        self.assertEqual(skel_view["status"], st.U_SEALED)
        self.assertEqual(skel_view["artifact"], "docs/skeleton.md")
        # rounds view: one clean round per family
        self.assertEqual(len(skel_view["rounds"]), 2)
        for r in skel_view["rounds"]:
            self.assertEqual(
                set(r.keys()),
                {"id", "family", "kind", "findings", "severity",
                 "invalidated", "model", "effort", "duration_s", "at"},
            )
            self.assertEqual(r["findings"], 0)
        # seals view: one passed attempt with per-family finding counts
        self.assertEqual(len(skel_view["seals"]), 1)
        seal = skel_view["seals"][0]
        self.assertEqual(
            set(seal.keys()),
            {"attempt", "passed", "invalidated", "findings", "duration_s",
             "severity", "at"},
        )
        self.assertEqual(seal["attempt"], 1)
        self.assertTrue(seal["passed"])
        self.assertIsNone(seal["invalidated"])
        self.assertEqual(seal["findings"], {"codex": 0, "claude": 0})
        # doc view carries the dirty round's finding count
        self.assertEqual(doc_view["rounds"][0]["findings"], 2)
        self.assertEqual(doc_view["seals"], [])

    def test_summary_surfaces_effective_models_for_chips(self):
        state = make_state(self.workspace)
        state["config"]["model_defaults"] = {
            "codex": {"model": "gpt-5.6-sol", "effort": "high"},
            "claude": {"model": "claude-fable-5", "effort": "medium"},
        }
        state["config"]["acts"] = {
            "review_codex": {"model": "gpt-5.6-terra"},
        }
        unit = state["units"][0]
        st.record_draft(
            state, unit, contracts.KIND_DRAFT_SKELETON,
            skeleton_draft(1), family="claude",
        )
        st.transition_unit(state, unit, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, unit, st.U_ROUNDS)
        st.record_round(
            state, unit, "codex", contracts.KIND_REVIEW_ROUND,
            clean_review(), meta={"model": "gpt-exact"},
        )

        summ = st.summary(state)
        view = summ["units"][0]
        self.assertEqual(view["draft"]["model"], "claude-fable-5")
        self.assertEqual(view["draft"]["effort"], "medium")
        self.assertEqual(view["rounds"][0]["model"], "gpt-exact")
        self.assertEqual(view["rounds"][0]["effort"], "high")
        self.assertEqual(summ["current_model"], "gpt-5.6-terra")

    def test_summary_includes_fix_and_delta_rounds(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        rec = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        st.enter_fix_episode(
            state, unit, [queued(f) for f in rec["result"]["findings"]],
            "round", "codex", rec["id"], st.U_ROUNDS,
        )
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_FINDINGS,
            fix_result([fixed_finding("F1")]),
            meta={"source_round_id": rec["id"]},
        )
        st.transition_unit(state, unit, st.U_DELTA_REVIEW)
        st.record_round(
            state, unit, "codex", contracts.KIND_DELTA_REVIEW,
            clean_review(contracts.KIND_DELTA_REVIEW),
        )
        summ = st.summary(state)
        self.assertEqual(
            [r["kind"] for r in summ["units"][0]["rounds"]],
            [contracts.KIND_REVIEW_ROUND, contracts.KIND_FIX_FINDINGS,
             contracts.KIND_DELTA_REVIEW],
        )
        self.assertEqual(
            [r["findings"] for r in summ["units"][0]["rounds"]], [1, 1, 0]
        )

    def test_summary_carries_gate_sha(self):
        # The panel links each sealed unit to its gate commit on git web;
        # unsealed units have no sha yet.
        state = make_state(self.workspace)
        summ = st.summary(state)
        self.assertIsNone(summ["units"][0]["gate_sha"])
        state["units"][0]["gate_commit"] = "abc1234"
        summ = st.summary(state)
        self.assertEqual(summ["units"][0]["gate_sha"], "abc1234")

    def test_summary_carries_wip_sha_until_sealed(self):
        # A unit in flight surfaces its LATEST working commit (amends
        # replace it); the gate commit supersedes it once sealed.
        state = make_state(self.workspace)
        uk = st.unit_key(state["units"][0])
        st.append_event(state, "wip_commit", unit=uk, sha="aaa1111")
        summ = st.summary(state)
        self.assertEqual(summ["units"][0]["wip_sha"], "aaa1111")
        st.append_event(state, "amended", unit=uk, sha="bbb2222")
        summ = st.summary(state)
        self.assertEqual(summ["units"][0]["wip_sha"], "bbb2222")
        state["units"][0]["gate_commit"] = "abc1234"
        summ = st.summary(state)
        self.assertIsNone(summ["units"][0]["wip_sha"])
        self.assertEqual(summ["units"][0]["gate_sha"], "abc1234")

    def test_summary_of_closed_milestone(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        while True:
            if st.ensure_next_unit(state) is None:
                break
            unit = seal_current_unit(state)
            if unit["kind"] == st.UNIT_SLICE_IMPL:
                st.close_slice(state, unit)
        st.maybe_close_milestone(state)
        summ = st.summary(state)
        self.assertEqual(summ["milestone_status"], st.M_CLOSED)
        self.assertIsNone(summ["current_unit"])
        self.assertIsNone(summ["current_unit_status"])
        self.assertIsNone(summ["failure"])
        self.assertEqual(
            [u["unit"] for u in summ["units"]],
            ["skeleton", "slice_doc-01", "slice_impl-01"],
        )

    def test_summary_handles_seal_half_without_result(self):
        # An invalidated half may carry result=None; summary must not crash.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_SEALING)
        halves = make_halves()
        halves["claude"]["result"] = None
        halves["claude"]["workspace_modified"] = True
        st.record_seal_attempt(
            state, unit, halves, False, invalidated="claude half modified workspace"
        )
        summ = st.summary(state)
        seal = summ["units"][0]["seals"][0]
        self.assertEqual(seal["findings"], {"codex": 0, "claude": None})
        self.assertEqual(seal["invalidated"], "claude half modified workspace")


class TestTypedResume(TempWorkspaceCase):
    def test_phantom_fix_resume_restores_to_fixing(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_DELTA_REVIEW)
        st.fail_run(state, "phantom twice", unit=unit, type_="phantom_fix")
        self.assertEqual(unit["status"], st.U_FAILED)
        restored = st.resume_run(state)
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertEqual(list(restored.values()), [st.U_FIXING])

    def test_resume_grants_a_fresh_fix_budget(self):
        # A convergence failure (fix_loop_rounds exhausted) must be
        # RECOVERABLE: resume resets the counter so it does not re-fail
        # instantly. Otherwise "did not converge" is a dead end and the
        # guard's emergency resume would spin uselessly.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_FIXING)
        unit["fix_loop_rounds"] = 6
        unit["verify_fix_attempts"] = {"pre_review": 4, "pre_seal": 0}
        st.fail_run(state, "did not converge after 6 loops", unit=unit)
        st.resume_run(state)
        self.assertEqual(unit["status"], st.U_FIXING)
        self.assertEqual(unit["fix_loop_rounds"], 0)
        self.assertEqual(unit["verify_fix_attempts"],
                         {"pre_review": 0, "pre_seal": 0})

    def test_resume_grants_a_fresh_review_round_budget(self):
        # The max_rounds_per_family cap counts immutable rounds history, so
        # without an amnesty marker a run failed on it would re-fail
        # instantly on every resume (the guard's emergency resume included).
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        for _ in range(12):
            unit["rounds"].append(
                {"family": "codex", "kind": "review_round", "result": {}}
            )
        st.fail_run(
            state, "family codex reached max_rounds_per_family=12", unit=unit
        )
        st.resume_run(state)
        self.assertEqual(unit["status"], st.U_ROUNDS)
        self.assertEqual(unit["rounds_amnesty"], 12)
        post = [
            r
            for r in unit["rounds"][unit["rounds_amnesty"]:]
            if r["family"] == "codex" and r["kind"] == "review_round"
        ]
        self.assertEqual(post, [])  # the cap's view is empty again

    def test_resume_grants_a_fresh_seal_attempt_budget(self):
        # Same dead-end as the review-round cap: seals are immutable
        # history, so the max_seal_attempts cap needs the amnesty marker.
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_SEALING)
        unit["seals"] = [{"attempt": i + 1} for i in range(8)]
        st.fail_run(state, "max_seal_attempts=8 reached", unit=unit)
        st.resume_run(state)
        self.assertEqual(unit["seals_amnesty"], 8)
        # The cap's view (records after the marker) is empty again, while
        # attempt numbering keeps counting the full history.
        self.assertEqual(len(unit["seals"]) - unit["seals_amnesty"], 0)

    def test_quota_failure_records_type_and_resume_at(self):
        state = make_state(self.workspace)
        st.fail_run(state, "usage limit", type_="quota",
                    resume_at="2026-07-06T00:37:00+0200")
        self.assertEqual(state["failure"]["type"], "quota")
        self.assertEqual(state["failure"]["resume_at"],
                         "2026-07-06T00:37:00+0200")
        ev = [e for e in state["events"] if e["type"] == "run_failed"][-1]
        self.assertEqual(ev["failure_type"], "quota")


class TestReopenForRepair(TempWorkspaceCase):
    """Reopening a SEALED unit for an upstream repair (reform §3): the one
    deliberate exit from the otherwise-terminal sealed state."""

    def _sealed(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        return state, state["units"][0]

    def test_reopen_transitions_and_grants_fresh_budgets(self):
        state, unit = self._sealed()
        self.assertEqual(unit["status"], st.U_SEALED)
        n_rounds, n_seals = len(unit["rounds"]), len(unit["seals"])
        gap = {"target": "goal", "forced_decision": "carry the field",
               "plain": "the plan uses a field the pipes drop"}
        st.reopen_for_repair(state, unit, gap, "downstream gap",
                             reported_by="slice_doc-01")
        self.assertEqual(unit["status"], st.U_REPAIRING)
        self.assertEqual(unit["rounds_amnesty"], n_rounds)
        self.assertEqual(unit["seals_amnesty"], n_seals)
        self.assertEqual(unit["fix_loop_rounds"], 0)
        ev = [e for e in state["events"] if e["type"] == "reopened_for_repair"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["reported_by"], "slice_doc-01")
        self.assertEqual(ev[0]["target"], "goal")

    def test_reopen_requires_a_sealed_unit(self):
        state = make_state(self.workspace)
        with self.assertRaises(st.IllegalTransition):
            st.reopen_for_repair(state, st.current_unit(state),
                                 {"target": "goal"}, "x")

    def test_repair_enters_a_fix_episode_and_reseals(self):
        state, unit = self._sealed()
        st.reopen_for_repair(state, unit, {"target": "goal"}, "gap")
        st.enter_fix_episode(
            state, unit,
            [{"id": "G1", "severity": "P1", "summary": "resolve the gap"}],
            "repair", None, "skeleton-gap", st.U_PRE_SEAL_VERIFY)
        self.assertEqual(unit["status"], st.U_FIXING)  # repairing -> fixing
        st.transition_unit(state, unit, st.U_DELTA_REVIEW)
        st.transition_unit(state, unit, unit["fix_source"]["return_to"])
        self.assertEqual(unit["status"], st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, unit, st.U_SEALING)
        st.record_seal_attempt(state, unit, make_halves(), True)
        st.transition_unit(state, unit, st.U_SEALED)  # resealed
        self.assertEqual(unit["status"], st.U_SEALED)

    def test_append_only_permits_the_reopen(self):
        state, unit = self._sealed()
        path = os.path.join(self.workspace, "reopen.json")
        st.save_new(path, state)
        st.reopen_for_repair(state, unit, {"target": "goal"}, "gap")
        st.save(path, state)  # must NOT raise HistoryRewriteError
        self.assertEqual(st.load(path)["units"][0]["status"], st.U_REPAIRING)

    def test_append_only_still_freezes_a_unit_that_stays_sealed(self):
        state, unit = self._sealed()
        path = os.path.join(self.workspace, "frozen.json")
        st.save_new(path, state)
        unit["artifact"] = "tampered.md"  # modified while STAYING sealed
        with self.assertRaises(st.HistoryRewriteError):
            st.save(path, state)


if __name__ == "__main__":
    unittest.main()
