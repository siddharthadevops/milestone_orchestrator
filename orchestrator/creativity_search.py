"""Categorical choices over accepted creativity search material.

Callers admit model material through the served create_genes_result contract.
These helpers trust its dimensions, admitted configuration and evaluations.
The caller supplies comparable evaluations and explored genome identities.
Fixed problem fields stay with the caller and never become candidate state.
"""

import copy
from fractions import Fraction
from itertools import chain, product
import math
import random


ORDER_GENE = "__order__"
FIXED_ORDER = "fixed"
INTERCHANGEABLE_ORDER = "interchangeable"


def _order_mode(configuration):
    """Read current configuration while keeping legacy work fixed."""
    mode = configuration.get("order_mode")
    if mode is None:
        return FIXED_ORDER
    if mode not in (FIXED_ORDER, INTERCHANGEABLE_ORDER):
        raise ValueError("unknown creativity order mode: %r" % mode)
    return mode


def _dimension_ids(dimensions):
    ids = [dimension["id"] for dimension in dimensions]
    if ORDER_GENE in ids:
        raise ValueError("%s is reserved for the synthetic order gene" % ORDER_GENE)
    return ids


def unrank_order(dimension_ids, value):
    """Return the stable lexicographic permutation named by ``value``.

    The calculation keeps only the remaining dimension ids; it never builds a
    permutation table. Permutation zero is the admitted dimension-list order.
    """
    canonical = list(dimension_ids)
    if len(set(canonical)) != len(canonical):
        raise ValueError("dimension ids must be unique")
    limit = math.factorial(len(canonical))
    if type(value) is not int or not 0 <= value < limit:
        raise ValueError("order value must be an integer in [0, %s)" % limit)
    remaining = list(canonical)
    ordered = []
    for width in range(len(remaining), 0, -1):
        block = math.factorial(width - 1)
        index, value = divmod(value, block)
        ordered.append(remaining.pop(index))
    return ordered


def rank_order(dimension_ids, ordered_ids):
    """Return the integer naming one permutation of the canonical ids."""
    canonical = list(dimension_ids)
    ordered = list(ordered_ids)
    if len(set(canonical)) != len(canonical):
        raise ValueError("dimension ids must be unique")
    if len(ordered) != len(canonical) or set(ordered) != set(canonical):
        raise ValueError("ordered ids must be one permutation of dimension ids")
    remaining = list(canonical)
    value = 0
    for offset, dimension_id in enumerate(ordered):
        index = remaining.index(dimension_id)
        value += index * math.factorial(len(canonical) - offset - 1)
        remaining.pop(index)
    return value


def make_genome(dimensions, variant_indices, *, order=None):
    """Build an independent genome from a variant index per dimension id.

    Each index is a zero-based position in that dimension's variants list. An
    optional validated order integer is inserted first as synthetic material.
    """
    dimension_ids = _dimension_ids(dimensions)
    genome = {}
    if order is not None:
        order_count = math.factorial(len(dimension_ids))
        if type(order) is not int or not 0 <= order < order_count:
            raise ValueError("order value must be an integer in [0, %s)" % order_count)
        genome[ORDER_GENE] = order
    genome.update({
        dimension["id"]: dimension["variants"][variant_indices[dimension["id"]]]["id"]
        for dimension in dimensions
    })
    return genome


def genome_key(genome):
    """Identify choices within one material, independent of mapping order."""
    return frozenset(genome.items())


def genome_components(dimensions, genome, order_mode=None):
    """Return readable semantic components in their effective order.

    Missing ``order_mode`` is the legacy fixed interpretation. The synthetic
    gene is consumed here and never becomes an evaluator-facing component.
    """
    mode = _order_mode({"order_mode": order_mode})
    dimension_ids = _dimension_ids(dimensions)
    if mode == INTERCHANGEABLE_ORDER:
        ordered_ids = unrank_order(dimension_ids, genome[ORDER_GENE])
    else:
        if ORDER_GENE in genome:
            raise ValueError("fixed-order genome cannot contain %s" % ORDER_GENE)
        ordered_ids = dimension_ids
    by_id = {dimension["id"]: dimension for dimension in dimensions}
    components = []
    for dimension_id in ordered_ids:
        dimension = by_id[dimension_id]
        variant_id = genome[dimension_id]
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


def _repertoire(dimensions, order_mode):
    """Yield every genome lazily, including order when interchangeable."""
    dimension_ids = _dimension_ids(dimensions)
    order_values = (
        range(math.factorial(len(dimension_ids)))
        if order_mode == INTERCHANGEABLE_ORDER else (None,)
    )
    for order in order_values:
        # Recreate this small categorical product for each order; feeding the
        # factorial range itself to itertools.product would cache that range.
        combinations = product(*(
            range(len(dimension["variants"])) for dimension in dimensions
        ))
        for indices in combinations:
            yield make_genome(
                dimensions, dict(zip(dimension_ids, indices)), order=order,
            )


def _fill_population(dimensions, proposals, count, explored, order_mode):
    """Take distinct proposals, then scan the repertoire to settle shortages."""
    if count == 0:
        return []
    seen = set(explored)
    population = []
    for genome in chain(proposals, _repertoire(dimensions, order_mode)):
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
    order_mode = _order_mode(configuration)
    dimension_ids = _dimension_ids(dimensions)
    order_count = math.factorial(len(dimension_ids))
    proposals = (
        make_genome(dimensions, {
            dimension["id"]: rng.randrange(len(dimension["variants"]))
            for dimension in dimensions
        }, order=(rng.randrange(order_count)
                  if order_mode == INTERCHANGEABLE_ORDER else None))
        for _ in range(count)
    )
    return _fill_population(dimensions, proposals, count, explored, order_mode)


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


def make_child(dimensions, parents, mutation_rate, *, order_mode=None, rng=random):
    """Cross nonempty selected parent pairs and mutate each mutable choice.

    A child contains only choices, with no inherited evaluation. Each semantic
    dimension and the optional order gene independently receive the configured
    mutation probability; mutation chooses a different categorical value.
    """
    mates = rng.sample(parents, min(2, len(parents)))
    child = {}
    mode = _order_mode({"order_mode": order_mode})
    if mode == INTERCHANGEABLE_ORDER:
        order_count = math.factorial(len(_dimension_ids(dimensions)))
        choice = rng.choice(mates)[0][ORDER_GENE]
        if order_count > 1 and rng.random() < mutation_rate:
            replacement = rng.randrange(order_count - 1)
            choice = replacement + (replacement >= choice)
        child[ORDER_GENE] = choice
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
    order_mode = _order_mode(configuration)
    excluded = set(explored) | {genome_key(genome) for genome, _ in parents}
    proposals = (
        make_child(
            dimensions, parents, configuration["mutation_rate"],
            order_mode=order_mode, rng=rng,
        )
        for _ in range(count)
    )
    return _fill_population(dimensions, proposals, count, excluded, order_mode)


def new_progress():
    """Task-owned search-progress handoff; persistence belongs to the task owner.

    Archive entries use the selector's (genome, evaluation) pairs. A pending
    generation retains score-free candidate identities across bounded waves.
    Only a complete comparison may update selection or the progress window.
    """
    return {
        "archive": [], "best_score": None, "reference_score": None,
        "reference_revision": None, "stagnant_generations": 0,
        "consecutive_expansions": 0, "expansion_interventions": 0,
        "generations_completed": 0, "evaluated_candidates": 0,
        "progress_made": False, "window_complete": False,
        "stop_reason": None, "pending": None, "expansions": [],
    }


def begin_generation(progress, candidates, configuration):
    """Open one generation with owner-supplied fresh candidate ids and genomes.

    The owner calls this after the previous comparison completes. An empty
    population can observe stagnation, but does not itself prove exhaustion.
    """
    if progress["stop_reason"] is not None:
        return
    if candidates and progress["evaluated_candidates"] == configuration["max_evaluated_candidates"]:
        progress["stop_reason"] = "evaluation_budget"
        return
    retained = {item["candidate_id"]: dict(genome) for genome, item in progress["archive"]}
    progress["pending"] = {
        "phase": "generation", "survivor_ids": list(retained),
        "candidates": dict(retained, **{key: dict(genome) for key, genome in candidates.items()}),
        "unfinished": list(candidates),
    }
    progress["progress_made"] = False
    progress["window_complete"] = False


def progress_evaluation_request(progress):
    """Arguments for evaluate_wave, including required survivor reassessment.

    The wave remains the sole owner of score eligibility and accepted work;
    passing these ids does not force it to repeat current-regime evaluations.
    A rebaseline compares only retained survivors before the pending generation
    can compare its new candidates against that reference.
    """
    pending = progress["pending"]
    if progress["stop_reason"] is not None or pending is None:
        return None
    candidates = pending["candidates"]
    if pending["phase"] == "rebaseline":
        candidates = {key: candidates[key] for key in pending["survivor_ids"]}
    return {
        "candidates": candidates, "comparison_ids": list(candidates),
        "reference_revision": progress["reference_revision"],
    }


def accept_evaluation_wave(progress, wave, configuration):
    """Consume the trusted wave handoff without rechecking its eligibility.

    Reassessment is a separate comparison, not a generation or progress event.
    The original generation remains pending through any number of bounded
    waves; only the wave's accepted count charges the evaluation allowance.
    Interruptions remain task-control outcomes, never normal search stops.
    """
    pending = progress["pending"]
    progress["evaluated_candidates"] = wave["accepted_count"]
    progress["progress_made"] = False
    pending["unfinished"] = wave["unfinished"]
    changed = wave["rebaseline_required"] and pending["phase"] == "generation"
    if changed:
        pending["phase"] = "rebaseline"
        # Keep only the identities needed for reassessment, not an eligible
        # archive or reference carrying the previous evaluator's scores.
        progress["archive"] = []
        progress["best_score"] = progress["reference_score"] = None
    if wave["interruption"] is not None:
        return
    if not wave["comparison_ready"]:
        if wave["unfinished"] and wave["accepted_count"] == configuration["max_evaluated_candidates"]:
            progress["stop_reason"] = "evaluation_budget"
        return
    if changed:
        return

    progress["archive"] = select_survivors(wave["evaluated"], configuration)
    best = progress["archive"][0][1]["score"] if progress["archive"] else None
    progress["best_score"] = best
    progress["reference_revision"] = wave["regime_revision"]
    if pending["phase"] == "rebaseline":
        progress["reference_score"] = best
        progress["stagnant_generations"] = 0
        old_survivors = pending["survivor_ids"]
        retained = {item["candidate_id"]: genome for genome, item in progress["archive"]}
        pending["candidates"] = {
            key: genome for key, genome in pending["candidates"].items()
            if key not in old_survivors
        }
        pending["candidates"].update(retained)
        pending["survivor_ids"] = list(retained)
        pending["phase"] = "generation"
        return

    # Compare decimal spellings exactly: binary subtraction can put a gain
    # that reaches the threshold just below it.
    reference = progress["reference_score"]
    if reference is None and best is not None:
        progress["reference_score"] = best
        progress["stagnant_generations"] = 0
    elif best is not None and (
        Fraction(str(best)) - Fraction(str(reference))
        >= Fraction(str(configuration["minimum_improvement"]))
    ):
        progress["reference_score"] = best
        progress["stagnant_generations"] = 0
        progress["consecutive_expansions"] = 0
        progress["progress_made"] = True
    else:
        progress["stagnant_generations"] += 1
    progress["generations_completed"] += 1
    progress["pending"] = None
    progress["window_complete"] = (
        progress["stagnant_generations"] >= configuration["patience_generations"]
    )
    if progress["generations_completed"] == configuration["generation_limit"]:
        progress["stop_reason"] = "generation_limit"


def expansion_due(progress, configuration):
    """Decide the completed window's intervention or exact limiting stop.

    Pending comparisons cannot request expansion. Generation completion has
    already chosen its stop; no intervention can bypass evaluation capacity.
    """
    if progress["stop_reason"] is not None or progress["pending"] is not None:
        return False
    if not progress["window_complete"]:
        return False
    if progress["evaluated_candidates"] == configuration["max_evaluated_candidates"]:
        progress["stop_reason"] = "evaluation_budget"
    elif progress["consecutive_expansions"] == configuration["max_stagnation_expansions"]:
        progress["stop_reason"] = "persistent_stagnation"
    else:
        return True
    return False


def accept_expansion(progress, search_material, expansion, configuration, *, explored):
    """Incorporate one allowed, validated intervention and retain its evidence.

    The owner supplies explored genome keys across all regimes. The existing
    population supplier settles exhaustion independently of parent validity or
    random collisions. Accepted additions are structural novelty only.
    """
    material = copy.deepcopy(search_material)
    dimensions = {dimension["id"]: dimension for dimension in material["dimensions"]}
    for addition in expansion["additions"]:
        dimensions[addition["dimension_id"]]["variants"].extend(
            {"id": variant["id"], "text": variant["text"]}
            for variant in addition["variants"]
        )
    progress["expansions"].append(expansion)
    progress["consecutive_expansions"] += 1
    progress["expansion_interventions"] += 1
    progress["reference_score"] = progress["best_score"]
    progress["stagnant_generations"] = 0
    progress["window_complete"] = progress["progress_made"] = False
    if not expansion["additions"] and not make_population(
        material["dimensions"], 1, configuration, explored=explored,
    ):
        progress["stop_reason"] = "repertoire_exhausted"
    return material
