"""Evaluation waves and routed expansion for the task-owned creativity search.

The owner supplies admitted material, configuration and candidate genomes, and
a DirectTaskHost-created TaskCallGroup. This caller owns semantic invocation,
accepted checkpoints and comparison eligibility; the group owns controls and
physical evidence.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import threading
import uuid
from types import SimpleNamespace

from . import creativity_search, prompt_contracts, prompt_router, runners, staffing, tasks


def create_genes(
    group, runner, *, objective, context, references, home, session, workspace,
    configuration, execution_context, prompt_set="default", prompt_values=None,
):
    """Derive compact search material from the original operator request."""
    values = dict(prompt_values or {})
    values.update(workspace=workspace, objective=objective,
                  context=json.dumps(context, ensure_ascii=False),
                  references=json.dumps(references, ensure_ascii=False))
    group.ensure_quiescent()
    try:
        reply, result = _call_semantic_job(
            group, runner, job="create_genes", home=home, session=session,
            workspace=workspace, configuration=configuration, values=values,
            validation_context={},
            context={"job": "create_genes", "generation": 0, "batch": uuid.uuid4().hex},
            execution_context=execution_context, prompt_set=prompt_set,
        )
    finally:
        group.ensure_quiescent()
    return (None if isinstance(result, runners.ControlledInterruptionResult)
            else reply["search_material"]), result


def call_evaluation_batch(
    group, runner, *, home, session, workspace, configuration, search_material,
    candidates, generation, batch, execution_context, prompt_set="default",
    prompt_values=None, record_dispatch=None,
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
    values = dict(prompt_values or {})
    values.update(
        workspace=workspace,
        search_material=json.dumps(search_material, ensure_ascii=False),
        candidates=json.dumps([
            {"candidate_id": candidate_id, "components": creativity_search.genome_components(
                search_material["dimensions"], genome, configuration.get("order_mode"),
            )}
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


def _call_semantic_job(
    group, runner, *, job, home, session, workspace, configuration, values,
    validation_context, context, execution_context, prompt_set, record_dispatch=None,
):
    """Share live routing, served validation and correction preparation."""

    def prepare_call(error):
        context["material"] = staffing.session_material(home, session)
        selected = prompt_router.resolve(
            home, job=job + "@creativity", executor="agent_call",
            material=context["material"], values=values, prompt_set=prompt_set,
        )
        bound = prompt_contracts.bind(selected.prompt)
        prompt = prompt_router.render(bound.prompt, values)
        if error is not None:
            prompt += runners.REPAIR_SUFFIX % error
        return SimpleNamespace(
            prompt=prompt,
            validate=lambda reply: prompt_contracts.validate(
                bound, reply, **validation_context,
            ),
            prompt_set_fallback=selected.prompt_set_fallback,
        )

    def resolve_dispatch():
        answer = staffing.resolve(
            home, session, material=context["material"],
            **tasks.creativity_job_staffing_request(job, configuration),
        ).answer
        return answer["agent"], answer["model"], answer["effort"]

    def before_dispatch(agent, model, effort, _fallback):
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
    prompt_set="default", prompt_values=None,
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


def _current_evaluations(state):
    return {
        item["candidate_id"]: (batch["genomes"][item["candidate_id"]], item)
        for batch in state["batches"]
        if batch["regime_revision"] == state["regime_revision"]
        for item in batch["evaluations"]
    }


def evaluate_wave(
    group, runner, *, store, checkpoint_key, candidates, comparison_ids,
    reference_revision=None, **call_options,
):
    """Assess at most batch_size * concurrency candidates, then hand off.

    The owner supplies the existing whole task checkpoint in ``store`` (a
    LocalKVClient) and retains sole write ownership during the wave. Only its
    ``evaluation`` portion is changed. Stable candidate ids keep their genomes
    across waves; ``candidates`` is the work the owner requests, whereas
    ``comparison_ids`` includes every requested id and the retained survivors.

    Same-regime accepted work is skipped on explicit re-entry. Old-regime work
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
            "accepted_count": 0, "regime": None, "regime_revision": 0, "batches": [],
        }
        store.put(checkpoint_key, checkpoint)
    state = checkpoint["evaluation"]
    current = _current_evaluations(state)
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
                # Keep invalidation even if this attempt is interrupted or its
                # reply is rejected, so explicit re-entry cannot revive scores.
                store.put(checkpoint_key, checkpoint)
            return state["regime_revision"]

    def run_batch(ids, batch_id):
        accepted, result = call_evaluation_batch(
            group, runner, candidates={key: candidates[key] for key in ids},
            batch=batch_id, record_dispatch=record_dispatch, **call_options,
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
    current = _current_evaluations(state)
    unfinished = [candidate_id for candidate_id in comparison_ids if candidate_id not in current]
    ready = not unfinished and interruption is None
    return {
        "regime": state["regime"], "regime_revision": state["regime_revision"],
        "accepted_count": state["accepted_count"], "unfinished": unfinished,
        "comparison_ready": ready,
        "evaluated": [current[key] for key in comparison_ids] if ready else [],
        "rebaseline_required": state["regime_revision"] > (
            1 if reference_revision is None else reference_revision
        ),
        "interruption": interruption,
    }


def evaluate_progress_wave(group, runner, *, progress, configuration, **call_options):
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
    )
    creativity_search.accept_evaluation_wave(progress, wave, configuration)
    return wave
