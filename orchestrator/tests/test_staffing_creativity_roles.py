"""Dedicated Creativity staffing, including the explicit old-document cutover."""

import copy
import json
import os
import tempfile
import unittest

from orchestrator import staffing
from orchestrator.tests.test_staffing_documents import (
    claude_lead_shaped, stored_default_shaped, valid_doc,
)


def old_document():
    document = valid_doc("default")
    for role in staffing.CREATIVITY_ROLES:
        document["roles"].pop(role)
        document["assignment"].pop(role)
        for by_slot in document["tuning"].values():
            for by_role in by_slot.values():
                by_role.pop(role)
    return document


class CreativityRolesTest(unittest.TestCase):
    def test_vocabulary_adds_exactly_three_independent_roles(self):
        self.assertEqual(staffing.CREATIVITY_ROLES, (
            "creativity_create_genes", "creativity_compose_candidates",
            "creativity_evaluate_candidates",
        ))
        self.assertEqual(len(staffing.ROLES), 12)
        document = staffing.add_creativity_roles(old_document())
        for role in staffing.CREATIVITY_ROLES:
            self.assertEqual(document["roles"][role], {})
            self.assertEqual(set(document["assignment"][role]), {"1"})

    def test_cutover_is_pure_and_preserves_every_existing_entry(self):
        original = old_document()
        original["assignment"]["plan"] = {"1": 2, "2": 1}
        original["assignment"]["brainstorm"] = {"1": 2, "2": 1, "3": 2}
        original["assignment"]["review"] = {"1": 2, "2": 1}
        original["tuning"]["low"]["2"]["plan"] = [3, 2]
        original["tuning"]["medium"]["1"]["brainstorm"] = [9, 5]
        original["tuning"]["medium"]["1"]["review"] = [9, 9]
        original["overrides"]["prose"]["tuning"] = {
            "low": {"1": {"plan": [1, 3]}},
        }
        before = copy.deepcopy(original)
        result = staffing.add_creativity_roles(original)
        self.assertEqual(original, before)
        for role, source in zip(staffing.CREATIVITY_ROLES,
                                ("plan", "brainstorm", "review")):
            for slot in original["families"]:
                evaluator = role == "creativity_evaluate_candidates"
                self.assertEqual(result["tuning"]["low"][slot][role],
                                 [1, 4 if evaluator else 2])
                for target, prior in (("medium", "low"), ("high", "medium")):
                    expected = list(original["tuning"][prior][slot][source])
                    # Copy the model tier only; production is always medium
                    # and evaluation is always xhigh, at every rigor.
                    expected[1] = 4 if evaluator else 2
                    self.assertEqual(result["tuning"][target][slot][role],
                                     expected)
        self.assertEqual(result["assignment"][staffing.CREATIVITY_ROLES[0]],
                         {"1": 2})
        self.assertEqual(result["assignment"][staffing.CREATIVITY_ROLES[1]],
                         {"1": 2})
        # Codex evaluates even when ordinary review index 1 is Claude.
        self.assertEqual(result["assignment"][staffing.CREATIVITY_ROLES[2]],
                         {"1": 1})
        for role in staffing.CREATIVITY_ROLES:
            result["roles"].pop(role)
            result["assignment"].pop(role)
            for by_slot in result["tuning"].values():
                for by_role in by_slot.values():
                    by_role.pop(role)
        self.assertEqual(result, before)
        result["tuning"]["low"]["1"]["plan"][0] = 99
        self.assertEqual(original, before)

    def test_low_uses_first_model_and_named_efforts_without_changing_ladders(self):
        document = old_document()
        document["families"]["1"]["models"].reverse()
        document["families"]["1"]["efforts"] = [
            "minimal", "low", "medium", "high", "xhigh"]
        document["families"]["2"]["efforts"] = [
            "quick", "medium", "deep", "xhigh"]
        result = staffing.add_creativity_roles(document)
        for role in staffing.CREATIVITY_ROLES:
            evaluator = role == "creativity_evaluate_candidates"
            self.assertEqual(result["tuning"]["low"]["1"][role],
                             [1, 5 if evaluator else 3])
            self.assertEqual(result["tuning"]["low"]["2"][role],
                             [1, 4 if evaluator else 2])
        for rigor in staffing.RIGORS:
            for role in staffing.CREATIVITY_ROLES:
                evaluator = role == "creativity_evaluate_candidates"
                self.assertEqual(result["tuning"][rigor]["1"][role][1],
                                 5 if evaluator else 3)
                self.assertEqual(result["tuning"][rigor]["2"][role][1],
                                 4 if evaluator else 2)
        self.assertEqual(result["families"], document["families"])

    def test_cutover_refuses_missing_required_efforts_without_mutating_input(self):
        for required in ("medium", "xhigh"):
            with self.subTest(missing=required):
                document = old_document()
                document["families"]["2"]["efforts"].remove(required)
                before = copy.deepcopy(document)
                with self.assertRaisesRegex(staffing.StaffingError, required):
                    staffing.add_creativity_roles(document)
                self.assertEqual(document, before)

    def test_cutover_refuses_a_malformed_source_pair_without_mutating_input(self):
        document = old_document()
        document["tuning"]["low"]["1"]["plan"] = []
        before = copy.deepcopy(document)
        with self.assertRaises(staffing.StaffingError):
            staffing.add_creativity_roles(document)
        self.assertEqual(document, before)

    def test_evaluator_without_codex_uses_review_first_assignment(self):
        document = old_document()
        document["families"]["1"]["name"] = "other"
        document["assignment"]["review"] = {"1": 2, "2": 1}
        result = staffing.add_creativity_roles(document)
        self.assertEqual(
            result["assignment"]["creativity_evaluate_candidates"], {"1": 2})
        self.assertEqual(result["roles"]["creativity_evaluate_candidates"], {})

    def test_cutover_refuses_partial_or_already_extended_documents(self):
        for field in ("roles", "assignment"):
            with self.subTest(field=field):
                document = old_document()
                document[field].pop("sync")
                with self.assertRaises(staffing.StaffingError):
                    staffing.add_creativity_roles(document)
        document = old_document()
        document["tuning"]["high"]["1"].pop("sync")
        with self.assertRaises(staffing.StaffingError):
            staffing.add_creativity_roles(document)
        with self.assertRaises(staffing.StaffingError):
            staffing.add_creativity_roles(valid_doc())

    def test_seeds_define_explicit_creativity_tiers_for_both_families(self):
        for profile in (stored_default_shaped(), claude_lead_shaped()):
            document = staffing.convert_profile(profile)
            for slot, family in document["families"].items():
                # Exercise every cell even for the non-assigned family:
                # single-family sessions may need those cells on collapse.
                for role in staffing.CREATIVITY_ROLES:
                    document["assignment"][role] = {"1": int(slot)}
                name = family["name"]
                first = ("gpt-6-luna" if name == "codex"
                         else "claude-sonnet-5")
                model = ("gpt-6-sol" if name == "codex"
                         else "claude-opus-5-5")
                for role in staffing.CREATIVITY_ROLES:
                    expected_effort = ("xhigh" if role == "creativity_evaluate_candidates"
                                       else "medium")
                    self.assertEqual(
                        staffing.base_staffing(document, "low", role),
                        (name, first, expected_effort))
                for rigor in ("medium", "high"):
                    with self.subTest(profile=profile["name"], family=name,
                                      rigor=rigor):
                        self.assertEqual(staffing.base_staffing(
                            document, rigor, "creativity_create_genes"),
                            (name, model, "medium"))
                        self.assertEqual(staffing.base_staffing(
                            document, rigor, "creativity_compose_candidates"),
                            (name, model, "medium"))
                        # The evaluator's existing model tier is preserved in
                        # both family slots; only its effort is fixed to xhigh.
                        source_rigor = "low" if rigor == "medium" else "medium"
                        review_model_rank = document["tuning"][source_rigor][slot][
                            "review"][0]
                        review_model = family["models"][review_model_rank - 1]
                        self.assertEqual(staffing.base_staffing(
                            document, rigor, "creativity_evaluate_candidates"),
                            (name, review_model, "xhigh"))

    def test_old_documents_are_not_automatically_rewritten_on_load_or_ensure(self):
        with tempfile.TemporaryDirectory(prefix="orch-creativity-roles-") as home:
            directory = staffing.staffing_documents_dir(home)
            os.makedirs(directory)
            path = os.path.join(directory, "default.json")
            contents = json.dumps(old_document())
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(contents)
            for action in (lambda: staffing.load(home, "default"),
                           lambda: staffing.ensure_documents(home)):
                with self.assertRaises(staffing.StaffingError):
                    action()
                with open(path, encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), contents)


if __name__ == "__main__":
    unittest.main()
