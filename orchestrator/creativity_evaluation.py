"""Evaluation waves and routed expansion for the task-owned creativity search.

The owner supplies admitted material, configuration and candidate genomes, and
a DirectTaskHost-created TaskCallGroup. This caller owns semantic invocation,
accepted checkpoints and comparison eligibility; the group owns controls and
physical evidence.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import threading
import uuid
from itertools import product
from types import SimpleNamespace

from . import (
    creativity_search, prompt_contracts, prompt_router, prompt_sets, runners,
    staffing, tasks,
)


CREATIVITY_CONTRACT = "ordered_fragments_v1"


def _validate_sparse_prompt(prompt, defaulted_variables):
    """Reject a stored creativity prompt that predates sparse semantics.

    Named prompt sets are operator-owned and may legitimately retain the legacy
    contract.  They cannot, however, serve a sparse task unless the mounted
    route declares the service-owned semantics coordinate.  Let the ordinary
    prompt-set resolver fall back before a provider call instead of asking a
    worker to satisfy a contract different from the validator's.
    """
    declarations = [
        variable
        for unit in prompt["instructions"] + prompt["output_contract"]
        for variable in unit["variables"]
    ]
    semantics = [
        variable for variable in declarations
        if variable.get("name") == "creativity_semantics"
    ]
    contracts = [
        variable for variable in declarations
        if variable.get("name") == "creativity_contract"
    ]
    if (
        len(semantics) != 1
        or len(contracts) != 1
        or contracts[0].get("default") != CREATIVITY_CONTRACT
        or "creativity_contract" not in defaulted_variables
    ):
        raise prompt_sets.PromptSetError(
            "sparse creativity prompt must declare the current semantics and contract"
        )


def _search_material_from_gene_pool(pool, *, objective, context, references):
    """Turn the extractor's three literal lists into the existing sparse ABI."""
    dimensions = [
        {"id": "subject_%02d" % index, "meaning": subject}
        for index, subject in enumerate(pool["subjects"], 1)
    ]
    variants = [
        {
            "id": "verb_%02d__adjective_%02d" % (verb_index, adjective_index),
            "text": 'verb "%s"; adjective "%s"' % (verb, adjective),
        }
        for (verb_index, verb), (adjective_index, adjective) in product(
            enumerate(pool["verbs"], 1), enumerate(pool["adjectives"], 1),
        )
    ]
    material = {
        "objective": objective,
        "context_summary": json.dumps({
            "context": context, "reference_documents": references,
        }, ensure_ascii=False),
        "facts": [],
        "constraints": [],
        "assumptions": [],
        "unknowns": [],
        "dimensions": dimensions,
        "variants": variants,
        "composition_guidance": (
            "Use every active subject and its exact verb-adjective pair without "
            "adding substantive facts, actors, capabilities, interfaces, or mechanisms."
        ),
        "criteria": [
            {"id": "objective_fit", "text": "Meets the operator's stated objective."},
            {"id": "feasibility", "text": "Is supported by the supplied material."},
            {"id": "seed_fidelity", "text": "Uses every selected seed faithfully."},
        ],
        "order_semantics": (
            "The active seeds shape the proposal in their supplied order; that order "
            "does not authorize missing causal or factual detail."
        ),
    }
    return prompt_contracts.validate_create_genes_reply(
        {"search_material": material}, creativity_semantics="sparse_v2",
    )["search_material"]


def _problem_material(search_material):
    return {key: search_material[key] for key in (
        "objective", "context_summary", "facts", "constraints", "assumptions",
        "unknowns", "composition_guidance", "criteria", "order_semantics",
    )}


def search_material_from_fragments(fragments, *, objective, context, references):
    """Keep the brief intact and encode inclusion/negation on each fragment.

    The existing sparse engine supplies omission and ordering. A fragment is
    never paired with another fragment or interpreted as a grammatical slot.
    """
    return {
        "objective": objective,
        "context_summary": json.dumps({
            "context": context, "reference_documents": references,
        }, ensure_ascii=False),
        "facts": [], "constraints": [], "assumptions": [], "unknowns": [],
        "dimensions": [
            {"id": "fragment_%02d" % index, "meaning": fragment}
            for index, fragment in enumerate(fragments, 1)
        ],
        "variants": [
            {"id": "affirmed", "text": "Include"},
            {"id": "negated", "text": "Exclude"},
        ],
        "composition_guidance": (
            "Fulfil the operator's brief and context using the ordered fragments as "
            "inspiration. Create the proposal freely within that brief. An affirmed "
            "fragment inspires inclusion; a negated fragment excludes only that "
            "concept, without prescribing its replacement. Omitted fragments impose "
            "nothing. The brief takes precedence over the inspiration."
        ),
        "criteria": [
            {"id": "objective_fit", "text": "Fulfils the operator's brief and context."},
            {"id": "inspiration_order", "text": (
                "Uses the inspiration in its supplied order, respecting its polarity."
            )},
        ],
        "order_semantics": (
            "Follow the semantic order of the inspiration while meeting the brief. "
            "Do not impose a sentence, scene, causal role or amount of detail per "
            "fragment. For casa, roja, limpiar: introducing a house, painting it red "
            "and then cleaning it follows the order; cleaning a red house reverses it."
        ),
    }


def create_genes(
    group, runner, *, objective, context, references, home, session, workspace,
    configuration, execution_context, prompt_set="default", prompt_values=None,
    creativity_semantics=None, resolve_rigor=None,
):
    """Derive compact search material from the original operator request."""
    values = dict(prompt_values or {})
    values.update(workspace=workspace, objective=objective,
                  creativity_semantics=creativity_semantics or "legacy",
                  context=json.dumps(context, ensure_ascii=False),
                  references=json.dumps(references, ensure_ascii=False))
    if creativity_semantics == "fragments_v3":
        values["gene_count"] = configuration["gene_count"]
    group.ensure_quiescent()
    try:
        reply, result = _call_semantic_job(
            group, runner, job="create_genes", home=home, session=session,
            workspace=workspace, configuration=configuration, values=values,
            validation_context={
                "creativity_semantics": creativity_semantics,
                "gene_count": configuration.get("gene_count", 10),
            },
            context={"job": "create_genes", "generation": 0, "batch": uuid.uuid4().hex},
            execution_context=execution_context, prompt_set=prompt_set,
            resolve_rigor=resolve_rigor,
        )
    finally:
        group.ensure_quiescent()
    if isinstance(result, runners.ControlledInterruptionResult):
        return None, result
    result.diligence_questions = reply.get("questions", [])
    if creativity_semantics == "fragments_v3":
        return search_material_from_fragments(
            reply["gene_pool"], objective=objective, context=context,
            references=references,
        ), result
    material = (
        _search_material_from_gene_pool(
            reply["gene_pool"], objective=objective, context=context,
            references=references,
        )
        if creativity_semantics == "sparse_v2"
        else reply["search_material"]
    )
    return material, result


def call_composition_batch(
    group, runner, *, home, session, workspace, configuration, search_material,
    candidates, generation, batch, execution_context, prompt_set="default",
    prompt_values=None, creativity_semantics=None, resolve_rigor=None,
):
    """Materialize candidate text once, before any reviewer sees it."""
    genomes = {candidate_id: dict(genome) for candidate_id, genome in candidates.items()}
    sparse = creativity_semantics in ("sparse_v2", "fragments_v3")
    values = dict(prompt_values or {})
    values.update(
        workspace=workspace,
        creativity_semantics=creativity_semantics or "legacy",
        search_material=json.dumps(_problem_material(search_material), ensure_ascii=False),
        candidates=json.dumps([
            {
                "candidate_id": candidate_id,
                "components": creativity_search.genome_components(
                    search_material["dimensions"], genome,
                    configuration.get("order_mode"),
                    variants=search_material["variants"] if sparse else None,
                    creativity_semantics=creativity_semantics,
                ),
            }
            for candidate_id, genome in genomes.items()
        ], ensure_ascii=False),
    )
    context = {"job": "compose_candidates", "generation": generation, "batch": batch}
    reply, result = _call_semantic_job(
        group, runner, job="compose_candidates", home=home, session=session,
        workspace=workspace, configuration=configuration, values=values,
        validation_context={"candidate_ids": list(genomes)}, context=context,
        execution_context=execution_context, prompt_set=prompt_set,
        resolve_rigor=resolve_rigor,
    )
    if isinstance(result, runners.ControlledInterruptionResult):
        return None, result
    return {
        "generation": generation,
        "batch": batch,
        "call_id": result.call_id,
        "prompt_path": result.call_context["prompt_path"],
        "regime": {
            "material": result.call_context["material"],
            "agent": result.resolved_family,
            "model": result.resolved_model,
            "effort": result.resolved_effort,
        },
        "genomes": genomes,
        "compositions": reply["compositions"],
        "questions": reply.get("questions", []),
    }, result


def call_evaluation_batch(
    group, runner, *, home, session, workspace, configuration, search_material,
    candidates, generation, batch, execution_context, prompt_set="default",
    prompt_values=None, record_dispatch=None, creativity_semantics=None,
    compositions=None, resolve_rigor=None,
):
    """Evaluate one owner-admitted batch, including the runner's one correction.

    ``candidates`` maps stable candidate ids to genomes. A successful return is
    (validated batch, runner result); interruption retains the shared boundary's
    (None, ControlledInterruptionResult). Operational and protocol faults raise.
    The batch is input for checkpointing, not a selection-ready comparison.
    Its caller must enforce wave/budget bounds and commit accepted work.
    A wave's optional ``record_dispatch`` returns the current regime revision
    immediately before each attempt, so completion order cannot choose it.
    """
    genomes = {candidate_id: dict(genome) for candidate_id, genome in candidates.items()}
    sparse = creativity_semantics in ("sparse_v2", "fragments_v3")
    problem = _problem_material(search_material)
    compositions = list(compositions or [])
    by_candidate = {item["candidate_id"]: item for item in compositions}
    if set(by_candidate) != set(genomes):
        raise ValueError("compositions must cover exactly the evaluation candidates")
    values = dict(prompt_values or {})
    values.update(
        workspace=workspace,
        creativity_semantics=creativity_semantics or "legacy",
        search_material=json.dumps(problem, ensure_ascii=False),
        compositions=json.dumps([
            {
                "candidate_id": candidate_id,
                "components": creativity_search.genome_components(
                    search_material["dimensions"], genome,
                    configuration.get("order_mode"),
                    variants=search_material["variants"] if sparse else None,
                    creativity_semantics=creativity_semantics,
                ),
                "proposal": by_candidate[candidate_id]["proposal"],
            }
            for candidate_id, genome in genomes.items()
        ], ensure_ascii=False),
    )
    context = {"job": "evaluate_candidates", "generation": generation, "batch": batch}
    constraint_ids = [constraint["id"] for constraint in search_material["constraints"]]
    reply, result = _call_semantic_job(
        group, runner, job="evaluate_candidates", home=home, session=session,
        workspace=workspace, configuration=configuration, values=values,
        validation_context={"candidate_ids": list(genomes), "constraint_ids": constraint_ids},
        context=context, execution_context=execution_context, prompt_set=prompt_set,
        record_dispatch=record_dispatch,
        resolve_rigor=resolve_rigor,
    )
    if isinstance(result, runners.ControlledInterruptionResult):
        return None, result
    return {
        "generation": generation,
        "batch": batch,
        "call_id": result.call_id,
        "prompt_path": result.call_context["prompt_path"],
        "regime": {
            "material": result.call_context["material"],
            "agent": result.resolved_family,
            "model": result.resolved_model,
            "effort": result.resolved_effort,
        },
        "genomes": genomes,
        "evaluations": [dict(
            item, proposal=by_candidate[item["candidate_id"]]["proposal"],
        ) for item in reply["evaluations"]],
        "questions": reply.get("questions", []),
    }, result


def _call_semantic_job(
    group, runner, *, job, home, session, workspace, configuration, values,
    validation_context, context, execution_context, prompt_set, record_dispatch=None,
    resolve_rigor=None,
):
    """Share live routing, served validation and correction preparation."""
    prepared_prompt = None

    def prepare_call(error):
        nonlocal prepared_prompt
        context["material"] = staffing.session_material(home, session)
        selected = prompt_router.resolve(
            home, job=job + "@creativity", executor="agent_call",
            material=context["material"], values=values, prompt_set=prompt_set,
            prompt_validator=(
                _validate_sparse_prompt
                if values.get("creativity_semantics") in ("sparse_v2", "fragments_v3")
                and job in ("create_genes", "compose_candidates", "evaluate_candidates")
                else None
            ),
        )
        bound = prompt_contracts.bind(selected.prompt)
        prompt = prompt_router.render(bound.prompt, values)
        if error is not None:
            prompt += runners.REPAIR_SUFFIX % error
        prepared_prompt = prompt
        return SimpleNamespace(
            prompt=prompt,
            validate=lambda reply: prompt_contracts.validate(
                bound, reply, **validation_context,
            ),
            prompt_set_fallback=selected.prompt_set_fallback,
        )

    def resolve_dispatch():
        current_configuration = (
            dict(configuration, rigor=resolve_rigor())
            if resolve_rigor is not None else configuration
        )
        answer = staffing.resolve(
            home, session, material=context["material"],
            **tasks.creativity_job_staffing_request(job, current_configuration),
        ).answer
        return answer["agent"], answer["model"], answer["effort"]

    def before_dispatch(agent, model, effort, _fallback):
        if job in ("compose_candidates", "evaluate_candidates"):
            context["prompt_path"] = runners.save_prompt_trace(
                os.path.join(group.lease.task_dir, "prompts"), agent,
                prepared_prompt, label=context["batch"],
            )
        if record_dispatch is not None:
            context["regime_revision"] = record_dispatch({
                "material": context["material"], "agent": agent,
                "model": model, "effort": effort,
            })

    return group.call_worker(
        runner, None, "", job, workspace,
        prepare_call=prepare_call, resolve_dispatch=resolve_dispatch,
        call_context=context, execution_context=execution_context,
        before_dispatch=before_dispatch,
    )


def expand_progress(
    group, runner, *, progress, search_material, explored, explored_account,
    home, session, workspace, configuration, execution_context,
    prompt_set="default", prompt_values=None, resolve_rigor=None,
):
    """Apply one due intervention; return (current material, runner result).

    No due intervention returns no runner result. Interruptions preserve the
    old material; faults raise. The task owner persists accepted search state.
    ``explored_account`` is the owner's compact account of explored directions.
    """
    if not creativity_search.expansion_due(progress, configuration):
        return search_material, None
    group.ensure_quiescent()
    values = dict(prompt_values or {})
    values.update(
        workspace=workspace, objective=search_material["objective"],
        search_material=json.dumps(search_material, ensure_ascii=False),
        promising_candidates=json.dumps([
            dict(candidate_id=item["candidate_id"], proposal=item["proposal"],
                 constraint_valid=item["constraint_valid"],
                 constraint_violations=item["constraint_violations"],
                 reason=item["reason"], assumptions=item["assumptions"],
                 score=item["score"], components=creativity_search.genome_components(
                     search_material["dimensions"], genome, configuration.get("order_mode"),
                 ))
            for genome, item in progress["archive"]
        ], ensure_ascii=False),
        explored_account=explored_account,
    )
    context = {"job": "expand_genes", "generation": progress["generations_completed"],
               "batch": uuid.uuid4().hex}
    try:
        reply, result = _call_semantic_job(
            group, runner, job="expand_genes", home=home, session=session,
            workspace=workspace, configuration=configuration, values=values,
            validation_context={"dimensions": search_material["dimensions"]},
            context=context, execution_context=execution_context, prompt_set=prompt_set,
            resolve_rigor=resolve_rigor,
        )
    finally:
        group.ensure_quiescent()
    if isinstance(result, runners.ControlledInterruptionResult):
        return search_material, result
    material = creativity_search.accept_expansion(progress, search_material, {
        "generation": context["generation"], "batch": context["batch"],
        "call_id": result.call_id, "additions": reply["additions"],
    }, configuration, explored=explored)
    return material, result


def _current_evaluations(state, creativity_semantics=None):
    return {
        item["candidate_id"]: (batch["genomes"][item["candidate_id"]], item)
        for batch in state["batches"]
        if creativity_semantics in ("sparse_v2", "fragments_v3") or batch["regime_revision"] == state["regime_revision"]
        for item in batch["evaluations"]
    }


def _current_compositions(state):
    return {
        item["candidate_id"]: item
        for batch in state.get("composition_batches", [])
        for item in batch["compositions"]
    }


def evaluate_wave(
    group, runner, *, store, checkpoint_key, candidates, comparison_ids,
    reference_revision=None, creativity_semantics=None, **call_options,
):
    """Assess at most batch_size * concurrency candidates, then hand off.

    The owner supplies the existing whole task checkpoint in ``store`` (a
    LocalKVClient) and retains sole write ownership during the wave. Only its
    ``evaluation`` portion is changed. Stable candidate ids keep their genomes
    across waves; ``candidates`` is the work the owner requests, whereas
    ``comparison_ids`` includes every requested id and the retained survivors.

    Sparse accepted work is skipped regardless of evaluator configuration.
    Legacy same-regime work is skipped on explicit re-entry. Old-regime work
    is assessed again only when the owner includes it in ``candidates``; a live
    regime change never causes automatic reassessment inside this wave.
    ``reference_revision`` is the regime revision of the owner's progress
    reference, or None before its first reference. A revision counts regime
    changes at dispatch, including corrections, never prompt edits.

    The returned handoff has selection pairs only for a complete comparison,
    plus unfinished ids and an optional ControlledInterruptionResult. Faults
    raise after siblings settle; their accepted checkpoints remain available.
    Re-entry and return both use the group's existing quiescence boundary.
    """
    group.ensure_quiescent()
    checkpoint = store.get(checkpoint_key)
    if "evaluation" not in checkpoint:
        checkpoint["evaluation"] = {
            "accepted_count": 0, "regime": None, "regime_revision": 0,
            "composition_batches": [], "batches": [],
        }
        store.put(checkpoint_key, checkpoint)
    state = checkpoint["evaluation"]
    if "composition_batches" not in state:
        state["composition_batches"] = []
        store.put(checkpoint_key, checkpoint)
    current = _current_evaluations(state, creativity_semantics)
    configuration = call_options["configuration"]
    capacity = configuration["max_evaluated_candidates"] - state["accepted_count"]
    batch_size = configuration["evaluation_batch_size"]
    concurrency = configuration["evaluation_concurrency"]
    pending = [candidate_id for candidate_id in candidates if candidate_id not in current]
    # Reserve the entire wave before dispatch: siblings and correction attempts
    # cannot spend these same places again. There is no waiting batch queue.
    pending = pending[:min(capacity, batch_size * concurrency)]
    lock = threading.Lock()

    def record_dispatch(regime):
        with lock:
            checkpoint = store.get(checkpoint_key)
            state = checkpoint["evaluation"]
            if regime != state["regime"]:
                state["regime"] = regime
                state["regime_revision"] += 1
                # Keep dispatch provenance even on interruption or rejection;
                # only legacy eligibility depends on this revision.
                store.put(checkpoint_key, checkpoint)
            return state["regime_revision"]

    def run_batch(ids, batch_id):
        with lock:
            state = store.get(checkpoint_key)["evaluation"]
            composed = _current_compositions(state)
        missing = [candidate_id for candidate_id in ids if candidate_id not in composed]
        if missing:
            composition, result = call_composition_batch(
                group, runner,
                candidates={key: candidates[key] for key in missing},
                batch=batch_id, creativity_semantics=creativity_semantics,
                **call_options,
            )
            if composition is None:
                return result
            with lock:
                checkpoint = store.get(checkpoint_key)
                checkpoint["evaluation"].setdefault(
                    "composition_batches", []
                ).append(composition)
                store.put(checkpoint_key, checkpoint)
        with lock:
            composed = _current_compositions(
                store.get(checkpoint_key)["evaluation"]
            )
        accepted, result = call_evaluation_batch(
            group, runner, candidates={key: candidates[key] for key in ids},
            compositions=[composed[key] for key in ids], batch=batch_id,
            record_dispatch=record_dispatch,
            creativity_semantics=creativity_semantics, **call_options,
        )
        if accepted is not None:
            accepted["regime_revision"] = result.call_context["regime_revision"]
            with lock:
                checkpoint = store.get(checkpoint_key)
                state = checkpoint["evaluation"]
                state["batches"].append(accepted)
                state["accepted_count"] += len(ids)
                store.put(checkpoint_key, checkpoint)
        else:
            return result

    interruption = None
    if pending:
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(
                    run_batch, pending[offset:offset + batch_size],
                    uuid.uuid4().hex,
                ) for offset in range(0, len(pending), batch_size)]
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        interruption = result
        finally:
            group.ensure_quiescent()

    state = store.get(checkpoint_key)["evaluation"]
    current = _current_evaluations(state, creativity_semantics)
    unfinished = [candidate_id for candidate_id in comparison_ids if candidate_id not in current]
    ready = not unfinished and interruption is None
    return {
        "regime": state["regime"], "regime_revision": state["regime_revision"],
        "accepted_count": state["accepted_count"], "unfinished": unfinished,
        "comparison_ready": ready,
        "evaluated": [current[key] for key in comparison_ids] if ready else [],
        "rebaseline_required": creativity_semantics not in ("sparse_v2", "fragments_v3") and state["regime_revision"] > (
            1 if reference_revision is None else reference_revision
        ),
        "interruption": interruption,
    }


def evaluate_progress_wave(group, runner, *, progress, configuration,
                           creativity_semantics=None, **call_options):
    """Advance one search comparison through the existing bounded wave.

    The task owner opens generations with creativity_search.begin_generation
    and decides when to call again. No loop, retry or task lifecycle is added.
    The returned wave preserves interruption and accepted-work evidence.
    """
    request = creativity_search.progress_evaluation_request(progress)
    if request is None:
        return None
    wave = evaluate_wave(
        group, runner, configuration=configuration, **request, **call_options,
        creativity_semantics=creativity_semantics,
    )
    creativity_search.accept_evaluation_wave(
        progress, wave, configuration,
        dimensions=call_options["search_material"]["dimensions"],
        creativity_semantics=creativity_semantics,
    )
    return wave
