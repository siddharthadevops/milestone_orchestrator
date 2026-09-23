"""Two document candidates, independent criticism, and bounded revisions.

The task owns the round barriers and accepted results. Prompts own the work;
question answers are discarded. Validation checks the declared deliverables,
never audits either author's writes elsewhere in the repository.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
import os
from types import SimpleNamespace

from . import prompt_contracts, prompt_router, prompt_sets, runners, staffing, tasks


CANDIDATES = ("a", "b")
KINDS = {"author_candidate": "duel_author", "review_candidate": "duel_review"}


def new_checkpoint(record, workspace):
    request = record["order"]["request"]
    output = request.get("output_directory") or os.path.join(
        workspace, "duel", record["id"],
    )
    output = os.path.realpath(output)
    candidates = []
    for identity in CANDIDATES:
        directory = tasks.resolve_derived_path(output, identity)
        if os.path.isdir(directory) and os.listdir(directory):
            raise ValueError("Duel candidate directory must start empty: %s" % directory)
        os.makedirs(directory, exist_ok=True)
        candidates.append({
            "id": identity, "directory": directory, "artifacts": [],
            "finished": False, "score": None, "report_path": None,
            "production_round": 0, "review_round": 0,
        })
    return {
        "output_directory": output, "round": 1, "phase": "author",
        "rounds_completed": 0, "candidates": candidates,
        "rounds": [{"round": 1, "authors": {}, "reviews": {}}],
        "stop_reason": None, "native_result": None,
    }


def delivered_artifacts(directory, paths):
    """Establish positive evidence inside this candidate's work directory."""
    artifacts = []
    if not isinstance(paths, list) or not paths:
        raise ValueError("Duel requires at least one delivered document")
    for relative in paths:
        if not isinstance(relative, str) or not relative.strip() or os.path.isabs(relative):
            raise ValueError("Duel artifact paths must be relative to the candidate directory")
        path = tasks.resolve_derived_path(directory, relative)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise ValueError("Duel deliverable is missing or empty: %s" % path)
        if path in artifacts:
            raise ValueError("Duel deliverables must not repeat the same document")
        artifacts.append(path)
    return artifacts


def call_candidate(
    group, runner, *, job, candidate_id, round_number, home, session, workspace,
    configuration, values, execution_context, prompt_set=prompt_sets.DEFAULT_SET_NAME,
    families=(),
):
    """Resolve this Duel charge and staff one independent physical call."""
    context = {"job": job, "candidate_id": candidate_id, "round": round_number}
    prepared_prompt = None

    def prepare_call(_error):
        nonlocal prepared_prompt
        context["material"] = staffing.session_material(home, session)
        selected = prompt_router.resolve(
            home, job=job + "@duel", executor="agent_call",
            material=context["material"], values=values, prompt_set=prompt_set,
        )
        bound = prompt_contracts.bind(selected.prompt)
        prepared_prompt = prompt_router.render(bound.prompt, values)
        return SimpleNamespace(
            prompt=prepared_prompt,
            validate=lambda reply: prompt_contracts.validate(
                bound, reply, duel_round=round_number,
            ),
            prompt_set_fallback=selected.prompt_set_fallback,
        )

    def resolve_dispatch():
        resolution = staffing.resolve(
            home, session, material=context["material"], families=families,
            round=round_number,
            **tasks.duel_job_staffing_request(job, candidate_id, configuration),
            **({"review_breadth": "independent"} if job == "review_candidate" else {}),
        )
        answer = resolution.answer
        if resolution.staffing_fallback is not None:
            context["staffing_fallback"] = resolution.staffing_fallback
        return answer["agent"], answer["model"], answer["effort"]

    def before_dispatch(agent, _model, _effort, _fallback):
        context["prompt_path"] = runners.save_prompt_trace(
            os.path.join(group.lease.task_dir, "prompts"), agent, prepared_prompt,
            label="duel-%s-%s-%d" % (job, candidate_id, round_number),
        )

    reply, result = group.call_worker(
        runner, None, "", KINDS[job], workspace,
        prepare_call=prepare_call, resolve_dispatch=resolve_dispatch,
        before_dispatch=before_dispatch, call_context=context,
        execution_context=execution_context, single_attempt=True,
    )
    if isinstance(result, runners.ControlledInterruptionResult):
        return None, result
    # The answers have done their job by making the agent seek context. They
    # are not task state, review findings, or a continuation decision.
    fields = ("action", "artifacts", "summary") if job == "author_candidate" else ("score", "report")
    return {key: reply[key] for key in fields}, result


def _values(checkpoint, candidate, request, configuration, ecosystem_map):
    author = checkpoint["phase"] == "author"
    opponent = next(item for item in checkpoint["candidates"] if item["id"] != candidate["id"])
    previous_reviews = [
        {key: item[key] for key in ("id", "score", "report_path", "review_round", "finished")}
        for item in checkpoint["candidates"] if item["report_path"] is not None
    ] if author else []
    return {
        "workspace": request["work_area"].get("workspace_path") or (
            request["work_area"]["primary"].get("path")
            if isinstance(request["work_area"]["primary"], dict)
            else request["work_area"]["primary"]
        ),
        "request": request["request"], "context": json.dumps(request["context"], ensure_ascii=False),
        "references": json.dumps(request["reference_documents"], ensure_ascii=False),
        "candidate_id": candidate["id"], "candidate_directory": candidate["directory"],
        "opponent_directory": opponent["directory"] if author else "",
        "round": checkpoint["round"], "max_rounds": configuration["max_rounds"],
        "previous_reviews": json.dumps(previous_reviews, ensure_ascii=False),
        "artifacts": json.dumps([
            os.path.relpath(path, candidate["directory"]) for path in candidate["artifacts"]
        ], ensure_ascii=False),
        "ecosystem_map": ecosystem_map,
    }


def run_phase(group, runner, *, store, request, configuration, ecosystem_map, **options):
    """Run at most two calls concurrently and save each accepted sibling.

    All calls settle before the next phase starts or an error leaves this
    function. Resume only calls the missing members of the current phase.
    """
    group.ensure_quiescent()
    checkpoint = store.get("checkpoint")
    author = checkpoint["phase"] == "author"
    charge = "author_candidate" if author else "review_candidate"
    ledger = checkpoint["rounds"][-1]["authors" if author else "reviews"]
    pending = [
        candidate for candidate in checkpoint["candidates"]
        if not candidate["finished"] and candidate["id"] not in ledger
    ]
    interruption, errors = None, []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="duel") as pool:
        futures = {
            pool.submit(
                call_candidate, group, runner, job=charge, candidate_id=candidate["id"],
                round_number=checkpoint["round"], configuration=configuration,
                values=_values(checkpoint, candidate, request, configuration, ecosystem_map),
                **options,
            ): candidate
            for candidate in pending
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                reply, result = future.result()
                if reply is None:
                    interruption = result
                    continue
                if author:
                    _accept_author(checkpoint, candidate, reply, result)
                else:
                    _accept_review(checkpoint, candidate, reply, result)
                store.put("checkpoint", checkpoint)
            except Exception as exc:
                errors.append(exc)
    group.ensure_quiescent()
    if errors:
        raise errors[0]
    return interruption


def _accept_author(checkpoint, candidate, reply, result):
    artifacts = delivered_artifacts(candidate["directory"], reply["artifacts"])
    if reply["action"] == "finish":
        if not candidate["production_round"]:
            raise ValueError("Duel authors must produce a version before finishing")
        # Finishing preserves the last production and its evaluation.
        candidate["finished"] = True
    else:
        candidate.update(artifacts=artifacts, production_round=checkpoint["round"])
    checkpoint["rounds"][-1]["authors"][candidate["id"]] = {
        "action": reply["action"], "summary": reply["summary"],
        "artifacts": list(candidate["artifacts"]), "call_id": result.call_id,
    }


def _accept_review(checkpoint, candidate, reply, result):
    directory = tasks.resolve_derived_path(
        checkpoint["output_directory"], "reports/round-%03d" % checkpoint["round"],
    )
    os.makedirs(directory, exist_ok=True)
    path = tasks.resolve_derived_path(directory, candidate["id"] + ".md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# Candidate %s — round %d\n\nScore: %s / 1\n\n%s\n" % (
            candidate["id"].upper(), checkpoint["round"], reply["score"], reply["report"],
        ))
    candidate.update(score=reply["score"], report_path=path, review_round=checkpoint["round"])
    checkpoint["rounds"][-1]["reviews"][candidate["id"]] = {
        "score": reply["score"], "report_path": path, "call_id": result.call_id,
    }


def advance(checkpoint, max_rounds):
    """Cross one completed phase barrier; only authors can finish themselves."""
    if checkpoint["phase"] == "author":
        if any(not item["finished"] and item["id"] not in checkpoint["rounds"][-1]["authors"]
               for item in checkpoint["candidates"]):
            raise ValueError("Duel author phase is incomplete")
        checkpoint["phase"] = "review"
        return
    if any(not item["finished"] and item["id"] not in checkpoint["rounds"][-1]["reviews"]
           for item in checkpoint["candidates"]):
        raise ValueError("Duel review phase is incomplete")
    checkpoint["rounds_completed"] = checkpoint["round"]
    finished = all(item["finished"] for item in checkpoint["candidates"])
    if finished or checkpoint["round"] >= max_rounds:
        for candidate in checkpoint["candidates"]:
            delivered_artifacts(candidate["directory"], [
                os.path.relpath(path, candidate["directory"]) for path in candidate["artifacts"]
            ])
        checkpoint["stop_reason"] = "both_finished" if finished else "round_limit"
        checkpoint["phase"] = "complete"
        checkpoint["native_result"] = {
            key: copy.deepcopy(checkpoint[key]) for key in (
                "stop_reason", "rounds_completed", "candidates", "rounds",
            )
        }
    else:
        checkpoint["round"] += 1
        checkpoint["phase"] = "author"
        checkpoint["rounds"].append({"round": checkpoint["round"], "authors": {}, "reviews": {}})
