# Prompt Analysis — Brainstorming Path

Status: **non-canonical analysis, input for a future prompt-router goal**. It
describes how Brainstorming builds its prompts today, read from the
implementation workspace while the staffing-router milestone is mid-flight
there. Companion: [`prompt-analysis-milestone.md`](prompt-analysis-milestone.md).

## Assembly model

- Session prompt text lives in **two modules**: the coordinator owns the four
  session prompts (discussion turn, closure proposal, closure vote, Dante
  narrator) built as a shared intro stack — sources, amendments,
  common-sense-check — plus a per-role stance and an output contract; the
  task adapter owns the production-effect prompt and the creation brief. The
  narrator has its own parallel stack with distinct wording. Same plain
  constant-concatenation style as the milestone path.
- **Seat prompts are thin pointers.** Almost all domain content reaches the
  models indirectly: the transcript (`chat.md`), which every in-session prompt
  (turns, closure, narrator) orders the seat to read end-to-end and whose
  Opening quotes the caller's request and brief, and the Sources block of file
  paths read from disk. The production-effect prompt is the exception — it
  inlines the caller request and the agreed target as JSON instead. Milestone-attached
  and standalone sessions share **one template set**; every difference between
  them lives in creation-time request payload (brief, references, amendments,
  source payload), not in templates.
- **Prompt text is composed before staffing is asked.** Staffing resolves per
  physical call at one shared execution seam (router path) or was frozen as
  pins at admission (static path). No template varies by family, model or
  effort.
- Every physical call's prompt is persisted as a trace file referenced from
  the activity ledger beside family/model/effort and the fallback marker — a
  complete per-call audit trail already exists.

## The prompt set

| Prompt | When | Notes |
| --- | --- | --- |
| discussion turn | each seat, each round | three hardcoded role stances (Initial Position ownership, Contrary Position adversarial burden, common-sense anti-drift questions) |
| closure proposal | lead, after each complete round | proposal is the lead's accept vote; closing-account completeness doctrine |
| closure vote | each contrary seat | accept/object only, no rationale |
| Dante narrator | external common-sense seat | separate persona stack; never votes |
| production effect | lead, after agreed closure | replays the full frozen caller request as JSON; contract-shielding clause |
| repair retry | once per exchange on contract failure | original prompt + repair suffix, shared with the milestone path |

Creation **briefs** are inputs, not templates: the task session brief, the two
milestone rethink briefs (design amendment vs source proposal), the guarantee
calibration brief, and the milestone production brief (built by the milestone
prompt module and frozen into the task order — the only bridge between the two
prompt sets). They reach seats through the transcript Opening, and the task
order's brief and context reach the lead a second time inside the
production-effect replay.

One staffed call sits outside this set: the **failure classifier**, whose
prompt lives in the shared error-classification module, bypasses the common
execution seam, and resolves the document's classify seat with the round
pinned to one. It still records its own activity with staffing and prompt
trace.

## What varies today (axes that change text)

Role stance, round number, accepted-revision presence and authority label,
target existence, execution-context roots, amendments/references presence, and
paths. Everything else — which discussion this is, whose goal, what subject —
varies through the **request payload**, not the templates.

## Where subject matter is hardcoded

The in-session path is **already domain-neutral**: no test, git, compile or
code-review vocabulary anywhere in turns, closure, narrator or transcript.
Coding assumptions enter only through the milestone-side production brief
(focused tests, full-suite boundary, skeleton/slice vocabulary) and whatever a
caller writes into its request. The severity/damage doctrine (affected
parties, realistic damage, proportionality, escalation evidence) is hardcoded
in neutral language in four places: the shared common-sense-check block that
every in-session prompt carries (its fullest statement), the Contrary Position
stance (fragments of it), the closure summary field set, and the transcript
closing labels.

## Material awareness today

The task's material rides the staffing binding only — fixed per seat resolver
while session and document stay live — and **never enters any prompt text**.

## Routing observations

- The **templates-vs-briefs split is the routing surface**: "which discussion
  is this" is a creation-time payload question. A prompt router could route
  brief content by material without touching the session templates at all —
  and conversely, template routing would be a genuinely new axis, since no
  text varies by staffing today.
- One shared execution seam dispatches every session prompt, and each call
  already persists its prompt beside its staffing record — routing here would
  be observable for free.
- Prompt **delivery** differs by staffing path even though the text does not:
  static-pinned seats receive each prompt as a continuation into one durable
  provider session, while router-backed seats get a fresh, self-contained call
  every time. A router changing text mid-discussion lands on accumulated
  provider context on one path and on clean calls on the other.
- **Round** is the only per-call consumer fact that reaches both the prompt
  (trivially, a number) and staffing (materially, via step-up rules).
- Latent wart: the narrator prompt is built before the action-kind branch and
  refuses closure votes; harmless today only because the narrator seat never
  votes. A router inserted at that seam inherits the ordering.
