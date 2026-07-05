# Review Log

Durable review record for S9.

## Skeleton

- `2026-07-04` - Opened S9 skeleton for planned reviewed release `v0.10.0`;
  review pending.
- Pre-review verification: `git diff --check` passed.
- Normal Codex clean state: skeleton review r1 returned `VERDICT: 0
  findings`, `EXIT=0`
  (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-codex-r1.md`);
  reviewed artifact: S9 skeleton README plus registry and roadmap
  bookkeeping, uncommitted worktree state.
- Claude skeleton review r1 returned two findings (`VERDICT: 2 findings`,
  `EXIT=0`). Fixed:
  - `F01 [P3]` - Reuse Posture listed fresh-agent self-review as new
    machinery without stating why it is necessary under the Reuse Gate
    (verified against `canon/process/README.md`). Reuse Posture now states
    the same-thread false-negative rationale.
  - `F02 [P3]` - Boundary framed the watchdog change as review-fix
    convergence even though the watchdog is a runtime rule and the roadmap
    frames S9 as runtime plus pre-relaunch self-review hardening (verified
    against `canon/process/codex-review.md` and `implementation/roadmap.md`).
    Boundary now separates runtime from post-fix preflight discipline.
  - self-review of pending diff: 1 correction folded in.
- Claude skeleton review r2 returned one finding (`VERDICT: 1 findings`,
  `EXIT=0`). Fixed:
  - `F01 [P3]` - The Claude r1 self-review line was indented under the F02
    finding, making the round-level pre-relaunch self-review look like part
    of F02 only (verified against S8 review-log convention and the common
    self-review record rule). The self-review line now sits as a sibling
    bullet for the round's fix entry.
  - self-review of pending diff: 1 correction folded in.
- Claude skeleton review r3 returned one finding (`VERDICT: 1 findings`,
  `EXIT=0`). Fixed:
  - `F01 [P3]` - The Work Log said Claude r3 was due after preflight even
    though the r2 fix entry already recorded that preflight, making durable
    state ambiguous about whether the preflight had run (verified against
    the Work Log and review-log sequence). Work Log now records Claude r3
    fixed without describing preflight as pending.
  - self-review of pending diff: clean.
- Claude skeleton review r4 returned one finding (`VERDICT: 1 findings`,
  `EXIT=0`). Fixed:
  - `F01 [P3]` - The Work Log repeated the same preflight-pending ambiguity
    by saying Claude r4 was due after preflight while the r3 fix entry had
    already recorded self-review clean (verified against the Work Log and
    review-log sequence). Work Log now records the Claude finding as fixed
    and says only that the Claude rerun is due.
  - self-review of pending diff: clean.
- Normal Claude clean state: skeleton review r5 returned `VERDICT: 0
  findings`, `EXIT=0`
  (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-claude-r5.md`);
  reviewed artifact: S9 skeleton README plus registry and roadmap
  bookkeeping, uncommitted worktree state after r1-r4 fixes.
- Post-review verification: `git diff --check` passed.
- Skeleton seal attempt a1 (concurrent Codex + Claude CLI, same prompt, no
  shared outputs) did not pass:
  - Codex a1 (Codex CLI reviewer; default `codex exec` model/settings;
    Codex CLI runner command surface with 900-second watchdog, later found
    non-canon before S9 release and not used as passing seal evidence) returned
    `VERDICT: 0 findings`, `EXIT=0`, no worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a1-codex.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after post-review
    verification.
  - Claude CLI a1 (Claude CLI reviewer; model `opus`, `--effort max`,
    `--permission-mode bypassPermissions`; canon Claude CLI runner command
    surface) returned one finding (`VERDICT: 1 findings`, `EXIT=0`), no
    worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a1-claude.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after post-review
    verification.
    - `F01 [P3]` - The global milestone index still recorded S9 as
      `Active (skeleton draft)` while the milestone README and Work Log had
      advanced to skeleton seal (verified against both files). Fixed by
      updating the registry status to `Active (skeleton under seal)`.
  - self-review of pending diff: clean.
- Skeleton seal attempt a2 (concurrent Codex + Claude CLI, same prompt, no
  shared outputs) did not pass:
  - Codex a2 (Codex CLI reviewer; default `codex exec` model/settings;
    Codex CLI runner command surface with 900-second watchdog, later found
    non-canon before S9 release and not used as passing seal evidence) returned
    one finding (`VERDICT: 1 findings`, `EXIT=0`), no worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a2-codex.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a1 fix.
    - `F01 [P3]` - The a1 seal record omitted required seal-half evidence
      fields for model/settings, command surface, run path, reviewed
      artifact/ref, and worktree invalidation status (verified against the
      review-log template and a1 outputs). Fixed by completing both a1 seal
      half records.
  - Claude CLI a2 (Claude CLI reviewer; model `opus`, `--effort max`,
    `--permission-mode bypassPermissions`; canon Claude CLI runner command
    surface) returned one finding (`VERDICT: 1 findings`, `EXIT=0`), no
    worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a2-claude.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a1 fix.
    - `F01 [P3]` - Same incomplete a1 seal evidence, especially missing
      Claude output path and worktree-invalidation status (verified against
      `implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a1-claude.md`
      and the review-log template). Fixed by completing both a1 seal half
      records.
  - self-review of pending diff: 1 correction folded in.
- Skeleton seal attempt a3 (concurrent Codex + Claude CLI, same prompt, no
  shared outputs) did not pass:
  - Codex a3 (Codex CLI reviewer; default `codex exec` model/settings;
    Codex CLI runner command surface with 900-second watchdog, later found
    non-canon before S9 release and not used as passing seal evidence) returned
    four findings (`VERDICT: 4 findings`, `EXIT=0`), no worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a3-codex.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a2 fix.
    - `F01 [P1]` - The a1/a2 Codex seal records presented a 900-second
      watchdog as the canon command surface even though the current reviewed
      canon remains 480 seconds until S9 is sealed and released (verified
      against `canon/process/codex-review.md`). Fixed by treating those
      failed attempts as non-passing evidence and requiring the next Codex
      seal rerun under the current 480-second watchdog.
    - `F02 [P2]` - Shared Contract said "Codex review runs" without
      clarifying scope across normal reviews, seal halves, and disagreement
      dialogues (verified against the Watchdog and dialogue rules). Shared
      Contract now names normal Codex review rounds and Codex seal halves,
      while leaving disagreement dialogues to their separate evidence rule.
    - `F03 [P2]` - Fresh-agent preflight did not state report-only/no-edit
      authority (verified against the new machinery wording). Shared
      Contract now calls the fresh agent report-only.
    - `F04 [P3]` - The a2 self-review line was nested under the Claude half
      instead of recording one fix-pass self-review for both a2 findings
      (verified against the a2 entry). The self-review line now sits as an
      attempt-level sibling.
  - Claude CLI a3 (Claude CLI reviewer; model `opus`, `--effort max`,
    `--permission-mode bypassPermissions`; canon Claude CLI runner command
    surface) returned one finding (`VERDICT: 1 findings`, `EXIT=0`), no
    worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a3-claude.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a2 fix.
    - `F01 [P3]` - Same non-canon 900-second watchdog wording in the a1/a2
      Codex seal records; current canon still specifies 480 seconds and no
      local deviation is active (verified against `canon/process/codex-review.md`
      and `implementation/process/codex-review.md`). Fixed by recording that
      the next seal rerun uses the current 480-second watchdog.
  - self-review of pending diff: clean.
- Skeleton seal attempt a4 (concurrent Codex + Claude CLI, same prompt, no
  shared outputs) did not pass:
  - Codex a4 (Codex CLI reviewer; default `codex exec` model/settings;
    current canon Codex CLI runner command surface with 480-second watchdog)
    returned one finding (`VERDICT: 1 findings`, `EXIT=0`), no worktree
    invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a4-codex.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a3 fix.
    - `F01 [P3]` - The a3 seal attempt omitted required seal-half
      bookkeeping for output path, reviewed artifact/ref, worktree
      invalidation status, and Codex model/settings/command surface (verified
      against the a3 outputs and review-log template). Fixed by completing
      both a3 seal half records.
  - Claude CLI a4 (Claude CLI reviewer; model `opus`, `--effort max`,
    `--permission-mode bypassPermissions`; canon Claude CLI runner command
    surface) returned one finding (`VERDICT: 1 findings`, `EXIT=0`), no
    worktree invalidation
    (`implementation/review-work/codex-timeout-and-agent-self-review/skeleton-seal-a4-claude.md`);
    reviewed artifact: S9 skeleton README plus registry, roadmap, and
    review-log bookkeeping, uncommitted worktree state after a3 fix.
    - `F01 [P3]` - The a1 self-review line remained nested under the Claude
      a1 half instead of recording one attempt-level pre-relaunch
      self-review (verified against a2/a3 convention and prior nesting
      fixes). Fixed by moving the a1 self-review line to attempt level.
  - self-review of pending diff: 1 correction folded in.
