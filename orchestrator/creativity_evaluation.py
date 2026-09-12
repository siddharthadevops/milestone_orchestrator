"""Routed evaluation batches for the task-owned creativity search.

The owner supplies admitted material, configuration and candidate genomes, and
a DirectTaskHost-created TaskCallGroup. This adapter owns semantic invocation
and accepted batch attribution; the group owns controls and physical evidence.
"""

import json
from types import SimpleNamespace

from . import creativity_search, prompt_contracts, prompt_router, runners, staffing, tasks


def call_evaluation_batch(
    group, runner, *, home, session, workspace, configuration, search_material,
    candidates, generation, batch, execution_context, prompt_set="default",
    prompt_values=None,
):
    """Evaluate one owner-admitted batch, including the runner's one correction.

    ``candidates`` maps stable candidate ids to genomes. A successful return is
    (validated batch, runner result); interruption retains the shared boundary's
    (None, ControlledInterruptionResult). Operational and protocol faults raise.
    The batch is input for checkpointing, not a selection-ready comparison.
    Its caller must enforce wave/budget bounds and commit accepted work.
    """
    genomes = {candidate_id: dict(genome) for candidate_id, genome in candidates.items()}
    values = dict(prompt_values or {})
    values.update(
        workspace=workspace,
        search_material=json.dumps(search_material, ensure_ascii=False),
        candidates=json.dumps([
            {"candidate_id": candidate_id, "components": creativity_search.genome_components(
                search_material["dimensions"], genome,
            )}
            for candidate_id, genome in genomes.items()
        ], ensure_ascii=False),
    )
    context = {"job": "evaluate_candidates", "generation": generation, "batch": batch}
    constraint_ids = [constraint["id"] for constraint in search_material["constraints"]]

    def prepare_call(error):
        context["material"] = staffing.session_material(home, session)
        selected = prompt_router.resolve(
            home, job="evaluate_candidates@creativity", executor="agent_call",
            material=context["material"], values=values, prompt_set=prompt_set,
        )
        bound = prompt_contracts.bind(selected.prompt)
        prompt = prompt_router.render(bound.prompt, values)
        if error is not None:
            prompt += runners.REPAIR_SUFFIX % error
        return SimpleNamespace(
            prompt=prompt,
            validate=lambda reply: prompt_contracts.validate(
                bound, reply, candidate_ids=list(genomes), constraint_ids=constraint_ids,
            ),
            prompt_set_fallback=selected.prompt_set_fallback,
        )

    def resolve_dispatch():
        answer = staffing.resolve(
            home, session, material=context["material"],
            **tasks.creativity_job_staffing_request("evaluate_candidates", configuration),
        ).answer
        return answer["agent"], answer["model"], answer["effort"]

    reply, result = group.call_worker(
        runner, None, "", "evaluate_candidates", workspace,
        prepare_call=prepare_call, resolve_dispatch=resolve_dispatch,
        call_context=context, execution_context=execution_context,
    )
    if isinstance(result, runners.ControlledInterruptionResult):
        return None, result
    return {
        "generation": generation,
        "batch": batch,
        "call_id": result.call_id,
        "regime": {
            "material": result.call_context["material"],
            "agent": result.resolved_family,
            "model": result.resolved_model,
            "effort": result.resolved_effort,
        },
        "genomes": genomes,
        "evaluations": reply["evaluations"],
    }, result
