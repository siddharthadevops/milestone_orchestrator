"""Categorical representation and evolution over accepted creativity replies."""

import copy
import math
import random
import unittest
from unittest import mock

from orchestrator import creativity_search as search
from orchestrator import prompt_contracts, tasks
from orchestrator.tests.test_tasks import creativity_configuration, legacy_creativity_configuration


OBJECTIVE = "Find a way to reach readers."


class CreativitySearchTest(unittest.TestCase):
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
            "order_semantics": "sequence in which the selected components are applied",
        }}
        return prompt_contracts.validate_create_genes_reply(reply)["search_material"]

    def evaluated(self, genomes, scores, invalid=(), prefix="candidate"):
        evaluations = [{
            "candidate_id": "%s-%s" % (prefix, index),
            "proposal": "Use the proposed combination.",
            "constraint_valid": index not in invalid,
            "constraint_violations": ["budget"] if index in invalid else [],
            "reason": "Assessment against the supplied objective and constraints.",
            "assumptions": [], "score": score,
        } for index, score in enumerate(scores)]
        return list(zip(genomes, evaluations))

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

    def observe_generation(self, progress, pairs, configuration, *, dimensions=None,
                           creativity_semantics=None):
        search.begin_generation(progress, {
            item["candidate_id"]: genome for genome, item in pairs
        }, configuration, creativity_semantics=creativity_semantics)
        search.accept_evaluation_wave(progress, {
            "accepted_count": progress["evaluated_candidates"] + len(pairs),
            "regime_revision": 1, "rebaseline_required": False,
            "comparison_ready": True, "unfinished": [], "interruption": None,
            "evaluated": progress["archive"] + pairs,
        }, configuration, dimensions=dimensions, creativity_semantics=creativity_semantics)

    def sparse_material(self, dimension_count=3, variant_count=2):
        material = self.accepted_material()
        material["dimensions"] = [
            {"id": "d%s" % i, "meaning": "Focus %s" % i} for i in range(dimension_count)
        ]
        material["variants"] = [
            {"id": "v%s" % i, "text": "Action %s" % i} for i in range(variant_count)
        ]
        return prompt_contracts.validate_create_genes_reply(
            {"search_material": material}, creativity_semantics="sparse_v2",
        )["search_material"]

    def sparse_key(self, material, genome, mode=None):
        return search.genome_key(
            genome, material["dimensions"], mode, creativity_semantics="sparse_v2",
        )

    def fragment_material(self, *fragments):
        return {
            "dimensions": [
                {"id": "fragment_%02d" % index, "meaning": fragment}
                for index, fragment in enumerate(fragments, 1)
            ],
            "variants": [
                {"id": "affirmed", "text": "Include"},
                {"id": "negated", "text": "Exclude"},
            ],
        }

    def test_fragments_exhaust_exact_nonempty_repertoire(self):
        for fragments in (("Firebase",), ("Firebase", "local storage")):
            material = self.fragment_material(*fragments)
            dimensions = material["dimensions"]
            ids = [d["id"] for d in dimensions]
            context = dict(variants=material["variants"], creativity_semantics="fragments_v3")
            singletons = {((dimension, value),) for dimension in ids
                          for value in ("affirmed", "negated")}
            for mode in ("fixed", "interchangeable"):
                expected = set(singletons)
                if len(ids) == 2:
                    for left in ("affirmed", "negated"):
                        for right in ("affirmed", "negated"):
                            pair = ((ids[0], left), (ids[1], right))
                            expected.add(pair)
                            if mode == "interchangeable":
                                expected.add(pair[::-1])
                with self.subTest(fragments=fragments, mode=mode):
                    configuration = creativity_configuration(population_size=20, order_mode=mode)
                    rng = random.Random(4)
                    # Even exclusively empty random draws must enumerate every
                    # nonempty inspiration once, then report real exhaustion.
                    with mock.patch.object(rng, "random", return_value=0):
                        population = search.make_population(
                            dimensions, 20, configuration, rng=rng, **context,
                        )
                    keys = {search.genome_key(g, dimensions, mode,
                                              creativity_semantics="fragments_v3")
                            for g in population}
                    self.assertEqual(keys, expected)
                    self.assertEqual(len(population), len(expected))
                    self.assertNotIn(None, keys)
                    self.assertEqual(search.make_population(
                        dimensions, 20, configuration, explored=keys, rng=rng, **context,
                    ), [])
                    progress = search.new_progress()
                    search.begin_generation(progress, {}, configuration,
                                            creativity_semantics="fragments_v3")
                    self.assertEqual(progress["stop_reason"], "repertoire_exhausted")

    def test_fragments_identity_tracks_polarity_and_effective_order(self):
        material = self.fragment_material("casa", "roja", "limpiar")
        dimensions = material["dimensions"]
        genome = {search.ORDER_GENE: 0, "fragment_01": "affirmed",
                  "fragment_02": search.OMIT, "fragment_03": "affirmed"}

        def key(value):
            return search.genome_key(value, dimensions, "interchangeable",
                                     creativity_semantics="fragments_v3")

        self.assertEqual(key(genome), (("fragment_01", "affirmed"), ("fragment_03", "affirmed")))
        # Moving only the omitted fragment leaves the effective inspiration unchanged.
        self.assertEqual(key(dict(genome, **{search.ORDER_GENE: 2})), key(genome))
        distinct = [genome, dict(genome, fragment_01="negated"),
                    dict(genome, fragment_01=search.OMIT),
                    dict(genome, **{search.ORDER_GENE: 5})]
        self.assertEqual(len({key(value) for value in distinct}), 4)
        empty = {search.ORDER_GENE: 0, **{dimension["id"]: search.OMIT for dimension in dimensions}}
        self.assertIsNone(key(empty))

    def test_fragments_ordered_components_preserve_words_and_negation(self):
        material = self.fragment_material("casa", "roja", "limpiar")
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="fragments_v3")
        genome = search.make_genome(dimensions, {
            "fragment_01": 0, "fragment_02": 1, "fragment_03": 0,
        }, **context)
        expected = [
            {"dimension_id": "fragment_01", "dimension": "casa", "variant_id": "affirmed", "variant": "Include"},
            {"dimension_id": "fragment_02", "dimension": "roja", "variant_id": "negated", "variant": "Exclude"},
            {"dimension_id": "fragment_03", "dimension": "limpiar", "variant_id": "affirmed", "variant": "Include"},
        ]
        self.assertEqual(search.genome_components(dimensions, genome, "fixed", **context), expected)
        reordered = dict(genome, **{search.ORDER_GENE: search.rank_order(
            [d["id"] for d in dimensions], ["fragment_03", "fragment_01", "fragment_02"],
        )})
        self.assertEqual(search.genome_components(dimensions, reordered, "interchangeable", **context),
                         [expected[2], expected[0], expected[1]])
        omitted = dict(genome, fragment_02=search.OMIT)
        self.assertEqual(search.genome_components(dimensions, omitted, "fixed", **context),
                         [expected[0], expected[2]])

    def test_fragments_mutation_can_toggle_every_polarity_and_participation(self):
        material = self.fragment_material("Firebase")
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="fragments_v3")
        cases = [
            ("affirmed", "negated", 0.75), ("negated", "affirmed", 0.75),
            ("affirmed", search.OMIT, 0.25), ("negated", search.OMIT, 0.25),
            (search.OMIT, "affirmed", 0.25), (search.OMIT, "negated", 0.25),
        ]
        for source, target, mutation_kind in cases:
            with self.subTest(source=source, target=target):
                parent = {"fragment_01": source}
                parents = self.evaluated([parent], [0.8])
                before = copy.deepcopy(parents)
                rng = random.Random(1)

                def choose(choices):
                    if choices and isinstance(choices[0], dict):
                        return next(value for value in choices if value["id"] == target)
                    return choices[0]

                with mock.patch.object(rng, "random", side_effect=[0, mutation_kind]), \
                     mock.patch.object(rng, "choice", side_effect=choose):
                    child = search.make_child(dimensions, parents, 1, rng=rng, **context)
                self.assertEqual(child, {"fragment_01": target})
                self.assertEqual(parents, before)

        parent = {"fragment_01": "affirmed"}
        empty = {"fragment_01": search.OMIT}
        with mock.patch.object(search, "make_child", return_value=empty):
            offspring = search.reproduce(
                dimensions, self.evaluated([parent], [1]), 10,
                creativity_configuration(population_size=10), **context,
            )
        self.assertEqual(offspring, [{"fragment_01": "negated"}])

    def test_fragments_reject_invalid_survivors_when_valid_candidate_exists(self):
        material = self.fragment_material("Firebase", "local storage")
        context = dict(dimensions=material["dimensions"], creativity_semantics="fragments_v3")
        configuration = creativity_configuration(generation_limit=3)
        pairs = self.evaluated([
            {"fragment_01": "affirmed", "fragment_02": "affirmed"},
            {"fragment_01": "negated", "fragment_02": "affirmed"},
        ], [1, 0.4], invalid=(0,))
        self.assertEqual(search.select_survivors(pairs, configuration, **context), pairs[1:])
        provisional = search.select_survivors(pairs[:1], configuration, **context)
        self.assertEqual(provisional, pairs[:1])
        self.assertFalse(provisional[0][1]["constraint_valid"])
        progress = search.new_progress()
        self.observe_generation(progress, provisional, configuration, **context)
        self.assertIsNone(progress["stop_reason"])
        self.assertEqual(progress["stagnant_generations"], 0)
        progress["window_complete"] = True
        self.assertFalse(search.expansion_due(progress, configuration, creativity_semantics="fragments_v3"))
        self.assertIsNone(progress["stop_reason"])

    def test_sparse_search_context_and_legacy_compatibility(self):
        material = self.sparse_material(2)
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
        for mode in (None, "fixed", "interchangeable"):
            configuration = creativity_configuration(population_size=20, order_mode=mode)
            population = search.make_population(dimensions, 20, configuration, **context)
            self.assertEqual(len(population), 12 if mode == "interchangeable" else 8)
            for dimension in dimensions:
                self.assertEqual({g[dimension["id"]] for g in population}, {search.OMIT, "v0", "v1"})
            reversed_values = search.make_population(
                dimensions, 20, configuration, variants=list(reversed(material["variants"])),
                creativity_semantics="sparse_v2",
            )
            self.assertEqual(
                {self.sparse_key(material, g, mode) for g in population},
                {self.sparse_key(material, g, mode) for g in reversed_values},
            )
            legacy = self.accepted_material()["dimensions"]
            self.assertEqual(
                search.make_population(legacy, 20, configuration, rng=random.Random(3)),
                search.make_population(legacy, 20, configuration, rng=random.Random(3),
                                       variants=material["variants"]),
            )

    def test_sparse_participation_and_variation(self):
        for width in (2, 100):
            material = self.sparse_material(5, width)
            original = copy.deepcopy(material)
            dimensions = material["dimensions"]
            context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
            rng = random.Random(7)
            with mock.patch.object(rng, "random", side_effect=[0.75, 0.25, 0.75, 0.25, 0.75]), \
                 mock.patch.object(rng, "randrange", return_value=0):
                population = search.make_population(
                    dimensions, 1, creativity_configuration(), rng=rng, **context,
                )
            parent = {"d0": "v0", "d1": search.OMIT, "d2": "v0", "d3": search.OMIT, "d4": "v0"}
            self.assertEqual(population, [parent])
            parents = self.evaluated(population, [0.8])
            before = copy.deepcopy((material, parents))
            # Deactivate, activate, change value, then leave the last two unchanged.
            draws = [0.25, 0.25, 0.25, 0.25, 0.25, 0.75, 0.75, 0.75]
            with mock.patch.object(rng, "random", side_effect=draws), \
                 mock.patch.object(rng, "choice", side_effect=lambda choices: choices[0]):
                child = search.make_child(dimensions, parents, 0.5, rng=rng, **context)
            self.assertEqual(child, {
                "d0": search.OMIT, "d1": "v0", "d2": "v1", "d3": search.OMIT, "d4": "v0",
            })
            self.assertEqual((material, parents), before)
            other = self.evaluated([{d["id"]: "v1" for d in dimensions}], [0.7])
            inherited_from = [other[0], parents[0], other[0], parents[0], other[0]]
            with mock.patch.object(rng, "sample", return_value=parents + other), \
                 mock.patch.object(rng, "choice", side_effect=inherited_from):
                inherited = search.make_child(dimensions, parents + other, 0, rng=rng, **context)
            self.assertEqual(inherited, {
                "d0": "v1", "d1": search.OMIT, "d2": "v1", "d3": search.OMIT, "d4": "v1",
            })
            self.assertEqual(material, original)

        material = self.sparse_material(5, 1)
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
        for active_count in range(1, 6):
            with mock.patch.object(rng, "random", side_effect=[0.75] * active_count + [0.25] * (5 - active_count)):
                population = search.make_population(
                    dimensions, 1, creativity_configuration(), rng=rng, **context,
                )
            self.assertEqual(sum(value != search.OMIT for value in population[0].values()), active_count)
        with mock.patch.object(rng, "random", return_value=0.75):
            population = search.make_population(dimensions, 1, creativity_configuration(), rng=rng, **context)
            self.assertEqual(population, [{d["id"]: "v0" for d in dimensions}])
            self.assertEqual(search.make_child(dimensions, self.evaluated(population, [1]), 1,
                                               rng=rng, **context), population[0])
        with mock.patch.object(rng, "random", return_value=0.25):
            empty = search.make_child(dimensions, self.evaluated(population, [1]), 1, rng=rng, **context)
            self.assertEqual(empty, {d["id"]: search.OMIT for d in dimensions})
            self.assertEqual(
                search.make_child(dimensions, [(empty, {})], 1, rng=rng, **context), population[0],
            )

    def test_sparse_ordered_components(self):
        material = self.sparse_material(10)
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
        genome = {d["id"]: search.OMIT for d in dimensions}
        genome.update(d0="v0", d4="v1", d9="v0")
        expected = [{"dimension_id": "d%s" % i, "dimension": "Focus %s" % i,
                     "variant_id": "v%s" % v, "variant": "Action %s" % v}
                    for i, v in ((0, 0), (4, 1), (9, 0))]
        self.assertEqual(search.genome_components(dimensions, genome, "fixed", **context), expected)
        genome[search.ORDER_GENE] = math.factorial(10) - 1
        self.assertEqual(
            search.genome_components(dimensions, genome, "interchangeable", **context), expected[::-1],
        )

        material = self.sparse_material(3, 1)
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
        parent = {search.ORDER_GENE: 0, "d0": "v0", "d1": search.OMIT, "d2": "v0"}
        reversed_parent = dict(parent, **{search.ORDER_GENE: 5})
        parents = self.evaluated([parent, reversed_parent], [1, 0.8])
        rng = random.Random(2)
        with mock.patch.object(rng, "choice", return_value=parents[1]):
            self.assertEqual(search.make_child(dimensions, parents, 0, order_mode="interchangeable",
                                               rng=rng, **context), reversed_parent)
        with mock.patch.object(rng, "random", return_value=0.75), \
             mock.patch.object(rng, "randrange", return_value=4):
            children = search.reproduce(dimensions, parents[:1], 1, creativity_configuration(
                order_mode="interchangeable", mutation_rate=1,
            ), rng=rng, **context)
        self.assertEqual(children, [reversed_parent])

    def test_sparse_effective_identity_and_nonempty_handoff(self):
        material = self.sparse_material()
        dimensions = material["dimensions"]
        context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
        genome = {search.ORDER_GENE: 0, "d0": "v0", "d1": search.OMIT, "d2": "v0"}
        key = self.sparse_key(material, genome, "interchangeable")
        self.assertEqual(key, (("d0", "v0"), ("d2", "v0")))
        for order in (0, 1, 2):
            equivalent = dict(reversed(list(dict(genome, **{search.ORDER_GENE: order}).items())))
            self.assertEqual(self.sparse_key(material, equivalent, "interchangeable"), key)
        for changes in ({"d0": "v1"}, {"d2": search.OMIT}, {search.ORDER_GENE: 5}):
            self.assertNotEqual(self.sparse_key(material, dict(genome, **changes), "interchangeable"), key)
        empty = {search.ORDER_GENE: 5, **{d["id"]: search.OMIT for d in dimensions}}
        self.assertIsNone(self.sparse_key(material, empty, "interchangeable"))
        configuration = creativity_configuration(order_mode="interchangeable", population_size=4)
        rng = random.Random(2)
        with mock.patch.object(rng, "random", return_value=0), \
             mock.patch.object(search, "make_child", return_value=empty):
            populations = [
                search.make_population(dimensions, 4, configuration, explored={key}, rng=rng, **context),
                search.reproduce(
                    dimensions, self.evaluated([genome], [1]), 4, configuration, rng=rng, **context,
                ),
            ]
        for population in populations:
            keys = {self.sparse_key(material, g, "interchangeable") for g in population}
            self.assertEqual(len(keys), 4)
            self.assertTrue(keys.isdisjoint({None, key}))

    def test_sparse_effective_diversity(self):
        material = self.sparse_material()
        base = {"d0": "v0", "d1": search.OMIT, "d2": "v0"}
        for mode in ("fixed", "interchangeable"):
            context = dict(dimensions=material["dimensions"], creativity_semantics="sparse_v2")
            configuration = creativity_configuration(order_mode=mode)
            elite = dict(base)
            if mode == "interchangeable":
                elite[search.ORDER_GENE] = 0
            equivalent = dict(elite)
            if mode == "interchangeable":
                equivalent[search.ORDER_GENE] = 2  # Only the omitted position moves.
            differences = [({"d0": "v1"}, {"d1": "v0"}),
                           ({"d1": "v0"}, {"d0": "v1"})]
            if mode == "interchangeable":
                differences.append(({"d0": "v1"}, {search.ORDER_GENE: 5}))
            for first, second in differences:
                near = dict(elite, **first)
                far = dict(near, **second)
                pairs = self.evaluated([elite, equivalent, near, far], [1, 0.99, 0.8, 0.8])
                before = copy.deepcopy(pairs)
                selected = search.select_survivors(pairs, configuration, **context)
                self.assertEqual([g for g, _ in selected], [elite, far])
                self.assertIs(selected[1][1], pairs[3][1])
                self.assertEqual(pairs, before)
            pairs = self.evaluated([
                elite, equivalent, dict(elite, d0="v1"), dict(elite, d1="v0"),
                dict(elite, d0="v1", d2="v1"),
            ], [1, 0.99, 0.9, 0.8, 0.7])
            configuration.update(elite_count=2, diversity_count=2, population_size=4)
            selected = search.select_survivors(pairs, configuration, **context)
            self.assertEqual([e["score"] for _, e in selected[:2]], [1, 0.9])
            self.assertEqual(len({self.sparse_key(material, g, mode) for g, _ in selected}), 4)
            relabeled = copy.deepcopy(material)
            for dimension in relabeled["dimensions"]:
                dimension["meaning"] = "New label " + dimension["id"]
            for _, evaluation in pairs:
                evaluation["proposal"] = "Unrelated prose"
            self.assertEqual([g for g, _ in search.select_survivors(
                pairs, configuration, dimensions=relabeled["dimensions"], creativity_semantics="sparse_v2",
            )], [g for g, _ in selected])

    def test_sparse_effective_exhaustion(self):
        # Independent oracle: extend visible sequences, never raw omission/order genes.
        def seeds(ids, values, interchangeable, prefix=()):
            result = {prefix} if prefix else set()
            for index, dimension_id in enumerate(ids):
                remaining = ids[:index] + ids[index + 1:] if interchangeable else ids[index + 1:]
                for value in values:
                    result.update(seeds(
                        remaining, values, interchangeable, prefix + ((dimension_id, value),),
                    ))
            return result

        for size, width, fixed_count, ordered_count in ((2, 2, 8, 12), (3, 1, 7, 15), (1, 1, 1, 1)):
            material = self.sparse_material(size, width)
            dimensions = material["dimensions"]
            ids = [d["id"] for d in dimensions]
            context = dict(variants=material["variants"], creativity_semantics="sparse_v2")
            for mode, capacity in (("fixed", fixed_count), ("interchangeable", ordered_count)):
                configuration = creativity_configuration(order_mode=mode, population_size=10)
                expected = seeds(ids, [v["id"] for v in material["variants"]], mode == "interchangeable")
                self.assertEqual(len(expected), capacity)
                parent = {d: "v0" for d in ids}
                if mode == "interchangeable":
                    parent[search.ORDER_GENE] = 0
                parents = self.evaluated([parent], [1])
                parent_key = self.sparse_key(material, parent, mode)
                for draw in (0, 0.75):
                    proposal = {d: search.OMIT for d in ids} if draw == 0 else dict(parent)
                    if mode == "interchangeable":
                        proposal[search.ORDER_GENE] = 0
                    rng = random.Random(5)
                    with self.subTest(size=size, width=width, mode=mode, draw=draw), \
                         mock.patch.object(rng, "random", return_value=draw), \
                         mock.patch.object(rng, "randrange", return_value=0), \
                         mock.patch.object(search, "make_child", return_value=proposal):
                        for request in (0, 1, 4, 30):
                            initial = search.make_population(
                                dimensions, request, configuration, rng=rng, **context,
                            )
                            offspring = search.reproduce(
                                dimensions, parents, request, configuration, rng=rng, **context,
                            )
                            for population, available in ((initial, expected), (offspring, expected - {parent_key})):
                                keys = {self.sparse_key(material, g, mode) for g in population}
                                self.assertEqual(len(keys), len(population))
                                self.assertEqual(len(keys), min(request, 10, len(available)))
                                self.assertTrue(keys <= available)
                        for last in expected:
                            explored = expected - {last}
                            initial = search.make_population(
                                dimensions, 10, configuration, explored=explored, rng=rng, **context,
                            )
                            offspring = search.reproduce(
                                dimensions, parents, 10, configuration, explored=explored, rng=rng, **context,
                            )
                            self.assertEqual([self.sparse_key(material, g, mode) for g in initial], [last])
                            self.assertEqual(
                                [self.sparse_key(material, g, mode) for g in offspring],
                                [] if last == parent_key else [last],
                            )
                        self.assertEqual(search.make_population(
                            dimensions, 10, configuration, explored=expected, rng=rng, **context,
                        ), [])
                        self.assertEqual(search.reproduce(
                            dimensions, parents, 10, configuration, explored=expected, rng=rng, **context,
                        ), [])

    def test_sparse_valid_selection_and_provisional_rejected_parents(self):
        material = self.sparse_material()
        original_material = copy.deepcopy(material)
        context = dict(dimensions=material["dimensions"], creativity_semantics="sparse_v2")
        for mode in ("fixed", "interchangeable"):
            with self.subTest(order_mode=mode):
                configuration = creativity_configuration(
                    order_mode=mode, generation_limit=3, max_evaluated_candidates=10,
                    population_size=3, mutation_rate=0.5,
                )
                elite = {"d0": "v0", "d1": "v0", "d2": search.OMIT}
                near = dict(elite, d0="v1")
                harmful = {"d0": search.OMIT, "d1": "v1", "d2": "v1"}
                if mode == "interchangeable":
                    for genome in (elite, near, harmful):
                        genome[search.ORDER_GENE] = 0
                pairs = self.evaluated([elite, near, harmful], [0.9, 0.8, 0.1], invalid=(0, 2))
                pairs[2][1]["reason"] = "The d2 action undermines the d1 action."
                original_pairs = copy.deepcopy(pairs)
                progress = search.new_progress()
                self.observe_generation(progress, pairs, configuration, **context)
                self.assertEqual([g for g, _ in progress["archive"]], [near])
                self.assertEqual(progress["best_score"], 0.8)
                self.assertTrue(progress["archive"][0][1]["constraint_valid"])

                changed_validity = copy.deepcopy(pairs)
                for _, item in changed_validity:
                    item["constraint_valid"] = not item["constraint_valid"]
                    item["constraint_violations"] = [] if item["constraint_valid"] else ["budget"]
                self.assertEqual([g for g, _ in search.select_survivors(
                    changed_validity, configuration, **context,
                )], [elite, harmful])

                all_rejected = copy.deepcopy(pairs)
                for _, item in all_rejected:
                    item["constraint_valid"] = False
                    item["constraint_violations"] = ["budget"]
                provisional = search.select_survivors(
                    all_rejected, configuration, **context,
                )
                self.assertTrue(provisional)
                self.assertTrue(all(
                    not item["constraint_valid"] for _, item in provisional
                ))
                self.assertEqual(pairs, original_pairs)
                self.assertEqual(material, original_material)

    def test_sparse_fixed_repertoire_and_stops(self):
        material = self.sparse_material(2)
        original_material = copy.deepcopy(material)
        context = dict(dimensions=material["dimensions"], creativity_semantics="sparse_v2")
        for mode, capacity in (("fixed", 8), ("interchangeable", 12)):
            for patience, improvement, expansions in ((1, 1, 0), (7, 0, 3)):
                cases = (
                    (3, 100, "generation_limit", 3, min(9, capacity)),
                    (100, 4, "evaluation_budget", 1, 4),
                    (100, 6, "evaluation_budget", 2, 6),
                    (2, 6, "generation_limit", 2, 6),
                    (100, 100, "repertoire_exhausted", math.ceil(capacity / 3), capacity),
                    (100, capacity, "evaluation_budget", math.ceil(capacity / 3), capacity),
                )
                for generations, budget, stop, completed, accepted in cases:
                    with self.subTest(mode=mode, patience=patience, generations=generations, budget=budget):
                        configuration = creativity_configuration(
                            order_mode=mode, population_size=3, generation_limit=generations,
                            max_evaluated_candidates=budget, patience_generations=patience,
                            minimum_improvement=improvement, max_stagnation_expansions=expansions,
                        )
                        progress, explored, evidence = search.new_progress(), set(), []
                        rng = random.Random(9)
                        for generation in range(1, 10):
                            self.assertFalse(search.expansion_due(
                                progress, configuration, creativity_semantics="sparse_v2",
                            ))
                            if progress["stop_reason"] is not None:
                                break
                            options = dict(explored=explored, rng=rng, variants=material["variants"],
                                           creativity_semantics="sparse_v2")
                            population = (search.reproduce(
                                material["dimensions"], progress["archive"], 3, configuration, **options,
                            ) if progress["archive"] else search.make_population(
                                material["dimensions"], 3, configuration, **options,
                            ))
                            keys = {self.sparse_key(material, g, mode) for g in population}
                            self.assertEqual(len(keys), len(population))
                            self.assertNotIn(None, keys)
                            self.assertTrue(keys.isdisjoint(explored))
                            explored.update(keys)
                            pairs = self.evaluated(population, [0] * len(population),
                                                   invalid=range(len(population)), prefix=str(generation))
                            search.begin_generation(progress, {
                                item["candidate_id"]: genome for genome, item in pairs
                            }, configuration, creativity_semantics="sparse_v2")
                            if progress["stop_reason"] is not None:
                                break
                            allowance = budget - progress["evaluated_candidates"]
                            evidence.extend(pairs[:allowance])
                            unfinished = [item["candidate_id"] for _, item in pairs[allowance:]]
                            search.accept_evaluation_wave(progress, {
                                "accepted_count": len(evidence), "regime_revision": 1,
                                "rebaseline_required": False, "comparison_ready": not unfinished,
                                "unfinished": unfinished, "interruption": None,
                                "evaluated": [] if unfinished else progress["archive"] + pairs,
                            }, configuration, **context)
                        self.assertEqual(progress["stop_reason"], stop)
                        self.assertEqual(progress["generations_completed"], completed)
                        self.assertEqual(progress["evaluated_candidates"], accepted)
                        self.assertEqual(len(evidence), accepted)
                        self.assertEqual(progress["best_score"], 0)
                        self.assertTrue(all(not item["constraint_valid"] for _, item in progress["archive"]))
                        self.assertEqual(progress["expansion_interventions"], 0)
                        self.assertEqual(progress["expansions"], [])
                        self.assertEqual(progress["stagnant_generations"], 0)
                        self.assertEqual(progress["consecutive_expansions"], 0)
                        self.assertFalse(progress["window_complete"])
                        self.assertFalse(progress["progress_made"])
                        self.assertIsNone(progress["reference_score"])
                        self.assertEqual(material, original_material)
                        if budget == 4:
                            self.assertEqual(len(progress["pending"]["unfinished"]), 2)
                        else:
                            self.assertIsNone(progress["pending"])

    def test_population_bounds_and_explored_identity(self):
        dimensions = self.accepted_material()["dimensions"]
        configuration = tasks.resolve_creativity_configuration(creativity_configuration(
            population_size=8, max_evaluated_candidates=8, order_mode="fixed",
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
            order_mode="fixed",
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
        self.assertEqual(search.select_survivors(evaluated[:1], configuration), [evaluated[0]])
        self.assertEqual(search.select_survivors([], configuration), [])

        invalid = self.evaluated(genomes[:4], [0.4, 0.9, 0.7, 0.6], invalid=range(4))
        provisional = search.select_survivors(invalid, configuration)
        self.assertEqual([item[1]["score"] for item in provisional[:2]], [0.9, 0.7])
        self.assertTrue(all(not item[1]["constraint_valid"] for item in provisional))

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
                    order_mode="fixed",
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
                    order_mode="fixed",
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

    def test_order_ranking_is_stable_bounded_and_one_to_one(self):
        expected = [
            ["a", "b", "c"], ["a", "c", "b"], ["b", "a", "c"],
            ["b", "c", "a"], ["c", "a", "b"], ["c", "b", "a"],
        ]
        self.assertEqual(
            [search.unrank_order(["a", "b", "c"], value) for value in range(6)],
            expected,
        )
        for count in range(1, 6):
            dimension_ids = ["d%s" % index for index in range(count)]
            permutations = []
            for value in range(math.factorial(count)):
                ordered = search.unrank_order(dimension_ids, value)
                permutations.append(tuple(ordered))
                self.assertEqual(search.rank_order(dimension_ids, ordered), value)
            self.assertEqual(len(set(permutations)), math.factorial(count))
        for value in (-1, 6, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                search.unrank_order(["a", "b", "c"], value)
        for ordered in (["a", "b"], ["a", "a", "c"], ["a", "b", "other"]):
            with self.subTest(ordered=ordered), self.assertRaises(ValueError):
                search.rank_order(["a", "b", "c"], ordered)

    def test_interchangeable_order_is_ordinary_categorical_material(self):
        dimensions = self.accepted_material(dimensions=[{
            "id": dimension_id, "meaning": "Component " + dimension_id,
            "variants": [{"id": "selected", "text": "Value " + dimension_id}],
        } for dimension_id in "abc"])["dimensions"]
        configuration = creativity_configuration(
            order_mode="interchangeable", population_size=8,
        )
        rng = random.Random(2)
        with mock.patch.object(rng, "randrange", return_value=0):
            population = search.make_population(
                dimensions, 8, configuration, rng=rng,
            )
        self.assertEqual(len(population), 6)
        self.assertEqual({genome[search.ORDER_GENE] for genome in population}, set(range(6)))
        self.assertTrue(all(list(genome)[0] == search.ORDER_GENE for genome in population))
        self.assertEqual(len({search.genome_key(genome) for genome in population}), 6)
        self.assertEqual(search.make_population(
            dimensions, 8, configuration,
            explored={search.genome_key(genome) for genome in population},
        ), [])

        canonical = dict(population[0], **{search.ORDER_GENE: 0})
        reordered = dict(population[0], **{search.ORDER_GENE: 4})
        self.assertNotEqual(search.genome_key(canonical), search.genome_key(reordered))
        self.assertEqual(
            [component["dimension_id"] for component in search.genome_components(
                dimensions, canonical, "interchangeable",
            )],
            ["a", "b", "c"],
        )
        reordered_components = search.genome_components(
            dimensions, reordered, "interchangeable",
        )
        self.assertEqual(
            [component["dimension_id"] for component in reordered_components],
            ["c", "a", "b"],
        )
        self.assertNotIn(search.ORDER_GENE, {
            component["dimension_id"] for component in reordered_components
        })

        selected = search.select_survivors(
            self.evaluated([canonical, reordered], [1, 0.9]),
            creativity_configuration(elite_count=1, diversity_count=1),
        )
        self.assertEqual([genome[search.ORDER_GENE] for genome, _ in selected], [0, 4])

    def test_order_gene_initialization_inheritance_and_mutation(self):
        dimensions = self.accepted_material(dimensions=[{
            "id": dimension_id, "meaning": "Component " + dimension_id,
            "variants": [{"id": "selected", "text": "Value " + dimension_id}],
        } for dimension_id in "abc"])["dimensions"]
        configuration = creativity_configuration(
            order_mode="interchangeable", population_size=2,
        )
        rng = random.Random(9)
        with mock.patch.object(rng, "randrange", side_effect=[0, 0, 0, 4]):
            initialized = search.make_population(dimensions, 1, configuration, rng=rng)
        self.assertEqual(initialized[0][search.ORDER_GENE], 4)

        semantic = {dimension_id: "selected" for dimension_id in "abc"}
        parents = [
            (dict({search.ORDER_GENE: value}, **semantic), {"score": score})
            for value, score in ((1, 1), (4, 0.9))
        ]
        inherited = search.make_child(
            dimensions, parents, 0, order_mode="interchangeable", rng=rng,
        )
        self.assertIn(inherited[search.ORDER_GENE], (1, 4))
        with mock.patch.object(rng, "randrange", return_value=0):
            mutated = search.make_child(
                dimensions, parents, 1, order_mode="interchangeable", rng=rng,
            )
        self.assertIn(mutated[search.ORDER_GENE], range(6))
        # Replacement zero differs from either admitted parent value.
        self.assertEqual(mutated[search.ORDER_GENE], 0)

        singleton = dimensions[:1]
        immutable = search.make_child(
            singleton,
            [({search.ORDER_GENE: 0, "a": "selected"}, {"score": 1})],
            1, order_mode="interchangeable", rng=rng,
        )
        self.assertEqual(immutable[search.ORDER_GENE], 0)

    def test_fixed_and_legacy_modes_keep_the_admitted_order(self):
        dimensions = self.accepted_material()["dimensions"]
        indices = {"format": 1, "channel": 0}
        fixed = search.make_population(
            dimensions, 8, creativity_configuration(
                order_mode="fixed", population_size=8,
            ), rng=random.Random(4),
        )
        legacy = search.make_population(
            dimensions, 8, creativity_configuration(population_size=8),
            rng=random.Random(4),
        )
        self.assertEqual(
            {search.genome_key(genome) for genome in fixed},
            {search.genome_key(genome) for genome in legacy},
        )
        self.assertTrue(all(search.ORDER_GENE not in genome for genome in fixed + legacy))
        fixed_components = search.genome_components(
            dimensions, search.make_genome(dimensions, indices), "fixed",
        )
        order_zero = search.genome_components(
            dimensions, search.make_genome(dimensions, indices, order=0),
            "interchangeable",
        )
        self.assertEqual(fixed_components, order_zero)
        with self.assertRaises(ValueError):
            search.genome_components(
                dimensions, search.make_genome(dimensions, indices, order=0),
                "fixed",
            )

    def test_cumulative_best_valid_progress(self):
        configuration = legacy_creativity_configuration(
            generation_limit=12, max_evaluated_candidates=24,
            minimum_improvement=0.125, patience_generations=3,
            order_mode="fixed",
        )
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
        for index in range(4):
            observe(empty, genomes[index:index + 1], [1], invalid=(0,))
            self.assertEqual(empty["reference_score"], 1)
            self.assertEqual(empty["best_score"], 1)
            self.assertTrue(empty["archive"])
            self.assertFalse(empty["archive"][0][1]["constraint_valid"])
            self.assertEqual(empty["window_complete"], index == 3)
        observe(empty, genomes[4:5], [0.25])
        self.assertEqual(empty["reference_score"], 0.25)
        self.assertEqual(empty["stagnant_generations"], 0)
        self.assertTrue(empty["progress_made"])
        self.assertEqual(empty["consecutive_expansions"], 0)

    def test_full_windows_bound_expansion(self):
        configuration = legacy_creativity_configuration(
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
        configuration = legacy_creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
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
                configuration = legacy_creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
                progress = search.new_progress()
                pairs = self.evaluated(choices[:len(explored)], [1] * len(explored), invalid=(0, 1))
                self.observe_generation(progress, pairs, configuration)
                progress["window_complete"] = True
                self.assertTrue(search.expansion_due(progress, configuration))
                with mock.patch.object(search.random, "randrange", return_value=0):
                    search.accept_expansion(progress, material, {"additions": []},
                                            configuration, explored=explored)
                self.assertEqual(progress["stop_reason"],
                                 "repertoire_exhausted" if explored == all_keys else None)
                self.assertEqual(len(progress["archive"]), len(explored))
                self.assertEqual(progress["best_score"], 1 if explored else None)
                self.assertEqual(progress["evaluated_candidates"], len(explored))
                self.assertEqual(progress["generations_completed"], 1)
                self.assertEqual(progress["expansion_interventions"], 1)
        for reason, limits in (("generation_limit", {"generation_limit": 1}),
                               ("evaluation_budget", {"max_evaluated_candidates": 2})):
            configuration = legacy_creativity_configuration(generation_limit=10, max_evaluated_candidates=20)
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
