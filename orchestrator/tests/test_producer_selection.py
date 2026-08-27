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
from orchestrator import canonical_plan
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import model_profiles
from orchestrator import registry
from orchestrator import runners
from orchestrator import service
from orchestrator import staffing as stf
from orchestrator import state as st
from orchestrator import tasks

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    init_state,
    make_config,
    ok,
    step,
    write_file,
)


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


def material_document(name, materials):
    """A complete document carrying the operator's own material vocabulary.

    Built from the seed so only the vocabulary differs from what every other
    test staffs with; `review` keeps a single seat so a two-family run
    reviews without a declared split refusing anything.
    """
    document = stf.default_document_seed()
    document["name"] = name
    document["materials"] = copy.deepcopy(materials)
    document["assignment"]["review"] = {"1": 1}
    return document


def canonical_skeleton_step():
    planned = {
        "id": 1,
        "title": "One",
        "intent": "Exercise canonical producer selection.",
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }
    document = (
        "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
        % json.dumps({"slices": [planned]})
    )
    return step(
        "draft_skeleton",
        ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
        ),
        side_effect=write_file("docs/skeleton.md", document),
    )


class PlannerMaterialCatalogueTest(DriverTestCase):
    """The routed skeleton charge has no legacy staffing-material input."""

    VOCABULARY = {
        "research": {"examples": ["reading unfamiliar code",
                                  "tracing an unclear failure"]},
        "plumbing": {"examples": ["wiring one existing seam"]},
    }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="planner-material-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        model_profiles.ensure_default(self.home)
        stf.ensure_documents(self.home)

    def bound_to(self, document, name="ws"):
        """A homed run whose one session points at *document*."""
        stf.save(self.home, document)
        workspace = os.path.join(self.tmp.name, name)
        os.makedirs(workspace, exist_ok=True)
        path = init_state(workspace, make_config())
        drv.open_run_staffing_session(
            path, self.home, document["name"], "medium"
        )
        return path

    def driver_for(self, path, script=()):
        return drv.Driver(
            path,
            runner=runners.MockRunner(list(script)),
            model_profiles_home=self.home,
        )

    @staticmethod
    def catalogue_in(prompt):
        """The material catalogue one assembled prompt actually carries."""
        block = prompt.split("MATERIAL CATALOGUE (name to usage phrases):\n", 1)
        if len(block) == 1:
            return None
        return json.JSONDecoder().raw_decode(block[1])[0]

    def test_legacy_material_is_neither_solicited_nor_projected(self):
        path = self.bound_to(material_document("vocab", self.VOCABULARY))
        subject = self.driver_for(path, [canonical_skeleton_step()])

        subject.step()
        drafted = subject.runner.calls[-1]
        self.assertEqual(drafted[1], "draft_skeleton")
        self.assertIsNone(self.catalogue_in(drafted[2]))
        self.assertNotIn("reading unfamiliar code", drafted[2])
        self.assertNotIn("material", subject.state["milestone"]["slices"][0])

    def test_legacy_material_is_readable_but_removed_from_projection(self):
        base = {
            "id": 1,
            "title": "one",
            "intent": "Exercise material projection.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "agent_call",
            },
        }

        for value in (
            "research",
            "no-such-material",
            json.loads('"re\\ud800\\udc00search"'),
        ):
            planned = copy.deepcopy(base)
            planned["material"] = value
            document = (
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": [planned]}, ensure_ascii=True)
            )
            with self.subTest(material=value):
                with self.assertRaises(canonical_plan.CanonicalPlanError):
                    canonical_plan.validate_canonical_plan(document)
                validated = canonical_plan.read_canonical_plan(document)
                self.assertNotIn("material", validated["slices"][0])
                self.assertNotIn("material", validated["projection"][0])

        absent_document = (
            "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps({"slices": [base]})
        )
        absent = canonical_plan.validate_canonical_plan(absent_document)
        self.assertNotIn("material", absent["projection"][0])

        for value in (None, True, "", ["research"], {"name": "research"}, 3):
            planned = copy.deepcopy(base)
            planned["material"] = value
            document = (
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": [planned]})
            )
            with self.subTest(material=value), self.assertRaises(
                canonical_plan.CanonicalPlanError
            ):
                canonical_plan.read_canonical_plan(document)


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
            slices or [{
                "id": 1,
                "title": "Independent producers",
                "intent": "Exercise current producer selection.",
                "producer_task_executor": {
                    "draft_slice_note": {"task_executor": "agent_call"},
                    "implement": {"task_executor": "agent_call"},
                },
            }]
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

    def test_legacy_plan_controls_are_absent_while_projection_and_tasks_remain(
        self,
    ):
        planned = [{
            "id": 1,
            "title": "Canonical projection",
            "intent": "Exercise canonical projection and order selection.",
            "material": "code",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "agent_call"},
            },
        }]
        run_id, entry, workspace = self._planned_run("retired-controls", planned)
        before = st.load(entry["state_path"])

        for suffix, payload in (
            ("producer", {
                "task_kind": "implement",
                "task_executor": "brainstorming",
            }),
            ("material", {"material": "research"}),
        ):
            with self.subTest(suffix=suffix):
                status, response = self._json(
                    "POST",
                    "/api/runs/%s/slices/1/%s" % (run_id, suffix),
                    payload,
                )
                self.assertEqual(status, 404, response)
                self.assertEqual(response["error"], "not found")
                self.assertEqual(st.load(entry["state_path"]), before)

        status, detail = self._json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200, detail)
        self.assertEqual(
            detail["summary"]["slices"], tasks.effective_slice_plan(planned)
        )
        order = tasks.producer_order(
            planned[0],
            contracts.KIND_IMPLEMENT,
            _request(workspace, contracts.KIND_IMPLEMENT, "slice_impl-01"),
        )
        self.assertEqual(order["task_executor"], "agent_call")
        self.assertNotIn("staffing_material", order)
        for owner, name in (
            (service, "set_slice_producer"),
            (service, "set_slice_material"),
            (tasks, "update_slice_producer"),
            (tasks, "update_slice_material"),
            (drv.Driver, "_adopt_live_producer_updates"),
        ):
            self.assertFalse(hasattr(owner, name), name)

    def test_canonical_plan_validates_complete_producer_map_from_catalogue(self):
        catalogue = {
            entry["id"] for entry in tasks.task_executor_catalogue()
        }
        self.assertIn("agent_call", catalogue)
        self.assertIn("brainstorming", catalogue)

        planned = {
            "id": 1,
            "title": "one",
            "intent": "Choose both current producers.",
            "producer_task_executor": {
                "draft_slice_note": "agent_call",
                "implement": "brainstorming",
            },
        }

        def document(slice_plan):
            return (
                "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
                % json.dumps({"slices": [slice_plan]})
            )

        validated = canonical_plan.validate_canonical_plan(document(planned))
        self.assertEqual(
            validated["projection"][0]["producer_task_executor"],
            {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        )

        invalid_maps = (
            {"draft_slice_note": "agent_call"},
            {
                "draft_slice_note": "agent_call",
                "implement": "brainstorming",
                "review_round": "agent_call",
            },
            {
                "draft_slice_note": "agent_call",
                "implement": "no-such-executor",
            },
            {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": "brainstorming",
            },
        )
        for producer_map in invalid_maps:
            malformed = copy.deepcopy(planned)
            malformed["producer_task_executor"] = producer_map
            with self.subTest(producer_map=producer_map), self.assertRaises(
                canonical_plan.CanonicalPlanError
            ):
                canonical_plan.validate_canonical_plan(document(malformed))

    def test_standalone_partial_maps_use_generic_order_defaults(self):
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
        agent_call = {"task_executor": "agent_call"}
        self.assertEqual(
            effective[0]["producer_task_executor"],
            {"draft_slice_note": agent_call, "implement": agent_call},
        )
        self.assertEqual(
            effective[1]["producer_task_executor"]["draft_slice_note"],
            agent_call,
        )
        self.assertEqual(
            effective[1]["producer_task_executor"]["implement"]["configuration"],
            {"closure_policy": "majority"},
        )

        state = st.new_state("goal", "/workspace", {"families_order": ["codex"]})
        state["milestone"]["slices"] = source
        self.assertEqual(st.summary(state)["slices"], effective)
        self.assertEqual(state["milestone"]["slices"], before)

    @unittest.skipIf(st.fcntl is None, "fcntl unavailable on this platform")
    def test_run_refuses_a_concurrent_state_change(self):
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

    def test_skeleton_review_context_uses_current_producer_projection(self):
        _run_id, entry, _workspace = self._planned_run("review-plan", [{
            "id": 1,
            "title": "Independent producers",
            "intent": "Use the selected implementation producer.",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "brainstorming"},
            },
        }])
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
        self.assertEqual(set(context), {"producer_task_executor_by_slice"})

    def test_worker_adapter_does_not_claim_a_brainstorming_choice(self):
        initial = [{
            "id": 1,
            "title": "Independent producers",
            "intent": "Delegate the slice note to Brainstorming.",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "brainstorming"},
                "implement": {"task_executor": "agent_call"},
            },
        }]
        _run_id, entry, _workspace = self._planned_run(
            "brainstorming-owned-elsewhere", initial
        )
        driver = drv.Driver(entry["state_path"], runner=runners.MockRunner([]))
        unit = next(
            candidate for candidate in driver.state["units"]
            if candidate["kind"] == st.UNIT_SLICE_DOC
        )
        with self.assertRaisesRegex(
            st.IllegalTransition, "not an agent-call task"
        ):
            driver._admit_worker_task(
                unit,
                contracts.KIND_DRAFT_SLICE_NOTE,
                "draft the note",
                "codex",
            )
        durable = st.load(entry["state_path"])
        self.assertIsNone(durable["failure"])
        self.assertEqual(tasks.task_records(durable), [])

    def test_non_producer_jobs_do_not_adopt_slice_producer_choices(self):
        selected = {
            "id": 1,
            "title": "one",
            "intent": "Keep judgment on its dedicated agent route.",
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
        self.assertEqual(review["order"]["task_executor"], "agent_call")


if __name__ == "__main__":
    unittest.main()
