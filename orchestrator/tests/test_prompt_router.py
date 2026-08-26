"""Focused proof for canonical charge resolution and assembled prompt JSON."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator import prompt_router
from orchestrator import prompt_sets


CORPUS = (
    Path(__file__).resolve().parents[2]
    / "implementation/brainstorming/prompt-router/adapted-kinds"
)
EXPECTED_GOLDENS = frozenset((
    "brainstorming/discussion_turn.contrary.prompt.txt",
    "brainstorming/discussion_turn.prompt.txt",
    "brainstorming/questioner_turn.prompt.txt",
    "milestone/delta_review.prompt.txt",
    "milestone/draft_skeleton.prompt.txt",
    "milestone/draft_slice_note.prompt.txt",
    "milestone/fix_findings.prompt.txt",
    "milestone/implement.prompt.txt",
    "milestone/merge_repair.agent_call.prompt.txt",
    "milestone/merge_repair.prompt.txt",
    "milestone/reclassify.prompt.txt",
    "milestone/review_round.prompt.txt",
    "milestone/suite_checkpoint.prompt.txt",
))
GLOBAL_QUESTION_IDS = (
    "guarantee_fit",
    "cheapest_sufficient",
    "rare_failure_posture",
)


def validation_values(prompt_set):
    """Supply opaque fixture values for every declaration in the seed."""
    names = set()
    fixed = {"kind", "role"}

    def walk(value):
        if isinstance(value, dict):
            for item in value.get("variables", ()):
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    names.add(item["name"])
            defaults = value.get("defaults")
            if isinstance(defaults, dict):
                fixed.update(defaults)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(prompt_set.documents)
    return {name: "validation value" for name in names - fixed}


class PromptRouterTest(unittest.TestCase):
    def setUp(self):
        self.prompt_set = prompt_sets.default_seed()

    def values(self, job):
        values = validation_values(self.prompt_set)
        if job != "draft_skeleton@skeleton":
            values.pop("task_executor_catalogue", None)
        return values

    @staticmethod
    def text(prompt):
        units = prompt["instructions"] + prompt["output_contract"]
        return "\n".join(line for unit in units for line in unit["text"])

    @staticmethod
    def write_set(home, name, documents):
        directory = Path(prompt_sets.prompt_set_dir(home, name))
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
        return directory

    @staticmethod
    def marked_documents(marker):
        documents = copy.deepcopy(prompt_sets.default_seed().documents)
        documents["shared/shared.json"]["material_layers"] = {
            "implement@slice_impl": {
                "code": {
                    "instructions": {"parts": [{
                        "text": ["Layer instruction"], "variables": []
                    }]},
                    "questions": {
                        "intro": ["Layer questions"],
                        "items": [{
                            "id": "layer_question",
                            "text": "Was the layer assembled?",
                        }],
                    },
                    "output_contract": {"sections": [{
                        "id": "layer_result",
                        "text": ["Return the layer result."],
                        "variables": [],
                    }]},
                }
            }
        }

        def mark(value):
            if isinstance(value, dict):
                if (
                    isinstance(value.get("text"), list)
                    and isinstance(value.get("variables"), list)
                ):
                    value["text"].append(marker)
                if set(value) == {"id", "text"}:
                    value["text"] = "%s %s" % (marker, value["text"])
                questions = value.get("questions")
                if (
                    isinstance(questions, dict)
                    and isinstance(questions.get("intro"), list)
                ):
                    questions["intro"] = [
                        "%s %s" % (marker, line)
                        for line in questions["intro"]
                    ]
                for item in value.values():
                    mark(item)
            elif isinstance(value, list):
                for item in value:
                    mark(item)

        mark(documents)
        return documents

    def assert_prompt_marked(self, prompt, marker):
        for unit in prompt["instructions"] + prompt["output_contract"]:
            self.assertIn(marker, unit["text"])
        for line in prompt["questions"]["intro"]:
            self.assertIn(marker, line)
        for question in prompt["questions"]["items"]:
            self.assertIn(marker, question["text"])

    def test_canonical_plan_corpus_seed_and_goldens_are_recaptured(self):
        reviewed = {
            member: json.loads((CORPUS / member).read_text(encoding="utf-8"))
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        self.assertEqual(reviewed, self.prompt_set.documents)
        corpus_text = json.dumps(reviewed, sort_keys=True)
        self.assertNotIn("rethink@doc", corpus_text)
        self.assertNotIn("rethink@impl", corpus_text)
        self.assertNotIn("plan_authoring_authorized", corpus_text)
        self.assertNotIn("design_update", corpus_text)
        merge_repair = reviewed["milestone/merge_repair.json"]
        repair_variables = {
            variable["name"]
            for part in merge_repair["instructions"]["parts"]
            for variable in part.get("variables", [])
        }
        self.assertEqual(
            repair_variables,
            {
                "accepted_revision",
                "opening_reconciliation_account",
                "required_outcome",
                "source_base_revision",
                "source_base_role",
                "source_kind",
                "wipe_boundary",
                "wipe_reason",
            },
        )
        planning_refs = []
        for member, document in reviewed.items():
            if member == "shared/shared.json":
                continue
            for part in document["instructions"]["parts"]:
                if part.get("ref") == "producer_planning":
                    planning_refs.append(member)
            contracts = json.dumps(document["output_contract"])
            self.assertNotIn('"slices"', contracts)
        self.assertEqual(planning_refs, ["milestone/draft_skeleton.json"])

        actual_goldens = {
            path.relative_to(CORPUS).as_posix()
            for path in CORPUS.rglob("*.prompt.txt")
        }
        self.assertEqual(actual_goldens, EXPECTED_GOLDENS)
        goldens = {
            member: (CORPUS / member).read_bytes()
            for member in EXPECTED_GOLDENS
        }
        with tempfile.TemporaryDirectory(
            prefix="orch-prompt-goldens-"
        ) as rendered_dir:
            subprocess.run(
                [
                    "python3",
                    str(CORPUS / "render_examples.py"),
                    "--output-dir",
                    rendered_dir,
                ],
                cwd=CORPUS.parents[3],
                check=True,
                capture_output=True,
                text=True,
            )
            rendered_root = Path(rendered_dir)
            emitted = {
                path.relative_to(rendered_root).as_posix()
                for path in rendered_root.rglob("*.prompt.txt")
            }
            self.assertEqual(emitted, EXPECTED_GOLDENS)
            self.assertEqual(
                goldens,
                {
                    member: (rendered_root / member).read_bytes()
                    for member in emitted
                },
            )

    def test_merge_repair_route_assembles_and_renders(self):
        job = "merge_repair@workspace"
        values = self.values(job)
        prompt = prompt_router.assemble(
            self.prompt_set,
            job=job,
            executor="agent_call",
            material="code",
            values=values,
        )
        self.assertEqual(prompt["kind"], "merge_repair")
        self.assertTrue(prompt_router.render(prompt, values))

    def test_canonical_charge_matrix_and_session_target_mounts(self):
        self.assertEqual(len(prompt_router.DIRECT_ROUTES), 15)
        for job, (kind, unused_target) in prompt_router.DIRECT_ROUTES.items():
            del unused_target
            with self.subTest(job=job):
                prompt = prompt_router.assemble(
                    self.prompt_set,
                    job=job,
                    executor="agent_call",
                    material="code",
                    values=self.values(job),
                )
                self.assertEqual(prompt["kind"], kind)
                ids = [item["id"] for item in prompt["questions"]["items"]]
                for question_id in GLOBAL_QUESTION_IDS:
                    self.assertEqual(ids.count(question_id), 1)

        cases = (
            ("draft_slice_note@slice_doc", None, "initial_position", True,
             "TWO-REGISTER DOCUMENT", "IMPLEMENTATION RULES"),
            ("implement@slice_impl", None, "initial_position", True,
             "IMPLEMENTATION RULES", "TWO-REGISTER DOCUMENT"),
            ("rethink", "document", "contrary_position", False,
             "EVIDENCE", "IMPLEMENTATION RULES"),
            ("rethink", "implementation", "common_sense", False,
             "REUSE GATE", "ALTITUDE\n"),
        )
        for job, artifact_type, role, lead, present, absent in cases:
            with self.subTest(job=job, role=role, artifact_type=artifact_type):
                prompt = prompt_router.assemble(
                    self.prompt_set,
                    job=job,
                    executor="brainstorming",
                    material="code",
                    values=self.values(job),
                    role=role,
                    lead=lead,
                    artifact_type=artifact_type,
                )
                text = self.text(prompt)
                self.assertIn(present, text)
                self.assertNotIn(absent, text)
                ids = [item["id"] for item in prompt["questions"]["items"]]
                for question_id in GLOBAL_QUESTION_IDS:
                    self.assertEqual(ids.count(question_id), 1)
        lead = prompt_router.assemble(
            self.prompt_set,
            job="draft_slice_note@slice_doc",
            executor="brainstorming",
            material="code",
            values=self.values("draft_slice_note@slice_doc"),
            role="initial_position",
            lead=True,
        )
        self.assertIn(
            "due_diligence_count",
            [item["id"] for item in lead["questions"]["items"]],
        )

        invalid = self.values("implement@slice_impl")
        invalid["plan_authoring_authorized"] = True
        with self.assertRaises(prompt_router.PromptRouterError):
            prompt_router.assemble(
                self.prompt_set,
                job="implement@slice_impl",
                executor="agent_call",
                material="code",
                values=invalid,
            )
        with self.assertRaises(prompt_router.PromptRouterError):
            prompt_router.assemble(
                self.prompt_set,
                job="rethink@doc",
                executor="brainstorming",
                material="code",
                values=self.values("rethink"),
                role="initial_position",
                lead=True,
            )
        for numeric_lead in (0, 1):
            with self.subTest(numeric_lead=numeric_lead):
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(
                        self.prompt_set,
                        job="implement@slice_impl",
                        executor="brainstorming",
                        material="code",
                        values=self.values("implement@slice_impl"),
                        role=("initial_position" if numeric_lead
                              else "contrary_position"),
                        lead=numeric_lead,
                    )

    def test_invalid_charge_coordinates_and_raw_selectors_are_rejected(self):
        job = "implement@slice_impl"
        valid = {
            "job": job,
            "executor": "agent_call",
            "material": "code",
            "values": self.values(job),
        }
        invalid_coordinates = (
            ("job_none", {"job": None}),
            ("job_boolean", {"job": False}),
            ("job_empty", {"job": ""}),
            ("job_unknown", {"job": "implement"}),
            ("executor_none", {"executor": None}),
            ("executor_boolean", {"executor": False}),
            ("executor_unknown", {"executor": "worker"}),
            ("material_none", {"material": None}),
            ("material_boolean", {"material": False}),
            ("material_empty", {"material": ""}),
            ("direct_role", {"role": "initial_position"}),
            ("direct_lead", {"lead": False}),
            ("direct_artifact_type", {"artifact_type": "implementation"}),
        )
        for case, change in invalid_coordinates:
            with self.subTest(case=case):
                charge = dict(valid)
                charge.update(change)
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(self.prompt_set, **charge)

        invalid_executor_jobs = (
            ("agent_call", "rethink"),
            ("brainstorming", "reclassify@doc"),
            ("brainstorming", "rethink@doc"),
            ("brainstorming", "rethink@impl"),
        )
        for executor, invalid_job in invalid_executor_jobs:
            with self.subTest(executor=executor, job=invalid_job):
                charge = {
                    "job": invalid_job,
                    "executor": executor,
                    "material": "code",
                    "values": self.values("rethink"),
                }
                if executor == "brainstorming":
                    charge.update(role="initial_position", lead=True)
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(self.prompt_set, **charge)

        retired_controls = frozenset((
            "_continuation_may_plan_slices",
            "artifact_type",
            "design_update",
            "kind_file",
            "optional_units",
            "options",
            "plan_authoring_authorized",
            "producer_planning",
            "producer_planning_replan",
            "questions_from",
            "role_stance",
            "slices",
            "target_frame",
            "target_type",
            "variant",
            "variants",
        ))
        self.assertEqual(prompt_router._FORBIDDEN_VALUES, retired_controls)
        for control in retired_controls:
            with self.subTest(raw_control=control):
                values = dict(self.values(job), **{control: "caller choice"})
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(
                        self.prompt_set,
                        job=job,
                        executor="agent_call",
                        material="code",
                        values=values,
                    )

        invalid_values = (None, [], {1: "not a string key"})
        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(
                        self.prompt_set,
                        job=job,
                        executor="agent_call",
                        material="code",
                        values=values,
                    )

        catalogue = dict(
            self.values(job), task_executor_catalogue="caller catalogue"
        )
        with self.assertRaises(prompt_router.PromptRouterError):
            prompt_router.assemble(
                self.prompt_set,
                job=job,
                executor="agent_call",
                material="code",
                values=catalogue,
            )

    def test_all_session_seats_and_artifact_coordinates_are_closed(self):
        session_targets = (
            ("draft_slice_note@slice_doc", None),
            ("implement@slice_impl", None),
            ("rethink", "document"),
            ("rethink", "implementation"),
        )
        for job, artifact_type in session_targets:
            for (role, lead), kind in prompt_router.SEATS.items():
                with self.subTest(
                    job=job, artifact_type=artifact_type,
                    role=role, lead=lead,
                ):
                    prompt = prompt_router.assemble(
                        self.prompt_set,
                        job=job,
                        executor="brainstorming",
                        material="code",
                        values=self.values(job),
                        role=role,
                        lead=lead,
                        artifact_type=artifact_type,
                    )
                    self.assertEqual(prompt["kind"], kind)

        candidate_roles = (
            "initial_position", "contrary_position", "common_sense",
            "observer", None,
        )
        for role in candidate_roles:
            for lead in (False, True):
                if (role, lead) in prompt_router.SEATS:
                    continue
                with self.subTest(invalid_role=role, invalid_lead=lead):
                    with self.assertRaises(prompt_router.PromptRouterError):
                        prompt_router.assemble(
                            self.prompt_set,
                            job="implement@slice_impl",
                            executor="brainstorming",
                            material="code",
                            values=self.values("implement@slice_impl"),
                            role=role,
                            lead=lead,
                        )

        for role in (
            "initial_position", "contrary_position", "common_sense"
        ):
            for lead in (None, 0, 1, "true"):
                with self.subTest(role=role, non_boolean_lead=lead):
                    with self.assertRaises(prompt_router.PromptRouterError):
                        prompt_router.assemble(
                            self.prompt_set,
                            job="implement@slice_impl",
                            executor="brainstorming",
                            material="code",
                            values=self.values("implement@slice_impl"),
                            role=role,
                            lead=lead,
                        )

        for job in ("draft_slice_note@slice_doc", "implement@slice_impl"):
            for artifact_type in ("document", "implementation"):
                with self.subTest(job=job, artifact_type=artifact_type):
                    with self.assertRaises(prompt_router.PromptRouterError):
                        prompt_router.assemble(
                            self.prompt_set,
                            job=job,
                            executor="brainstorming",
                            material="code",
                            values=self.values(job),
                            role="initial_position",
                            lead=True,
                            artifact_type=artifact_type,
                        )

        for artifact_type in (None, "", "slice_impl", False):
            with self.subTest(rethink_artifact_type=artifact_type):
                with self.assertRaises(prompt_router.PromptRouterError):
                    prompt_router.assemble(
                        self.prompt_set,
                        job="rethink",
                        executor="brainstorming",
                        material="code",
                        values=self.values("rethink"),
                        role="initial_position",
                        lead=True,
                        artifact_type=artifact_type,
                    )

    def test_invalid_stored_routing_metadata_makes_the_rung_unreadable(self):
        defects = {}

        conflicting_default = copy.deepcopy(self.prompt_set.documents)
        common_fields = next(
            part for part in conflicting_default["milestone/implement.json"]
            ["output_contract"]["sections"]
            if part.get("ref") == "common_fields"
        )
        common_fields.setdefault("defaults", {})["kind"] = "review_round"
        defects["conflicting_fixed_default"] = conflicting_default

        forbidden_variable = copy.deepcopy(self.prompt_set.documents)
        forbidden_variable["milestone/implement.json"]["instructions"][
            "parts"
        ].append({
            "text": ["Target: {{target_type}}"],
            "variables": [{"name": "target_type", "required": True}],
        })
        defects["caller_forbidden_variable"] = forbidden_variable

        conditional_catalogue = copy.deepcopy(self.prompt_set.documents)
        conditional_catalogue["milestone/implement.json"]["instructions"][
            "parts"
        ].append({
            "text": ["Catalogue: {{task_executor_catalogue}}"],
            "variables": [{
                "name": "task_executor_catalogue", "required": True
            }],
        })
        defects["conditional_catalogue_variable"] = conditional_catalogue

        for defect, documents in defects.items():
            with self.subTest(defect=defect):
                with tempfile.TemporaryDirectory(
                    prefix="orch-prompt-router-"
                ) as home:
                    prompt_sets.ensure_default(home)
                    directory = Path(prompt_sets.prompt_set_dir(home, "operator"))
                    for member, document in documents.items():
                        path = directory / member
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(json.dumps(document), encoding="utf-8")
                    resolution = prompt_router.resolve(
                        home,
                        prompt_set="operator",
                        job="implement@slice_impl",
                        executor="agent_call",
                        material="code",
                        values=self.values("implement@slice_impl"),
                    )
                    self.assertEqual(
                        resolution.prompt_set_fallback,
                        prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                    )
                    self.assertEqual(resolution.prompt["kind"], "implement")

    def test_routing_and_layer_defects_fall_named_to_default_to_seed(self):
        def malformed_layer(documents):
            documents["shared/shared.json"]["material_layers"][
                "implement@slice_impl"
            ]["code"]["questions"] = []

        def duplicate_question_id(documents):
            documents["shared/shared.json"]["material_layers"][
                "implement@slice_impl"
            ]["code"]["questions"]["items"][0]["id"] = "machinery_trust"

        def duplicate_contract_id(documents):
            documents["shared/shared.json"]["material_layers"][
                "implement@slice_impl"
            ]["code"]["output_contract"]["sections"][0][
                "id"
            ] = "implement_result"

        defects = {
            "malformed_layer": malformed_layer,
            "duplicate_question_id": duplicate_question_id,
            "duplicate_contract_id": duplicate_contract_id,
        }
        job = "implement@slice_impl"
        charge = {
            "job": job,
            "executor": "agent_call",
            "material": "code",
            "values": self.values(job),
            "prompt_set": "operator",
        }
        named_marker = "[[named-rung]]"
        default_marker = "[[default-rung]]"

        for defect_name, apply_defect in defects.items():
            with self.subTest(defect=defect_name):
                with tempfile.TemporaryDirectory(
                    prefix="orch-prompt-router-fallback-"
                ) as home:
                    named = self.marked_documents(named_marker)
                    stored_default = self.marked_documents(default_marker)
                    self.write_set(home, "operator", named)
                    self.write_set(home, "default", stored_default)

                    selected = prompt_router.resolve(home, **charge)
                    self.assertIsNone(selected.prompt_set_fallback)
                    self.assert_prompt_marked(selected.prompt, named_marker)
                    self.assertNotIn(
                        default_marker, json.dumps(selected.prompt)
                    )

                    broken_named = copy.deepcopy(named)
                    apply_defect(broken_named)
                    self.write_set(home, "operator", broken_named)
                    selected = prompt_router.resolve(home, **charge)
                    self.assertEqual(
                        selected.prompt_set_fallback,
                        prompt_sets.PROMPT_SET_FALLBACK_DEFAULT,
                    )
                    self.assert_prompt_marked(selected.prompt, default_marker)
                    self.assertNotIn(named_marker, json.dumps(selected.prompt))

                    broken_default = copy.deepcopy(stored_default)
                    apply_defect(broken_default)
                    self.write_set(home, "default", broken_default)
                    selected = prompt_router.resolve(home, **charge)
                    self.assertEqual(
                        selected.prompt_set_fallback,
                        prompt_sets.PROMPT_SET_FALLBACK_SEED,
                    )
                    self.assertEqual(
                        selected.prompt,
                        prompt_router.assemble(
                            self.prompt_set,
                            job=job,
                            executor="agent_call",
                            material="code",
                            values=self.values(job),
                        ),
                    )
                    self.assertNotIn(named_marker, json.dumps(selected.prompt))
                    self.assertNotIn(
                        default_marker, json.dumps(selected.prompt)
                    )
                    self.assertEqual(
                        selected._fields,
                        ("prompt", "prompt_set_fallback"),
                    )
                    self.assertEqual(
                        list(selected.prompt),
                        [
                            "kind", "instructions", "questions",
                            "output_contract",
                        ],
                    )
                    self.assertNotIn(
                        "prompt_set_fallback", json.dumps(selected.prompt)
                    )

    def test_unrelated_route_defaults_do_not_replace_the_named_rung(self):
        named_marker = "[[named-implement]]"
        documents = self.marked_documents(named_marker)
        documents["shared/shared.json"]["units"]["unrelated_route_tone"] = {
            "text": ["Route tone: {{route_tone}}"],
            "variables": [{"name": "route_tone", "required": True}],
        }
        documents["milestone/review_round.json"]["instructions"][
            "parts"
        ].append({
            "ref": "unrelated_route_tone",
            "defaults": {"route_tone": "measured"},
        })
        documents["milestone/suite_checkpoint.json"]["instructions"][
            "parts"
        ].append({"ref": "unrelated_route_tone"})

        with tempfile.TemporaryDirectory(
            prefix="orch-prompt-router-mounted-route-"
        ) as home:
            prompt_sets.ensure_default(home)
            self.write_set(home, "operator", documents)

            selected = prompt_router.resolve(
                home,
                prompt_set="operator",
                job="implement@slice_impl",
                executor="agent_call",
                material="code",
                values=self.values("implement@slice_impl"),
            )

        self.assertIsNone(selected.prompt_set_fallback)
        self.assert_prompt_marked(selected.prompt, named_marker)

    def test_resolution_reads_completed_edits_fresh_and_freezes_answers(self):
        job = "implement@slice_impl"
        charge = {
            "job": job,
            "executor": "agent_call",
            "material": "code",
            "values": self.values(job),
            "prompt_set": "operator",
        }
        first_marker = "[[first-edit]]"
        second_marker = "[[second-edit]]"
        with tempfile.TemporaryDirectory(
            prefix="orch-prompt-router-fresh-"
        ) as home:
            self.write_set(
                home, "operator", self.marked_documents(first_marker)
            )
            first = prompt_router.resolve(home, **charge)
            frozen_first = copy.deepcopy(first.prompt)

            self.write_set(
                home, "operator", self.marked_documents(second_marker)
            )
            second = prompt_router.resolve(home, **charge)

            self.assertIsNone(first.prompt_set_fallback)
            self.assertIsNone(second.prompt_set_fallback)
            self.assertEqual(first.prompt, frozen_first)
            self.assert_prompt_marked(first.prompt, first_marker)
            self.assert_prompt_marked(second.prompt, second_marker)
            self.assertNotIn(second_marker, json.dumps(first.prompt))
            self.assertNotIn(first_marker, json.dumps(second.prompt))

    def test_assembled_shape_and_substitution_contract(self):
        job = "implement@slice_impl"
        values = self.values(job)
        prompt = prompt_router.assemble(
            self.prompt_set,
            job=job,
            executor="agent_call",
            material="code",
            values=values,
        )
        self.assertEqual(
            list(prompt),
            ["kind", "instructions", "questions", "output_contract"],
        )
        self.assertTrue(all(
            set(unit) == {"text", "variables"}
            for unit in prompt["instructions"]
        ))
        self.assertTrue(all(
            set(unit) == {"id", "text", "variables"}
            for unit in prompt["output_contract"]
        ))
        self.assertEqual(set(prompt["questions"]), {"intro", "items"})
        self.assertTrue(all(
            set(question) == {"id", "text"}
            for question in prompt["questions"]["items"]
        ))
        self.assertNotIn("{{kind}}", self.text(prompt))
        metering = next(
            unit for unit in prompt["instructions"]
            if any("driver meters" in line for line in unit["text"])
        )
        defaults = {item["name"]: item.get("default")
                    for item in metering["variables"]}
        self.assertEqual(defaults, {"soft_lines": None, "hard_lines": None})
        self.assertTrue(all(
            declaration.get("drop_unit_if_absent")
            for declaration in metering["variables"]
        ))

        missing = dict(values)
        missing.pop("workspace")
        with self.assertRaises(prompt_router.PromptRouterError):
            prompt_router.assemble(
                self.prompt_set, job=job, executor="agent_call",
                material="code", values=missing,
            )
        overridden = dict(values, kind="review_round")
        with self.assertRaises(prompt_router.PromptRouterError):
            prompt_router.assemble(
                self.prompt_set, job=job, executor="agent_call",
                material="code", values=overridden,
            )
        unrelated = dict(values, harmless_future_value="ignored")
        self.assertEqual(
            prompt,
            prompt_router.assemble(
                self.prompt_set, job=job, executor="agent_call",
                material="code", values=unrelated,
            ),
        )

    def test_render_preserves_placeholder_like_substitution_bytes(self):
        prompt = {
            "kind": "implement",
            "instructions": [{
                "text": ["A={{first}} B={{second}}"],
                "variables": [{"name": "first"}, {"name": "second"}],
            }],
            "questions": {"intro": [], "items": []},
            "output_contract": [],
        }

        self.assertEqual(
            prompt_router.render(
                prompt,
                {
                    "first": "{{second}} and {{unknown}}",
                    "second": "rendered",
                },
            ),
            "A={{second}} and {{unknown}} B=rendered\n",
        )

    def test_part_defaults_are_rendered_once_as_opaque_text(self):
        documents = copy.deepcopy(self.prompt_set.documents)
        sections = documents["milestone/implement.json"]["output_contract"][
            "sections"
        ]
        common_fields = next(
            part for part in sections if part.get("ref") == "common_fields"
        )
        shared_common = documents["shared/shared.json"]["contract_sections"][
            "common_fields"
        ]
        shared_common["text"].append("Workspace: {{workspace}}")
        shared_common["variables"].append({
            "name": "workspace",
            "required": True,
        })
        opaque = (
            '"ok" | "{{workspace}}" | "{{soft_lines}}" | "{{unknown}}"'
        )
        common_fields["defaults"]["status_vocabulary"] = opaque
        candidate = prompt_sets.PromptSet(
            name="placeholder-default", documents=documents
        )
        values = self.values("implement@slice_impl")

        assembled = prompt_router.assemble(
            candidate,
            job="implement@slice_impl",
            executor="agent_call",
            material="code",
            values=values,
        )

        common = next(
            section for section in assembled["output_contract"]
            if section["id"] == "common_fields"
        )
        self.assertNotIn(
            "status_vocabulary",
            {item["name"] for item in common["variables"]},
        )
        self.assertNotIn(
            "workspace",
            {item["name"] for item in common["variables"]},
        )
        rendered = prompt_router.render(
            assembled,
            dict(
                values,
                status_vocabulary='"caller override"',
                workspace="later workspace",
            ),
        )
        self.assertIn(opaque, rendered)
        self.assertIn("Workspace: %s" % values["workspace"], rendered)
        self.assertNotIn("Workspace: later workspace", rendered)
        self.assertNotIn('"caller override"', rendered)

    def test_material_layer_is_exact_and_data_only(self):
        documents = copy.deepcopy(self.prompt_set.documents)
        documents["shared/shared.json"]["material_layers"] = {
            "implement@slice_impl": {
                "code": {
                    "instructions": {"parts": [{
                        "text": ["CODE LAYER"], "variables": []
                    }]},
                    "questions": {"intro": [], "items": [{
                        "id": "code_layer", "text": "Was the code layer used?"
                    }]},
                    "output_contract": {"sections": [{
                        "id": "code_layer_result",
                        "text": ["Return the code-layer result."],
                        "variables": [],
                    }]},
                }
            }
        }
        layered_set = prompt_sets.PromptSet("layered", documents)
        values = self.values("implement@slice_impl")
        code = prompt_router.assemble(
            layered_set, job="implement@slice_impl", executor="agent_call",
            material="code", values=values,
        )
        other = prompt_router.assemble(
            layered_set, job="implement@slice_impl", executor="agent_call",
            material="legal_contract", values=values,
        )
        self.assertEqual(code["instructions"][-1]["text"], ["CODE LAYER"])
        self.assertEqual(code["questions"]["items"][-1]["id"], "code_layer")
        self.assertEqual(code["output_contract"][-1]["id"], "code_layer_result")
        self.assertNotIn("CODE LAYER", self.text(other))


if __name__ == "__main__":
    unittest.main()
