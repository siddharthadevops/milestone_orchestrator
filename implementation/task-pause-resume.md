# Task Pause / Resume

Operator-directed implementation, 2026-09-06. This extends the ordinary task
lifecycle; it does not introduce a scheduler, a new task executor, or an
independent process for each task.

## Contract

The standalone `agent_call`, `reviewed_task`, and `deep_task` executors and
the children admitted by a standalone deep task share durable Pause / Resume.
An operational failure is a recoverable pause, not a terminal task result.
Manual Pause is cooperative: the current action may complete, then no next
action begins. The panel shows `pausing` until that safe boundary is reached.
There is no automatic retry after a failed physical call in this host.

The canonical task identity, order, parent relation, completed work and terminal
result shape are unchanged. Open paused tasks retain `result: null`. The
existing task-store document carries revisioned control state and append-only
pause/resume/attempt history. API and panel share this state; no browser-only
flag controls execution.

Resume must name the current paused revision. It continues the same family and
the same reviewed unit using the existing failed-from state and Git-gate
recovery. It renews the existing convergence budgets through ordinary explicit
run recovery, not by rewriting old reviews. Completed documentation, parts,
WIP/gate commits and direct-call results are not repeated. Failed direct-call
accounting and retained completions are counted once.

Pause and Resume applied to a deep child operate on its enclosing task family.
An attached discussion cannot bypass that pause through its own Start or
Continue endpoints. Resume the owning task first; a discussion stopped by its
owner resumes under the same session identity. Exhausted-round waits retain
their own explicit Continue/Add rounds contract.
Cancel is different: the existing Stop endpoint terminalizes the family and
settles attached discussions. A durable Cancel also settles after restart;
it cannot silently turn into another resumable failure. Historical successes,
failures and cancellations are not reopened or rewritten.

## Physical execution safety

A task execution lease is acquired before loading/recovering a reviewed
Driver, because that constructor can restore Git state. Both worker transports
inherit the lease descriptor. A write-ahead dispatch journal records the worker
process group, covering workers that close unknown descriptors and descendants
that outlive their leader. Releasing the host descriptor never unlocks a
surviving worker's copy. Resume does not kill a surviving worker.

After a backend restart, interrupted ordinary tasks require an explicit Resume.
They remain `pausing` while physical work survives or its quiescence is unknown,
then become `paused`. Repeated adoption preserves the control intent and never
dispatches another worker.
An independently running owned discussion is first stopped through its native
lifecycle. The task family remains `pausing` until both the discussion process
and its retained provider-attempt evidence confirm quiescence. This applies to
error pauses, restart adoption, and sessions created before their attachment
was saved, including Brainstorming producers. Interrupted adoption uses a
control-only host thread: it retries Stop/inspection, never loads a Driver,
restores Git or repeats a provider call. Unknown quiescence blocks Resume and
workspace release, even if Cancel wins during that wait. The panel keeps live
indicators active until pausing actually finishes.
Resume and ordinary deep successor handoffs fence every prior family member,
including terminal children with retained execution evidence. Resume refuses
while any member remains active or its physical quiescence is unknown.
The task-owned transport also holds results and exceptions before post-call
callbacks or Driver delivery until worker quiescence is positive; even Cancel
cannot bypass that check. This prevents same-action Git restoration or a WIP
commit from racing a surviving worker. Paused work retains its reservation; another
task cannot overwrite it. Even terminal records with uncertain surviving work
retain that reservation and cannot be deleted to bypass it.

Legacy in-flight markers without worker-tracking evidence, malformed execution
markers, and a crash before a spawned worker's identity was recorded fail
closed with an explicit blocked reason. They require establishing quiescence;
absence of a new journal is not proof that an old worker died. Unrelated work
areas remain usable, including when a paused task's directory has disappeared.
Cancel can settle retained accounting without reopening or recreating that
directory. A completed direct-call marker is imported once before publishing
Cancel after a crash; reviewed cancellation imports its retained marker without
ordinary Driver startup or workspace restoration.
Resume imports a completed direct-call marker before returning to `running`,
including after a transient failure to publish the original result/attempt.
Definite ambient `Popen` argument/environment validation errors clear the
pre-spawn journal; opaque factories that may already have spawned remain
fail-closed.

The execution lease and reviewed recovery are independent of HTTP and remain
reusable when tasks later receive their own processes. Milestone-owned tasks
continue to use their existing run controls and recovery semantics; this change
does not replace the milestone driver or its historical terminal-successor
rules.

## Verification

The focused regressions exercise real Git, HTTP task controls, executed panel
JavaScript, and real subprocess survival after killing a deep-task coordinator.
They cover manual/error pauses, same-child recovery, landed-gate adoption,
retained successful calls, exactly-once attempt accounting, stale/concurrent
Resume, Cancel races, failed Resume rollback, legacy/corrupt markers, process
group quiescence, work-area exclusion and authorization.

Pre-review verification (`ORCH_REAL_LLM` unset; disposable repositories/services only):

- `python3 -m unittest orchestrator.tests.suite_checkpoint`: 1,491 tests,
  317.606 seconds, OK; two filesystem case-sensitivity skips. The final
  checkpoint included the initial 70 control/recovery/execution/panel regressions.
- The reviewed/deep compatibility modules plus the then-current recovery
  regressions passed 59 tests in 187.983 seconds. The final expanded recovery
  module passed all 17 cases in 33.735 seconds; the three existing wait/guard
  cases affected by discussion restart also passed on the final implementation.
- Both real worker transports and their unchanged runner contracts passed
  214 runner tests. The final execution-fence module separately passed 22
  tests, including killing a real deep-task coordinator during a surviving fix.
- Public controls, the existing public-task API, and the reviewed-producer
  waiting contract passed 72 tests in 77.901 seconds after the owner-discussion
  bypass correction. Panel behavior is covered by executed JavaScript, not
  only string assertions.
- The additional service-project and worker-adapter checks passed 127 cases.
  The accompanying conformance wrappers exposed two obsolete terminal-failure
  assertions; those are adjusted to require a paused error with retained native
  evidence and exact task cardinality, not to relax success acceptance. The
  final `test_task_conformance` rerun passed all seven wrappers in 140.270
  seconds; the worker-adapter tests were not changed.
- Python compilation, panel JavaScript syntax, `git diff --check`, and the
  explicit suite inventory passed. The retained partition is 1,491 checkpoint
  plus 952 extended cases (2,443 total).

The full extended suite was not rerun, and no full-release gate is claimed.
No production service restart, source-checkout synchronization or remote push
is included in this implementation request.

### Independent-review corrections

The five findings from the console Codex review (`gpt-5.6-sol`, `xhigh`) are
addressed: failure/restart discussion quiescence, completed-marker accounting
on Cancel, cancellation without the workspace, and live pausing indicators.
The follow-up adds 22 regressions: 12 discussion-quiescence cases, eight Cancel
recovery cases, and two executed-panel-JavaScript cases. Cross-checking also
covered producer sessions created before attachment and Cancel during unknown
discussion quiescence. The existing rethink crash compatibility fixture now
uses a real durable session, rather than an unregistered synthetic ID, so it
can prove a safe recovery boundary without bypassing the new check.

Final post-correction verification (`ORCH_REAL_LLM` unset):

- `python3 -m unittest orchestrator.tests.suite_checkpoint`: 1,513 tests in
  350.525 seconds, OK, with the two filesystem case-sensitivity skips. This
  includes all 92 new control/recovery/execution/panel regressions.
- `test_deep_task_documentation`, `test_deep_task_implementation`, and
  `test_reviewed_task_api`: 43 tests in 152.118 seconds, OK.
- The 12 discussion-quiescence regressions separately passed in 13.174 seconds;
  the eight cancellation regressions and existing control/recovery cases also
  passed their focused runs. No real provider was dispatched by these tests.
- Python compilation, full panel JavaScript parsing, `git diff --check`, and
  the explicit inventory passed: 1,513 checkpoint plus 952 extended tests,
  2,465 retained in total. The complete extended suite remains unrun.

Only the `impl` checkout was changed. No commit, push or service restart was
performed; the source checkout remains clean at `678b1953e08ed41bcbdd399851530f8bd7fe4e09`.

### Second independent-review follow-up

The next console review found four additional issues. The corrections fence
terminal family members on Resume and normal successor handoffs, import
completed direct-call evidence before Resume, preserve `pausing` until physical
quiescence, and release definite ambient pre-spawn validation failures without
trusting ambiguous custom factories.

Cross-checking this correction also identified same-action repository work
after an uncertain cleanup. The existing execution lease now holds transport
outcomes before post-call completion callbacks and Driver delivery. The host
marks the wait durably and retains the original outcome; no additional provider
is dispatched. Cancel still waits for positive physical quiescence. Owned
lease inspections are serialized with reservation release so startup cannot
inspect a descriptor while Resume closes it.

There are 25 additional regressions: eight pre-spawn validation cases, seven
family/worker-quiescence and reservation cases, four completed-call Resume
accounting cases, and six physical-result delivery cases. All use disposable
fixtures; the process tests exercise both transports without real providers.
The legacy and crash-recovery assertions now require `pausing` while evidence
is unknown and a fresh paused revision after quiescence is established.

### Static-review follow-up and verification order

The third independent console review found two remaining issues: deep terminal
children also require their discussion-quiescence fence at normal handoffs and
Cancel, and completed direct-call markers from the earlier accounting-only
format must preserve their charge on Resume and Cancel.

Deep boundaries now check independently owned discussions throughout the
family, including historical sessions without a current attachment. Cancel
stops and inspects those sessions without reopening terminal children or
importing their accounting again. Missing-session cancellation checks retained
provider-attempt evidence before removing the obsolete attachment, preserving
the existing discarded-session ledger and cancellation behavior.
For already-terminal legacy children, an explicitly recorded missing-session
detach is honored only after confirming the registry entry is absent and its
retained provider attempts are quiet; neither the child nor its ledger is
rewritten.

The legacy marker import uses the existing `call_id` receipt deduplication.
Because the earlier format retained no outcome, its accounting becomes a
failure receipt with an explicit explanation, never an invented reusable
success. A malformed modern `result` is not reinterpreted as legacy data.

Per the user's verification order, all subsequent reviews are static only and
the reviewer is explicitly forbidden to run tests or executable reproductions.
The last in-flight checkpoint was interrupted; it is not a passing result.
New regressions are written but remain unexecuted until the independent review
returns CLEAN. The earlier results above are historical evidence, not a claim
that this latest revision has passed its final verification.

The fourth static review identified a durable-Cancel liveness gap after a
restart: a surviving lease could reject cancellation startup without leaving
an automatic settlement owner. Adoption now reuses the existing control-only
settlement thread for that wait, including a lease race at its final handoff.
Deep cancellation likewise retries transient child-control/adoption conflicts
inside its existing loop. It does not retry provider work, bypass quiescence,
or require a second Cancel when the surviving worker finally exits.

The fifth independent static review returned CLEAN; only then were the final
tests started. The selected extended compatibility checks passed all 102
cases. The fail-fast checkpoint exposed a retained-discussion path mismatch
and stopped after 1,124 cases; that run failed and is not completion evidence.
Retained relative targets now use the existing workspace-relative resolver,
including the Cancel caller, without accessing or recreating the workspace.
This correction returns to static review before any further test execution.

### Final accepted verification (2026-09-06)

The console Codex reviewer (`gpt-5.6-sol`, `xhigh`, read-only) returned CLEAN
for the retained-target correction and adjusted immutable-state fixtures.
A subsequent focused run passed all 24 Cancel/family cases and exposed only
a test assertion that counted a control transition without an `attempt` as an
additional accounting receipt. The test now counts actual receipts, retaining
exact accounting and native-result assertions. That test-only adjustment also
received an independent static CLEAN before tests resumed; production was
unchanged. Every reviewer was explicitly forbidden to execute tests.

Final evidence, all with `ORCH_REAL_LLM` unset:

- `python3 -m unittest -f orchestrator.tests.suite_checkpoint`: **1,554 tests
  in 384.449 seconds, OK**, with two existing filesystem case-sensitivity skips.
- `python3 -m unittest -f orchestrator.tests.test_reviewed_task_api`: **24 tests
  in 79.921 seconds, OK** on the final production revision.
- The remaining completed-call accounting and retained-target regressions:
  **11 tests in 5.654 seconds, OK**, after their latest static CLEAN. These and
  all 24 Cancel/family regressions are included in the final checkpoint above.
- Full panel JavaScript syntax and `git diff --check`: **OK**. Checksums of
  every pending file matched the CLEAN-reviewed snapshot through the final
  test run; only this evidence note was appended afterward.

The earlier 102-case compatibility selection passed before the small retained
target-path correction. Its directly affected reviewed-task module was rerun
above; the complete extended suite was not run. The final retained inventory
is 1,554 checkpoint plus 952 extended cases (2,506 total).

Only `impl` was changed. No commit, push, production service restart, or source
checkout synchronization was performed. The source checkout remains clean at
`678b1953e08ed41bcbdd399851530f8bd7fe4e09`.
