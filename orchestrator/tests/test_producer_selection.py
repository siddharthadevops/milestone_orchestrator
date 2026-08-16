"""Focused proof for independent slice-producer planning and override."""

import copy
import json
import os
import signal
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import prompts
from orchestrator import registry
from orchestrator import runners
from orchestrator import service
from orchestrator import state as st
from orchestrator import tasks


def _request(workspace, kind, unit):
    return {
        "work_area": {
            "workspace_path": workspace,
            "primary": workspace,
            "additional": [],
        },
        "request": "Produce the selected slice work.",
        "context": {"task_kind": kind, "unit": unit},
        "reference_documents": [],
    }


def _failure(reason="the selected producer could not finish"):
    return {
        "status": "failure",
        "reason": reason,
        "duration_s": 1.0,
        "token_usage": None,
        "token_usage_partial": True,
        "cost": None,
        "cost_partial": True,
        "native_result": {"request": "preserved"},
    }


class ProducerSelectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="producer-selection-")
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.server = service.make_server(self.home, 0)
        self.port = self.server.server_address[1]
        self.base = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()

    def tearDown(self):
        try:
            for entry in registry.load(self.home)["runs"]:
                pid = entry.get("pid")
                if pid and pid != os.getpid() and registry.pid_alive(pid):
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except OSError:
                        os.kill(pid, signal.SIGKILL)
        finally:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            self.tmp.cleanup()

    def _json(self, method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method
        )
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            with exc:
                status = exc.code
                body = exc.read()
        return status, json.loads(body.decode("utf-8"))

    def _planned_run(self, label="run", slices=None):
        workspace = os.path.join(self.tmp.name, label)
        os.makedirs(workspace)
        subprocess.run(["git", "init", "-q", workspace], check=True)
        status, created = self._json(
            "POST",
            "/api/runs",
            {
                "workspace": workspace,
                "goal": "Choose independent producers.",
                "autostart": False,
                "config": {"docs_dir": "docs"},
            },
        )
        self.assertEqual(status, 201, created)
        run_id = created["run"]["id"]
        entry = registry.get(registry.load(self.home), run_id)
        state = st.load(entry["state_path"])
        state["milestone"]["slices"] = copy.deepcopy(
            slices or [{"id": 1, "title": "Independent producers"}]
        )
        skeleton = state["units"][0]
        skeleton.update({"status": st.U_SEALED, "artifact": "docs/skeleton.md"})
        state["units"].extend(
            [
                st._new_unit(st.UNIT_SLICE_DOC, 1),
                st._new_unit(st.UNIT_SLICE_IMPL, 1),
            ]
        )
        st.save(entry["state_path"], state)
        service._evict_summary(entry["state_path"])
        return run_id, entry, workspace

    @staticmethod
    def _route(run_id):
        return "/api/runs/%s/slices/1/producer" % run_id

    def test_planner_uses_shared_catalogue_and_validates_supplied_maps(self):
        catalogue = tasks.task_executor_catalogue()
        prompt = prompts.build_draft_skeleton("codex", "/workspace", "goal")
        self.assertIn("`draft_slice_note` and `implement`", prompt)
        self.assertIn(
            "In the skeleton document's slice table, visibly show both choices",
            prompt,
        )
        self.assertIn(
            json.dumps(
                catalogue, ensure_ascii=False, sort_keys=True, indent=2
            ),
            prompt,
        )

        response = {
            "status": "ok",
            "kind": contracts.KIND_DRAFT_SKELETON,
            "artifact": "docs/skeleton.md",
            "slices": [
                {
                    "id": 1,
                    "title": "one",
                    "producer_task_executor": {
                        "draft_slice_note": {"task_executor": "worker"},
                        "implement": {
                            "task_executor": "brainstorming",
                            "configuration": {"max_rounds": 4},
                        },
                    },
                }
            ],
        }
        contracts.validate_worker_output(
            copy.deepcopy(response), contracts.KIND_DRAFT_SKELETON
        )
        self.assertEqual(
            response["slices"][0]["producer_task_executor"]["implement"]
            ["configuration"],
            {"max_rounds": 4},
        )

        invalid_maps = (
            {"review_round": {"task_executor": "worker"}},
            {"implement": {"task_executor": "worker", "extra": True}},
            {
                "implement": {
                    "task_executor": "brainstorming",
                    "configuration": {"max_rounds": 0},
                }
            },
        )
        for producer_map in invalid_maps:
            malformed = copy.deepcopy(response)
            malformed["slices"][0]["producer_task_executor"] = producer_map
            with self.subTest(producer_map=producer_map), self.assertRaises(
                contracts.ContractError
            ):
                contracts.validate_worker_output(
                    malformed, contracts.KIND_DRAFT_SKELETON
                )

    def test_plan_repair_receives_shared_catalogue(self):
        cases = (
            (st.UNIT_SKELETON, False),
            (st.UNIT_SLICE_IMPL, True),
        )
        for unit_kind, producer_planning in cases:
            with self.subTest(unit_kind=unit_kind):
                prompt = prompts.build_fix_findings(
                    "codex",
                    "/workspace",
                    "goal",
                    "the current unit",
                    [],
                    [],
                    "claude",
                    "consult",
                    unit_kind=unit_kind,
                    editable_design_paths=["docs/skeleton.md"],
                    producer_planning=producer_planning,
                )
                self.assertIn(
                    json.dumps(
                        tasks.task_executor_catalogue(),
                        ensure_ascii=False,
                        sort_keys=True,
                        indent=2,
                    ),
                    prompt,
                )
                self.assertIn(
                    "In the skeleton document's slice table, visibly show both choices",
                    prompt,
                )

    def test_initial_design_update_producers_receive_shared_catalogue(self):
        catalogue = json.dumps(
            tasks.task_executor_catalogue(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        prompts_by_kind = {
            contracts.KIND_DRAFT_SLICE_NOTE: prompts.build_draft_slice_note(
                "codex",
                "/workspace",
                "goal",
                {"id": 5, "title": "producer planning"},
                "docs/skeleton.md",
                editable_design_paths=["docs/skeleton.md"],
            ),
            contracts.KIND_IMPLEMENT: prompts.build_implement(
                "codex",
                "/workspace",
                "goal",
                {"id": 5, "title": "producer planning"},
                "docs/slice-05.md",
                ["python3 -m unittest focused"],
                editable_design_paths=["docs/skeleton.md"],
            ),
        }
        for kind, prompt in prompts_by_kind.items():
            with self.subTest(kind=kind):
                self.assertIn("SLICE PRODUCER PLANNING", prompt)
                self.assertIn(catalogue, prompt)
                self.assertIn(
                    'also return the complete\n  updated plan in "slices"',
                    prompt,
                )

        ordinary = prompts.build_implement(
            "codex",
            "/workspace",
            "goal",
            {"id": 5, "title": "producer planning"},
            "docs/slice-05.md",
            [],
        )
        self.assertNotIn("\nSLICE PRODUCER PLANNING\n", ordinary)
        self.assertNotIn(catalogue, ordinary)

    def test_accepted_plan_rethink_receives_shared_catalogue(self):
        prompt = prompts.build_rethink_continuation(
            contracts.KIND_IMPLEMENT,
            "codex",
            "/workspace",
            {
                "session_id": "session-1",
                "accepted_target_revision": 1,
                "result": {"outcome": "success"},
                "retained_target": {"content": "Add one future slice."},
            },
            accepted_design_amendment=True,
            editable_design_paths=["docs/skeleton.md"],
            original_request="KIND: implement\nOUTPUT CONTRACT",
            producer_planning=True,
        )
        self.assertIn(
            json.dumps(
                tasks.task_executor_catalogue(),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ),
            prompt,
        )

    def test_absent_and_partial_maps_project_defaults_without_migration(self):
        source = [
            {"id": 1, "title": "absent"},
            {
                "id": 2,
                "title": "partial",
                "producer_task_executor": {
                    "implement": {
                        "task_executor": "brainstorming",
                        "configuration": {"closure_policy": "majority"},
                    }
                },
            },
        ]
        before = copy.deepcopy(source)
        effective = tasks.effective_slice_plan(source)
        self.assertEqual(source, before)
        self.assertEqual([item["id"] for item in effective], [1, 2])
        self.assertEqual([item["title"] for item in effective], ["absent", "partial"])
        worker = {"task_executor": "worker"}
        self.assertEqual(
            effective[0]["producer_task_executor"],
            {"draft_slice_note": worker, "implement": worker},
        )
        self.assertEqual(
            effective[1]["producer_task_executor"]["draft_slice_note"], worker
        )
        self.assertEqual(
            effective[1]["producer_task_executor"]["implement"]["configuration"],
            {"closure_policy": "majority"},
        )

        state = st.new_state("goal", "/workspace", {"families_order": ["codex"]})
        state["milestone"]["slices"] = source
        self.assertEqual(st.summary(state)["slices"], effective)
        self.assertEqual(state["milestone"]["slices"], before)

    def test_route_writes_each_choice_independently_and_projects_it(self):
        run_id, entry, _workspace = self._planned_run("independent")
        route = self._route(run_id)
        status, first = self._json(
            "POST",
            route,
            {
                "task_kind": "draft_slice_note",
                "task_executor": "brainstorming",
                "configuration": {"max_rounds": 4},
            },
        )
        self.assertEqual(status, 200, first)
        self.assertEqual(
            first["producer_task_executor"]["implement"],
            {"task_executor": "worker"},
        )
        status, second = self._json(
            "POST",
            route,
            {
                "task_kind": "implement",
                "task_executor": "brainstorming",
                "configuration": {"closure_policy": "majority"},
            },
        )
        self.assertEqual(status, 200, second)
        self.assertEqual(
            second["producer_task_executor"]["draft_slice_note"],
            first["producer_task_executor"]["draft_slice_note"],
        )

        status, detail = self._json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200, detail)
        projected = detail["summary"]["slices"][0]
        self.assertEqual(projected["producer_task_executor"], second["producer_task_executor"])
        self.assertEqual((projected["id"], projected["title"]), (1, "Independent producers"))
        raw = st.load(entry["state_path"])["milestone"]["slices"][0]
        self.assertEqual(
            raw["producer_task_executor"]["implement"]["configuration"],
            {"closure_policy": "majority"},
        )

    @unittest.skipIf(st.fcntl is None, "fcntl unavailable on this platform")
    def test_busy_run_refuses_override_without_queuing_a_driver_collision(self):
        run_id, entry, _workspace = self._planned_run("busy-override")
        before = st.load(entry["state_path"])
        with st.exclusive_mutation(entry["state_path"]):
            status, response = self._json(
                "POST",
                self._route(run_id),
                {"task_kind": "implement", "task_executor": "worker"},
            )
        self.assertEqual((status, response["error"]), (409, tasks.TASK_UPDATE_BUSY))
        self.assertEqual(st.load(entry["state_path"]), before)

    @unittest.skipIf(st.fcntl is None, "fcntl unavailable on this platform")
    def test_accepted_override_at_run_lock_handoff_does_not_stop_driver(self):
        run_id, entry, _workspace = self._planned_run("override-handoff")
        loaded = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )
        writer_inside_lock = threading.Event()
        release_writer = threading.Event()
        writer_result = []
        original_update = tasks.update_slice_producer

        def gated_update(state, slice_id, value):
            if threading.current_thread().name == "producer-writer":
                writer_inside_lock.set()
                self.assertTrue(release_writer.wait(timeout=2))
            return original_update(state, slice_id, value)

        def write_override():
            try:
                writer_result.append(service.set_slice_producer(
                    self.home,
                    run_id,
                    1,
                    {
                        "task_kind": "implement",
                        "task_executor": "brainstorming",
                    },
                ))
            except Exception as exc:  # surfaced by the assertion below
                writer_result.append(exc)

        with mock.patch.object(
            tasks, "update_slice_producer", side_effect=gated_update
        ):
            writer = threading.Thread(
                target=write_override, name="producer-writer"
            )
            writer.start()
            self.assertTrue(writer_inside_lock.wait(timeout=2))
            timer = threading.Timer(0.05, release_writer.set)
            timer.start()
            try:
                self.assertEqual(loaded.run(max_steps=0), 3)
            finally:
                release_writer.set()
                writer.join(timeout=2)
                timer.cancel()

        self.assertEqual(len(writer_result), 1)
        self.assertNotIsInstance(writer_result[0], Exception)
        self.assertEqual(
            loaded.state["milestone"]["slices"][0]
            ["producer_task_executor"]["implement"],
            {"task_executor": "brainstorming"},
        )

    @unittest.skipIf(st.fcntl is None, "fcntl unavailable on this platform")
    def test_run_handoff_still_refuses_a_non_producer_state_change(self):
        _run_id, entry, _workspace = self._planned_run("foreign-handoff")
        loaded = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )
        holder_inside_lock = threading.Event()
        release_holder = threading.Event()

        def hold_with_unrelated_update():
            with st.exclusive_mutation(entry["state_path"]):
                holder_inside_lock.set()
                release_holder.wait(timeout=2)
                state = st.load(entry["state_path"])
                st.append_event(state, "unrelated_driver_update")
                st.save(entry["state_path"], state)

        holder = threading.Thread(target=hold_with_unrelated_update)
        holder.start()
        self.assertTrue(holder_inside_lock.wait(timeout=2))
        timer = threading.Timer(0.05, release_holder.set)
        timer.start()
        try:
            with self.assertRaises(drv.ConcurrentRunError):
                loaded.run(max_steps=0)
        finally:
            release_holder.set()
            holder.join(timeout=2)
            timer.cancel()

    def test_loaded_driver_adopts_successful_live_override(self):
        initial = [{
            "id": 1,
            "title": "Independent producers",
            "producer_task_executor": {
                "implement": {
                    "task_executor": "brainstorming",
                    "configuration": {"max_rounds": 3},
                }
            },
        }]
        run_id, entry, workspace = self._planned_run(
            "live-override", initial
        )
        loaded = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )

        status, response = self._json(
            "POST",
            self._route(run_id),
            {"task_kind": "implement", "task_executor": "worker"},
        )
        self.assertEqual(status, 200, response)
        with loaded._exclusive():
            loaded._assert_not_stale()

        self.assertEqual(loaded.state, st.load(entry["state_path"]))
        selected = tasks.producer_order(
            loaded.state["milestone"]["slices"][0],
            contracts.KIND_IMPLEMENT,
            _request(workspace, contracts.KIND_IMPLEMENT, "slice_impl-01"),
        )
        self.assertEqual(selected["task_executor"], "worker")

    def test_loaded_driver_adopts_override_after_changed_plan_installation(self):
        run_id, entry, _workspace = self._planned_run("replacement-live-override")
        loaded = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )
        skeleton = next(
            unit for unit in loaded.state["units"]
            if unit["kind"] == st.UNIT_SKELETON
        )
        loaded._maybe_update_slices(
            skeleton,
            {"slices": [{"id": 1, "title": "Replaced plan"}]},
        )
        loaded._save()
        replacement_event = copy.deepcopy(loaded.state["events"][-1])

        status, response = self._json(
            "POST",
            self._route(run_id),
            {"task_kind": "implement", "task_executor": "brainstorming"},
        )
        self.assertEqual(status, 200, response)
        with loaded._exclusive():
            loaded._assert_not_stale()

        self.assertEqual(loaded.state, st.load(entry["state_path"]))
        self.assertEqual(loaded.state["events"][-2], replacement_event)
        self.assertEqual(
            loaded.state["milestone"]["slices"][0]
            ["producer_task_executor"]["implement"],
            {"task_executor": "brainstorming"},
        )

    def test_every_review_covering_skeleton_receives_operative_plan(self):
        run_id, entry, _workspace = self._planned_run("review-plan")
        status, _response = self._json(
            "POST",
            self._route(run_id),
            {
                "task_kind": "implement",
                "task_executor": "brainstorming",
                "configuration": {"max_rounds": 2},
            },
        )
        self.assertEqual(status, 200)
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        skeleton = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SKELETON
        )
        context = driver._producer_review_context(skeleton)
        self.assertEqual(
            context["producer_task_executor_by_slice"][0]
            ["producer_task_executor"]["implement"]["task_executor"],
            "brainstorming",
        )
        self.assertEqual(
            context["explicit_operator_overrides"],
            [{
                "slice_id": 1,
                "task_kind": "implement",
                "selection": {
                    "task_executor": "brainstorming",
                    "configuration": {"max_rounds": 2},
                },
            }],
        )
        expected = json.dumps(
            context, ensure_ascii=False, sort_keys=True, indent=2
        )
        full = prompts.build_review_round(
            "codex", "/workspace", "goal", "skeleton", "docs/skeleton.md",
            [], producer_review_context=context,
        )
        delta = prompts.build_delta_review(
            "codex", "/workspace", "goal", "skeleton", [],
            producer_review_context=context,
        )
        for prompt in (full, delta):
            self.assertIn("OPERATIVE SLICE PRODUCER PLAN", prompt)
            self.assertIn(expected, prompt)
            self.assertIn("A missing or malformed choice", prompt)
            self.assertIn("is always a finding", prompt)
            self.assertIn("A value mismatch is not a finding only", prompt)
            self.assertIn(
                "override never excuses missing or malformed structure",
                prompt,
            )

        doc = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SLICE_DOC
        )
        self.assertIsNone(driver._producer_review_context(doc))
        doc["design_update"] = {
            "changed_paths": [skeleton["artifact"]],
        }
        self.assertEqual(driver._producer_review_context(doc), context)

    def test_plan_replacement_drops_prior_override_authority(self):
        run_id, entry, _workspace = self._planned_run("plan-replacement")
        status, _response = self._json(
            "POST",
            self._route(run_id),
            {
                "task_kind": "implement",
                "task_executor": "brainstorming",
                "configuration": {"max_rounds": 3},
            },
        )
        self.assertEqual(status, 200)
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        skeleton = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SKELETON
        )
        driver._maybe_update_slices(
            skeleton,
            {
                "slices": [
                    {
                        "id": 1,
                        "title": "Repaired title",
                        "producer_task_executor": {
                            "draft_slice_note": {
                                "task_executor": "brainstorming",
                                "configuration": {"closure_policy": "majority"},
                            },
                            "implement": {"task_executor": "worker"},
                        },
                    },
                    {"id": 2, "title": "New planned slice"},
                ]
            },
        )
        repaired = driver.state["milestone"]["slices"]
        self.assertEqual(repaired[0]["title"], "Repaired title")
        self.assertEqual(
            repaired[0]["producer_task_executor"]["draft_slice_note"]
            ["task_executor"],
            "brainstorming",
        )
        self.assertEqual(
            repaired[0]["producer_task_executor"]["implement"],
            {"task_executor": "worker"},
        )
        self.assertNotIn("producer_task_executor", repaired[1])
        self.assertEqual(tasks.operator_producer_overrides(driver.state), [])

        events_before = copy.deepcopy(driver.state["events"])
        driver._maybe_update_slices(skeleton, {"slices": repaired})
        self.assertEqual(driver.state["events"], events_before)

    def test_equal_plan_response_keeps_current_override_authority(self):
        run_id, entry, _workspace = self._planned_run("plan-no-op")
        status, _response = self._json(
            "POST",
            self._route(run_id),
            {"task_kind": "implement", "task_executor": "brainstorming"},
        )
        self.assertEqual(status, 200)
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        skeleton = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SKELETON
        )
        installed = copy.deepcopy(driver.state["milestone"]["slices"])
        events_before = copy.deepcopy(driver.state["events"])
        driver._maybe_update_slices(skeleton, {"slices": installed})
        self.assertEqual(driver.state["events"], events_before)
        self.assertEqual(
            tasks.operator_producer_overrides(driver.state)[0]["task_kind"],
            contracts.KIND_IMPLEMENT,
        )

    def test_brainstorming_choice_fails_durably_until_slice_6_adapter(self):
        initial = [{
            "id": 1,
            "title": "Independent producers",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "brainstorming"},
            },
        }]
        _run_id, entry, _workspace = self._planned_run(
            "brainstorming-not-yet-executable", initial
        )
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        unit = next(
            candidate for candidate in driver.state["units"]
            if candidate["kind"] == st.UNIT_SLICE_DOC
        )
        with self.assertRaisesRegex(
            drv.StopStep, "requires the slice-production adapter"
        ):
            driver._admit_worker_task(
                unit,
                contracts.KIND_DRAFT_SLICE_NOTE,
                "draft the note",
                "codex",
            )
        durable = st.load(entry["state_path"])
        self.assertIn(
            "requires the slice-production adapter",
            durable["failure"]["reason"],
        )
        self.assertEqual(tasks.task_records(durable), [])
        recovered = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )
        action, _note = recovered._decide_at_strategy_boundary()
        self.assertEqual(action.type, drv.A_FAILED)

    def test_in_flight_design_update_is_reviewed_without_skeleton_edit(self):
        _run_id, entry, _workspace = self._planned_run("design-update-review")
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        skeleton = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SKELETON
        )
        doc = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SLICE_DOC
        )
        doc["design_update"] = {
            "editable_paths": [skeleton["artifact"]],
        }

        driver._maybe_update_slices(
            doc,
            {
                "slices": [{
                    "id": 1,
                    "title": "Independent producers",
                    "producer_task_executor": {
                        "draft_slice_note": {"task_executor": "worker"},
                        "implement": {"task_executor": "brainstorming"},
                    },
                }],
            },
        )

        self.assertEqual(driver._design_review_paths(doc), [])
        self.assertNotIn("producer_plan_review_required", doc["design_update"])
        driver._save()
        driver = drv.Driver(
            entry["state_path"], runner=runners.MockRunner([])
        )
        doc = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SLICE_DOC
        )
        self.assertNotIn("producer_plan_review_required", doc["design_update"])
        context = driver._producer_review_context(doc)
        self.assertEqual(
            context["producer_task_executor_by_slice"][0]
            ["producer_task_executor"]["implement"],
            {"task_executor": "brainstorming"},
        )
        self.assertEqual(context["explicit_operator_overrides"], [])
        prompt = prompts.build_review_round(
            "codex", "/workspace", "goal", "slice note", "docs/slice.md",
            [], producer_review_context=context,
        )
        self.assertIn("OPERATIVE SLICE PRODUCER PLAN", prompt)

    def test_pre_fix_admitted_reviews_recover_only_with_live_authority(self):
        cases = (
            (contracts.KIND_REVIEW_ROUND, st.U_ROUNDS),
            (contracts.KIND_DELTA_REVIEW, st.U_DELTA_REVIEW),
        )
        for kind, status in cases:
            with self.subTest(kind=kind):
                _run_id, entry, workspace = self._planned_run(
                    "admitted-%s" % kind
                )
                driver = drv.Driver(
                    entry["state_path"], runner=runners.MockRunner([])
                )
                skeleton = next(
                    unit for unit in driver.state["units"]
                    if unit["kind"] == st.UNIT_SKELETON
                )
                doc = next(
                    unit for unit in driver.state["units"]
                    if unit["kind"] == st.UNIT_SLICE_DOC
                )
                doc.update({"status": status, "artifact": "docs/slice.md"})
                doc["design_update"] = {
                    "editable_paths": [skeleton["artifact"]],
                }
                if kind == contracts.KIND_DELTA_REVIEW:
                    doc["fix_source"] = {
                        "type": "round",
                        "origin_type": "round",
                        "family": "codex",
                        "return_to": st.U_ROUNDS,
                    }
                driver._maybe_update_slices(
                    doc,
                    {
                        "slices": [{
                            "id": 1,
                            "title": "Independent producers",
                            "producer_task_executor": {
                                "draft_slice_note": {
                                    "task_executor": "worker"
                                },
                                "implement": {
                                    "task_executor": "brainstorming"
                                },
                            },
                        }],
                    },
                )
                frozen_prompt = "legacy frozen %s prompt" % kind
                family = st.current_family(driver.state, doc) or "codex"
                task = driver._admit_worker_task(
                    doc, kind, frozen_prompt, family
                )

                recovered = drv.Driver(
                    entry["state_path"], runner=runners.MockRunner([])
                )
                authority = {
                    "amendments": [],
                    "operator_complete": False,
                    "project_context": None,
                    "extensions": [],
                    "roots": [workspace],
                }
                seen = []

                def reached(_unit, _family, prompt, *_args, **_kwargs):
                    seen.append(prompt)
                    raise RuntimeError("review dispatch reached")

                report_patch = mock.patch.object(
                    recovered, "_report_call", side_effect=reached
                )
                if kind == contracts.KIND_REVIEW_ROUND:
                    evidence_patch = mock.patch.object(
                        recovered,
                        "_review_evidence_inputs",
                        return_value=(
                            "review-evidence", None, [], [workspace], [], False
                        ),
                    )
                    with report_patch, evidence_patch, self.assertRaisesRegex(
                        RuntimeError, "review dispatch reached"
                    ):
                        recovered._do_review_round()
                else:
                    authority_patch = mock.patch.object(
                        recovered,
                        "_worker_episode_authority",
                        return_value=authority,
                    )
                    with (
                        report_patch,
                        authority_patch,
                        mock.patch.object(
                            drv.gitops,
                            "worktree_diff",
                            return_value="pending delta",
                        ),
                        self.assertRaisesRegex(
                            RuntimeError, "review dispatch reached"
                        ),
                    ):
                        recovered._do_delta_review()

                self.assertEqual(len(seen), 1)
                self.assertTrue(seen[0].startswith(frozen_prompt + "\n\n"))
                self.assertEqual(
                    seen[0].count("WORKER EPISODE AUTHORITY REFRESH"), 1
                )
                self.assertNotIn("OPERATIVE SLICE PRODUCER PLAN", seen[0])
                self.assertEqual(
                    tasks.task_record(recovered.state, task["id"])["order"]
                    ["request"]["request"],
                    frozen_prompt,
                )

    def test_rejected_route_bodies_leave_state_unchanged(self):
        run_id, entry, _workspace = self._planned_run("rejected")
        route = self._route(run_id)
        cases = (
            ({"task_executor": "worker"}, 400, tasks.INVALID_TASK_REQUEST),
            (
                {"task_kind": "review_round", "task_executor": "worker"},
                400,
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                {"task_kind": "implement", "task_executor": "missing"},
                400,
                tasks.UNKNOWN_TASK_EXECUTOR,
            ),
            (
                {
                    "task_kind": "implement",
                    "task_executor": "brainstorming",
                    "configuration": {"closure_policy": "plurality"},
                },
                400,
                tasks.INVALID_TASK_REQUEST,
            ),
            (
                {"task_kind": "implement", "task_executor": "worker", "extra": 1},
                400,
                tasks.INVALID_TASK_REQUEST,
            ),
        )
        for payload, expected_status, expected_error in cases:
            before = st.load(entry["state_path"])
            status, response = self._json("POST", route, payload)
            self.assertEqual(status, expected_status, response)
            self.assertEqual(response["error"], expected_error)
            self.assertEqual(st.load(entry["state_path"]), before)

    def test_admission_freezes_only_matching_choice(self):
        run_id, entry, workspace = self._planned_run("freeze")
        route = self._route(run_id)
        status, _response = self._json(
            "POST",
            route,
            {
                "task_kind": "draft_slice_note",
                "task_executor": "brainstorming",
                "configuration": {"max_rounds": 4},
            },
        )
        self.assertEqual(status, 200)
        state = st.load(entry["state_path"])
        slice_plan = state["milestone"]["slices"][0]
        doc = next(u for u in state["units"] if u["kind"] == st.UNIT_SLICE_DOC)
        order = tasks.producer_order(
            slice_plan,
            contracts.KIND_DRAFT_SLICE_NOTE,
            _request(workspace, contracts.KIND_DRAFT_SLICE_NOTE, st.unit_key(doc)),
        )
        admitted = tasks.admit_task(
            state, order, {"seats": ["initial", "contrary", "dante"]}, workspace
        )
        doc["active_task"] = {
            "id": admitted["id"],
            "kind": contracts.KIND_DRAFT_SLICE_NOTE,
        }
        st.save(entry["state_path"], state)

        status, frozen = self._json(
            "POST",
            route,
            {"task_kind": "draft_slice_note", "task_executor": "worker"},
        )
        self.assertEqual((status, frozen["error"]), (409, tasks.TASK_SELECTION_FROZEN))
        status, sibling = self._json(
            "POST",
            route,
            {
                "task_kind": "implement",
                "task_executor": "brainstorming",
                "configuration": {"closure_policy": "majority"},
            },
        )
        self.assertEqual(status, 200, sibling)
        durable = tasks.task_record(st.load(entry["state_path"]), admitted["id"])
        self.assertEqual(durable, admitted)
        self.assertEqual(
            durable["order"]["configuration"],
            {"max_rounds": 4, "closure_policy": "unanimity"},
        )

    def test_terminal_failure_allows_distinct_successor_selection(self):
        run_id, entry, workspace = self._planned_run("successor")
        route = self._route(run_id)
        state = st.load(entry["state_path"])
        doc = next(u for u in state["units"] if u["kind"] == st.UNIT_SLICE_DOC)
        predecessor = tasks.admit_task(
            state,
            tasks.producer_order(
                state["milestone"]["slices"][0],
                contracts.KIND_DRAFT_SLICE_NOTE,
                _request(workspace, contracts.KIND_DRAFT_SLICE_NOTE, st.unit_key(doc)),
            ),
            {"worker": {"agent": "codex"}},
            workspace,
        )
        doc["active_task"] = {
            "id": predecessor["id"],
            "kind": contracts.KIND_DRAFT_SLICE_NOTE,
        }
        st.save(entry["state_path"], state)
        state = st.load(entry["state_path"])
        doc = next(u for u in state["units"] if u["kind"] == st.UNIT_SLICE_DOC)
        terminal = tasks.record_task_result(
            state, predecessor["id"], _failure()
        )
        doc.pop("active_task")
        st.fail_run(state, "producer failed", unit=doc)
        st.save(entry["state_path"], state)

        status, response = self._json(
            "POST",
            route,
            {
                "task_kind": "draft_slice_note",
                "task_executor": "brainstorming",
                "configuration": {"max_rounds": 2},
            },
        )
        self.assertEqual(status, 200, response)
        state = st.load(entry["state_path"])
        self.assertEqual(tasks.task_record(state, predecessor["id"]), terminal)
        st.resume_run(state)
        successor = tasks.admit_task(
            state,
            tasks.producer_order(
                state["milestone"]["slices"][0],
                contracts.KIND_DRAFT_SLICE_NOTE,
                _request(workspace, contracts.KIND_DRAFT_SLICE_NOTE, st.unit_key(doc)),
            ),
            {"seats": ["initial", "contrary", "dante"]},
            workspace,
        )
        self.assertNotEqual(successor["id"], predecessor["id"])
        self.assertEqual(successor["order"]["task_executor"], "brainstorming")
        self.assertEqual(successor["order"]["configuration"]["max_rounds"], 2)

    def test_review_and_fixer_orders_remain_worker_only(self):
        selected = {
            "id": 1,
            "title": "one",
            "producer_task_executor": {
                kind: {"task_executor": "brainstorming"}
                for kind in tasks.PRODUCER_TASK_KINDS
            },
        }
        for kind in (
            contracts.KIND_DRAFT_SKELETON,
            contracts.KIND_REVIEW_ROUND,
            contracts.KIND_DELTA_REVIEW,
            contracts.KIND_FIX_FINDINGS,
        ):
            with self.subTest(kind=kind), self.assertRaises(tasks.TaskRequestError):
                tasks.producer_order(selected, kind, _request("/workspace", kind, "unit"))

        _run_id, entry, _workspace = self._planned_run("worker-only", [selected])
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        implementation = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SLICE_IMPL
        )
        review = driver._admit_worker_task(
            implementation,
            contracts.KIND_REVIEW_ROUND,
            "KIND: review_round\n",
            "codex",
        )
        self.assertEqual(review["order"]["task_executor"], "worker")


if __name__ == "__main__":
    unittest.main()
