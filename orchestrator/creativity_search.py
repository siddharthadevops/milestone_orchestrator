"""Categorical choices over accepted creativity search material.

Callers admit model material through the served create_genes_result contract.
These helpers trust its dimensions and the driver's choices. Fixed problem
fields stay with the caller and never become candidate state.
"""


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
