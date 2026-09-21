"""One bounded, opt-in capture using the existing service and real task host.

Run from the repository root with: python3 <this-file> --run
The retained declaration prevents accidentally overwriting a measured run.
No model, search, routing, validation or accounting implementation lives here.
"""

import copy
from collections import Counter
import datetime
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from orchestrator import creativity_search, kvstore, service, staffing, task_api

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parent / "examples"
CONFIGURATION = {
    "population_size": 4, "generation_limit": 2,
    "max_evaluated_candidates": 8, "elite_count": 2, "diversity_count": 1,
    "mutation_rate": 0.35, "evaluation_batch_size": 4,
    "evaluation_concurrency": 1, "shortlist_size": 3,
    "order_mode": "interchangeable",
    "rigor": {"default": "medium", "evaluate_candidates": "low"},
}
SEQUENCE = [domain + "-" + form for domain in
            ("literature", "strategy", "planning") for form in ("literal", "abstract")]
ADDITIONAL = ["/Users/siddhartha/Development/source/" + name for name in
              ("life", "life_prod/agent_99", "life_prod/life_product_components", "life_prod/tutor")]


def read(path):
    return json.loads(Path(path).read_text())


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run():
    if (HERE / "declaration.json").exists():
        raise SystemExit("A declared capture already exists; do not overwrite or automatically rerun it.")
    home = tempfile.mkdtemp(prefix="creativity-v2-comparison-")
    current = {"label": None, "calls": 0, "draws": []}

    def runner_factory(config, workspace):
        runner = task_api.DirectTaskHost._runner(config, workspace)
        physical_call = runner.call

        def capture(family, prompt, workspace, **kwargs):
            current["calls"] += 1
            name = "%s-call-%02d.json" % (current["label"], current["calls"])
            transcript = {"family": family, "model": kwargs.get("model"),
                          "effort": kwargs.get("effort"), "prompt": prompt}
            save(name, transcript)
            try:
                result = physical_call(family, prompt, workspace, **kwargs)
                transcript.update({key: getattr(result, key) for key in
                                   ("text", "exit_code", "duration_s", "token_usage", "cost_payloads")})
                save(name, transcript)
                return result
            except BaseException as exc:
                transcript["error"] = str(exc)
                save(name, transcript)
                raise

        runner.call = capture
        return runner

    # Observe the existing supplier's identity decision, without changing it.
    # A duplicate means a drawn effective seed was already in its actual `seen`.
    def profile(frame, event, value):
        if (event == "return" and frame.f_code is creativity_search.genome_key.__code__
                and frame.f_back.f_code is creativity_search._fill_population.__code__):
            parent = frame.f_back.f_locals
            current["draws"].append({
                "genome": dict(frame.f_locals["genome"]), "effective_seed": value,
                "decision": "empty" if value is None else
                            "duplicate" if value in parent["seen"] else "accepted",
            })

    host = task_api.DirectTaskHost(home, runner_factory=runner_factory)
    server = service.make_server(home, 0, task_host=host)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base = "http://127.0.0.1:%s" % server.server_address[1]

    def request(method, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)

    try:
        request("POST", "/api/projects", {"slug": "orchestrators"})
        request("POST", "/api/projects/orchestrators/work-areas", {
            "name": "implementation", "primary_path": str(ROOT), "additional_paths": ADDITIONAL,
        })
        document = read(HERE.parent.parent / "creativity/evidence/staffing.json")
        document["name"] = "creativity-v2-comparison"
        staffing.save(home, document)
        save("staffing.json", document)
        save("declaration.json", {
            "declared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "execution_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "service_home": home, "sequence": SEQUENCE,
            "configuration": CONFIGURATION, "random_seed_per_task": 20260921,
            "formulation_authority": "Six supplied initial_genes files; unchanged default prompt set and sparse_v2 engine.",
            "comparison": "Identical immutable problem, five foci, twelve shared values and initial RNG state per pair. Later selection can diverge with returned scores.",
            "low_score_threshold": {"operator": "<", "value": 0.5},
            "work_bound": "Six tasks, two generations and eight distinct evaluated seeds per task. Twelve planned evaluation calls; existing contract correction may add attempts, all retained. No creation, expansion, judge or automatic rerun calls.",
            "cost_basis": "Existing physical-call/task accounting: API-equivalent USD and configured subscription real USD. No asserted equal spend or enforced dollar cap.",
            "assessment": "Model validity and scores are diagnostics. Record assistant inspection separately from actual operator judgments; do not infer human approval.",
            "limitations": "Small authored-vocabulary pilot, literal first, one draw per cell, supplied rather than model-generated material. No superiority or causal effect estimate.",
        })
        threading.setprofile(profile)
        for label in SEQUENCE:
            current.update(label=label, calls=0, draws=[])
            domain = label.split("-")[0]
            session = staffing.create_session(home, {
                "work_area": {"project": "orchestrators", "work_area": "implementation"},
                "families": ["codex"], "document": document["name"], "rigor": "medium",
                "material": {"literature": "literature", "strategy": "business", "planning": "default"}[domain],
            })
            save(label + "-session.json", session)
            problem = read(EXAMPLES / (domain + "-problem.json"))
            order = {"task_executor": "creativity", "request": dict(problem, work_area=session["work_area"]),
                     "configuration": copy.deepcopy(CONFIGURATION), "staffing_session": session["id"],
                     "prompt_set": "default", "initial_genes": read(EXAMPLES / (label + ".json"))}
            save(label + "-order.json", order)
            random.seed(20260921)
            admitted = request("POST", "/api/tasks", order)
            save(label + "-admission.json", admitted)
            task_id = admitted["task"]["id"]
            print(label, task_id, "started", flush=True)
            while host.is_active(task_id):
                time.sleep(0.25)
            public = request("GET", "/api/tasks/" + task_id)
            save(label + "-task.json", public)
            checkpoint = task_api.creativity_checkpoint_store(home, task_id)
            if checkpoint.get("checkpoint") is not kvstore.ABSENT:
                shutil.copyfile(Path(checkpoint.directory) / kvstore.STORE_FILENAME,
                                HERE / (label + "-checkpoint-store.json"))
                save(label + "-checkpoint.json", checkpoint.get("checkpoint"))
            save(label + "-draws.json", current["draws"])
            save(label + "-lifecycle.json", host.store.lifecycle(task_id))
            print(label, "finished", (public["task"]["result"] or {}).get("status"), flush=True)
            if not public["task"]["result"] or public["task"]["result"]["status"] != "success":
                raise RuntimeError("Task did not succeed; retained the attempt and stopped without a rerun.")
    finally:
        threading.setprofile(None)
        if Path(task_api.records_path(home)).exists():
            shutil.copyfile(task_api.records_path(home), HERE / "task-store.json")
        server.shutdown()
        server.server_close()
        server_thread.join()


def summarize():
    """Reconcile retained outputs with existing projections and call receipts."""
    from orchestrator import prompt_contracts
    rows = []
    material_fields = ("objective", "context_summary", "facts", "constraints", "assumptions",
                       "unknowns", "composition_guidance", "criteria", "order_semantics")
    paired = {}
    for label in SEQUENCE:
        public = read(HERE / (label + "-task.json"))
        task, view = public["task"], public["creativity"]
        result, native = task["result"], task["result"]["native_result"]
        checkpoint = read(HERE / (label + "-checkpoint.json"))
        supplied = read(EXAMPLES / (label + ".json"))
        normalized = prompt_contracts.validate_create_genes_reply(supplied, creativity_semantics="sparse_v2")
        assert normalized["search_material"] == checkpoint["search_material"] == view["search_material"]
        assert task["order"]["creativity_semantics"] == "sparse_v2"
        assert view["initial_genes_supplied"] and result["status"] == "success"
        assert native["stop_reason"] == "generation_limit" and native["generations_completed"] == 2
        assert native["expansion_interventions"] == 0 and native["evaluated_candidates"] == 8
        evaluations = {item["candidate_id"]: item for item in view["candidate_evaluations"]}
        assert len(evaluations) == len(view["candidate_evaluations"]) == 8
        seeds = {key: creativity_search.genome_key(genome, supplied["search_material"]["dimensions"],
                 "interchangeable", creativity_semantics="sparse_v2")
                 for key, genome in checkpoint["candidates"].items()}
        assert len(seeds) == len(set(seeds.values())) == 8 and None not in seeds.values()
        for key, item in evaluations.items():
            assert tuple((c["dimension_id"], c["variant_id"]) for c in item["components"]) == seeds[key]
            assert item["active_count"] == len(seeds[key]) and item["omitted_count"] == 5 - len(seeds[key])
        life = read(HERE / (label + "-lifecycle.json"))
        events = [e for e in life["history"] if "physical_dispatch" in e]
        calls = [read(f) for f in sorted(HERE.glob(label + "-call-*.json"))]
        assert len(events) == len(calls)
        by_call = {e["call_id"]: call for e, call in zip(events, calls)}
        assert len(by_call) == len(events)
        for event, call in zip(events, calls):
            receipt = event["physical_dispatch"]
            assert receipt["call_context"]["job"] == "evaluate_candidates"
            assert receipt["prompt_set_fallback"] is None
            for field in ("family", "model", "effort", "duration_s", "token_usage", "cost_payloads"):
                assert receipt[field] == call[field]
            immutable = json.JSONDecoder().raw_decode(call["prompt"].split(
                "IMMUTABLE SEARCH MATERIAL AND CRITERIA (JSON):\n", 1)[1])[0]
            assert immutable == {key: supplied["search_material"][key] for key in material_fields}
            sent = json.JSONDecoder().raw_decode(call["prompt"].split(
                "CANDIDATE BATCH (JSON; IDs identify candidates, not rank):\n", 1)[1])[0]
            assert "__omit__" not in json.dumps(sent) and "__order__" not in json.dumps(sent)
            for candidate in sent:
                assert set(candidate) == {"candidate_id", "components"}
                assert candidate["components"] == evaluations[candidate["candidate_id"]]["components"]
        for batch in checkpoint["evaluation"]["batches"]:
            assert json.loads(by_call[batch["call_id"]]["text"])["evaluations"] == batch["evaluations"]
        assert not result["cost_partial"] and not result["token_usage_partial"]
        for field in result["token_usage"]:
            assert result["token_usage"][field] == sum(e["attempt"]["token_usage"][field] for e in events)
        for field in result["cost"]:
            assert math.isclose(result["cost"][field], sum(e["attempt"]["cost"][field] for e in events), abs_tol=1e-12)
        assert math.isclose(result["duration_s"], sum(e["attempt"]["duration_s"] for e in events), abs_tol=1e-9)
        draws = read(HERE / (label + "-draws.json"))
        assert {tuple(map(tuple, d["effective_seed"])) for d in draws if d["decision"] == "accepted"} == set(seeds.values())
        paired[label] = (immutable, [d["effective_seed"] for d in draws[:4]])
        counts = Counter(item["active_count"] for item in evaluations.values())
        rows.append({
            "label": label, "task_id": task["id"], "evaluated_candidates": len(evaluations),
            "seed_size_counts": dict(sorted(counts.items())),
            "mean_seed_size": sum(size * count for size, count in counts.items()) / len(evaluations),
            "low_score_count": sum(item["score"] < 0.5 for item in evaluations.values()),
            "model_valid_count": sum(item["constraint_valid"] for item in evaluations.values()),
            "repeated_seeds_avoided": sum(d["decision"] == "duplicate" for d in draws),
            "empty_draws_ignored": sum(d["decision"] == "empty" for d in draws),
            "physical_calls": len(events), "accounting": {key: result[key] for key in
                ("duration_s", "token_usage", "token_usage_partial", "cost", "cost_partial")},
            "stop_reason": native["stop_reason"], "mechanical_checks": "passed",
        })
    for domain in ("literature", "strategy", "planning"):
        assert paired[domain + "-literal"] == paired[domain + "-abstract"]
    save("summary.json", {"low_score_threshold": "score < 0.5", "runs": rows,
                          "checks": "All six terminal runs reconcile with admitted inputs, exact sent seeds, accepted replies, physical receipts and task totals; immutable problems and first-generation genetic draws match within pairs."})
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    if sys.argv[1:] == ["--run"]:
        run()
    elif sys.argv[1:] == ["--summarize"]:
        summarize()
    else:
        raise SystemExit("Pass --run for live calls, or --summarize to verify and summarize retained evidence offline.")
