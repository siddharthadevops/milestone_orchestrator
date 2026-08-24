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


class PromptRouterTest(unittest.TestCase):
    def setUp(self):
        self.prompt_set = prompt_sets.default_seed()

    def values(self, job):
        values = prompt_router._validation_values(self.prompt_set)
        if job != "draft_skeleton@skeleton":
            values.pop("task_executor_catalogue", None)
        return values

    @staticmethod
    def text(prompt):
        units = prompt["instructions"] + prompt["output_contract"]
        return "\n".join(line for unit in units for line in unit["text"])

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

    def test_canonical_charge_matrix_and_session_target_mounts(self):
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

        unreachable_mount = copy.deepcopy(self.prompt_set.documents)
        unreachable_mount["milestone/implement.json"]["instructions"][
            "parts"
        ][0]["mount"] = ["role:initial_position"]
        defects["document_specific_unreachable_mount"] = unreachable_mount

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
        self.assertEqual(defaults, {"soft_lines": "500", "hard_lines": "750"})

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
