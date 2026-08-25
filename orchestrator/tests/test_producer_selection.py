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

from orchestrator import brainstorming_milestone
from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import model_profiles
from orchestrator import prompts
from orchestrator import registry
from orchestrator import runners
from orchestrator import service
from orchestrator import staffing as stf
from orchestrator import state as st
from orchestrator import tasks

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    finding,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    step,
    triaged,
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


class PlannerMaterialCatalogueTest(DriverTestCase):
    """Slice 9: what a plan-authoring prompt shows, read live per prompt."""

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

    def test_planning_prompts_and_slice_contract_carry_material_catalogue(self):
        path = self.bound_to(material_document("vocab", self.VOCABULARY))
        script = [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "One", "material": "research"}]),
                 side_effect=write_file("docs/skeleton.md", "# Skeleton\n")),
            step("review_round",
                 report("review_round", [finding("F1", "no non-goals")])),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "no non-goals")],
                        files_changed=["docs/skeleton.md"]),
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\n## Non-goals\n")),
        ]
        subject = self.driver_for(path, script)

        # The INITIAL plan-authoring prompt: exactly the document's own
        # names and usage phrases, in the document's own order.
        subject.step()
        drafted = subject.runner.calls[-1]
        self.assertEqual(drafted[1], "draft_skeleton")
        self.assertEqual(
            self.catalogue_in(drafted[2]),
            {"research": ["reading unfamiliar code",
                          "tracing an unclear failure"],
             "plumbing": ["wiring one existing seam"]},
        )
        # The planner's proposal survives validation and installation.
        self.assertEqual(
            subject.state["milestone"]["slices"],
            [{"id": 1, "title": "One", "material": "research"}],
        )

        # A COMPLETED document edit reaches the next such prompt; the one
        # already dispatched keeps what it carried.
        edited = material_document(
            "vocab",
            {"research": {"examples": ["reading unfamiliar code"]},
             "cleanup": {"examples": ["deleting dead machinery"]}},
        )
        stf.save(self.home, edited)
        for _ in range(12):
            if any(call[1] == contracts.KIND_FIX_FINDINGS
                   for call in subject.runner.calls):
                break
            subject.step()
        fixer = next(call for call in subject.runner.calls
                     if call[1] == contracts.KIND_FIX_FINDINGS)
        self.assertEqual(
            self.catalogue_in(fixer[2]),
            {"research": ["reading unfamiliar code"],
             "cleanup": ["deleting dead machinery"]},
        )
        self.assertEqual(
            self.catalogue_in(drafted[2])["plumbing"],
            ["wiring one existing seam"],
        )

    def test_unreadable_guidance_leaves_the_catalogue_empty(self):
        for repointed in ("no-such-document", None):
            with self.subTest(repointed=repointed):
                path = self.bound_to(
                    material_document("vocab", self.VOCABULARY),
                    name="unreadable-%s" % (repointed or "unbound"),
                )
                state = st.load(path)
                session = st.staffing_session(state)
                if repointed is None:
                    # A run that holds no session at all: there is no
                    # referenced document, so there is no vocabulary either.
                    state.pop(st.STAFFING_SESSION_KEY)
                    st.save(path, state)
                else:
                    stf.edit_session(
                        self.home, session, {"document": repointed}
                    )
                subject = self.driver_for(
                    path,
                    [step("draft_skeleton",
                          ok("draft_skeleton", artifact="docs/skeleton.md",
                             slices=[{"id": 1, "title": "One"}]),
                          side_effect=write_file(
                              "docs/skeleton.md", "# Skeleton\n"))],
                )
                self.assertEqual(subject._planning_materials(), {})
                subject.step()
                drafted = subject.runner.calls[-1]
                self.assertEqual(self.catalogue_in(drafted[2]), {})
                # Guidance is not a dispatch: nothing failed and the call ran.
                self.assertIsNone(subject.state["failure"])
                self.assertEqual(drafted[1], "draft_skeleton")

    def test_guidance_a_prompt_must_escape_is_still_carried_exactly(self):
        # JSON admits an escaped unpaired surrogate; the store keeps it and
        # hands it back as an ordinary `str`, so this document is valid,
        # saved and reloaded. No UTF-8 encoder emits one, so a prompt
        # quoting it RAW would be a request no task order accepts and the
        # run would stop at admission with nothing dispatched. That is a
        # question about how to QUOTE the vocabulary, not a licence to
        # supply less of it: the block falls back to the same ASCII escape
        # the document's own stored bytes carry, so a readable document
        # still supplies every name it validated.
        unwritable = material_document(
            "unwritable",
            {"research": {"examples": ["reading \ud800 code"]},
             "plumbing": {"examples": ["wiring one existing seam"]}},
        )
        # The store really does accept and return it: what is being tested
        # is this run's quoting, not the document store's validation.
        stf.save(self.home, unwritable)
        self.assertEqual(
            stf.load(self.home, "unwritable")["materials"]["research"],
            {"examples": ["reading \ud800 code"]},
        )
        path = self.bound_to(unwritable, name="unwritable")
        subject = self.driver_for(
            path,
            [step("draft_skeleton",
                  ok("draft_skeleton", artifact="docs/skeleton.md",
                     slices=[{"id": 1, "title": "One"}]),
                  side_effect=write_file("docs/skeleton.md", "# Skeleton\n"))],
        )
        self.assertEqual(
            subject._planning_materials(), unwritable["materials"]
        )
        subject.step()
        drafted = subject.runner.calls[-1]
        self.assertEqual(drafted[1], "draft_skeleton")
        # Exactly the validated mapping, never a filtered or empty one: the
        # ordinary name is not collateral damage of the exotic one, and the
        # exotic one round-trips to the very string the document holds.
        self.assertEqual(
            self.catalogue_in(drafted[2]),
            {"research": ["reading \ud800 code"],
             "plumbing": ["wiring one existing seam"]},
        )
        self.assertIn("wiring one existing seam", drafted[2])
        self.assertIn("reading \\ud800 code", drafted[2])
        self.assertIsNone(subject.state["failure"])
        # The prompt that actually went out is a request an order accepts.
        drafted[2].encode("utf-8")

    def test_a_proposal_continuation_that_may_plan_reads_the_live_vocabulary(
        self,
    ):
        # A skeleton fixer's queued finding may open a focused discussion
        # that returns a PROPOSAL rather than a design amendment. It then
        # finishes the same task, and its frozen request still tells it to
        # return the FULL updated `slices` array, which this driver installs.
        # So the continuation is a plan-authoring prompt: it needs the pair
        # read at ITS boundary, not only the one quoted inside the request
        # its first call was dispatched with.
        path = self.bound_to(
            material_document("vocab", self.VOCABULARY), name="continuation"
        )
        subject = self.driver_for(path)
        unit = st.current_unit(subject.state)
        self.assertEqual(unit["kind"], st.UNIT_SKELETON)
        frozen = prompts.build_fix_findings(
            "codex", subject.workspace, subject.state["goal"],
            "milestone skeleton",
            [{"id": "F1", "severity": "P2", "summary": "the table is wrong"}],
            subject._registry(), "claude", "consult",
            unit_kind="skeleton",
            materials={"retired": {"examples": ["work nobody asks for now"]}},
        )
        self.assertIn("FULL updated `slices`", frozen)
        self.assertIn("work nobody asks for now", frozen)
        subject.state["tasks"] = [{
            "id": "task-1",
            "order": {
                "request": {
                    "request": frozen,
                    "context": {"worker_validation": {}},
                },
            },
        }]
        unit["brainstorming_wait"] = {
            "session_id": "b1",
            "references": [],
            "signal": {
                "status": "need_rethink",
                "kind": contracts.KIND_FIX_FINDINGS,
                "request": "Which reading of the boundary governs?",
                "finding": {"id": "F1", "summary": "the table is wrong"},
                "target_path": "docs/skeleton.md",
                "max_rounds": 20,
                "result_mode": contracts.RETHINK_RESULT_PROPOSAL,
            },
            "origin": {
                "unit": st.unit_key(unit),
                "kind": contracts.KIND_FIX_FINDINGS,
                "family": "codex",
                "model": "gpt-5.6-sol",
                "effort": "high",
                "raw_name": "skeleton-fix1",
                "provider_session_ref": "codex-thread-1",
                "task_id": "task-1",
                "duration_s": 1.0,
                "pre_snapshot": {},
            },
        }
        handoff = {
            "session_id": "b1",
            "accepted_target_revision": 2,
            "result": {"outcome": "success"},
            "retained_target": {
                "exists": True,
                "encoding": "utf-8",
                "content": "Read the boundary the narrower way.",
            },
        }
        subject._call = mock.Mock(return_value=(
            {"status": "ok", "kind": contracts.KIND_FIX_FINDINGS,
             "findings": [triaged("F1", "fixed", "the table is wrong")],
             "files_changed": ["docs/skeleton.md"]},
            runners.RunnerResult("{}", 0, 0.2),
            "raw/continued.txt",
        ))

        with mock.patch.object(
            brainstorming_milestone, "terminal_handoff", return_value=handoff
        ), mock.patch.object(
            brainstorming_milestone, "prompt_handoff", return_value=handoff
        ):
            subject._do_brainstorming_wait()

        prompt = subject._call.call_args.args[1]
        # A proposal grants no design edit: this is the plain continuation
        # the earlier reviewed gate left without a live catalogue.
        self.assertIsNone(unit.get("design_update"))
        # The quotation is still byte-for-byte the request that was
        # dispatched, retired vocabulary and all.
        self.assertTrue(prompt.startswith(frozen.rstrip()))
        self.assertIn("work nobody asks for now", prompt)
        # ... and beside it, read at THIS boundary, the document's current
        # pair, named as the one that governs.
        self.assertEqual(
            self.catalogue_in(
                prompt[prompt.rindex("PLANNING VOCABULARY PRECEDENCE"):]
            ),
            {"research": ["reading unfamiliar code",
                          "tracing an unclear failure"],
             "plumbing": ["wiring one existing seam"]},
        )
        self.assertEqual(prompt.count("PLANNING VOCABULARY PRECEDENCE"), 1)
        self.assertEqual(prompt.count("TASKEXECUTOR CATALOGUE"), 2)

        # The decision is what this driver can INSTALL, not the result mode:
        # the skeleton's own fixer always, a unit holding the skeleton among
        # its editable design paths always, and nothing else.
        self.assertTrue(subject._continuation_may_plan_slices(unit))
        other = {"kind": st.UNIT_SLICE_IMPL, "slice_id": 1}
        self.assertFalse(subject._continuation_may_plan_slices(other))
        other["design_update"] = {
            "editable_paths": [subject._skeleton_artifact()]
        }
        self.assertTrue(subject._continuation_may_plan_slices(other))

    def test_slice_contract_takes_a_string_or_nothing_and_never_migrates(self):
        base = {
            "status": "ok",
            "kind": contracts.KIND_DRAFT_SKELETON,
            "artifact": "docs/skeleton.md",
            "slices": [{"id": 1, "title": "one"}],
        }
        # The last one arrives as JSON writes it — two escapes, a surrogate
        # PAIR — and decodes to the single scalar U+10000. The rule is on the
        # decoded value, so a spelling that looks like the refusal below is
        # admitted, and the pinned fact is the character, not the escape.
        for value in (
            "research",
            "no-such-material",
            "",
            json.loads('"re\\ud800\\udc00search"'),
        ):
            response = copy.deepcopy(base)
            response["slices"][0]["material"] = value
            with self.subTest(material=value):
                contracts.validate_worker_output(
                    response, contracts.KIND_DRAFT_SKELETON
                )
                # Verbatim, including a name no document carries: the
                # router owns what a material MEANS.
                self.assertEqual(response["slices"][0]["material"], value)
        for value in (None, True, ["research"], {"name": "research"}, 3):
            response = copy.deepcopy(base)
            response["slices"][0]["material"] = value
            with self.subTest(material=value), self.assertRaises(
                contracts.ContractError
            ):
                contracts.validate_worker_output(
                    response, contracts.KIND_DRAFT_SKELETON
                )

        # JSON hands back an escaped unpaired surrogate as an ordinary str,
        # but no UTF-8 encoder can emit it, so "preserved verbatim in state"
        # is unkeepable for it. Refused at admission — the repairable answer
        # the malformed shapes get — rather than installed and then crashing
        # the save that would have made the planner's result durable.
        response = copy.deepcopy(base)
        response["slices"][0] = json.loads(
            '{"id": 1, "title": "one", "material": "re\\ud800search"}'
        )
        with self.assertRaises(contracts.ContractError):
            contracts.validate_worker_output(
                response, contracts.KIND_DRAFT_SKELETON
            )
        state = st.new_state("goal", "/workspace", {"families_order": ["codex"]})
        state["milestone"]["slices"] = [copy.deepcopy(response["slices"][0])]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnicodeEncodeError):
                st.save_new(os.path.join(tmp, "state.json"), state)

        source = [
            {"id": 1, "title": "absent"},
            {"id": 2, "title": "proposed", "material": "research"},
        ]
        before = copy.deepcopy(source)
        effective = tasks.effective_slice_plan(source)
        self.assertEqual(source, before)
        self.assertNotIn("material", effective[0])
        self.assertEqual(effective[1]["material"], "research")
        state = st.new_state("goal", "/workspace", {"families_order": ["codex"]})
        state["milestone"]["slices"] = source
        self.assertEqual(st.summary(state)["slices"], effective)
        self.assertEqual(state["milestone"]["slices"], before)


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

    def test_legacy_plan_controls_are_absent_while_projection_and_tasks_remain(
        self,
    ):
        planned = [{
            "id": 1,
            "title": "Canonical projection",
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
        self.assertEqual(detail["summary"]["slices"], planned)
        order = tasks.producer_order(
            planned[0],
            contracts.KIND_IMPLEMENT,
            _request(workspace, contracts.KIND_IMPLEMENT, "slice_impl-01"),
        )
        self.assertEqual(order["task_executor"], "agent_call")
        self.assertEqual(order["staffing_material"], "code")
        for owner, name in (
            (service, "set_slice_producer"),
            (service, "set_slice_material"),
            (tasks, "update_slice_producer"),
            (tasks, "update_slice_material"),
            (drv.Driver, "_adopt_live_producer_updates"),
        ):
            self.assertFalse(hasattr(owner, name), name)

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
                        "draft_slice_note": {"task_executor": "agent_call"},
                        "implement": {
                            "task_executor": "brainstorming",
                            "configuration": {"max_rounds": 24},
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
            {"max_rounds": 24},
        )

        invalid_maps = (
            {"review_round": {"task_executor": "agent_call"}},
            {"implement": {"task_executor": "agent_call", "extra": True}},
            {
                "implement": {
                    "task_executor": "brainstorming",
                    # not an integer: a low integer is raised to the floor,
                    # not refused
                    "configuration": {"max_rounds": "six"},
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

    def test_every_review_covering_skeleton_receives_operative_plan(self):
        _run_id, entry, _workspace = self._planned_run("review-plan", [{
            "id": 1,
            "title": "Independent producers",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {
                    "task_executor": "brainstorming",
                    "configuration": {"max_rounds": 22},
                },
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
            self.assertIn("directly with this canonical projection", prompt)

        doc = next(
            unit for unit in driver.state["units"]
            if unit["kind"] == st.UNIT_SLICE_DOC
        )
        self.assertIsNone(driver._producer_review_context(doc))
        doc["design_update"] = {
            "changed_paths": [skeleton["artifact"]],
        }
        self.assertEqual(driver._producer_review_context(doc), context)

    def test_worker_adapter_does_not_claim_a_brainstorming_choice(self):
        initial = [{
            "id": 1,
            "title": "Independent producers",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "brainstorming"},
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
                        "draft_slice_note": {"task_executor": "agent_call"},
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
        self.assertEqual(set(context), {"producer_task_executor_by_slice"})
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
                                    "task_executor": "agent_call"
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

    def test_retired_producer_id_projects_without_rewriting_its_plan(self):
        """A plan written before the rename projects without mutation."""
        stored = [{
            "id": 1,
            "title": "Planned before the rename",
            "producer_task_executor": {
                "draft_slice_note": {"task_executor": "worker"},
                "implement": {"task_executor": "worker"},
            },
        }]
        run_id, entry, _workspace = self._planned_run("retired-plan", stored)
        agent_call = {"task_executor": "agent_call"}

        status, detail = self._json("GET", "/api/runs/%s" % run_id)
        self.assertEqual(status, 200, detail)
        self.assertEqual(
            detail["summary"]["slices"][0]["producer_task_executor"],
            {"draft_slice_note": agent_call, "implement": agent_call},
        )
        self.assertEqual(
            st.load(entry["state_path"])["milestone"]["slices"], stored
        )
        durable = st.load(entry["state_path"])["milestone"]["slices"][0]
        self.assertEqual(
            durable["producer_task_executor"]["draft_slice_note"],
            {"task_executor": "worker"},
        )
        self.assertEqual(
            tasks.effective_slice_producers(durable)["draft_slice_note"],
            agent_call,
        )

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
        self.assertEqual(review["order"]["task_executor"], "agent_call")


if __name__ == "__main__":
    unittest.main()
