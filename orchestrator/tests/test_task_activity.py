"""Focused proof for the best-effort task activity projection."""

import copy
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import brainstorming_lifecycle, contracts, registry, service
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

    def test_milestone_verification_projects_compact_canonical_task_facts(self):
        state = self.state()
        unit = st._new_unit(
            st.UNIT_MILESTONE_VERIFICATION, None, part="1"
        )
        unit["status"] = st.U_SEALED
        order = self.order(
            st.unit_key(unit), tasks.REVIEWED_COMPLETE_VERIFICATION,
            executor="reviewed_task",
        )
        order["configuration"] = tasks.resolve_reviewed_task_configuration(
            {"task_kind": tasks.REVIEWED_COMPLETE_VERIFICATION}, {}
        )
        record = tasks.admit_task(state, order, {}, self.workspace)
        unit["reviewed_task_id"] = record["id"]
        state["units"].append(unit)

        # A gate/result crash window must still read as an open task even
        # though the unit has already sealed.
        projected = st.summary(state)["units"][-1]
        self.assertEqual(projected["task_ids"], [record["id"]])
        self.assertEqual(projected["task"], {
            "id": record["id"],
            "task_executor": "reviewed_task",
            "status": "open",
            "duration_s": 0.0,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
        })

        result = self.terminal(
            duration_s=4.0,
            token_usage={
                "input_tokens": 5,
                "cached_input_tokens": 1,
                "output_tokens": 3,
                "reasoning_output_tokens": 1,
                "total_tokens": 8,
            },
            token_usage_partial=False,
            cost={"api_usd": 0.4, "real_usd": 0.0},
            cost_partial=False,
            native={"large": "canonical detail only"},
        )
        tasks.record_task_result(state, record["id"], result)
        compact = st.summary(state)["units"][-1]["task"]
        self.assertEqual(compact["status"], "success")
        self.assertEqual(compact["duration_s"], 4.0)
        self.assertEqual(compact["cost"], result["cost"])
        self.assertFalse(compact["cost_partial"])
        for copied in ("order", "configuration", "native_result", "result"):
            self.assertNotIn(copied, compact)

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

    def test_sidebar_lists_only_top_level_tasks_before_applying_limit(self):
        parent_order = self.order(executor="deep_task")
        parent_order["configuration"] = tasks.resolve_deep_task_configuration(
            {}, defaults={}
        )
        parent_order["staffing_session"] = None
        store = task_api.StandaloneTaskStore(self.home)
        parent = store.admit(parent_order, {}, self.workspace)
        direct_review = store.admit(
            tasks.deep_documentation_order(parent), {}, self.workspace
        )
        child_review = store.admit_related_locked(
            parent["id"], "documentation", None,
            tasks.deep_documentation_order(parent), {}, self.workspace,
        )
        for record in (parent, direct_review, child_review):
            store.record_result(record["id"], self.terminal())

        rows = service.visible_direct_task_rows(
            self.home, {"admin": True}
        )
        self.assertEqual(
            [row["record"]["id"] for row in rows],
            [direct_review["id"], parent["id"]],
        )
        limited = service.visible_direct_task_rows(
            self.home, {"admin": True}, limit=1
        )
        self.assertEqual(
            [row["record"]["id"] for row in limited],
            [direct_review["id"]],
        )
        with mock.patch.object(
            service, "direct_reviewed_task_view",
            side_effect=AssertionError("terminal timing consulted activity"),
        ):
            timing = service._direct_task_sidebar_timing(
                self.home, {"admin": True}, limited[0]["record"]
            )
        sidebar_row = service._sidebar_task_row(limited[0], timing)
        self.assertEqual(sidebar_row["process"], "stopped")
        self.assertEqual(sidebar_row["work_duration_s"], 1.0)
        self.assertIsNone(sidebar_row["in_flight"])
        self.assertEqual(
            {record["id"] for record in service.visible_tasks(
                self.home, {"admin": True}
            )},
            {parent["id"], direct_review["id"], child_review["id"]},
        )
        self.assertEqual(
            service.read_task(
                self.home, {"admin": True}, child_review["id"]
            )["parent"]["task_id"],
            parent["id"],
        )

    def test_direct_reviewed_activity_preserves_part_and_normalizes_billing(self):
        order = self.order(executor="reviewed_task")
        order["configuration"] = tasks.resolve_reviewed_task_configuration(
            {"task_kind": contracts.KIND_IMPLEMENT}, defaults={}
        )
        store = task_api.StandaloneTaskStore(self.home)
        record = store.admit(order, {}, self.workspace)
        path = task_api.ensure_reviewed_state(
            self.home, record,
            {"families_order": ["codex", "claude"], "model_defaults": {}},
        )
        lifecycle = st.load(path)
        target = next(
            unit for unit in lifecycle["units"]
            if st.unit_key(unit) == lifecycle["reviewed_task"]["unit"]
        )
        st.record_draft(
            lifecycle, target, contracts.KIND_IMPLEMENT,
            {
                "status": "ok",
                "kind": contracts.KIND_IMPLEMENT,
                "files_changed": [],
                "suite_command": "true",
                "notes": "first coherent part",
                "implementation_cut": {
                    "cut_scope": "coherent first part",
                    "remaining_scope": "remaining second part",
                },
            },
            family="codex",
            duration=5.0,
        )
        lifecycle["config"]["billing"] = True
        st.save(path, lifecycle)

        class Host:
            @staticmethod
            def is_active(task_id):
                return task_id == record["id"]

        with mock.patch.object(
            service, "read_in_flight",
            return_value={"started_at": 200.0, "kind": "implement"},
        ):
            view = service.direct_reviewed_task_view(
                self.home, store.record(record["id"]), Host()
            )
            timing = service._direct_task_sidebar_timing(
                self.home, {"admin": True},
                store.record(record["id"]), Host(),
            )
        self.assertEqual(view["activity"]["unit"]["part"], "a")
        self.assertEqual(view["billing"], {})
        self.assertEqual(timing, {
            "process": "running",
            "work_duration_s": 5.0,
            "in_flight": {"started_at": 200.0},
        })

        with mock.patch.object(
            service, "direct_reviewed_task_view",
            return_value={"activity": None},
        ):
            unavailable = service._direct_task_sidebar_timing(
                self.home, {"admin": True},
                store.record(record["id"]), Host(),
            )
        self.assertEqual(unavailable, {
            "process": "running",
            "work_duration_s": None,
            "in_flight": None,
        })

    def test_sidebar_agent_call_clock_uses_only_a_live_worker_marker(self):
        store = task_api.StandaloneTaskStore(self.home)
        record = store.admit(self.order(), {}, self.workspace)

        class Host:
            active = True

            @classmethod
            def is_active(cls, task_id):
                return cls.active and task_id == record["id"]

        marker = {
            "task_id": record["id"],
            "started_at": 123.5,
        }
        task_api._write_worker_marker(self.home, record["id"], marker)
        timing = service._direct_task_sidebar_timing(
            self.home, {"admin": True}, record, Host()
        )
        self.assertEqual(timing, {
            "process": "running",
            "work_duration_s": 0.0,
            "in_flight": {"started_at": 123.5},
        })

        Host.active = False
        stale = service._direct_task_sidebar_timing(
            self.home, {"admin": True}, record, Host()
        )
        self.assertEqual(stale, {
            "process": "stopped",
            "work_duration_s": None,
            "in_flight": None,
        })

        Host.active = True
        task_api._write_worker_marker(self.home, record["id"], {
            **marker, "completed": True, "duration_s": 7.0,
        })
        settled = service._direct_task_sidebar_timing(
            self.home, {"admin": True}, record, Host()
        )
        self.assertEqual(settled, {
            "process": "running",
            "work_duration_s": 7.0,
            "in_flight": None,
        })

        store.record_result(record["id"], self.terminal(duration_s=9.0))
        terminal = store.record(record["id"])
        with mock.patch.object(
            task_api, "read_worker_marker",
            side_effect=AssertionError("terminal timing read stale marker"),
        ):
            timing = service._direct_task_sidebar_timing(
                self.home, {"admin": True}, terminal, Host()
            )
        self.assertEqual(timing, {
            "process": "stopped",
            "work_duration_s": 9.0,
            "in_flight": None,
        })

    def test_sidebar_brainstorming_clocks_reuse_session_accounting_once(self):
        record = {
            "id": "brainstorming-task",
            "order": {"task_executor": "brainstorming"},
            "result": None,
        }

        class Host:
            @staticmethod
            def is_active(task_id):
                return task_id == record["id"]

        session = {
            "process": "running",
            "work_duration_s": 6.0,
            "in_flight": {"started_at": 400.0, "kind": "discussion_turn"},
        }
        with mock.patch.object(
            task_api, "task_session_id", return_value="bs-timing"
        ), mock.patch.object(
            brainstorming_lifecycle, "inspect_session", return_value=session
        ):
            timing = service._direct_task_sidebar_timing(
                self.home, {"admin": True}, record, Host()
            )
        self.assertEqual(timing, {
            "process": "running",
            "work_duration_s": 6.0,
            "in_flight": {"started_at": 400.0},
        })

        with mock.patch.object(
            task_api, "task_session_id", return_value="bs-timing"
        ), mock.patch.object(
            brainstorming_lifecycle, "inspect_session",
            return_value={
                "process": "stopped",
                "work_duration_s": 6.0,
                "in_flight": {"started_at": 400.0},
            },
        ):
            settling = service._direct_task_sidebar_timing(
                self.home, {"admin": True}, record, Host()
            )
        self.assertEqual(settling, {
            "process": "running",
            "work_duration_s": 6.0,
            "in_flight": None,
        })

        waiting_activity = {
            "process": "running",
            "in_flight": None,
            "unit": {
                "work_duration_s": 4.0,
                "brainstormings": [{
                    "outcome": "waiting", "session_id": "bs-timing",
                    "duration_s": None,
                }],
            },
        }
        with mock.patch.object(
            brainstorming_lifecycle, "inspect_session", return_value=session
        ):
            waiting = service._reviewed_activity_timing(
                self.home, waiting_activity
            )
        self.assertEqual(waiting, {
            "process": "running",
            "work_duration_s": 10.0,
            "in_flight": {"started_at": 400.0},
        })

        recorded_activity = copy.deepcopy(waiting_activity)
        recorded_activity["unit"]["work_duration_s"] = 10.0
        recorded_activity["unit"]["brainstormings"][0]["duration_s"] = 6.0
        with mock.patch.object(
            brainstorming_lifecycle, "inspect_session",
            side_effect=AssertionError("recorded session was counted twice"),
        ):
            recorded = service._reviewed_activity_timing(
                self.home, recorded_activity
            )
        self.assertEqual(recorded["work_duration_s"], 10.0)

        with mock.patch.object(
            brainstorming_lifecycle, "inspect_session",
            side_effect=RuntimeError("session temporarily unreadable"),
        ):
            unavailable = service._reviewed_activity_timing(
                self.home, waiting_activity
            )
        self.assertEqual(unavailable, {
            "process": "running",
            "work_duration_s": 4.0,
            "in_flight": None,
        })

    def test_sidebar_clock_rejects_extreme_corrupt_numbers(self):
        huge = 10 ** 400
        self.assertEqual(service._task_timing(huge, {"started_at": huge}), {
            "process": "stopped",
            "work_duration_s": None,
            "in_flight": None,
        })

        record = {
            "id": "terminal-corrupt-duration",
            "order": {"task_executor": "agent_call"},
            "result": {"status": "failure", "duration_s": huge},
        }
        timing = service._direct_task_sidebar_timing(
            self.home, {"admin": True}, record
        )
        self.assertIsNone(timing["work_duration_s"])
        self.assertIsNone(timing["in_flight"])

    def test_direct_deep_task_projects_ordered_reviewed_child_activity(self):
        parent_order = self.order(executor="deep_task")
        parent_order["configuration"] = tasks.resolve_deep_task_configuration(
            {}, defaults={}
        )
        parent_order["staffing_session"] = None
        store = task_api.StandaloneTaskStore(self.home)
        parent = store.admit(parent_order, {}, self.workspace)
        documentation = store.admit_related_locked(
            parent["id"], "documentation", None,
            tasks.deep_documentation_order(parent), {}, self.workspace,
        )
        implementation_order = tasks.deep_implementation_order(
            parent, os.path.join(self.workspace, "slice.md")
        )
        implementation_a = store.admit_related_locked(
            parent["id"], "implementation", "a",
            implementation_order, {}, self.workspace,
        )
        implementation_b = store.admit_related_locked(
            parent["id"], "implementation", "b",
            implementation_order, {}, self.workspace,
        )
        implementation_z = store.admit_related_locked(
            parent["id"], "implementation", "z",
            implementation_order, {}, self.workspace,
        )
        implementation_aa = store.admit_related_locked(
            parent["id"], "implementation", "aa",
            implementation_order, {}, self.workspace,
        )
        foreign_order = copy.deepcopy(implementation_order)
        foreign_order["request"]["work_area"] = {
            "project": "foreign", "work_area": "main",
        }
        store.admit_related_locked(
            parent["id"], "implementation", "foreign",
            foreign_order, {}, self.workspace,
        )
        config = {
            "families_order": ["codex", "claude"],
            "model_defaults": {},
            "billing": {"codex": "subscription"},
        }
        for child in (documentation, implementation_a, implementation_b):
            task_api.ensure_reviewed_state(self.home, child, config)
        store.record_result(documentation["id"], self.terminal("failure"))
        for child, note, duration in (
            (implementation_a, "part a evidence", 2.0),
            (implementation_b, "part b evidence", 3.0),
        ):
            path = task_api.reviewed_state_path(self.home, child["id"])
            lifecycle = st.load(path)
            target = next(
                unit for unit in lifecycle["units"]
                if st.unit_key(unit) == lifecycle["reviewed_task"]["unit"]
            )
            st.record_draft(
                lifecycle, target, contracts.KIND_IMPLEMENT,
                {
                    "status": "ok",
                    "kind": contracts.KIND_IMPLEMENT,
                    "files_changed": [],
                    "suite_command": "true",
                    "notes": note,
                },
                family="codex",
                duration=duration,
            )
            st.save(path, lifecycle)
        store.record_result(
            implementation_z["id"], self.terminal(duration_s=4.0)
        )
        store.record_result(
            implementation_aa["id"], self.terminal(duration_s=5.0)
        )
        corrupt_path = task_api.reviewed_state_path(
            self.home, implementation_z["id"]
        )
        os.makedirs(os.path.dirname(corrupt_path), exist_ok=True)
        with open(corrupt_path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")

        class Host:
            @staticmethod
            def is_active(task_id):
                return task_id == implementation_a["id"]

        before = copy.deepcopy(store.records())
        real_load_summary = service.load_summary

        def summary_with_decoy(path, model_profiles_home=None):
            summary = copy.deepcopy(real_load_summary(
                path, model_profiles_home=model_profiles_home
            ))
            if documentation["id"] in path:
                target = next(
                    unit for unit in summary["units"]
                    if unit["unit"] == "slice_doc-01"
                )
                decoy = copy.deepcopy(target)
                decoy["unit"] = "slice_doc-99"
                summary["units"].insert(0, decoy)
            if implementation_b["id"] in path:
                summary["billing"] = True
            return summary

        with mock.patch.object(
            service, "load_summary", side_effect=summary_with_decoy
        ), mock.patch.object(
            service, "read_in_flight",
            side_effect=lambda _entry, active: (
                {"started_at": 300.0, "kind": "implement"}
                if active else None
            ),
        ):
            view = service.direct_deep_task_view(
                self.home, {"admin": True}, parent, Host()
            )
            reviewed_view = service.direct_reviewed_task_view(
                self.home, store.record(implementation_a["id"]), Host()
            )
            corrupt_view = service.direct_reviewed_task_view(
                self.home, store.record(implementation_z["id"]), Host()
            )
            sidebar_timing = service._direct_task_sidebar_timing(
                self.home, {"admin": True}, parent, Host()
            )
        self.assertEqual(store.records(), before)
        self.assertEqual(
            [(child["phase"], child["part"]) for child in view["children"]],
            [("documentation", None), ("implementation", "a"),
             ("implementation", "b"), ("implementation", "z"),
             ("implementation", "aa")],
        )
        by_id = {child["id"]: child for child in view["children"]}
        doc_activity = by_id[documentation["id"]]["activity"]
        self.assertEqual(doc_activity["unit"]["unit"], "slice_doc-01")
        self.assertEqual(doc_activity["unit"]["status"], "failure")
        self.assertEqual(by_id[documentation["id"]]["status"], "failure")
        self.assertEqual(
            doc_activity["unit"]["source_task_id"], documentation["id"]
        )
        self.assertEqual(
            by_id[implementation_a["id"]]["activity"]["process"],
            "running",
        )
        self.assertEqual(
            by_id[implementation_b["id"]]["activity"]["unit"]["part"], "b"
        )
        self.assertIsNone(by_id[implementation_z["id"]]["activity"])
        self.assertIsNone(by_id[implementation_aa["id"]]["activity"])
        self.assertEqual(reviewed_view["task_kind"], contracts.KIND_IMPLEMENT)
        self.assertEqual(
            reviewed_view["activity"]["unit"],
            by_id[implementation_a["id"]]["activity"]["unit"],
        )
        self.assertEqual(reviewed_view["activity"]["process"], "running")
        self.assertIsNone(corrupt_view["activity"])
        self.assertIsInstance(view["billing"], dict)
        self.assertEqual(view["work_duration_s"], 15.0)
        self.assertEqual(view["in_flight"], {"started_at": 300.0})
        self.assertEqual(sidebar_timing, {
            "process": "running",
            "work_duration_s": 15.0,
            "in_flight": {"started_at": 300.0},
        })
        for forbidden in ("goal", "events", "order", "result", "native_result"):
            self.assertNotIn(forbidden, reviewed_view)
        for child, note in (
            (implementation_a, "part a evidence"),
            (implementation_b, "part b evidence"),
        ):
            story = service.direct_task_story(
                self.home, {"admin": True}, child["id"],
                "draft:slice_impl-01",
            )
            self.assertEqual(story["task_id"], child["id"])
            self.assertEqual(story["result"]["notes"], note)
        with self.assertRaises(service.ApiError) as raised:
            service.direct_task_story(
                self.home, {"admin": True}, parent["id"], "draft:skeleton"
            )
        self.assertEqual(raised.exception.status, 404)
        for forbidden in ("goal", "events", "order", "result", "native_result"):
            self.assertNotIn(forbidden, doc_activity)

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
