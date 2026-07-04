"""Exhaustive tests for orchestrator/state.py: the append-only state machine.

Covers: new_state shape, the full unit lifecycle for every unit kind, the
complete legal/illegal transition table, write-once drafts, round-recording
guards, family ordering, the seal gate, seal attempts, slice and milestone
closure, run failure, append-only persistence, atomic rename-based saves,
and the summary() shape.

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
    obj = {"status": "ok", "kind": kind, "findings": [], "files_changed": []}
    contracts.validate_worker_output(obj, kind)
    return obj


def dirty_review(kind=contracts.KIND_REVIEW_ROUND, n=1):
    findings = [
        {
            "id": "F%d" % (i + 1),
            "severity": "P1",
            "summary": "issue %d" % (i + 1),
            "disposition": "fixed",
            "consultation": None,
        }
        for i in range(n)
    ]
    obj = {
        "status": "ok",
        "kind": kind,
        "findings": findings,
        "files_changed": ["src/f.py"],
    }
    contracts.validate_worker_output(obj, kind)
    return obj


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

    def test_initial_unit_is_pending_skeleton(self):
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
                "return_to": None,
                "closed_record": None,
            },
        )
        self.assertEqual(st.unit_key(unit), "skeleton")

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

    def test_slice_doc_lifecycle_with_verify_fix_detour(self):
        state = make_state(self.workspace)
        seal_current_unit(state, skeleton_draft(1))
        doc = st.ensure_next_unit(state)
        self.assertEqual(doc["kind"], st.UNIT_SLICE_DOC)
        st.record_draft(state, doc, contracts.KIND_DRAFT_SLICE_NOTE, default_draft_for(doc))
        st.transition_unit(state, doc, st.U_PRE_REVIEW_VERIFY)
        # verification fails -> verify_fix -> fix round -> back to pre-review
        st.transition_unit(state, doc, st.U_VERIFY_FIX)
        st.record_round(
            state, doc, "codex", contracts.KIND_FIX_VERIFICATION,
            dirty_review(contracts.KIND_FIX_VERIFICATION),
        )
        st.transition_unit(state, doc, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(state, doc, st.U_ROUNDS)
        run_reviews_clean(state, doc)
        # pre-seal verification can also fail into verify_fix and return
        st.transition_unit(state, doc, st.U_VERIFY_FIX)
        st.record_round(
            state, doc, "codex", contracts.KIND_FIX_VERIFICATION,
            clean_review(contracts.KIND_FIX_VERIFICATION),
        )
        st.transition_unit(state, doc, st.U_PRE_SEAL_VERIFY)
        st.transition_unit(state, doc, st.U_SEALING)
        st.record_seal_attempt(state, doc, make_halves(), True)
        st.transition_unit(state, doc, st.U_SEALED)
        self.assertEqual(doc["status"], st.U_SEALED)

    def test_slice_impl_lifecycle_with_seal_fix_loop(self):
        # Mirrors the demo baseline: seal attempt 1 fails -> seal_fix ->
        # attempt 2 passes on the impl unit.
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
        # attempt 1: claude half finds a problem
        rec1 = st.record_seal_attempt(state, impl, make_halves(claude=1), False)
        self.assertEqual(rec1["attempt"], 1)
        st.transition_unit(state, impl, st.U_SEAL_FIX)
        st.record_round(
            state, impl, "codex", contracts.KIND_SEAL_FIX,
            dirty_review(contracts.KIND_SEAL_FIX),
        )
        st.transition_unit(state, impl, st.U_PRE_SEAL_VERIFY)
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
    st.U_PENDING: {st.U_PRE_REVIEW_VERIFY, st.U_FAILED},
    st.U_PRE_REVIEW_VERIFY: {st.U_ROUNDS, st.U_VERIFY_FIX, st.U_FAILED},
    st.U_VERIFY_FIX: {st.U_PRE_REVIEW_VERIFY, st.U_PRE_SEAL_VERIFY, st.U_FAILED},
    st.U_ROUNDS: {st.U_ROUNDS, st.U_PRE_SEAL_VERIFY, st.U_FAILED},
    st.U_PRE_SEAL_VERIFY: {st.U_SEALING, st.U_VERIFY_FIX, st.U_FAILED},
    # U_SEALING -> U_PRE_SEAL_VERIFY: invalidated seal attempts re-verify
    # the modified workspace before the next attempt.
    st.U_SEALING: {st.U_SEALED, st.U_SEAL_FIX, st.U_PRE_SEAL_VERIFY, st.U_FAILED},
    st.U_SEAL_FIX: {st.U_PRE_SEAL_VERIFY, st.U_FAILED},
    st.U_SEALED: set(),
    st.U_FAILED: set(),
}


class TestTransitionTable(TempWorkspaceCase):
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
            (st.U_PENDING, st.U_SEALING),
            (st.U_PENDING, st.U_ROUNDS),
            (st.U_SEALED, st.U_ROUNDS),
            (st.U_SEALED, st.U_PENDING),
            (st.U_SEALED, st.U_FAILED),
            (st.U_FAILED, st.U_PENDING),
            (st.U_ROUNDS, st.U_VERIFY_FIX),
            (st.U_ROUNDS, st.U_SEALING),
            (st.U_VERIFY_FIX, st.U_ROUNDS),
            (st.U_SEAL_FIX, st.U_SEALING),
            (st.U_SEALING, st.U_ROUNDS),
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
    ALLOWED = {st.U_ROUNDS, st.U_VERIFY_FIX, st.U_SEAL_FIX}

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

    def test_round_ids_number_per_family(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        r1 = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        r2 = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        r3 = st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertEqual([r1["id"], r2["id"], r3["id"]],
                         ["skeleton-codex-r1", "skeleton-codex-r2", "skeleton-claude-r1"])
        self.assertEqual(st.family_rounds(unit, "codex"), [r1, r2])
        self.assertEqual(st.family_rounds(unit, "claude"), [r3])

    def test_result_is_deep_copied(self):
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_ROUNDS)
        res = dirty_review()
        rec = st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, res)
        res["findings"].append({"id": "F2", "severity": "P0", "summary": "later edit"})
        self.assertEqual(len(rec["result"]["findings"]), 1)


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

    def test_fix_verification_rounds_do_not_count(self):
        state, unit = self._unit_in_rounds()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, clean_review())
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        # a dirty fix_verification after the clean reviews must not close the gate
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_VERIFICATION,
            dirty_review(contracts.KIND_FIX_VERIFICATION),
        )
        self.assertTrue(st.can_open_seal(state, unit))

    def test_clean_fix_verification_cannot_substitute_for_review(self):
        state, unit = self._unit_in_rounds()
        st.record_round(
            state, unit, "codex", contracts.KIND_FIX_VERIFICATION,
            clean_review(contracts.KIND_FIX_VERIFICATION),
        )
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertFalse(st.can_open_seal(state, unit))

    def test_clean_seal_fix_cannot_mask_dirty_review(self):
        state, unit = self._unit_in_rounds()
        st.record_round(state, unit, "codex", contracts.KIND_REVIEW_ROUND, dirty_review())
        st.record_round(
            state, unit, "codex", contracts.KIND_SEAL_FIX,
            clean_review(contracts.KIND_SEAL_FIX),
        )
        st.record_round(state, unit, "claude", contracts.KIND_REVIEW_ROUND, clean_review())
        self.assertFalse(st.can_open_seal(state, unit))


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
        state = make_state(self.workspace)
        unit = unit_in_status(state, st.U_SEALING)
        r1 = st.record_seal_attempt(
            state, unit, make_halves(claude=1), False, invalidated=None
        )
        r2 = st.record_seal_attempt(
            state, unit, make_halves(), False, invalidated="half modified workspace"
        )
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


# ---------------------------------------------------------------------------
# Append-only persistence


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
        for field, value in (("artifact", "docs/other.md"), ("family_index", 0)):
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


# ---------------------------------------------------------------------------
# save() atomicity


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

    def test_load_rejects_wrong_schema_version(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": 0}, fh)
        with self.assertRaises(RuntimeError):
            st.load(self.path)

    def test_load_migrates_legacy_int_verify_fix_counter(self):
        state = make_state(self.workspace)
        st.save(self.path, state)
        # Simulate a pre-per-stage state file (plain int counter).
        with open(self.path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        raw["units"][0]["verify_fix_attempts"] = 3
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(raw, fh)
        loaded = st.load(self.path)
        self.assertEqual(
            loaded["units"][0]["verify_fix_attempts"],
            {"pre_review": 3, "pre_seal": 0},
        )
        # Saving the migrated state back must pass the append-only check
        # (load() normalizes the on-disk side too).
        st.save(self.path, loaded)


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
                "failure",
                "units",
                "events_total",
                "last_events",
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
            set(skel_view.keys()), {"unit", "status", "artifact", "rounds", "seals"}
        )
        self.assertEqual(skel_view["unit"], "skeleton")
        self.assertEqual(skel_view["status"], st.U_SEALED)
        self.assertEqual(skel_view["artifact"], "docs/skeleton.md")
        # rounds view: one clean round per family
        self.assertEqual(len(skel_view["rounds"]), 2)
        for r in skel_view["rounds"]:
            self.assertEqual(set(r.keys()), {"id", "family", "kind", "findings", "at"})
            self.assertEqual(r["findings"], 0)
        # seals view: one passed attempt with per-family finding counts
        self.assertEqual(len(skel_view["seals"]), 1)
        seal = skel_view["seals"][0]
        self.assertEqual(
            set(seal.keys()), {"attempt", "passed", "invalidated", "findings", "at"}
        )
        self.assertEqual(seal["attempt"], 1)
        self.assertTrue(seal["passed"])
        self.assertIsNone(seal["invalidated"])
        self.assertEqual(seal["findings"], {"codex": 0, "claude": 0})
        # doc view carries the dirty round's finding count
        self.assertEqual(doc_view["rounds"][0]["findings"], 2)
        self.assertEqual(doc_view["seals"], [])

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


if __name__ == "__main__":
    unittest.main()
