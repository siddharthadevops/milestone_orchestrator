"""Categorical representation and evolution over accepted creativity replies."""

import copy
import json
import random
import tempfile
import unittest
from unittest import mock

from orchestrator import creativity_search as search
from orchestrator import prompt_contracts, prompt_router, prompt_sets, tasks
from orchestrator.tests.test_tasks import creativity_configuration


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
        self.evaluation_bound = prompt_contracts.bind(prompt_router.resolve(
            home.name, job="evaluate_candidates@creativity", executor="agent_call",
            material="default", values={
                "workspace": "/workspace",
                "search_material": json.dumps(self.accepted_material()),
                "candidates": "[]",
            },
        ).prompt)

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

    def evaluated(self, genomes, scores, invalid=(), prefix="candidate"):
        evaluations = [{
            "candidate_id": "%s-%s" % (prefix, index),
            "proposal": "Use the proposed combination.",
            "constraint_valid": index not in invalid,
            "constraint_violations": ["budget"] if index in invalid else [],
            "reason": "Assessment against the supplied objective and constraints.",
            "assumptions": [], "score": score,
        } for index, score in enumerate(scores)]
        reply = prompt_contracts.validate(
            self.evaluation_bound, {"evaluations": evaluations},
            candidate_ids=[item["candidate_id"] for item in evaluations],
            constraint_ids=["budget"],
        )
        return list(zip(genomes, reply["evaluations"]))

    def assert_population(self, dimensions, population, bound, explored=()):
        keys = {search.genome_key(genome) for genome in population}
        self.assertEqual(len(keys), len(population))
        self.assertLessEqual(len(population), bound)
        self.assertTrue(keys.isdisjoint(explored))
        for genome in population:
            self.assertEqual(set(genome), {dimension["id"] for dimension in dimensions})
            self.assertEqual(
                [(component["dimension_id"], component["variant_id"])
                 for component in search.genome_components(dimensions, genome)],
                [(dimension["id"], genome[dimension["id"]]) for dimension in dimensions],
            )

    def observe_generation(self, progress, pairs, configuration):
        search.begin_generation(progress, {
            item["candidate_id"]: genome for genome, item in pairs
        }, configuration)
        search.accept_evaluation_wave(progress, {
            "accepted_count": progress["evaluated_candidates"] + len(pairs),
            "regime_revision": 1, "rebaseline_required": False,
            "comparison_ready": True, "unfinished": [], "interruption": None,
            "evaluated": progress["archive"] + pairs,
        }, configuration)

    def test_population_bounds_and_explored_identity(self):
        dimensions = self.accepted_material()["dimensions"]
        configuration = tasks.resolve_creativity_configuration(creativity_configuration(
            population_size=8, max_evaluated_candidates=8,
        ))
        expected = {search.genome_key({"format": f, "channel": c})
                    for f in ("a", "b") for c in ("a", "b", "c")}
        rng = random.Random(4)
        # Repeated ordinary draws must still fill from the finite repertoire.
        with mock.patch.object(rng, "randrange", return_value=0):
            for requested in (0, 2, 5, 8, 12):
                with self.subTest(requested=requested):
                    population = search.make_population(
                        dimensions, requested, configuration, rng=rng,
                    )
                    self.assertEqual(len(population), min(requested, 6))
                    self.assert_population(dimensions, population, min(requested, 8))
                    self.assertTrue({search.genome_key(g) for g in population} <= expected)
            unseen = {"channel": "c", "format": "b"}
            explored = expected - {search.genome_key(unseen)}
            before = set(explored)
            population = search.make_population(
                dimensions, 8, configuration, explored=explored, rng=rng,
            )
            self.assertEqual(population, [unseen])
            self.assertEqual(explored, before)
            self.assertEqual(search.make_population(
                dimensions, 8, configuration, explored=expected, rng=rng,
            ), [])
        self.assertEqual(len(search.make_population(
            dimensions, 8, creativity_configuration(), rng=rng,
        )), 2)
        singleton = self.accepted_material(dimensions=[{
            "id": "only", "meaning": "Only option",
            "variants": [{"id": "only", "text": "The sole choice"}],
        }])["dimensions"]
        population = search.make_population(singleton, 8, configuration, rng=rng)
        self.assertEqual(population, [{"only": "only"}])
        self.assertEqual(search.make_population(
            singleton, 8, configuration, explored={search.genome_key(population[0])},
        ), [])

    def test_valid_elites_and_unique_survivors(self):
        dimensions = self.accepted_material()["dimensions"]
        genomes = [{"format": f, "channel": c}
                   for f in ("a", "b") for c in ("a", "b", "c")]
        evaluated = self.evaluated(genomes, [1, 0.8, 0.3, 0.9, 0.7, 0.6], invalid={0})
        evaluated += self.evaluated(
            [dict(reversed(list(genomes[3].items())))], [0.4], prefix="retained",
        )
        original = copy.deepcopy(evaluated)
        configuration = tasks.resolve_creativity_configuration(creativity_configuration(
            population_size=4, max_evaluated_candidates=4, elite_count=2, diversity_count=2,
        ))
        survivors = search.select_survivors(evaluated, configuration)
        self.assertEqual([pair[0] for pair in survivors[:2]], [genomes[3], genomes[1]])
        self.assertEqual([pair[1]["score"] for pair in survivors[:2]], [0.9, 0.8])
        self.assertEqual(len(survivors), 4)
        self.assertTrue(all(evaluation["constraint_valid"] for _, evaluation in survivors))
        self.assert_population(dimensions, [pair[0] for pair in survivors], 4)
        self.assertIsNot(survivors[0][0], genomes[3])
        self.assertEqual(evaluated, original)
        self.assertEqual(search.select_survivors(evaluated[:2], configuration), [evaluated[1]])
        self.assertEqual(search.select_survivors(evaluated[:1], configuration), [])
        self.assertEqual(search.select_survivors([], configuration), [])

    def test_reserved_structural_diversity(self):
        dimensions = [{
            "id": "d%s" % index, "meaning": "Choice %s" % index,
            "variants": [{"id": value, "text": "Option " + value} for value in "ab"],
        } for index in range(4)]
        for relabeled in (False, True):
            with self.subTest(relabeled=relabeled):
                source = copy.deepcopy(dimensions)
                if relabeled:
                    source.reverse()
                    for dimension in source:
                        dimension["meaning"] = "Changed label"
                        for variant in dimension["variants"]:
                            variant["text"] = "Identical text for distinct ids"
                accepted = self.accepted_material(dimensions=source)["dimensions"]
                genomes = [search.make_genome(accepted, {
                    "d%s" % index: "ab".index(value) for index, value in enumerate(choices)
                }) for choices in ("aaaa", "aaab", "aaba", "aabb", "bbbb", "bbaa")]
                evaluated = self.evaluated(genomes, [1, 0.95, 0.9, 0.8, 0.4, 0.3])
                if relabeled:
                    evaluated.reverse()
                    for _, evaluation in evaluated:
                        evaluation["proposal"] = "Changed prose"
                small = search.select_survivors(evaluated, creativity_configuration())
                self.assertEqual([pair[0] for pair in small], [genomes[0], genomes[4]])
                configuration = tasks.resolve_creativity_configuration(creativity_configuration(
                    population_size=4, max_evaluated_candidates=4,
                    elite_count=2, diversity_count=2,
                ))
                larger = search.select_survivors(evaluated, configuration)
                self.assertEqual([pair[0] for pair in larger], [
                    genomes[0], genomes[1], genomes[4], genomes[5],
                ])

    def test_crossover_and_mutation_preserve_candidates(self):
        source = self.accepted_material()["dimensions"] + [{
            "id": "fixed", "meaning": "Singleton choice",
            "variants": [{"id": "only", "text": "Unchanging option"}],
        }]
        material = self.accepted_material(dimensions=source)
        dimensions = material["dimensions"]
        evaluated = self.evaluated([
            {"format": "a", "channel": "a", "fixed": "only"},
            {"format": "b", "channel": "b", "fixed": "only"},
        ], [0.9, 0.8])
        parents = search.select_survivors(evaluated, creativity_configuration())
        before = copy.deepcopy((material, evaluated, parents))
        rng = random.Random(8)
        with mock.patch.object(rng, "random", return_value=0.75):
            crossed = [search.make_child(dimensions, parents, 0.5, rng=rng) for _ in range(32)]
        self.assertTrue(any(child["format"] != child["channel"] for child in crossed))
        self.assertTrue(all(child["channel"] in ("a", "b") for child in crossed))
        mutated = [search.make_child(dimensions, parents, 1, rng=rng) for _ in range(32)]
        self.assertIn("c", {child["channel"] for child in mutated})
        for child in crossed + mutated:
            self.assert_population(dimensions, [child], 1)
            self.assertEqual(child["fixed"], "only")

        one_material = self.accepted_material(dimensions=source[1:])
        one_parent = self.evaluated([{"channel": "a", "fixed": "only"}], [0.9])
        one_before = copy.deepcopy((one_material, one_parent))
        for rate, draw, changes in ((1, 0.999, True), (0.5, 0.25, True), (0.5, 0.75, False)):
            with self.subTest(rate=rate, draw=draw), mock.patch.object(rng, "random", return_value=draw):
                child = search.make_child(one_material["dimensions"], one_parent, rate, rng=rng)
                self.assertEqual(child["channel"] != "a", changes)
                self.assertEqual(child["fixed"], "only")
        self.assertEqual((one_material, one_parent), one_before)
        siblings = copy.deepcopy(mutated[1:])
        mutated[0]["channel"] = "a" if mutated[0]["channel"] != "a" else "b"
        self.assertEqual(mutated[1:], siblings)
        self.assertEqual((material, evaluated, parents), before)

    def test_productive_generation_variation(self):
        dimensions = self.accepted_material(dimensions=[{
            "id": "choice", "meaning": "Approach",
            "variants": [{"id": value, "text": "Approach " + value} for value in "abcdefghijkl"],
        }])["dimensions"]
        for population_size in (2, 4):
            with self.subTest(population_size=population_size):
                configuration = tasks.resolve_creativity_configuration(creativity_configuration(
                    population_size=population_size, max_evaluated_candidates=12, mutation_rate=0.5,
                ))
                rng = random.Random(12)
                with mock.patch.object(rng, "randrange", return_value=0):
                    population = search.make_population(dimensions, population_size, configuration, rng=rng)
                evaluated = self.evaluated(population, [0.2] * len(population))
                survivors = search.select_survivors(evaluated, configuration)
                explored = {search.genome_key(genome) for genome in population}
                for generation, target in enumerate(("l", "k"), start=1):
                    before = copy.deepcopy(survivors)
                    # Prefer a known, unseen alternative whenever mutation offers it.
                    with mock.patch.object(rng, "random", return_value=0.25), mock.patch.object(
                        rng, "choice", side_effect=lambda choices: target if target in choices else choices[0],
                    ):
                        children = search.reproduce(
                            dimensions, survivors, population_size + 3, configuration,
                            explored=explored, rng=rng,
                        )
                    self.assertEqual(survivors, before)
                    self.assertEqual(len(children), population_size)
                    self.assertIn({"choice": target}, children)
                    self.assert_population(dimensions, children, population_size, explored)
                    fresh = self.evaluated(children, [0.2 + 0.2 * generation] * len(children),
                                           prefix="generation-%s" % generation)
                    survivors = search.select_survivors(survivors + fresh, configuration)
                    self.assertGreater(survivors[0][1]["score"], before[0][1]["score"])
                    self.assertEqual(len(survivors), 2)
                    explored.update(search.genome_key(genome) for genome in children)
                self.assertEqual(search.reproduce(dimensions, [], population_size, configuration), [])
                all_keys = {search.genome_key({"choice": value}) for value in "abcdefghijkl"}
                self.assertEqual(search.reproduce(
                    dimensions, survivors, population_size, configuration, explored=all_keys, rng=rng,
                ), [])

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

    def test_cumulative_best_valid_progress(self):
        configuration = tasks.resolve_creativity_configuration(creativity_configuration(
            generation_limit=12, max_evaluated_candidates=24,
            minimum_improvement=0.125, patience_generations=3,
        ))
        genomes = [{"format": f, "channel": c}
                   for f in ("a", "b") for c in ("a", "b", "c")]

        def observe(progress, choices, scores, invalid=()):
            pairs = self.evaluated(choices, scores, invalid, prefix=str(progress["generations_completed"]))
            candidates = {item["candidate_id"]: genome for genome, item in pairs}
            search.begin_generation(progress, candidates, configuration)
            search.accept_evaluation_wave(progress, {
                "accepted_count": progress["evaluated_candidates"] + len(pairs),
                "regime_revision": 1, "rebaseline_required": False,
                "comparison_ready": True, "unfinished": [], "interruption": None,
                "evaluated": progress["archive"] + pairs,
            }, configuration)

        progress = search.new_progress()
        observe(progress, genomes[:2], [0.25, 0.24])
        self.assertEqual(progress["reference_score"], 0.25)
        self.assertFalse(progress["progress_made"])
        # Prior intervention usage is part of the task-owned progress handoff.
        progress.update(consecutive_expansions=1, expansion_interventions=2)
        observe(progress, genomes[2:3], [0.3125])
        self.assertEqual(progress["best_score"], 0.3125)
        self.assertEqual(progress["reference_score"], 0.25)
        self.assertEqual(progress["stagnant_generations"], 1)
        # A poor round and an invalid high score do not finish a longer window.
        observe(progress, genomes[3:5], [0.01, 1], invalid=(1,))
        self.assertEqual(progress["best_score"], 0.3125)
        self.assertEqual(progress["reference_score"], 0.25)
        self.assertEqual(progress["stagnant_generations"], 2)
        self.assertFalse(progress["window_complete"])
        observe(progress, genomes[5:], [0.375])
        self.assertTrue(progress["progress_made"])
        self.assertEqual(progress["reference_score"], 0.375)
        self.assertEqual(progress["stagnant_generations"], 0)
        self.assertEqual(progress["consecutive_expansions"], 0)
        self.assertEqual(progress["expansion_interventions"], 2)
        self.assertEqual(progress["generations_completed"], 4)
        self.assertEqual(progress["evaluated_candidates"], 6)

        empty = search.new_progress()
        empty.update(consecutive_expansions=1, expansion_interventions=1)
        for index in range(3):
            observe(empty, genomes[index:index + 1], [1], invalid=(0,))
            self.assertIsNone(empty["reference_score"])
            self.assertIsNone(empty["best_score"])
            self.assertEqual(empty["archive"], [])
            self.assertEqual(empty["window_complete"], index == 2)
        observe(empty, genomes[3:4], [0.25])
        self.assertEqual(empty["reference_score"], 0.25)
        self.assertEqual(empty["stagnant_generations"], 0)
        self.assertFalse(empty["progress_made"])
        self.assertEqual(empty["consecutive_expansions"], 1)

    def test_full_windows_bound_expansion(self):
        configuration = creativity_configuration(
            generation_limit=20, max_evaluated_candidates=40,
            minimum_improvement=0.125, patience_generations=2,
        )
        material = self.accepted_material()
        progress = search.new_progress()
        choices = [{"format": f, "channel": c} for f in "ab" for c in "abc"]
        for index in range(3):
            self.observe_generation(progress, self.evaluated(
                choices[index:index + 1], [0.25], prefix=str(index),
            ), configuration)
            self.assertEqual(search.expansion_due(progress, configuration), index == 2)
        addition = {"additions": [{"dimension_id": "format", "variants": [
            {"id": "c", "text": "Serial reading", "reason": "Build repeated attendance."},
        ]}]}
        material = search.accept_expansion(progress, material, addition, configuration, explored=[])
        self.assertEqual(progress["reference_score"], 0.25)
        self.assertFalse(progress["progress_made"])
        self.assertFalse(search.expansion_due(progress, configuration))
        self.assertEqual(progress["consecutive_expansions"], 1)
        for index, score in enumerate((0.3125, 0.375), start=3):
            self.observe_generation(progress, self.evaluated(
                choices[index:index + 1], [score], prefix=str(index),
            ), configuration)
            self.assertFalse(search.expansion_due(progress, configuration))
        self.assertTrue(progress["progress_made"])
        self.assertEqual(progress["consecutive_expansions"], 0)
        self.assertEqual(progress["expansion_interventions"], 1)
        parent = progress["archive"][:1]
        child = search.reproduce(material["dimensions"], parent, 1, configuration)[0]
        self.assertTrue(all(child[key] != parent[0][0][key] for key in child))
        for index in range(2):
            self.observe_generation(progress, [], configuration)
            self.assertEqual(search.expansion_due(progress, configuration), index == 1)
        search.accept_expansion(progress, material, {"additions": []}, configuration, explored=[])
        for index in range(2):
            self.observe_generation(progress, [], configuration)
            self.assertFalse(search.expansion_due(progress, configuration))
            self.assertEqual(progress["stop_reason"], "persistent_stagnation" if index == 1 else None)
        self.assertEqual(progress["expansion_interventions"], 2)
        self.assertEqual(progress["generations_completed"], 9)
        self.assertEqual(progress["evaluated_candidates"], 5)

    def test_expansion_preserves_material_and_archive(self):
        material = self.accepted_material()
        original = copy.deepcopy(material)
        configuration = creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
        progress = search.new_progress()
        population = search.make_population(material["dimensions"], 2, configuration)
        self.observe_generation(progress, self.evaluated(population, [0.5, 0.25]), configuration)
        self.observe_generation(progress, [], configuration)
        archive = copy.deepcopy(progress["archive"])
        self.assertTrue(search.expansion_due(progress, configuration))
        expansion = {"generation": 2, "call_id": "expansion", "additions": [{
            "dimension_id": "format", "variants": [
                {"id": "new", "text": "Full story", "reason": "Another arrangement."},
            ],
        }]}
        expanded = search.accept_expansion(progress, material, expansion, configuration, explored=[])
        self.assertEqual(material, original)
        expected = copy.deepcopy(original)
        expected["dimensions"][0]["variants"].append({"id": "new", "text": "Full story"})
        self.assertEqual(expanded, expected)
        self.assertEqual(progress["archive"], archive)
        self.assertEqual(progress["expansions"], [expansion])
        self.assertEqual(progress["reference_score"], 0.5)
        self.assertFalse(progress["progress_made"])
        explored = {search.genome_key({"format": f, "channel": c}) for f in "ab" for c in "abc"}
        children = search.reproduce(expanded["dimensions"], archive, 2, configuration, explored=explored)
        self.assertEqual(len(children), 2)
        self.assertTrue(all(child["format"] == "new" for child in children))

    def test_exact_search_stop_reasons(self):
        material = self.accepted_material(dimensions=[{
            "id": "d", "meaning": "Direction", "variants": [
                {"id": "a", "text": "First"}, {"id": "b", "text": "Second"},
            ],
        }])
        choices = [{"d": "a"}, {"d": "b"}]
        all_keys = {search.genome_key(genome) for genome in choices}
        for explored in (set(), {search.genome_key(choices[0])}, all_keys):
            with self.subTest(explored=explored):
                configuration = creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
                progress = search.new_progress()
                pairs = self.evaluated(choices[:len(explored)], [1] * len(explored), invalid=(0, 1))
                self.observe_generation(progress, pairs, configuration)
                self.assertTrue(search.expansion_due(progress, configuration))
                self.assertEqual(search.reproduce(material["dimensions"], progress["archive"],
                                                  2, configuration, explored=explored), [])
                with mock.patch.object(search.random, "randrange", return_value=0):
                    search.accept_expansion(progress, material, {"additions": []},
                                            configuration, explored=explored)
                self.assertEqual(progress["stop_reason"],
                                 "repertoire_exhausted" if explored == all_keys else None)
                self.assertEqual(progress["archive"], [])
                self.assertIsNone(progress["best_score"])
                self.assertEqual(progress["evaluated_candidates"], len(explored))
                self.assertEqual(progress["generations_completed"], 1)
                self.assertEqual(progress["expansion_interventions"], 1)
        for reason, limits in (("generation_limit", {"generation_limit": 1}),
                               ("evaluation_budget", {"max_evaluated_candidates": 2})):
            configuration = creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
            configuration.update(limits)
            progress = search.new_progress()
            self.observe_generation(progress, self.evaluated(choices, [1, 1], invalid=(0, 1)), configuration)
            self.assertFalse(search.expansion_due(progress, configuration))
            self.assertEqual(progress["stop_reason"], reason)
            self.assertEqual(progress["expansion_interventions"], 0)

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
