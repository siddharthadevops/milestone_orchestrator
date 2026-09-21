# Slice 6 — Compare prompt formulations on three different problems

## INTENT

The operator has already accepted this slice as fulfilled. This note records
that decision so the ordinary milestone process can finish autonomously. It
builds no feature and requests no further experiment or human response.

The dependencies are the accepted work from the preceding five slices and
the existing completion process. Existing results stay intact. The risk is
reopening work the operator has explicitly discharged, wasting paid calls or
preventing completion. This documentation change is reversible; repeating
paid work would not be. The exact acceptance and scope are pinned below.

## PINNED-FACTS TABLE

Paths are workspace-relative. **A2** means the run mandate's **OPERATOR
AMENDMENTS → [A2] OPERATOR AMENDMENT — Slice 6 is already satisfied**.
**Strict** below denotes an authored scope or output obligation, checked by
artifact, response and action review; it promises no new runtime delivery
mechanism. No optimistic, eventual or best-effort mechanism is introduced.

| fact | value | authority (file:line) | touch / do-not-touch |
| --- | --- | --- | --- |
| Accepted no-op | **Strict.** A2 replaces A1 and satisfies every Slice 6 acceptance obligation. Dispatched `slice_doc-06`, `slice_impl-06` and their reviews return `status: "ok"` with only their existing contract's minimum output. Missing superseded work is neither a finding nor grounds for `blocked` or `need_rethink`; `CV2-001` is resolved. | Run mandate, A2; `implementation/milestones/creativity-v2/skeleton.md:62-65` | Record acceptance here; do not revise the skeleton or reopen comparison acceptance. |
| Artifact and response | **Strict.** The sole drafting artifact is `implementation/milestones/creativity-v2/slices/slice-06.md`. Return `kind: "draft_slice_note"`, that `artifact`, and answers to `due_diligence_count`, `machinery_trust`, `environment_fit`, `human_scale` in the existing JSON contract. | Run mandate, TASK / OUTPUT CONTRACT / QUESTIONS; `orchestrator/contracts.py:1062-1085`; `orchestrator/prompt_contracts.py:137-155,673,678` | Write only this note; reuse the existing result validator. |
| Scope and independence | **Strict.** No production-code change, live comparison, benchmark, Creativity task, downstream/nested model call, performance/creative-quality verification, semantic-fidelity assessment, token/cost comparison or human dependency. No response to `operator-judgments.json` is required. Existing comparison artifacts, commits, run history and accounting remain as they are, without cleanup, repair, repetition, normalization or judgment. | Run mandate, A2 / PROJECT CONTEXT / PROCESS AUTHORITY | Leave production, prompts, tests and existing evidence untouched. Additional roots remain read-only; agent instruction files and `.orchestrator/` are neither authority nor edit targets. |
| Retained assurance | **Strict mechanical contract evidence.** Completion rests on accepted Slices 1–5 and deterministic mechanical tests, including the configured repository suite through its existing lifecycle. All other accepted sparse-Creativity contracts remain unchanged. This slice adds no tests or verification prerequisite and makes no algorithm-performance, semantic-fidelity or creative-quality claim. | Run mandate, A2, final paragraph; `orchestrator/README.md:158-175`; existing example: `orchestrator/tests/test_creativity_task.py:1403-1439` | Preserve existing tests and suite configuration. Documentation does not run the full suite; this note reports no fresh suite result. |

### Due Diligence

| question | answer and verified evidence |
| --- | --- |
| victim | The operator's autonomous completion would be obstructed by reinstating discharged comparisons or human judgments. Exposure is needless waiting and paid calls; the note is reversible, spent calls are not. A2 independently establishes the need and discharges the original assignment (`implementation/milestones/creativity-v2/skeleton.md:62-65`; run mandate, A2). |
| machinery | None: one acceptance note and the existing structured response suffice. No module, API, dependency or runtime seam is introduced (`orchestrator/contracts.py:1084-1085`; run mandate, A2). |
| consumers_touched | Existing milestone workers consume the note as implementation/review authority; the driver already supplies that reference (`orchestrator/driver.py:2542-2553,8583-8589`). No runtime consumer is changed or created; A2 limits this unit to a no-op. |
| cheaper_alternative | Document the decision using the existing artifact contract. Doing nothing would omit the required handoff; additional code or an external component serves no remaining outcome. Workspace and granted-root searches disclosed no reuse need for this documentation-only delta (`orchestrator/contracts.py:1084-1085`; run mandate, TASK / A2). |
| cost | One short document and its review; no build, migration, operation or runtime-maintenance cost is introduced. Omitting it leaves the required lifecycle artifact absent; expanding it risks renewed calls or waiting (run mandate, A2 / OUTPUT CONTRACT). |
| threat_model | This slice handles no untrusted runtime input and has no attacker-facing surface. The operator decision, product code and existing validators are trusted; no defense around them is added. The only new input to the workflow is this authored note (`orchestrator/driver.py:8583-8589`; run mandate, A2). |
| pinned_facts | The four rows above are the complete delta: accepted no-op, exact artifact/response, untouched work and autonomous scope, and retained mechanical assurance. Their authority is A2 and the mounted TASK / OUTPUT CONTRACT / QUESTIONS, with the original assignment at `implementation/milestones/creativity-v2/skeleton.md:62-65`. |
| verification | Inspect this artifact, the returned JSON, changed paths and this worker's actions for compliance with the table. Existing `test_draft_slice_note` and `test_registered_contract_examples` cover the reused output boundary (`orchestrator/tests/test_runners.py:472-477`; `orchestrator/tests/test_prompt_contracts.py:413-430`). No new test, comparison or rerun is required by this slice (A2). |
| enforceability | The existing result validator enforces the artifact field and normalized relative path (`orchestrator/prompt_contracts.py:90-103,137-155,673`). A2 supplies acceptance authority; ordinary document/action and change review checks scope. These are authored obligations, not a claim that JSON validation prevents calls or guarantees milestone delivery. No new runtime invariant or semantic guarantee needs an enforcement mechanism (run mandate, A2). |
