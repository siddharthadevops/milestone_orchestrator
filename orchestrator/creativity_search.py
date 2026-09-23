"""Categorical choices over accepted creativity search material.

Callers admit model material through the served create_genes_result contract.
These helpers trust its dimensions, admitted configuration and evaluations.
The caller supplies comparable evaluations and explored genome identities.
Fixed problem fields stay with the caller and never become candidate state.
Sparse callers pass the saved order.creativity_semantics and shared variants
alongside admitted dimensions. Omitting semantics keeps legacy interpretation;
material shape does not select search behavior.
"""

import copy
from fractions import Fraction
from itertools import chain, permutations, product
import math
import random


ORDER_GENE = "__order__"
OMIT = "__omit__"
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


def make_genome(dimensions, variant_indices, *, order=None, variants=None,
                creativity_semantics=None):
    """Build an independent genome from a variant index per dimension id.

    Each index is a zero-based position in that dimension's variants list. An
    optional validated order integer is inserted first as synthetic material.
    Explicit sparse_v2 calls use shared variants and allow the OMIT sentinel.
    """
    dimension_ids = _dimension_ids(dimensions)
    genome = {}
    if order is not None:
        order_count = math.factorial(len(dimension_ids))
        if type(order) is not int or not 0 <= order < order_count:
            raise ValueError("order value must be an integer in [0, %s)" % order_count)
        genome[ORDER_GENE] = order
    sparse = creativity_semantics == "sparse_v2"
    for dimension in dimensions:
        index = variant_indices[dimension["id"]]
        values = variants if sparse else dimension["variants"]
        genome[dimension["id"]] = OMIT if sparse and index == OMIT else values[index]["id"]
    return genome


def genome_key(genome, dimensions=None, order_mode=None, *, creativity_semantics=None):
    """Identify choices within one material, independent of mapping order.

    Sparse identity is the effective sequence; empty proposals have no key.
    Pass the admitted dimensions and recorded order mode for sparse_v2.
    """
    if creativity_semantics == "sparse_v2":
        return _genome_pairs(dimensions, genome, order_mode, creativity_semantics) or None
    return frozenset(genome.items())


def _genome_pairs(dimensions, genome, order_mode, creativity_semantics):
    """Share effective composition between readable components and identity."""
    mode = _order_mode({"order_mode": order_mode})
    dimension_ids = _dimension_ids(dimensions)
    if mode == INTERCHANGEABLE_ORDER:
        ordered_ids = unrank_order(dimension_ids, genome[ORDER_GENE])
    else:
        if ORDER_GENE in genome:
            raise ValueError("fixed-order genome cannot contain %s" % ORDER_GENE)
        ordered_ids = dimension_ids
    return tuple(
        (dimension_id, genome[dimension_id]) for dimension_id in ordered_ids
        if creativity_semantics != "sparse_v2" or genome[dimension_id] != OMIT
    )


def genome_components(dimensions, genome, order_mode=None, *, variants=None,
                      creativity_semantics=None):
    """Return active semantic components in their effective order.

    Missing order_mode remains fixed. Only explicit sparse_v2 calls use the
    shared variants and omit inactive choices; legacy calls stay unchanged.
    """
    by_id = {dimension["id"]: dimension for dimension in dimensions}
    components = []
    for dimension_id, variant_id in _genome_pairs(
        dimensions, genome, order_mode, creativity_semantics,
    ):
        dimension = by_id[dimension_id]
        values = variants if creativity_semantics == "sparse_v2" else dimension["variants"]
        variant = next(
            variant for variant in values
            if variant["id"] == variant_id
        )
        components.append({
            "dimension_id": dimension["id"],
            "dimension": dimension["meaning"],
            "variant_id": variant_id,
            "variant": variant["text"],
        })
    return components


def _repertoire(dimensions, order_mode, *, variants=None, creativity_semantics=None):
    """Yield every effective seed lazily, including active interchangeable order."""
    dimension_ids = _dimension_ids(dimensions)
    if creativity_semantics == "sparse_v2":
        for choices in product([OMIT] + [v["id"] for v in variants], repeat=len(dimensions)):
            active = [d for d, value in zip(dimension_ids, choices) if value != OMIT]
            if not active:
                continue
            omitted = [d for d, value in zip(dimension_ids, choices) if value == OMIT]
            orders = permutations(active) if order_mode == INTERCHANGEABLE_ORDER else (active,)
            for ordered in orders:
                # Enumerate each effective order once, without hidden permutations.
                genome = {}
                if order_mode == INTERCHANGEABLE_ORDER:
                    genome[ORDER_GENE] = rank_order(dimension_ids, list(ordered) + omitted)
                genome.update(zip(dimension_ids, choices))
                yield genome
        return
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


def _fill_population(dimensions, proposals, count, explored, order_mode, *,
                     variants=None, creativity_semantics=None):
    """Take distinct proposals, then scan the repertoire to settle shortages."""
    if count == 0:
        return []
    seen = set(explored)
    population = []
    for genome in chain(proposals, _repertoire(
        dimensions, order_mode, variants=variants, creativity_semantics=creativity_semantics,
    )):
        key = genome_key(genome, dimensions, order_mode, creativity_semantics=creativity_semantics)
        if key is None or key in seen:
            continue
        seen.add(key)
        population.append(genome)
        if len(population) == count:
            break
    return population


def make_population(dimensions, count, configuration, *, explored=(), rng=random,
                    variants=None, creativity_semantics=None):
    """Draw a bounded fresh population, returning fewer only for a shortage.

    Random collisions fall through to finite enumeration; they never establish
    exhaustion. The repertoire is traversed lazily, not materialized.
    """
    count = min(count, configuration["population_size"])
    order_mode = _order_mode(configuration)
    dimension_ids = _dimension_ids(dimensions)
    order_count = math.factorial(len(dimension_ids))
    sparse = creativity_semantics == "sparse_v2"
    proposals = (
        make_genome(dimensions, {
            dimension["id"]: OMIT if sparse and rng.random() < 0.5 else rng.randrange(
                len(variants if sparse else dimension["variants"])
            )
            for dimension in dimensions
        }, order=(rng.randrange(order_count)
                  if order_mode == INTERCHANGEABLE_ORDER else None),
            variants=variants, creativity_semantics=creativity_semantics)
        for _ in range(count)
    )
    return _fill_population(
        dimensions, proposals, count, explored, order_mode,
        variants=variants, creativity_semantics=creativity_semantics,
    )


def _effective_distance(left, right):
    """Count participation/value changes and a change in common active order."""
    left_values, right_values = dict(left), dict(right)
    common = left_values.keys() & right_values.keys()
    changes = sum(
        left_values.get(dimension) != right_values.get(dimension)
        for dimension in left_values.keys() | right_values.keys()
    )
    return changes + (
        [dimension for dimension, _ in left if dimension in common]
        != [dimension for dimension, _ in right if dimension in common]
    )


def select_survivors(evaluated, configuration, *, dimensions=None, creativity_semantics=None):
    """Keep scored elites and structural diversity under the saved semantics.

    Input and output are (genome, accepted evaluation) pairs. The caller can
    combine retained and newly evaluated pairs here. Valid candidates are
    preferred; rejected candidates remain provisional parents only until a
    valid candidate exists. Duplicate identities keep their highest eligible
    score. Genome mappings are copied; evaluations remain unchanged.
    """
    eligible = [pair for pair in evaluated if pair[1]["constraint_valid"]]
    if not eligible:
        eligible = list(evaluated)
    ranked = sorted(eligible, key=lambda pair: pair[1]["score"], reverse=True)
    order_mode = _order_mode(configuration)
    seen = set()
    distinct = []
    for pair in ranked:
        key = genome_key(pair[0], dimensions, order_mode, creativity_semantics=creativity_semantics)
        if key not in seen:
            seen.add(key)
            distinct.append(pair)

    def distance(left, right):
        if creativity_semantics == "sparse_v2":
            return _effective_distance(
                genome_key(left, dimensions, order_mode, creativity_semantics=creativity_semantics),
                genome_key(right, dimensions, order_mode, creativity_semantics=creativity_semantics),
            )
        return sum(left[dimension] != right[dimension] for dimension in left)

    elite_count = configuration["elite_count"]
    selected, remaining = distinct[:elite_count], distinct[elite_count:]
    for _ in range(min(configuration["diversity_count"], len(remaining))):
        # Greedily prefer the greatest distance from the nearest survivor.
        diverse = max(remaining, key=lambda pair: min(
            distance(pair[0], kept[0])
            for kept in selected
        ))
        selected.append(diverse)
        remaining.remove(diverse)
    return [(dict(genome), evaluation) for genome, evaluation in selected]


def make_child(dimensions, parents, mutation_rate, *, order_mode=None, rng=random,
               variants=None, creativity_semantics=None):
    """Cross nonempty selected parent pairs and mutate each mutable choice.

    A child contains only choices, with no inherited evaluation. Each semantic
    dimension and the optional order gene independently receive the configured
    mutation probability. Sparse mutation independently chooses participation
    toggling or active-value change, regardless of shared repertoire width.
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
    sparse = creativity_semantics == "sparse_v2"
    for dimension in dimensions:
        dimension_id = dimension["id"]
        choice = rng.choice(mates)[0][dimension_id]
        values = variants if sparse else dimension["variants"]
        alternatives = [
            variant["id"] for variant in values
            if variant["id"] != choice
        ]
        if sparse:
            if rng.random() < mutation_rate:
                if rng.random() < 0.5:
                    choice = rng.choice(values)["id"] if choice == OMIT else OMIT
                elif choice != OMIT and alternatives:
                    choice = rng.choice(alternatives)
        elif alternatives and rng.random() < mutation_rate:
            choice = rng.choice(alternatives)
        child[dimension_id] = choice
    return child


def reproduce(dimensions, parents, count, configuration, *, explored=(), rng=random,
              variants=None, creativity_semantics=None):
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
    excluded = set(explored) | {
        genome_key(genome, dimensions, order_mode, creativity_semantics=creativity_semantics)
        for genome, _ in parents
    }
    proposals = (
        make_child(
            dimensions, parents, configuration["mutation_rate"],
            order_mode=order_mode, rng=rng,
            variants=variants, creativity_semantics=creativity_semantics,
        )
        for _ in range(count)
    )
    return _fill_population(
        dimensions, proposals, count, excluded, order_mode,
        variants=variants, creativity_semantics=creativity_semantics,
    )


def new_progress():
    """Task-owned search-progress handoff; persistence belongs to the task owner.

    Archive entries use the selector's (genome, evaluation) pairs. A pending
    generation retains score-free candidate identities across bounded waves.
    Only a complete comparison updates selection or the legacy progress window.
    """
    return {
        "archive": [], "best_score": None, "reference_score": None,
        "reference_revision": None, "stagnant_generations": 0,
        "consecutive_expansions": 0, "expansion_interventions": 0,
        "generations_completed": 0, "evaluated_candidates": 0,
        "progress_made": False, "window_complete": False,
        "stop_reason": None, "pending": None, "expansions": [],
    }


def begin_generation(progress, candidates, configuration, *, creativity_semantics=None):
    """Open one generation with owner-supplied fresh candidate ids and genomes.

    The owner calls this after the previous comparison completes. For sparse
    search, no fresh candidates from the exact population supplier means
    exhaustion. Legacy empty populations can still observe stagnation.
    """
    if progress["stop_reason"] is not None:
        return
    sparse = creativity_semantics == "sparse_v2"
    if (candidates or sparse) and progress["evaluated_candidates"] == configuration["max_evaluated_candidates"]:
        progress["stop_reason"] = "evaluation_budget"
        return
    if sparse and not candidates:
        progress["stop_reason"] = "repertoire_exhausted"
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


def accept_evaluation_wave(progress, wave, configuration, *, dimensions=None,
                           creativity_semantics=None):
    """Consume the trusted wave handoff without rechecking its eligibility.

    Reassessment is a separate comparison, not a generation or progress event.
    The original generation remains pending through any number of bounded
    waves; only the wave's accepted count charges the evaluation allowance.
    Sparse comparisons retain scores without calculating a stagnation window.
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

    previous_had_valid = creativity_semantics != "sparse_v2" and any(
        evaluation["constraint_valid"]
        for _genome, evaluation in progress["archive"]
    )
    progress["archive"] = select_survivors(
        wave["evaluated"], configuration,
        dimensions=dimensions, creativity_semantics=creativity_semantics,
    )
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

    progress["generations_completed"] += 1
    progress["pending"] = None
    if progress["generations_completed"] == configuration["generation_limit"]:
        progress["stop_reason"] = "generation_limit"
    if creativity_semantics == "sparse_v2":
        return

    # Compare decimal spellings exactly: binary subtraction can put a gain
    # that reaches the threshold just below it.
    best_is_valid = bool(
        progress["archive"]
        and progress["archive"][0][1]["constraint_valid"]
    )
    reference = progress["reference_score"]
    if reference is None and best is not None:
        progress["reference_score"] = best
        progress["stagnant_generations"] = 0
    elif best is not None and best_is_valid and not previous_had_valid:
        progress["reference_score"] = best
        progress["stagnant_generations"] = 0
        progress["consecutive_expansions"] = 0
        progress["progress_made"] = True
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
    progress["window_complete"] = (
        progress["stagnant_generations"] >= configuration["patience_generations"]
    )


def expansion_due(progress, configuration, *, creativity_semantics=None):
    """Decide the completed window's intervention or exact limiting stop.

    Pending comparisons cannot request expansion. Generation completion has
    already chosen its stop; no intervention can bypass evaluation capacity.
    Sparse search keeps its fixed repertoire and never requests expansion.
    """
    if progress["stop_reason"] is not None or progress["pending"] is not None:
        return False
    if progress["evaluated_candidates"] == configuration["max_evaluated_candidates"]:
        progress["stop_reason"] = "evaluation_budget"
        return False
    if creativity_semantics == "sparse_v2" or not progress["window_complete"]:
        return False
    if progress["consecutive_expansions"] == configuration["max_stagnation_expansions"]:
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
