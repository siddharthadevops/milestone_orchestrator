"""Focused contract tests for the prompt-set store and fallback resolver."""

import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from orchestrator import driver, runners, service
from orchestrator import prompt_sets as ps
from orchestrator import state as st


REVIEWED_CORPUS = (
    Path(__file__).resolve().parents[2]
    / "implementation"
    / "brainstorming"
    / "prompt-router"
    / "adapted-kinds"
)


class PromptSetStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-prompt-sets-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name

    def reviewed_corpus(self):
        return {
            member: json.loads(
                (REVIEWED_CORPUS / member).read_text(encoding="utf-8")
            )
            for member in ps.CANONICAL_MEMBERS
        }

    def set_dir(self, name):
        return Path(ps.prompt_set_dir(self.home, name))

    def write_set(self, name, documents=None):
        documents = copy.deepcopy(
            ps.default_seed().documents if documents is None else documents
        )
        directory = self.set_dir(name)
        for member, document in documents.items():
            path = directory / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document), encoding="utf-8")
        return directory

    @staticmethod
    def marked(marker):
        documents = copy.deepcopy(ps.default_seed().documents)
        for document in documents.values():
            document["description"] = marker
        return documents

    def stored_bytes(self):
        root = Path(ps.prompt_sets_dir(self.home))
        return {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

    def test_shipped_corpus_and_seed_are_equivalent(self):
        reviewed = self.reviewed_corpus()
        seed = ps.default_seed()

        self.assertEqual(tuple(reviewed), ps.CANONICAL_MEMBERS)
        self.assertEqual(seed.documents, reviewed)
        self.assertTrue(ps.ensure_default(self.home))
        self.assertEqual(ps.load(self.home, "default").documents, reviewed)
        installed = {
            str(path.relative_to(self.set_dir("default")))
            for path in self.set_dir("default").rglob("*")
            if path.is_file()
        }
        self.assertEqual(installed, set(ps.CANONICAL_MEMBERS))
        self.assertFalse(any(
            name.endswith(".prompt.txt") or name.endswith(".py")
            for name in installed
        ))

    def test_whole_set_validation_rejects_declared_defects(self):
        self.write_set("default")
        for defect in (
            "broken_json",
            "missing_member",
            "unavailable_member",
            "unresolved_ref",
            "duplicate_id",
            "invalid_variable",
            "impossible_mount",
            "invalid_optional_control",
            "missing_initial_position",
            "lead_turn_question_collision",
            "non_standard_json_nan",
            "non_standard_json_infinity",
            "non_standard_json_negative_infinity",
            "idless_output_variant",
            "inline_question_extra_field",
            "shared_question_extra_field",
        ):
            with self.subTest(defect=defect):
                name = "bad-%s" % defect.replace("_", "-")
                directory = self.write_set(name)
                kind_path = directory / "milestone/draft_skeleton.json"
                if defect == "broken_json":
                    kind_path.write_text("{broken", encoding="utf-8")
                elif defect == "missing_member":
                    kind_path.unlink()
                elif defect == "unavailable_member":
                    kind_path.unlink()
                    os.symlink(directory / "absent", kind_path)
                elif defect.startswith("non_standard_json_"):
                    shared_path = directory / "shared/shared.json"
                    document = json.loads(shared_path.read_text(encoding="utf-8"))
                    constants = {
                        "non_standard_json_nan": float("nan"),
                        "non_standard_json_infinity": float("inf"),
                        "non_standard_json_negative_infinity": float("-inf"),
                    }
                    document["units"]["implementation_metering"]["variables"][0][
                        "default"
                    ] = constants[defect]
                    shared_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "idless_output_variant":
                    kind_path = directory / "milestone/review_round.json"
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    document["output_contract"]["sections"].append(
                        {"one_of": "target_frame"}
                    )
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "lead_turn_question_collision":
                    kind_path = directory / "brainstorming/discussion_turn.json"
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    document["questions"]["items"][0]["id"] = "environment_fit"
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "invalid_optional_control":
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    document["instructions"]["parts"][1]["optional"] = []
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "impossible_mount":
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    document["instructions"]["parts"][1]["mount"] = [
                        "executor:agent_call", "role:initial_position"
                    ]
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "inline_question_extra_field":
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    document["instructions"]["parts"][1]["questions"] = [{
                        "id": "inline", "text": "Inline?",
                        "storage_note": "private",
                    }]
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "shared_question_extra_field":
                    shared_path = directory / "shared/shared.json"
                    document = json.loads(shared_path.read_text(encoding="utf-8"))
                    document["units"]["implementation_metering"]["questions"] = [{
                        "id": "shared", "text": "Shared?",
                        "storage_note": "private",
                    }]
                    shared_path.write_text(json.dumps(document), encoding="utf-8")
                elif defect == "missing_initial_position":
                    kind_path = directory / "brainstorming/discussion_turn.json"
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    del document["variants"]["role_stance"]["initial_position"]
                    kind_path.write_text(json.dumps(document), encoding="utf-8")
                else:
                    document = json.loads(kind_path.read_text(encoding="utf-8"))
                    if defect == "unresolved_ref":
                        document["instructions"]["parts"].append(
                            {"ref": "does_not_exist"}
                        )
                    elif defect == "duplicate_id":
                        item = copy.deepcopy(document["questions"]["items"][0])
                        document["questions"]["items"].append(item)
                    else:
                        declaration = document["instructions"]["parts"][1][
                            "variables"
                        ][0]
                        declaration["required"] = "yes"
                    kind_path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaises(ps.PromptSetError):
                    ps.load(self.home, name)
                selected = ps.resolve(self.home, name)
                self.assertEqual(
                    selected.prompt_set_fallback, ps.PROMPT_SET_FALLBACK_DEFAULT
                )
                self.assertEqual(selected.prompt_set.name, "default")

        contrary = self.write_set("contrary-question-overlap")
        discussion_path = contrary / "brainstorming/discussion_turn.json"
        discussion = json.loads(discussion_path.read_text(encoding="utf-8"))
        discussion["variants"]["role_stance"]["contrary_position"][
            "questions"
        ] = [{"id": "environment_fit", "text": "Contrary-only question"}]
        discussion_path.write_text(json.dumps(discussion), encoding="utf-8")
        self.assertEqual(
            ps.load(self.home, "contrary-question-overlap").name,
            "contrary-question-overlap",
        )

    def test_fallback_selects_one_complete_rung(self):
        self.write_set("default", self.marked("stored default"))
        named_dir = self.write_set("operator", self.marked("named set"))

        selected = ps.resolve(self.home, "operator")
        self.assertIsNone(selected.prompt_set_fallback)
        self.assertEqual(selected.prompt_set.name, "operator")
        self.assertEqual(
            {doc["description"] for doc in selected.prompt_set.documents.values()},
            {"named set"},
        )

        (named_dir / "milestone/implement.json").write_text(
            "{broken", encoding="utf-8"
        )
        before_default_fallback = self.stored_bytes()
        selected = ps.resolve(self.home, "operator")
        self.assertEqual(
            selected.prompt_set_fallback, ps.PROMPT_SET_FALLBACK_DEFAULT
        )
        self.assertEqual(selected.prompt_set.name, "default")
        self.assertEqual(
            {doc["description"] for doc in selected.prompt_set.documents.values()},
            {"stored default"},
        )
        self.assertEqual(self.stored_bytes(), before_default_fallback)

        (self.set_dir("default") / "shared/shared.json").write_text(
            "{broken", encoding="utf-8"
        )
        before_seed_fallback = self.stored_bytes()
        selected = ps.resolve(self.home, "operator")
        self.assertEqual(
            selected.prompt_set_fallback, ps.PROMPT_SET_FALLBACK_SEED
        )
        self.assertEqual(selected.prompt_set, ps.default_seed())
        self.assertEqual(self.stored_bytes(), before_seed_fallback)

    def test_selection_reads_fresh_without_a_snapshot(self):
        directory = self.write_set("live", self.marked("first read"))
        first = ps.resolve(self.home, "live")
        before_files = set(self.stored_bytes())

        shared_path = directory / "shared/shared.json"
        shared = json.loads(shared_path.read_text(encoding="utf-8"))
        shared["description"] = "second read"
        shared_path.write_text(json.dumps(shared), encoding="utf-8")
        second = ps.resolve(self.home, "live")

        self.assertEqual(
            first.prompt_set.documents["shared/shared.json"]["description"],
            "first read",
        )
        self.assertEqual(
            second.prompt_set.documents["shared/shared.json"]["description"],
            "second read",
        )
        self.assertIsNone(second.prompt_set_fallback)
        self.assertEqual(set(self.stored_bytes()), before_files)

    def test_default_install_is_missing_only_at_home_boundaries(self):
        def driver_start(home, workspace):
            workspace.mkdir()
            state_path = driver.default_state_path(str(workspace))
            st.save(
                state_path,
                st.new_state(
                    "prompt-set driver startup",
                    str(workspace),
                    driver.load_config(None),
                ),
            )
            driver.Driver(
                state_path,
                runner=runners.MockRunner([]),
                model_profiles_home=str(home),
            )

        def run_creation(home, workspace):
            driver.init_run(
                "prompt-set run creation",
                str(workspace),
                config=driver.load_config(None),
                model_profiles_home=str(home),
                creation_acts=None,
            )

        def service_start(home, workspace):
            del workspace
            server = service.make_server(str(home), 0)
            server.server_close()

        boundaries = {
            "driver_start": driver_start,
            "run_creation": run_creation,
            "service_start": service_start,
        }
        scenarios = ("empty", "valid_edit", "malformed")

        for boundary_name, initialize in boundaries.items():
            for scenario in scenarios:
                with self.subTest(boundary=boundary_name, scenario=scenario):
                    root = Path(self.tmp.name) / ("%s-%s" % (
                        boundary_name, scenario
                    ))
                    home = root / "home"
                    workspace = root / "workspace"
                    home.mkdir(parents=True)
                    before = None
                    if scenario != "empty":
                        ps.ensure_default(str(home))
                        member = (
                            Path(ps.prompt_set_dir(str(home), "default"))
                            / "milestone/implement.json"
                        )
                        if scenario == "valid_edit":
                            document = json.loads(member.read_text("utf-8"))
                            document["description"] = "operator edit"
                            member.write_text(
                                json.dumps(document, separators=(",", ":")),
                                encoding="utf-8",
                            )
                        else:
                            member.write_bytes(b"{malformed")
                        before = {
                            str(path.relative_to(home)): path.read_bytes()
                            for path in sorted(home.rglob("*"))
                            if path.is_file()
                        }

                    initialize(home, workspace)

                    if scenario == "empty":
                        self.assertEqual(
                            ps.load(str(home), "default"), ps.default_seed()
                        )
                    else:
                        after = {
                            str(path.relative_to(home)): path.read_bytes()
                            for path in sorted(home.rglob("*"))
                            if path.is_file() and "prompt_sets/default/" in str(
                                path.relative_to(home)
                            )
                        }
                        expected = {
                            path: value for path, value in before.items()
                            if path.startswith("prompt_sets/default/")
                        }
                        self.assertEqual(after, expected)


if __name__ == "__main__":
    unittest.main()
