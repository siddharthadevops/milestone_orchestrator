"""Focused proof for canonical charge resolution and assembled prompt JSON."""

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator import (
    contracts,
    prompt_contracts,
    prompt_router,
    prompt_sets,
    session_calls,
    staffing,
)


CORPUS = (
    Path(__file__).resolve().parents[2]
    / "implementation/brainstorming/prompt-router/adapted-kinds"
)
LITERATURE_CORPUS = (
    Path(__file__).resolve().parents[2] / "prompt_sets/literature"
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
def validation_values(prompt_set):
    """Supply opaque fixture values for every declaration in the seed."""
    names = set()
    fixed = {"kind", "role", "workarea_boundary"}

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
        documents["shared/shared.json"]["material_layers"].update({
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
        })

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
        format_refs = []
        for member, document in reviewed.items():
            if member == "shared/shared.json":
                continue
            for part in document["instructions"]["parts"]:
                if part.get("ref") == "producer_planning":
                    planning_refs.append(member)
                if part.get("ref") == "canonical_slice_plan_format":
                    format_refs.append((member, part.get("mount")))
            contracts = json.dumps(document["output_contract"])
            self.assertNotIn('"slices"', contracts)
        self.assertEqual(planning_refs, ["milestone/draft_skeleton.json"])
        self.assertEqual(
            format_refs,
            [("milestone/draft_skeleton.json", None)],
        )

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
        self.assertEqual(len(prompt_router.DIRECT_ROUTES), 21)
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
                self.assertEqual(len(ids), len(set(ids)))

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
                self.assertEqual(len(ids), len(set(ids)))

        job = "draft_slice_note@slice_doc"
        direct = prompt_router.assemble(
            self.prompt_set,
            job=job,
            executor="agent_call",
            material="code",
            values=self.values(job),
        )
        lead = prompt_router.assemble(
            self.prompt_set,
            job=job,
            executor="brainstorming",
            material="code",
            values=self.values(job),
            role="initial_position",
            lead=True,
        )
        direct_ids = [
            item["id"] for item in direct["questions"]["items"]
        ]
        lead_ids = [item["id"] for item in lead["questions"]["items"]]
        for question_id in direct_ids:
            self.assertEqual(lead_ids.count(question_id), 1)

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

    def test_canonical_slice_plan_format_is_shared_without_the_catalogue(self):
        marker = "CANONICAL SLICE PLAN FORMAT"
        shared = self.prompt_set.documents["shared/shared.json"]["units"]
        self.assertEqual(
            shared["canonical_slice_plan_format"],
            session_calls.canonical_slice_plan_format_instruction(),
        )
        draft = prompt_router.assemble(
            self.prompt_set,
            job="draft_skeleton@skeleton",
            executor="agent_call",
            material="document",
            values=self.values("draft_skeleton@skeleton"),
        )
        draft_text = self.text(draft)
        self.assertEqual(draft_text.count(marker), 1)
        self.assertIn("TASK EXECUTOR CATALOGUE:", draft_text)

    def test_standalone_brainstorming_has_its_own_closed_route(self):
        expected_questions = {
            "initial_position": [
                "turn_environment_fit", "turn_human_scale",
                "turn_machinery_trust",
            ],
            "contrary_position": [
                "turn_environment_fit", "turn_human_scale",
                "turn_machinery_trust",
                "turn_better_alternative",
            ],
            "common_sense": [
                "turn_environment_fit", "turn_human_scale", "request_focus",
                "turn_machinery_trust",
            ],
        }
        for (role, lead), kind in prompt_router.SEATS.items():
            with self.subTest(role=role):
                prompt = prompt_router.assemble(
                    self.prompt_set,
                    job=prompt_router.STANDALONE_SESSION_JOB,
                    executor="brainstorming",
                    material="default",
                    values=self.values(prompt_router.STANDALONE_SESSION_JOB),
                    role=role,
                    lead=lead,
                )
                self.assertEqual(prompt["kind"], kind)
                self.assertEqual(
                    [item["id"] for item in prompt["questions"]["items"]],
                    expected_questions[role],
                )
                text = self.text(prompt)
                better_alternative = (
                    "Look for a materially better alternative to the same "
                    "actual problem. If evidence supports one, offer it in "
                    "the chat"
                )
                if role == "contrary_position":
                    self.assertIn(better_alternative, text)
                else:
                    self.assertNotIn(better_alternative, text)
                self.assertNotIn("TWO-REGISTER DOCUMENT", text)
                self.assertNotIn("IMPLEMENTATION RULES", text)
                if role != "common_sense":
                    self.assertIn(
                        prompt_router.STANDALONE_WORKAREA_BOUNDARY, text
                    )
                    self.assertNotIn(
                        prompt_router.REPOSITORY_WORKAREA_BOUNDARY, text
                    )

    def test_standalone_repository_brainstorming_reuses_named_set(self):
        job = prompt_router.STANDALONE_REPOSITORY_SESSION_JOB
        values = self.values(job)
        expected_questions = {
            "initial_position": [
                "turn_environment_fit", "turn_human_scale",
                "turn_machinery_trust",
            ],
            "contrary_position": [
                "turn_environment_fit", "turn_human_scale",
                "turn_machinery_trust",
                "turn_better_alternative",
            ],
            "common_sense": [
                "turn_environment_fit", "turn_human_scale", "request_focus",
                "turn_machinery_trust",
            ],
        }
        route = prompt_router._route(
            job, "brainstorming", "default", "initial_position", True, None
        )
        self.assertEqual(
            route.mount_tags,
            frozenset(("job:producer", "role:initial_position")),
        )
        for (role, lead), kind in prompt_router.SEATS.items():
            with self.subTest(role=role):
                prompt = prompt_router.assemble(
                    self.prompt_set,
                    job=job,
                    executor="brainstorming",
                    material="default",
                    values=values,
                    role=role,
                    lead=lead,
                )
                self.assertEqual(prompt["kind"], kind)
                self.assertEqual(
                    [item["id"] for item in prompt["questions"]["items"]],
                    expected_questions[role],
                )
                text = self.text(prompt)
                self.assertNotIn("\nPROBLEM\n", text)
                self.assertNotIn("TWO-REGISTER DOCUMENT", text)
                self.assertNotIn("IMPLEMENTATION RULES", text)
                if role != "common_sense":
                    self.assertIn(
                        prompt_router.REPOSITORY_WORKAREA_BOUNDARY, text
                    )
                    self.assertNotIn(
                        prompt_router.STANDALONE_WORKAREA_BOUNDARY, text
                    )

        with tempfile.TemporaryDirectory(
            prefix="orch-repository-prompt-set-"
        ) as home:
            marker = "LITERATURE CUSTOM GUIDANCE"
            self.write_set(home, "literature", self.marked_documents(marker))
            resolution = prompt_router.resolve(
                home,
                job=job,
                executor="brainstorming",
                material="default",
                values=values,
                prompt_set="literature",
                role="initial_position",
                lead=True,
            )
            self.assertIsNone(resolution.prompt_set_fallback)
            self.assert_prompt_marked(resolution.prompt, marker)

    def test_literature_brainstorming_keeps_existing_questions_and_adds_missing_perspectives(self):
        documents = {
            member: json.loads(
                (LITERATURE_CORPUS / member).read_text(encoding="utf-8")
            )
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        with tempfile.TemporaryDirectory() as home:
            self.write_set(home, "literature", documents)
            literature = prompt_sets.load(home, "literature")

        shared = [
            "turn_environment_fit", "turn_human_scale",
            "turn_character_idiolect",
            "turn_reader_emotion", "turn_reader_legibility",
            "turn_meaningful_surprise",
        ]
        expected = {
            "initial_position": shared,
            "contrary_position": shared + ["turn_better_alternative"],
            "common_sense": [
                "turn_environment_fit", "turn_human_scale", "request_focus",
                "turn_character_idiolect",
                "turn_reader_emotion", "turn_reader_legibility",
                "turn_meaningful_surprise",
            ],
        }
        job = prompt_router.STANDALONE_SESSION_JOB
        for (role, lead), kind in prompt_router.SEATS.items():
            with self.subTest(role=role):
                prompt = prompt_router.assemble(
                    literature,
                    job=job,
                    executor="brainstorming",
                    material="default",
                    values=self.values(job),
                    role=role,
                    lead=lead,
                )
                bound = prompt_contracts.bind(prompt)
                self.assertEqual(list(bound.question_ids), expected[role])
                self.assertEqual(
                    len(bound.question_ids), len(set(bound.question_ids))
                )
                questions = {
                    item["id"]: item["text"]
                    for item in prompt["questions"]["items"]
                }
                self.assertNotIn("turn_machinery_trust", questions)
                self.assertNotIn(
                    "not applicable", questions["turn_reader_emotion"]
                )
                self.assertIn(
                    "creative freedom", questions["turn_meaningful_surprise"]
                )
                self.assertNotIn(
                    "not applicable", questions["turn_meaningful_surprise"]
                )
                reply = {
                    "kind": kind,
                    "markdown": "Focused literary turn.",
                    "questions": [
                        {"id": question_id, "answer": "Checked."}
                        for question_id in bound.question_ids
                    ],
                }
                self.assertEqual(prompt_contracts.validate(bound, reply), reply)
                reply["questions"].pop()
                with self.assertRaises(contracts.ContractError):
                    prompt_contracts.validate(bound, reply)

    def test_literature_creativity_requires_emotion_and_tests_available_surprise(self):
        documents = {
            member: json.loads(
                (LITERATURE_CORPUS / member).read_text(encoding="utf-8")
            )
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        with tempfile.TemporaryDirectory() as home:
            self.write_set(home, "literature", documents)
            literature = prompt_sets.load(home, "literature")

        expected = [
            "environment_fit", "human_scale", "character_idiolect",
            "reader_emotion", "reader_legibility", "meaningful_surprise",
        ]
        for kind in (
            "create_genes", "compose_candidates", "evaluate_candidates",
        ):
            job = kind + "@creativity"
            with self.subTest(kind=kind):
                prompt = prompt_router.assemble(
                    literature,
                    job=job,
                    executor="agent_call",
                    material="default",
                    values=self.values(job),
                )
                questions = {
                    item["id"]: item["text"]
                    for item in prompt["questions"]["items"]
                }
                self.assertEqual(list(questions), expected)
                self.assertNotIn("machinery_trust", questions)
                self.assertNotIn("not applicable", questions["reader_emotion"])
                self.assertNotIn("does not establish", questions["reader_emotion"])
                self.assertIn("creative freedom", questions["meaningful_surprise"])
                self.assertNotIn("requires surprise", questions["meaningful_surprise"])
                self.assertNotIn("calls for surprise", questions["meaningful_surprise"])
                self.assertNotIn("not applicable", questions["meaningful_surprise"])

    def test_repository_editing_seats_leave_commits_to_the_driver(self):
        for job in (
            prompt_router.STANDALONE_REPOSITORY_SESSION_JOB,
            "draft_slice_note@slice_doc",
            "implement@slice_impl",
            "rethink",
        ):
            with self.subTest(job=job):
                prompt = prompt_router.assemble(
                    self.prompt_set,
                    job=job,
                    executor="brainstorming",
                    material="code",
                    values=self.values(job),
                    role="initial_position",
                    lead=True,
                    **({"artifact_type": "implementation"}
                       if job == "rethink" else {}),
                )
                text = self.text(prompt)
                self.assertIn("Leave your changes uncommitted.", text)
                self.assertIn(
                    "Do not create or amend commits or move HEAD.", text
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
            "workarea_boundary",
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
            (prompt_router.STANDALONE_SESSION_JOB, None),
            (prompt_router.STANDALONE_REPOSITORY_SESSION_JOB, None),
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
            base = documents["milestone/implement.json"]["questions"][
                "items"
            ]
            if not base:
                base.append({
                    "id": "fixture_base_question",
                    "text": "Was the base fixture mounted?",
                })
            layer = documents["shared/shared.json"]["material_layers"][
                "implement@slice_impl"
            ]["code"]["questions"]["items"]
            if not layer:
                layer.append({
                    "id": "fixture_layer_question",
                    "text": "Was the layer fixture mounted?",
                })
            layer[0]["id"] = base[0]["id"]

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

    def test_creativity_jobs_and_materials(self):
        search_material = {
            "objective": "Find a useful {{next step}}.",
            "context_summary": "One room is available to current participants.",
            "facts": ["One room"], "constraints": [{"id": "budget", "text": "No spend"}],
            "assumptions": [], "unknowns": ["Interest"],
            "dimensions": [{"id": "approach", "meaning": "How to proceed", "variants": [
                {"id": "v1", "text": "Share the room"},
                {"id": "v2", "text": "Exchange time in the room"},
            ]}],
            "composition_guidance": "Interpret the chosen parts faithfully.",
            "criteria": [{"id": "useful", "text": "Serves current participants"}],
            "order_semantics": "Sequence in which the chosen actions are applied.",
        }
        candidates = [{"candidate_id": "c2", "components": {"approach": "v2"}},
                      {"candidate_id": "c1", "components": {"approach": "v1"}}]
        compositions = [
            {
                "candidate_id": "c2", "components": candidates[0]["components"],
                "proposal": "Exchange time in the room.",
            },
            {
                "candidate_id": "c1", "components": candidates[1]["components"],
                "proposal": "Share the room.",
            },
        ]
        jobs = {
            "create_genes": ("search_material", {
                "objective": search_material["objective"],
                "context": search_material["context_summary"],
                "references": json.dumps(["notes/z-last.md", "notes/a-first.md"]),
            }),
            "compose_candidates": ("compositions", {
                "search_material": json.dumps(search_material),
                "candidates": json.dumps(candidates),
            }),
            "evaluate_candidates": ("evaluations", {
                "search_material": json.dumps(search_material),
                "compositions": json.dumps(compositions),
            }),
            "expand_genes": ("additions", {
                "objective": search_material["objective"],
                "search_material": json.dumps(search_material),
                "promising_candidates": json.dumps(candidates[:1]),
                "explored_account": "Sharing and time exchange have been explored.",
            }),
        }
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for kind, (reply_key, inputs) in jobs.items():
                values = dict(inputs, workspace="/workspace",
                              ecosystem_map="ADDITIONAL ROOT /evidence — READ-ONLY")
                resolved = {}
                for material in ("default", "literature", "business", "unknown"):
                    with self.subTest(kind=kind, material=material):
                        selected = prompt_router.resolve(
                            home, job=kind + "@creativity", executor="agent_call",
                            material=material, values=values,
                        )
                        self.assertIsNone(selected.prompt_set_fallback)
                        self.assertEqual(selected.prompt["kind"], kind)
                        rendered = prompt_router.render(selected.prompt, values)
                        for value in values.values():
                            self.assertIn(value, rendered)
                        if kind == "create_genes":
                            self.assertLess(rendered.index("z-last.md"), rendered.index("a-first.md"))
                        self.assertIn("Do not edit files or execute proposals", rendered)
                        if kind == "create_genes":
                            self.assertIn("return only ten subjects, ten verbs and ten adjectives", rendered)
                            self.assertIn("do not compose a proposal", rendered)
                            self.assertIn("position-independent semantic", rendered)
                            self.assertIn("order_semantics", rendered)
                        elif kind == "compose_candidates":
                            self.assertIn("Composition and evaluation are separate", rendered)
                            self.assertIn("expose\nthe gap plainly", rendered)
                        elif kind == "evaluate_candidates":
                            self.assertIn("Composition has already happened in a separate call", rendered)
                            self.assertIn("__insufficient_detail__", rendered)
                            self.assertIn("Every invalid evaluation scores 0", rendered)
                        if kind == "expand_genes":
                            self.assertIn("The only top-level key is " + reply_key, rendered)
                            self.assertIn("No status, kind or questions envelope", rendered)
                            self.assertEqual(selected.prompt["questions"]["items"], [])
                            expected_sections = [kind + "_result"]
                        else:
                            if kind == "create_genes":
                                self.assertIn(
                                    "For sparse_v2 its only top-level keys are gene_pool and questions",
                                    rendered,
                                )
                                self.assertIn(
                                    "For legacy its only top-level keys are search_material and questions",
                                    rendered,
                                )
                            else:
                                self.assertIn(
                                    "The only top-level keys are %s and questions" % reply_key,
                                    rendered,
                                )
                            question_ids = tuple(
                                item["id"] for item in selected.prompt["questions"]["items"]
                            )
                            expected_ids = (
                                "machinery_trust", "environment_fit", "human_scale",
                            )
                            if material == "literature":
                                expected_ids += (
                                    "character_idiolect", "reader_emotion",
                                    "reader_legibility", "meaningful_surprise",
                                )
                            self.assertEqual(question_ids, expected_ids)
                            self.assertIn("one entry per QUESTIONS id", rendered)
                            expected_sections = [kind + "_result", "questions_output"]
                        self.assertEqual(
                            [part["id"] for part in selected.prompt["output_contract"]],
                            expected_sections,
                        )
                        self.assertEqual(
                            prompt_contracts.bind(selected.prompt).registered_section_ids,
                            tuple(expected_sections),
                        )
                        resolved[material] = selected.prompt
                self.assertEqual(resolved["default"], resolved["unknown"])
                for material in ("literature", "business"):
                    with self.subTest(kind=kind, layer=material):
                        self.assertEqual(resolved[material]["instructions"][:-1],
                                         resolved["default"]["instructions"])
                        self.assertIn(material.upper() + " REFINEMENT", self.text(resolved[material]))
                        self.assertEqual(resolved[material]["output_contract"],
                                         resolved["default"]["output_contract"])

    def test_fragment_prompts_mount_count_sources_order_and_polarity_in_both_sets(self):
        literature_documents = {
            member: json.loads(
                (LITERATURE_CORPUS / member).read_text(encoding="utf-8")
            )
            for member in prompt_sets.CANONICAL_MEMBERS
        }
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            self.write_set(home, "literature", literature_documents)
            for set_name, material in (
                ("default", "default"), ("default", "literature"),
                ("default", "business"), ("literature", "default"),
            ):
                for kind in (
                    "create_genes", "compose_candidates", "evaluate_candidates",
                ):
                    with self.subTest(prompt_set=set_name, material=material, kind=kind):
                        values = {
                            "workspace": "/workspace", "objective": "Invent a creature.",
                            "context": "It must manipulate a terminal.",
                            "references": '["species.md"]', "search_material": "{}",
                            "candidates": "[]", "compositions": "[]",
                            "creativity_semantics": "fragments_v3", "gene_count": 6,
                        }
                        selected = prompt_router.resolve(
                            home, job=kind + "@creativity", executor="agent_call",
                            material=material, values=values, prompt_set=set_name,
                        )
                        self.assertIsNone(selected.prompt_set_fallback)
                        rendered = prompt_router.render(selected.prompt, values)
                        self.assertIn("CREATIVITY CONTRACT: ordered_fragments_v1", rendered)
                        self.assertIn("workspace and admitted roots", rendered)
                        bound = prompt_contracts.bind(selected.prompt)
                        if kind == "create_genes":
                            self.assertIn("return exactly 6 distinct fragments", rendered)
                            self.assertIn("1-3 whitespace-separated words", rendered)
                            reply = {
                                "gene_pool": [
                                    "shared warmth", "flexible shell", "balance",
                                    "translucent fingers", "touch", "hinged plates",
                                ],
                                "questions": [
                                    {"id": question_id, "answer": "Inspected the context."}
                                    for question_id in bound.question_ids
                                ],
                            }
                            prompt_contracts.validate(
                                bound, reply, creativity_semantics="fragments_v3", gene_count=6,
                            )
                            with self.assertRaises(contracts.ContractError):
                                prompt_contracts.validate(
                                    bound, reply, creativity_semantics="fragments_v3", gene_count=10,
                                )
                            values.pop("gene_count")
                            defaulted = prompt_router.resolve(
                                home, job=kind + "@creativity", executor="agent_call",
                                material=material, values=values, prompt_set=set_name,
                            )
                            self.assertIn(
                                "return exactly 10 distinct fragments",
                                prompt_router.render(defaulted.prompt, values),
                            )
                        else:
                            self.assertIn("variant_id affirmed", rendered)
                            self.assertIn("variant_id negated", rendered)
                            self.assertIn("house -> red -> clean", rendered)
                            self.assertIn("Require only what the assignment asks", rendered)
                            self.assertIn("For sparse_v2 and legacy only", rendered)
                            if kind == "compose_candidates":
                                self.assertIn("You have creative freedom", rendered)
                            else:
                                self.assertIn("Do not reject an invented design", rendered)
                                self.assertIn("never fill the missing detail yourself", rendered)

    def test_sparse_evaluation_prompt_contract(self):
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for semantics in (None, "sparse_v2"):
                for material in ("default", "literature", "business"):
                    with self.subTest(semantics=semantics, material=material):
                        values = dict(
                            workspace="/workspace", search_material="{}",
                            compositions="[]",
                        )
                        if semantics is not None:
                            values["creativity_semantics"] = semantics
                        selected = prompt_router.resolve(home, job="evaluate_candidates@creativity",
                                                         executor="agent_call", material=material, values=values)
                        rendered = prompt_router.render(selected.prompt, values)
                        self.assertIn("SAVED MATERIAL SEMANTICS: " + (semantics or "legacy"), rendered)
                        for instruction in (
                            "Composition has already happened in a separate call",
                            "Judge only the supplied proposal",
                            "Do not compose, rewrite, improve, complete, reinterpret, reorder",
                            "If detail needed to judge\nor use the proposal is absent, reject it",
                            "__objective__", "__insufficient_detail__", "__seed__",
                            "Every invalid evaluation scores 0",
                            "Never rank or calibrate against batch mates",
                            "Do not return proposal",
                        ):
                            self.assertIn(instruction, rendered)
                        if semantics == "sparse_v2":
                            self.assertIn(
                                "Every active subject and verb-adjective value must retain its meaning",
                                rendered,
                            )
                        else:
                            self.assertIn("For legacy, assess the proposal", rendered)
                        if material != "default":
                            self.assertIn(material.upper() + " REFINEMENT", rendered)
                        expected_questions = 7 if material == "literature" else 3
                        self.assertEqual(
                            len(selected.prompt["questions"]["items"]), expected_questions,
                        )
                        self.assertEqual(prompt_contracts.bind(selected.prompt).registered_section_ids,
                                         ("evaluate_candidates_result", "questions_output"))

    def test_sparse_composition_prompt_contract(self):
        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for material in ("default", "literature", "business"):
                with self.subTest(material=material):
                    values = {
                        "workspace": "/workspace", "search_material": "{}",
                        "candidates": "[]", "creativity_semantics": "sparse_v2",
                    }
                    selected = prompt_router.resolve(
                        home, job="compose_candidates@creativity",
                        executor="agent_call", material=material, values=values,
                    )
                    rendered = prompt_router.render(selected.prompt, values)
                    for instruction in (
                        "Composition and evaluation are separate",
                        "Preserve every selected element and its supplied order exactly",
                        "never invent a fact, capability, requirement, event",
                        "expose\nthe gap plainly",
                        "Still return a proposal for every ID",
                        "exact ordered set of active subject and verb-adjective",
                        "Return no evaluation, score, validity, violations, assumptions",
                    ):
                        self.assertIn(instruction, rendered)
                    expected_questions = 7 if material == "literature" else 3
                    self.assertEqual(
                        len(selected.prompt["questions"]["items"]), expected_questions,
                    )
                    self.assertEqual(
                        prompt_contracts.bind(selected.prompt).registered_section_ids,
                        ("compose_candidates_result", "questions_output"),
                    )

    def test_creation_prompt_semantics(self):
        from orchestrator.tests.test_prompt_contracts import (
            question_answers, sparse_creation_reply, sparse_gene_pool_reply,
        )

        with tempfile.TemporaryDirectory() as home:
            prompt_sets.ensure_default(home)
            for semantics in ("legacy", "sparse_v2"):
                for material in ("default", "literature", "business"):
                    with self.subTest(semantics=semantics, material=material):
                        values = dict(workspace="/workspace", objective="Explore the room.", context="",
                                      references="[]", creativity_semantics=semantics)
                        selected = prompt_router.resolve(home, job="create_genes@creativity",
                                                         executor="agent_call", material=material, values=values)
                        rendered = prompt_router.render(selected.prompt, values)
                        self.assertIn("SAVED MATERIAL SEMANTICS: " + semantics, rendered)
                        bound = prompt_contracts.bind(selected.prompt)
                        self.assertEqual(
                            bound.registered_section_ids,
                            ("create_genes_result", "questions_output"),
                        )
                        expected_questions = 7 if material == "literature" else 3
                        self.assertEqual(len(bound.question_ids), expected_questions)
                        if semantics == "legacy":
                            self.assertIn("For legacy, formulate a concise objective", rendered)
                            reply = sparse_creation_reply()
                            variants = reply["search_material"].pop("variants")
                            for dimension in reply["search_material"]["dimensions"]:
                                dimension["variants"] = variants
                            reply["questions"] = question_answers(bound.question_ids)
                        else:
                            self.assertIn(
                                "return only ten subjects, ten verbs and ten adjectives", rendered,
                            )
                            self.assertIn("do not compose a proposal", rendered)
                            reply = sparse_gene_pool_reply(bound.question_ids)
                        prompt_contracts.validate(
                            bound, reply, creativity_semantics=semantics,
                        )

    def test_creativity_live_whole_set_resolution(self):
        kinds = ("create_genes", "compose_candidates", "evaluate_candidates", "expand_genes")
        routes = tuple(kind + "@creativity" for kind in kinds) + ("implement@slice_impl",)
        values = self.values(routes[0])
        with tempfile.TemporaryDirectory() as home:
            default = self.write_set(home, "default", self.marked_documents("DEFAULT"))
            named = self.write_set(home, "operator", self.marked_documents("NAMED"))
            session = staffing.create_session(home, {
                "work_area": {"project": "orchestrators", "work_area": "implementation"},
                "families": ["codex"], "document": "prose-first", "rigor": "medium",
            })

            def resolve(route, name="operator"):
                return prompt_router.resolve(
                    home, job=route, executor="agent_call",
                    material=staffing.session_material(home, session["id"]),
                    values=values, prompt_set=name,
                )

            def stored_bytes():
                return {path: path.read_bytes() for path in Path(home).rglob("*.json")}

            first = {route: resolve(route) for route in routes}
            frozen = copy.deepcopy(first)
            for route, selected in first.items():
                with self.subTest(route=route, source="complete"):
                    self.assertIsNone(selected.prompt_set_fallback)
                    self.assert_prompt_marked(selected.prompt, "NAMED")
                    direct_default = resolve(route, "default")
                    self.assertIsNone(direct_default.prompt_set_fallback)
                    self.assert_prompt_marked(direct_default.prompt, "DEFAULT")
            edited = self.marked_documents("EDITED")
            self.write_set(home, "operator", edited)
            for material in ("literature", "business", "unknown", None):
                staffing.edit_session(home, session["id"], {"material": material})
                for route in routes:
                    with self.subTest(route=route, material=material):
                        selected = resolve(route)
                        self.assertIsNone(selected.prompt_set_fallback)
                        self.assert_prompt_marked(selected.prompt, "EDITED")
                        self.assertEqual(selected.prompt, prompt_router.assemble(
                            prompt_sets.PromptSet("operator", edited), job=route,
                            executor="agent_call", material=material or "default", values=values,
                        ))
            self.assertEqual(first, frozen)
            staffing.edit_session(home, session["id"], {"material": "literature"})
            for missing_kind in kinds:
                self.write_set(home, "operator", edited)
                self.write_set(home, "default", self.marked_documents("DEFAULT"))
                member = "milestone/" + missing_kind + ".json"
                (named / member).unlink()
                before = stored_bytes()
                for route in routes:
                    with self.subTest(missing=missing_kind, route=route, source="default"):
                        fallback = resolve(route)
                        self.assertEqual(fallback.prompt_set_fallback, "stored_default")
                        self.assert_prompt_marked(fallback.prompt, "DEFAULT")
                        self.assertNotIn("EDITED", self.text(fallback.prompt))
                self.assertFalse(prompt_sets.ensure_default(home))
                self.assertEqual(before, stored_bytes())
                (default / member).unlink()
                before = stored_bytes()
                for route in routes:
                    with self.subTest(missing=missing_kind, route=route, source="seed"):
                        fallback = resolve(route)
                        self.assertEqual(fallback.prompt_set_fallback, "in_code_seed")
                        self.assertEqual(fallback.prompt, prompt_router.assemble(
                            self.prompt_set, job=route, executor="agent_call",
                            material="literature", values=values,
                        ))
                self.assertFalse(prompt_sets.ensure_default(home))
                self.assertEqual(before, stored_bytes())

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
