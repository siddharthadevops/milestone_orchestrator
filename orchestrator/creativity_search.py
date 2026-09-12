"""Categorical choices over accepted creativity search material.

Callers admit model material through the served create_genes_result contract.
These helpers trust its dimensions, admitted configuration and evaluations.
The caller supplies comparable evaluations and explored genome identities.
Fixed problem fields stay with the caller and never become candidate state.
"""

from itertools import chain, product
import random


def make_genome(dimensions, variant_indices):
    """Build an independent genome from a variant index per dimension id.

    Each index is a zero-based position in that dimension's variants list.
    Only dimension and variant ids enter the returned mapping.
    """
    return {
        dimension["id"]: dimension["variants"][variant_indices[dimension["id"]]]["id"]
        for dimension in dimensions
    }


def genome_key(genome):
    """Identify choices within one material, independent of mapping order."""
    return frozenset(genome.items())


def genome_components(dimensions, genome):
    """Return independent readable component records in material order."""
    components = []
    for dimension in dimensions:
        variant_id = genome[dimension["id"]]
        variant = next(
            variant for variant in dimension["variants"]
            if variant["id"] == variant_id
        )
        components.append({
            "dimension_id": dimension["id"],
            "dimension": dimension["meaning"],
            "variant_id": variant_id,
            "variant": variant["text"],
        })
    return components


def _fill_population(dimensions, proposals, count, explored):
    """Take distinct proposals, then scan the repertoire to settle shortages."""
    if count == 0:
        return []
    dimension_ids = [dimension["id"] for dimension in dimensions]
    combinations = product(*(
        range(len(dimension["variants"])) for dimension in dimensions
    ))
    repertoire = (
        make_genome(dimensions, dict(zip(dimension_ids, indices)))
        for indices in combinations
    )
    seen = set(explored)
    population = []
    for genome in chain(proposals, repertoire):
        key = genome_key(genome)
        if key in seen:
            continue
        seen.add(key)
        population.append(genome)
        if len(population) == count:
            break
    return population


def make_population(dimensions, count, configuration, *, explored=(), rng=random):
    """Draw a bounded fresh population, returning fewer only for a shortage.

    Random collisions fall through to finite enumeration; they never establish
    exhaustion. The repertoire is traversed lazily, not materialized.
    """
    count = min(count, configuration["population_size"])
    proposals = (
        make_genome(dimensions, {
            dimension["id"]: rng.randrange(len(dimension["variants"]))
            for dimension in dimensions
        })
        for _ in range(count)
    )
    return _fill_population(dimensions, proposals, count, explored)


def select_survivors(evaluated, configuration):
    """Keep valid elites followed by structurally diverse survivors.

    Input and output are (genome, accepted evaluation) pairs. The caller can
    combine retained and newly evaluated pairs from one evaluator regime here.
    Duplicate genomes keep their highest valid score. Genome mappings are
    copied; evaluations are retained unchanged.
    """
    ranked = sorted(
        (pair for pair in evaluated if pair[1]["constraint_valid"]),
        key=lambda pair: pair[1]["score"], reverse=True,
    )
    seen = set()
    distinct = []
    for pair in ranked:
        key = genome_key(pair[0])
        if key not in seen:
            seen.add(key)
            distinct.append(pair)
    elite_count = configuration["elite_count"]
    selected, remaining = distinct[:elite_count], distinct[elite_count:]
    for _ in range(min(configuration["diversity_count"], len(remaining))):
        # Greedily prefer the greatest distance from the nearest survivor.
        diverse = max(remaining, key=lambda pair: min(
            sum(pair[0][dimension] != kept[0][dimension] for dimension in pair[0])
            for kept in selected
        ))
        selected.append(diverse)
        remaining.remove(diverse)
    return [(dict(genome), evaluation) for genome, evaluation in selected]


def make_child(dimensions, parents, mutation_rate, *, rng=random):
    """Cross nonempty selected parent pairs and mutate each mutable choice.

    A child contains only choices, with no inherited evaluation. Each dimension
    independently receives the configured mutation probability; a mutation
    chooses a different existing variant, including variants absent in parents.
    """
    mates = rng.sample(parents, min(2, len(parents)))
    child = {}
    for dimension in dimensions:
        dimension_id = dimension["id"]
        choice = rng.choice(mates)[0][dimension_id]
        alternatives = [
            variant["id"] for variant in dimension["variants"]
            if variant["id"] != choice
        ]
        if alternatives and rng.random() < mutation_rate:
            choice = rng.choice(alternatives)
        child[dimension_id] = choice
    return child


def reproduce(dimensions, parents, count, configuration, *, explored=(), rng=random):
    """Build a bounded fresh population from selected parent pairs.

    Offspring capacity is independent of survivor quotas. Each requested place
    gets a crossover/mutation proposal; duplicate or explored proposals are
    replaced with unseen repertoire combinations. The caller retains survivors
    separately and evaluates new genomes before their next selection.
    """
    if not parents:
        return []
    count = min(count, configuration["population_size"])
    excluded = set(explored) | {genome_key(genome) for genome, _ in parents}
    proposals = (
        make_child(dimensions, parents, configuration["mutation_rate"], rng=rng)
        for _ in range(count)
    )
    return _fill_population(dimensions, proposals, count, excluded)
