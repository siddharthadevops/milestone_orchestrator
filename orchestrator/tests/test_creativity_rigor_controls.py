"""Live Creativity rigor controls preserve admitted work and search progress."""

import copy
import os
import unittest

from orchestrator import registry, task_api, tasks
from orchestrator import state as st
from orchestrator.tests import test_task_api as api_fixture
from orchestrator.tests.test_task_controls_api import HeldHost
from orchestrator.tests.test_tasks import creativity_configuration


class CreativityRigorControlsTest(unittest.TestCase):
    directory = api_fixture.TaskApiTest.directory
    start_server = api_fixture.TaskApiTest.start_server
    request = api_fixture.TaskApiTest.request
    order = api_fixture.TaskApiTest.order
    project = api_fixture.TaskApiTest.project
    member = staticmethod(api_fixture.TaskApiTest.member)

    def setUp(self):
        api_fixture.TaskApiTest.setUp(self)
        self.host = HeldHost(self.home)
        self.start_server(self.host)
        self.store = self.host.store

    def admit(self, rigor=None, executor="creativity", work_area=None):
        order = self.order(executor, work_area=work_area)
        if executor == "creativity":
            order["configuration"] = creativity_configuration()
            if rigor is not None:
                order["configuration"]["rigor"] = rigor
        return self.store.admit(order, {}, self.primary)

    @staticmethod
    def path(record):
        return "/api/tasks/%s/creativity-rigor" % record["id"]

    def document(self, record):
        return self.store._store.read(task_api.task_key(record["id"]))

    def assert_rigor(self, record, expected):
        code, response = self.request("GET", self.path(record))
        self.assertEqual(code, 200, response)
        self.assertEqual(response, {"ok": True, "rigor": expected})
        self.assertEqual(self.store.creativity_rigor(record["id"]), expected)

    def test_get_inherits_admitted_rigor_without_creating_an_override(self):
        for initial in (None, {}, {"default": "medium", "create_genes": "high"}):
            with self.subTest(initial=initial):
                record = self.admit(rigor=initial)
                before = self.document(record)
                self.assert_rigor(record, initial or {})
                self.assertEqual(self.document(record), before)
                self.assertNotIn("creativity_rigor", before["value"])

    def test_update_replaces_map_and_clear_persists_without_reverting_to_order(self):
        initial = {"default": "high", "create_genes": "high"}
        record = self.admit(rigor=initial)
        checkpoint_store = task_api.creativity_checkpoint_store(self.home, record["id"])
        checkpoint = {"generation": 3, "population": [{"id": "retained-candidate"}]}
        checkpoint_store.put("checkpoint", checkpoint)
        lifecycle = self.store.lifecycle(record["id"])

        for override in (
            {"default": "medium", "create_genes": "low", "compose_candidates": "medium",
             "evaluate_candidates": "high"},
            {"compose_candidates": "high"},
            {"evaluate_candidates": "low"},
            {},
        ):
            with self.subTest(override=override):
                code, response = self.request("POST", self.path(record), {"rigor": override})
                self.assertEqual(code, 200, response)
                self.assertEqual(response, {"ok": True, "rigor": override})
                self.assert_rigor(record, override)
                self.assertEqual(self.document(record)["value"]["creativity_rigor"], override)
                self.assertEqual(self.store.record(record["id"]), record)
                self.assertEqual(self.store.lifecycle(record["id"]), lifecycle)
                self.assertEqual(checkpoint_store.get("checkpoint"), checkpoint)
                self.assertEqual(self.host.started, [])

        fresh = HeldHost(self.home)
        self.start_server(fresh)
        self.store = fresh.store
        self.assert_rigor(record, {})
        self.assertEqual(self.store.record(record["id"])["order"]["configuration"]["rigor"], initial)
        self.assertEqual(checkpoint_store.get("checkpoint"), checkpoint)

    def test_running_pausing_and_paused_tasks_accept_each_supported_level(self):
        for status in ("running", "pausing", "paused"):
            with self.subTest(status=status):
                record = self.admit()
                if status != "running":
                    with registry.locked(self.home):
                        self.store.pause_locked(
                            record["id"], "Operator adjustment", pending=status == "pausing",
                        )
                lifecycle = self.store.lifecycle(record["id"])
                self.assertEqual(lifecycle["status"], status)
                for level in ("low", "medium", "high"):
                    override = dict.fromkeys(
                        ("default", "create_genes", "compose_candidates", "evaluate_candidates"), level,
                    )
                    code, response = self.request("POST", self.path(record), {"rigor": override})
                    self.assertEqual(code, 200, response)
                    self.assert_rigor(record, override)
                    self.assertEqual(self.store.lifecycle(record["id"]), lifecycle)
                    self.assertEqual(self.store.record(record["id"]), record)
        self.assertEqual(self.host.started, [])

    def test_invalid_bodies_leave_the_entire_durable_document_unchanged(self):
        record = self.admit(rigor={"default": "high"})
        before = self.document(record)
        invalid = [
            {}, [], None, "low", {"default": "low"},
            {"rigor": {}, "force": True},
            {"rigor": None}, {"rigor": []}, {"rigor": "low"},
            {"rigor": {"expand_genes": "low"}},
            {"rigor": {"unknown": "low"}},
        ]
        for key in ("default", "create_genes", "compose_candidates", "evaluate_candidates"):
            invalid.extend({"rigor": {key: level}} for level in (
                "max", "xhigh", "LOW", "", " low ", None, True, 1, [], {},
            ))
        for body in invalid:
            with self.subTest(body=body):
                code, response = self.request("POST", self.path(record), body,
                                              raw=b"null" if body is None else None)
                self.assertEqual(code, 400, response)
                self.assertEqual(self.document(record), before)
        self.assert_rigor(record, {"default": "high"})

    def test_terminal_tasks_remain_readable_but_cannot_change_rigor(self):
        for status in ("success", "failure"):
            with self.subTest(status=status):
                record = self.admit(rigor={"evaluate_candidates": "medium"})
                override = {"default": "low"} if status == "success" else {}
                code, response = self.request("POST", self.path(record), {"rigor": override})
                self.assertEqual(code, 200, response)
                result = {
                    "status": status, "duration_s": 1.0, "token_usage": None,
                    "token_usage_partial": True, "cost": None, "cost_partial": True,
                    "native_result": "Historical result",
                }
                if status == "failure":
                    result["reason"] = "Historical failure"
                self.store.record_result(record["id"], result)
                before = self.document(record)
                self.assert_rigor(record, override)
                self.assertEqual(before["value"]["creativity_rigor"], override)
                code, response = self.request("POST", self.path(record), {"rigor": {"default": "low"}})
                self.assertEqual(code, 409, response)
                self.assertEqual(self.document(record), before)

    def test_stop_retains_override_and_prevents_late_edits(self):
        record = self.admit(rigor={"default": "high"})
        override = {"evaluate_candidates": "low"}
        code, response = self.request("POST", self.path(record), {"rigor": override})
        self.assertEqual(code, 200, response)
        with registry.locked(self.home):
            self.store.record_stop_locked(record["id"], "Operator stopped this search")
        before = self.document(record)
        self.assert_rigor(record, override)
        self.assertEqual(before["value"]["creativity_rigor"], override)
        code, response = self.request("POST", self.path(record), {"rigor": {}})
        self.assertEqual(code, 409, response)
        self.assertEqual(self.document(record), before)

    def test_non_creativity_tasks_are_rejected_without_mutation(self):
        record = self.admit(executor="agent_call")
        before = self.document(record)
        for method, body in (("GET", None), ("POST", {"rigor": {}})):
            code, response = self.request(method, self.path(record), body)
            self.assertEqual(code, 409, response)
            self.assertEqual(self.document(record), before)

    def test_access_checks_precede_exposing_task_state(self):
        self.project("private", self.primary)
        for executor in ("creativity", "agent_call"):
            with self.subTest(executor=executor):
                record = self.admit(executor=executor, work_area={"project": "private", "work_area": "main"})
                before = self.document(record)
                for method, body in (("GET", None), ("POST", {"rigor": {}})):
                    code, response = self.request(method, self.path(record), body, self.member())
                    self.assertEqual(code, 403, response)
                    self.assertNotIn("rigor", response)
                    self.assertEqual(self.document(record), before)
                    code, response = self.request(method, "/api/tasks/no-such-task/creativity-rigor", body)
                    self.assertEqual(code, 404, response)
                    self.assertNotIn("rigor", response)

    def test_milestone_owned_creativity_does_not_accept_standalone_controls(self):
        order = self.order("creativity")
        order["configuration"] = creativity_configuration(rigor={"default": "high"})
        state = st.new_state("milestone", self.primary, {})
        record = tasks.admit_task(state, order, {}, self.primary)
        before = copy.deepcopy(state)
        path = os.path.join(self.tmp.name, "milestone.json")
        st.save_new(path, state)
        registry.add(self.home, registry.new_entry("milestone", "milestone", self.primary, path))
        for method, body in (("GET", None), ("POST", {"rigor": {}})):
            code, response = self.request(method, self.path(record), body)
            self.assertEqual(code, 409, response)
            self.assertIn("milestone", response["error"])
        self.assertEqual(st.load(path), before)


if __name__ == "__main__":
    unittest.main()
