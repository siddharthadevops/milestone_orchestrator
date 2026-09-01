"""Focused proof for the best-effort task activity projection."""

import copy
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts, registry, service
from orchestrator import state as st
from orchestrator import task_api, tasks


class TaskActivityProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-task-activity-")
        self.addCleanup(self.tmp.cleanup)
        self.workspace = os.path.join(self.tmp.name, "workspace")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.workspace)

    def state(self):
        return st.new_state(
            "Show task activity.",
            self.workspace,
            {"families_order": ["codex", "claude"]},
        )

    def order(self, unit=None, kind=None, executor="agent_call"):
        context = {"source": "focused test"}
        if unit is not None:
            context["unit"] = unit
        if kind is not None:
            context["task_kind"] = kind
        return {
            "task_executor": executor,
            "request": {
                "work_area": {
                    "workspace_path": self.workspace,
                    "primary": self.workspace,
                    "additional": [],
                },
                "request": "Produce the requested outcome.",
                "context": context,
                "reference_documents": [],
            },
        }

    def admit(self, state, unit=None, kind=None, executor="agent_call",
              staffing=None):
        return tasks.admit_task(
            state,
            self.order(unit, kind, executor),
            staffing or {
                "agent_call": {
                    "agent": "codex",
                    "model": "order-model",
                    "effort": "high",
                }
            },
            self.workspace,
        )

    @staticmethod
    def terminal(status="success", native=None, **changes):
        value = {
            "status": status,
            "duration_s": 1.0,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
            "native_result": native,
        }
        if status == "failure":
            value["reason"] = "worker requested design help"
        value.update(changes)
        return value

    @staticmethod
    def draft_result():
        return {
            "status": "ok",
            "kind": contracts.KIND_DRAFT_SKELETON,
            "artifact": "docs/skeleton.md",
            "slices": [],
        }

    @staticmethod
    def clean_review():
        return {
            "status": "ok",
            "kind": contracts.KIND_REVIEW_ROUND,
            "findings": [],
        }

    def test_unit_task_ids_follow_frozen_context_and_admission_order(self):
        state = self.state()
        before = copy.deepcopy(state)
        self.assertEqual(st.summary(state)["units"][0]["task_ids"], [])
        self.assertEqual(state, before)

        first = self.admit(
            state, "skeleton", contracts.KIND_REVIEW_ROUND
        )
        self.admit(state, "not-a-unit", contracts.KIND_IMPLEMENT)
        self.admit(state, kind=contracts.KIND_IMPLEMENT)
        last = self.admit(state, "skeleton", contracts.KIND_DELTA_REVIEW)

        view = st.summary(state)["units"][0]
        self.assertEqual(view["task_ids"], [first["id"], last["id"]])
        self.assertNotIn("tasks", view)
        self.assertNotIn("result", view)

        with mock.patch.object(
            tasks, "task_records",
            side_effect=AssertionError("summary copied full task records"),
        ):
            self.assertEqual(
                st.summary(state)["units"][0]["task_ids"],
                [first["id"], last["id"]],
            )

    def test_task_history_and_detail_use_canonical_records(self):
        direct = task_api.StandaloneTaskStore(self.home).admit(
            self.order(),
            {"agent_call": {"agent": "codex"}},
            self.workspace,
        )
        state = self.state()
        milestone = self.admit(
            state, "skeleton", contracts.KIND_DRAFT_SKELETON
        )
        state_path = os.path.join(self.tmp.name, "state.json")
        st.save_new(state_path, state)
        registry.add(
            self.home,
            registry.new_entry(
                "task-activity-run", "task activity", self.workspace,
                state_path,
            ),
        )

        who = {"admin": True}
        self.assertEqual(service.visible_tasks(self.home, who), [direct, milestone])
        self.assertEqual(
            service.visible_run_tasks(self.home, who, "task-activity-run"),
            [milestone],
        )
        self.assertEqual(
            service.read_task(self.home, who, direct["id"]), direct
        )
        self.assertEqual(
            service.read_task(self.home, who, milestone["id"]), milestone
        )
        self.assertEqual(
            service.read_task(
                self.home, who, milestone["id"],
                run_id="task-activity-run",
            ),
            milestone,
        )
        with self.assertRaises(service.ApiError) as raised:
            service.read_task(
                self.home, who, direct["id"], run_id="task-activity-run"
            )
        self.assertEqual(raised.exception.status, 404)

    def test_internal_call_activity_has_evidence_without_task_chips(self):
        state = self.state()
        unit = state["units"][0]
        st.record_draft(
            state,
            unit,
            contracts.KIND_DRAFT_SKELETON,
            self.draft_result(),
            family="codex",
            model="call-model",
            effort="high",
            duration=1.0,
        )
        unit["status"] = st.U_ROUNDS
        st.record_round(
            state,
            unit,
            "codex",
            contracts.KIND_REVIEW_ROUND,
            self.clean_review(),
            duration=2.0,
        )
        st.append_event(
            state,
            "worker_malformed",
            unit="skeleton",
            kind=contracts.KIND_REVIEW_ROUND,
            family="codex",
            fatal=False,
            raw_path=".orchestrator/raw/review-malformed.txt",
        )
        st.append_event(
            state,
            "reclassify_recorded",
            unit="skeleton",
            source_round="skeleton-codex-r1",
            finding_id="codex-F1",
            reclassifier="claude",
            drift_risk="low",
            drift_damage="low",
            threshold="low",
            defer_ok=True,
            reason="bounded debt",
            duration_s=3.0,
        )
        st.append_event(
            state,
            "brainstorming_origin_recorded",
            unit="skeleton",
            kind=contracts.KIND_REVIEW_ROUND,
            family="codex",
            raw_path=".orchestrator/raw/rethink-origin.txt",
            duration_s=4.0,
        )
        st.append_event(
            state,
            "brainstorming_wait_started",
            unit="skeleton",
            session_id="rethink-session",
            kind=contracts.KIND_REVIEW_ROUND,
            family="codex",
        )

        state_path = os.path.join(self.tmp.name, "state.json")
        st.save_new(state_path, state)
        registry.add(
            self.home,
            registry.new_entry(
                "reviewed-activity-run",
                "reviewed activity",
                self.workspace,
                state_path,
            ),
        )
        direct = task_api.StandaloneTaskStore(self.home).admit(
            self.order(),
            {"agent_call": {"agent": "codex"}},
            self.workspace,
        )

        summary = st.summary(state)
        view = summary["units"][0]
        self.assertEqual(view["task_ids"], [])
        self.assertEqual(len(view["drafts"]), 1)
        self.assertEqual(len(view["rounds"]), 1)
        self.assertEqual(len(view["reclassify"]), 1)
        self.assertEqual(len(view["brainstormings"]), 1)
        self.assertEqual(len(summary["malformed"]), 1)
        for evidence in (
            view["drafts"]
            + view["rounds"]
            + view["reclassify"]
            + view["brainstormings"]
            + summary["malformed"]
        ):
            self.assertNotIn("task_id", evidence)

        who = {"admin": True}
        self.assertEqual(
            service.visible_run_tasks(
                self.home, who, "reviewed-activity-run"
            ),
            [],
        )
        self.assertEqual(service.visible_tasks(self.home, who), [direct])
        self.assertEqual(
            service.read_task(self.home, who, direct["id"]), direct
        )

    def test_failed_review_origin_and_later_review_have_distinct_chips(self):
        state = self.state()
        failed = self.admit(
            state, "skeleton", contracts.KIND_REVIEW_ROUND
        )
        raw = {
            "status": "need_rethink",
            "kind": contracts.KIND_REVIEW_ROUND,
            "request": "Clarify one contradiction.",
            "finding": {"id": "F1"},
        }
        tasks.record_task_result(
            state, failed["id"], self.terminal("failure", raw)
        )
        successor = self.admit(
            state, "skeleton", contracts.KIND_REVIEW_ROUND
        )
        tasks.record_task_result(
            state, successor["id"], self.terminal(native={"findings": []})
        )

        self.assertNotEqual(failed["id"], successor["id"])
        self.assertEqual(
            st.summary(state)["units"][0]["task_ids"],
            [failed["id"], successor["id"]],
        )
        preserved = tasks.task_record(state, failed["id"])
        self.assertEqual(preserved["result"]["native_result"], raw)
        self.assertNotIn("predecessor", preserved)
        self.assertNotIn("successor", preserved)

    def test_draft_and_implementation_tasks_render_separately(self):
        state = self.state()
        draft = self.admit(
            state, "skeleton", contracts.KIND_DRAFT_SLICE_NOTE
        )
        implementation = self.admit(
            state,
            "skeleton",
            contracts.KIND_IMPLEMENT,
            executor="brainstorming",
            staffing={"dispatch_authority": "static"},
        )

        self.assertEqual(
            st.summary(state)["units"][0]["task_ids"],
            [draft["id"], implementation["id"]],
        )
        self.assertEqual(draft["order"]["task_executor"], "agent_call")
        self.assertEqual(
            implementation["order"]["task_executor"], "brainstorming"
        )

    def test_task_chips_preserve_linked_calls_and_non_task_activity(self):
        state = self.state()
        unit = state["units"][0]
        draft = self.admit(
            state, "skeleton", contracts.KIND_DRAFT_SKELETON
        )
        review = self.admit(
            state, "skeleton", contracts.KIND_REVIEW_ROUND
        )
        discussion = self.admit(
            state, "skeleton", contracts.KIND_IMPLEMENT,
            executor="brainstorming",
            staffing={"dispatch_authority": "static"},
        )
        st.record_draft(
            state, unit, contracts.KIND_DRAFT_SKELETON,
            self.draft_result(), task_id=draft["id"],
        )
        unit["status"] = st.U_ROUNDS
        st.record_round(
            state, unit, "codex", contracts.KIND_REVIEW_ROUND,
            self.clean_review(), task_id=review["id"],
        )
        st.append_event(
            state, "brainstorming_wait_started", unit="skeleton",
            session_id="production-session", kind=contracts.KIND_IMPLEMENT,
            task_id=discussion["id"],
        )
        st.append_event(
            state, "brainstorming_wait_started", unit="skeleton",
            session_id="attached-session", kind=contracts.KIND_REVIEW_ROUND,
        )
        st.append_event(
            state, "brainstorming_wait_started", unit="skeleton",
            session_id="work-linked-session", kind=contracts.KIND_IMPLEMENT,
        )
        st.append_event(
            state, "brainstorming_work_recorded", unit="skeleton",
            session_id="work-linked-session", duration_s=2,
            task_id=discussion["id"],
        )
        st.append_event(
            state, "verification", unit="skeleton", stage="pre_seal",
            ok=True, stable=True,
        )

        view = st.summary(state)["units"][0]
        self.assertEqual(view["drafts"][0]["task_id"], draft["id"])
        self.assertEqual(view["rounds"][0]["task_id"], review["id"])
        self.assertEqual(
            view["brainstormings"][0]["task_id"], discussion["id"]
        )
        self.assertNotIn("task_id", view["brainstormings"][1])
        self.assertEqual(
            view["brainstormings"][2]["task_id"], discussion["id"]
        )
        self.assertEqual(len(view["verifications"]), 1)
        self.assertNotIn("task_id", view["verifications"][0])

    def test_task_projection_does_not_reaggregate_or_infer_staffing(self):
        state = self.state()
        unit = state["units"][0]
        record = self.admit(
            state, "skeleton", contracts.KIND_DRAFT_SKELETON
        )
        usage = {
            "input_tokens": 10,
            "cached_input_tokens": 2,
            "output_tokens": 5,
            "reasoning_output_tokens": 1,
            "total_tokens": 15,
        }
        cost = {"api_usd": 0.2, "real_usd": 0.0}
        st.record_draft(
            state, unit, contracts.KIND_DRAFT_SKELETON,
            self.draft_result(), family="codex", model="call-model",
            effort="medium", duration=7, token_usage=usage, cost=cost,
            task_id=record["id"],
        )
        before = st.summary(state)
        tasks.record_task_result(
            state,
            record["id"],
            self.terminal(
                duration_s=7, token_usage=usage,
                token_usage_partial=False, cost=cost, cost_partial=False,
                native={"artifact": "docs/skeleton.md"},
            ),
        )
        after = st.summary(state)

        self.assertEqual(after["work_duration_s"], before["work_duration_s"])
        self.assertEqual(after["work_token_usage"], before["work_token_usage"])
        self.assertEqual(after["work_cost"], before["work_cost"])
        self.assertEqual(after["work_duration_s"], 7.0)
        self.assertEqual(after["units"][0]["drafts"][0]["model"], "call-model")
        self.assertNotIn("resolved_staffing", after["units"][0])
        self.assertEqual(
            tasks.task_record(state, record["id"])["resolved_staffing"]
            ["agent_call"]["model"],
            "order-model",
        )


if __name__ == "__main__":
    unittest.main()
