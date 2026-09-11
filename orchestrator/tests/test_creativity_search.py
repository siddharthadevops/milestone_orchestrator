"""Representation between the served material and native-result contracts."""

import copy
import tempfile
import unittest

from orchestrator import creativity_search as search
from orchestrator import prompt_contracts, prompt_router, prompt_sets, tasks


OBJECTIVE = "Find a way to reach readers."


class CreativitySearchTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        prompt_sets.ensure_default(home.name)
        served = prompt_router.resolve(
            home.name, job="create_genes@creativity", executor="agent_call",
            material="default", values={
                "workspace": "/workspace", "objective": OBJECTIVE,
                "context": "Use existing resources.", "references": "[]",
            },
        ).prompt
        self.bound = prompt_contracts.bind(served)

    def accepted_material(self, dimensions=None):
        if dimensions is None:
            dimensions = [
                {"id": "format", "meaning": "Reading format", "variants": [
                    {"id": "a", "text": "Full story"},
                    {"id": "b", "text": "Excerpt"},
                ]},
                {"id": "channel", "meaning": "Delivery channel", "variants": [
                    {"id": "a", "text": "Library reading"},
                    {"id": "b", "text": "Online reading"},
                    {"id": "c", "text": "Library reading"},
                ]},
            ]
        reply = {"search_material": {
            "objective": OBJECTIVE,
            "context_summary": "A finished story needs an audience.",
            "facts": ["The story is complete."],
            "constraints": [{"id": "budget", "text": "No new spending."}],
            "assumptions": ["Existing channels are available."],
            "unknowns": ["How many readers will attend?"],
            "dimensions": dimensions,
            "composition_guidance": "Combine the chosen format and channel.",
            "criteria": [{"id": "reach", "text": "Reach interested readers."}],
        }}
        return prompt_contracts.validate(
            self.bound, reply, expected_objective=OBJECTIVE,
        )["search_material"]

    def test_genome_representation(self):
        singleton = self.accepted_material(dimensions=[{
            "id": "channel", "meaning": "Delivery channel",
            "variants": [{"id": "only", "text": "Library reading"}],
        }])
        self.assertEqual(
            search.make_genome(singleton["dimensions"], {"channel": 0}),
            {"channel": "only"},
        )

        dimensions = self.accepted_material()["dimensions"]
        identities = set()
        for channel_index, channel_id in enumerate(("a", "b", "c")):
            for format_index, format_id in enumerate(("a", "b")):
                with self.subTest(channel=channel_id, format=format_id):
                    genome = search.make_genome(dimensions, {
                        "channel": channel_index, "format": format_index,
                    })
                    self.assertEqual(genome, {"channel": channel_id, "format": format_id})
                    key = search.genome_key(genome)
                    reordered = dict(reversed(list(genome.items())))
                    self.assertEqual(key, search.genome_key(reordered))
                    identities.add(key)
        # Shared ids across dimensions and equal text under different ids remain distinct.
        self.assertEqual(len(identities), 6)

    def test_problem_is_not_candidate_state(self):
        material = self.accepted_material()
        original = copy.deepcopy(material)
        dimensions = material["dimensions"]
        indices = {"channel": 0, "format": 1}
        first = search.make_genome(dimensions, indices)
        other = search.make_genome(dimensions, indices)
        other_before = dict(other)
        components = search.genome_components(dimensions, first)
        other_components = search.genome_components(dimensions, other)
        components_before = copy.deepcopy(other_components)

        first["channel"] = "b"
        components[1]["dimension"] = "Locally edited label"
        components[1]["variant"] = "Locally edited description"
        self.assertEqual(other, other_before)
        self.assertEqual(other_components, components_before)
        self.assertEqual(search.genome_components(dimensions, other), components_before)
        self.assertEqual(
            search.genome_components(dimensions, first)[1]["variant"], "Online reading",
        )
        self.assertEqual(material, original)

    def test_components_match_native_result_contract(self):
        dimensions = self.accepted_material()["dimensions"]
        first = search.make_genome(dimensions, {"channel": 0, "format": 1})
        second = search.make_genome(dimensions, {"channel": 1, "format": 0})
        first_components = search.genome_components(dimensions, first)
        second_components = search.genome_components(dimensions, second)
        self.assertEqual(first_components, [
            {"dimension_id": "format", "dimension": "Reading format",
             "variant_id": "b", "variant": "Excerpt"},
            {"dimension_id": "channel", "dimension": "Delivery channel",
             "variant_id": "a", "variant": "Library reading"},
        ])
        self.assertEqual(second_components, [
            {"dimension_id": "format", "dimension": "Reading format",
             "variant_id": "a", "variant": "Full story"},
            {"dimension_id": "channel", "dimension": "Delivery channel",
             "variant_id": "b", "variant": "Online reading"},
        ])
        # The same valid proposals as TaskContractsTest's native-result fixture,
        # with components supplied by the representation producer.
        native = {
            "outcome": "proposals",
            "proposals": [
                {"candidate_id": "candidate-1", "components": first_components,
                 "proposal": "Read an excerpt at a library.",
                 "reason": "Uses an existing place to meet readers.",
                 "assumptions": ["A library will host a reading."], "score": 0.75},
                {"candidate_id": "candidate-2", "components": second_components,
                 "proposal": "Share a complete reading online.",
                 "reason": "Reaches readers beyond the local venue.",
                 "assumptions": [], "score": 1},
            ],
            "stop_reason": "generation_limit", "generations_completed": 2,
            "evaluated_candidates": 4, "expansion_interventions": 1,
        }
        self.assertEqual(tasks.validate_creativity_native_result(
            native, dimensions=dimensions, shortlist_size=2,
        ), native)


if __name__ == "__main__":
    unittest.main()
