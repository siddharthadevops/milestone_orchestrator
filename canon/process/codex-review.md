# Codex Review Canon

Status: common canon

Codex CLI and Claude CLI are the normal review families. Codex is one half of
the double final seal, and Claude CLI is the required non-Codex half when Codex
is the worker/orchestrator. Each run must be fresh, stateless, review-only, and
saved as evidence under the consuming project's git-ignored
`implementation/review-work/` directory.

## Invocation

All Codex and Claude reviews, seals, and disagreement dialogues must run through
CLI invocations.

Default Codex CLI runner:

```bash
codex exec --dangerously-bypass-approvals-and-sandbox \
  --output-last-message /path/to/last-message.txt \
  - < /path/to/review-prompt.txt
```

Default Claude CLI runner:

```bash
claude -p --model opus --effort max --permission-mode bypassPermissions \
  < /path/to/review-prompt.txt > /path/to/last-message.txt
```

Broad CLI access is review-only. Every broad review prompt must say that the
reviewer must not edit, create, delete, move, format, write files, or otherwise
modify the workspace. If a reviewer believes a file should change, it reports a
finding instead of changing it.

Local constraints still bind broad review access. Sensitive Local Exclusions in
local context must be honored, and stricter local process deviations win over
this common broad default.

Review prompts do not need to enumerate every possible directory. Reviewers may
inspect sibling repositories or dependency checkouts only when they are relevant
to the artifact and discovered while tracing that artifact.

Review prompts must include a local-inspection rule: local checkout is the source of truth for content inspection when it contains the reviewed content.
Use local search and file-reading tools for speed. Git is used for scope, diff comparison, relevant history, and commits/refs verification.

## Worktree Check

Every broad Codex or Claude review run must compare worktree state before and
after the run. If tracked or untracked non-ignored files change, the output is
invalid and does not count as review or seal evidence.

Use a snapshot that covers dirty tracked state, staged changes, and untracked
non-ignored files, including content hashes for pre-existing untracked files:

```bash
snapshot_worktree() {
  git status --porcelain=v1
  git diff --no-ext-diff --binary
  git diff --cached --no-ext-diff --binary
  git ls-files --others --exclude-standard | while IFS= read -r f; do
    [ -f "$f" ] && shasum -a 256 "$f"
  done
}
```

Capture `PRE_STATE` immediately before the review command and `POST_STATE`
immediately after it exits. Append this marker to the saved output when they
differ:

```text
INVALID: worktree changed during review; discard this output and inspect git status/diff
```

The same worktree before/after invalidation applies to Claude CLI review runs.

Seal usable-output requirements:

- Codex seal: `EXIT=0`, `VERDICT:`, finding-count consistency, no worktree invalidation marker, unchanged artifact.
- Claude CLI seal: `EXIT=0`, `VERDICT:`, finding-count consistency, no worktree invalidation marker, unchanged artifact.
- authorized fallback: `EXIT=0`, `VERDICT:`, count consistency, no worktree invalidation marker, unchanged artifact.

## Review/Seal Convergence

The full official verification suite is the current verification command set
recorded in local state for the project and active slice.

For each reviewed artifact, after the approved change is applied:

1. Run local/focused checks after each modification when they are cheap or
   directly relevant.
2. Run the full official verification suite before normal review starts.
3. Run normal Codex CLI review rounds until Codex returns `VERDICT: 0`.
4. Record the normal Codex clean state in the durable review log.
5. Run normal Claude CLI review rounds until Claude returns `VERDICT: 0`.
6. Record the normal Claude clean state in the durable review log.
7. Run the full official verification suite again.
8. Run full seal rounds until clean.

A clean-state entry must include the reviewer family, run id or output path,
`EXIT=0`, `VERDICT: 0`, and the reviewed artifact or ref. The seal phase is not
open until the durable log records normal Codex clean followed by normal Claude
clean for the current artifact phase.

Fixes are batched by review round without changing the triage outcomes in the
common process. For findings triaged as fixed from one round, correct them in
one whole-artifact pass before relaunching that reviewer; do not relaunch a
reviewer per finding.

Before relaunching any reviewer after a fix pass, self-review the pending
uncommitted diff for finding coverage, phase-rule compliance, and stale
surrounding surfaces such as work logs, review logs, statuses, and acceptance
criteria. Corrections fold into the same pass.

The self-review is orchestration, not review: it is not a round, produces no
findings or `VERDICT:` evidence, and cannot substitute for reviewer
convergence. Record only one line inside the round's existing fix entry:
`self-review of pending diff: clean` or `self-review of pending diff: N
corrections folded in`.

After normal Claude review begins, do not return to normal Codex rounds for
Claude-driven fixes in the same phase. Fix valid Claude findings and continue
Claude rounds until `VERDICT: 0`; the final post-Claude artifact is next checked
by the Codex seal half. Reopen normal Codex review only if the operator
explicitly resets the phase or the fix substantially changes scope or design
before seal.

A full seal round means the Codex seal half and Claude CLI seal half review the
same unchanged artifact with the same prompt, under the no-peek independence
rules below.

If a seal round finds a valid issue, verify it against local files, diffs,
tests, or commands; fix it; run relevant local/focused checks; then repeat the
full seal round only. Do not return to normal review rounds after a seal
finding unless the fix substantially changes scope or design.

In documentation phases, reducing over-specified mechanism to its unchanged
contract is not a substantial scope or design change.

If the full official verification suite after normal review fails, fix it and
restart from the pre-review full verification step.

## Watchdog

macOS does not provide `timeout` by default, so run Codex reviews with a
watchdog and the worktree check. This 480-second watchdog is Codex-only; the
480-second watchdog does not apply to Claude CLI review or seal runs. Claude
CLI review and seal runs must allow at least 30 minutes before silence or
normal long runtime can be classified as unavailable.

```bash
OUT=implementation/review-work/<milestone>/<name>.md
mkdir -p "$(dirname "$OUT")"
RAW=$(mktemp); LAST=$(mktemp); PRE_STATE=$(mktemp); POST_STATE=$(mktemp)
snapshot_worktree > "$PRE_STATE"
codex exec --dangerously-bypass-approvals-and-sandbox \
  --output-last-message "$LAST" - < prompt.txt > "$RAW" 2>&1 &
CPID=$!
( sleep 480; pkill -9 -P "$CPID" 2>/dev/null; kill -9 "$CPID" 2>/dev/null ) &
WPID=$!
wait $CPID; STATUS=$?
kill $WPID 2>/dev/null; pkill -P "$WPID" 2>/dev/null
snapshot_worktree > "$POST_STATE"
awk '/^([0-9]+\. )?F[0-9]+ \[P[0-3]\]/{p=1} p{print} /^VERDICT:/{exit}' "$LAST" > "$OUT"
grep -q '^VERDICT:' "$OUT" || grep -m1 '^VERDICT:' "$LAST" >> "$OUT"
echo "EXIT=$STATUS" >> "$OUT"
if ! cmp -s "$PRE_STATE" "$POST_STATE"; then
  echo "INVALID: worktree changed during review; discard this output and inspect git status/diff" | tee -a "$OUT" >&2
fi
N=$(grep -oE 'VERDICT: [0-9]+' "$OUT" | grep -oE '[0-9]+' | head -1)
M=$(grep -cE '^([0-9]+\. )?F[0-9]+ \[P[0-3]\]' "$OUT")
{ ! grep -q '^VERDICT:' "$OUT" || [ "${N:-0}" != "${M:-0}" ]; } && \
  echo "INCOMPLETE: missing VERDICT or count mismatch (verdict ${N:-0}, captured $M)" | tee -a "$OUT" >&2
rm -f "$RAW" "$LAST" "$PRE_STATE" "$POST_STATE"
```

Disagreement dialogue sessions use the same launch/watch pattern but save the
whole last message plus `EXIT=`, with no `VERDICT:` parsing. Their prompts must
include the disputed finding or doubt, the orchestrator's proposed resolution,
and the files, diffs, tests, or commands already checked.

Use one continuous CLI dialogue session with the opposite LLM family for a
conceptual disagreement or doubt: Codex uses Claude CLI, and Claude uses Codex
CLI. Do not start separate consultations per review round for the same issue.
Run at most two dialogue rounds, stopping earlier if agreement is clear. If the
issue remains unresolved or the opposite CLI family is unavailable, stop and
consult the operator.

## Quota And Rate Limits

If a review CLI exits or refuses to start because of quota or rate limits and
prints a concrete resume time, record the condition and resume time in the
durable review log or work log, wait until that time, then rerun the same
review or continue from the recorded local state. This is a pause, not a
milestone blockage.

If the CLI gives no concrete resume time, treat it as reviewer unavailability
under the normal review or seal rules.

## Seal Independence

Run the double seal as two independent reviews on the same unchanged artifact.
Codex is the mandatory Codex seal half. Claude CLI is the required non-Codex
seal half when Codex is the worker/orchestrator. The non-Codex seal half must
run in a fresh independent context, not the thread or agent that drafted or
implemented the artifact. Give both halves the same review prompt; do not show
either reviewer the other output before both have completed.

Launch both seal halves concurrently when both required reviewers are available
and the runner can preserve no-peek independence. When a seal is not concurrent,
record the reason in the durable review log. Sequential seal launch still must
use the same unchanged artifact, same prompt, and no shared outputs until both
halves complete.

When Codex is the worker/orchestrator, run the required non-Codex half through
Claude CLI:

```bash
claude -p --model opus --effort max --permission-mode bypassPermissions \
  < /path/to/review-prompt.txt > /path/to/last-message.txt
```

Record the Claude CLI reviewer, model/settings, command surface, result, and
`EXIT=` in the durable review log. Do not use `--safe-mode`, `--tools ''`, or
`--permission-mode plan` for Claude seal runs.

If the required Claude CLI seal half is unavailable, do not silently fall back.
The seal remains incomplete unless the operator explicitly authorizes a fallback
for that seal attempt. Any authorized fallback must be an independent non-Codex
reviewer whose base model family differs from the mandatory Codex seal half.
Authorized fallback model independence is base-family independence;
settings-only differences are insufficient. An OpenAI/GPT-family reviewer
cannot replace the required non-Codex seal half for a Codex-orchestrated seal.

Record these fallback fields for every fallback attempt:

- fallback reviewer.
- fallback model/settings.
- fallback command surface.
- fallback reason.
- fallback operator authorization.
- fallback result.

Fallback output must meet the usable-output requirements above.

## Prompt Shape

Keep prompts thin. Include:

- the artifact under review.
- the phase: skeleton, slice documentation, implementation, or process-doc.
- the canonical references the artifact depends on.
- the reuse gate.
- the local context constraints relevant to the review, including any support
  order or platform preference when the artifact proposes new machinery.
- any named brainstorming or named `_drafts` material as non-canonical context,
  checking that the reviewed artifact explicitly records the relevant
  **Adopt / Revise / Reject** decision instead of approving linked material.
- for process-doc work, review planning-material mechanism and link wording for
  brainstorming and `_drafts`; do not review product or architecture content
  unless the operator names that content as the review artifact.
- the severity rubric.
- for skeleton, slice documentation, and process-doc phases only: the
  altitude check in both directions — under-specified observable contracts
  and over-specified mechanism (control flow in prose) are both findings;
  over-specified mechanism is `P3` by default and `P2` when acceptance
  criteria or tests anchor to mechanism instead of observable behavior.
- the no-edit instruction.
- the rule that reviewer findings are claims, not facts.
- the rule that the orchestrator must verify findings against files, diffs,
  tests, or commands before triage.
- the rule that memory or chat is not evidence for triage.
- the rule that the local filesystem checkout is the source of truth for
  content inspection when available, local search and file-reading tools are
  preferred for speed, and Git is used for scope, diff comparison, relevant
  history, and commit/ref verification.
- this exact reviewer exhaustiveness sentence for all review phases: "Do not stop at the first finding: report every defect you can verify in a complete pass of the artifact and the code it cites. An exhaustive pass with zero findings is a valid outcome."
- the rule that doubts and disagreements use one continuous CLI dialogue session
  with the opposite LLM family when available.
- the rule that unresolved disagreement, or unavailable opposite-family CLI
  dialogue, stops and asks the operator.
- the rule that quota or rate-limit pauses with a concrete resume time should
  be recorded, waited out, and resumed rather than treated as milestone
  blockage.
- instructions to ignore prior review outputs, review logs, closures, and work
  log findings.
- output format.

Required output format:

```text
F01 [P1] path/to/file.md#Section - Finding text.
F02 [P2] path/to/file.md#Section - Finding text.
VERDICT: 2 findings
```

## Egress

The rule is simple: review CLIs send read material to external services. This
includes `codex exec` and Claude CLI review commands.

Reviewers must honor local Sensitive Local Exclusions and avoid
unrelated personal material.
Never send secrets, credentials, tokens, private keys, raw PII, or
raw sensitive operational data.
Also, operator confirmation does not override those never-send categories. If
review appears to require other sensitive material, stop for operator
confirmation or use redacted non-sensitive excerpts.

## Saving Output

Scratch evidence lives under:

```text
implementation/review-work/<milestone>/
implementation/review-work/process/
```

Durable evidence lives in tracked local state:

- milestone review output is summarized compactly in the milestone's
  `review-log.md`.
- process-doc review output is summarized compactly in
  `implementation/process/review-log.md`.
- slice debt is recorded in the closure.
- skeleton or process-doc debt is recorded in the relevant review log.

Scratch evidence is regenerable and should not be committed. `review-work/`
must not hold durable architecture material or guide material.
