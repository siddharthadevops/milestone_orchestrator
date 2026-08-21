# Brainstorming is a task: one ordering path, no standalone Brainstorming system

Status: non-canonical brainstorming — operator-driven need (2026-08-18).
Queued after the staffing-router milestone.

## Need

Today a Brainstorming session can be born three ways: ordered as a task
(standalone or as a slice producer), opened by the driver "attached" without a
task (guarantee calibration, `need_rethink`), or ordered from the panel's own
Brainstorming form and `POST /api/brainstorming/sessions`. All three land in
the same session store, but only the first is a task: the other two have no
task record, no task accounting, and no place in a task list. The panel shows
one list of sessions and another of tasks, and the same discussion may appear
in both or in neither. Two ordering surfaces for one kind of work is one too
many.

The tasks goal already states the shape: a TaskExecutor may run "a whole
subordinate process"; its internal calls "remain inspectable evidence, but
they do not become extra tasks". Brainstorming is that executor. What is
surplus is the second front door, not the engine.

## Obligation

- **Every Brainstorming session is owned by a task.** No path opens a session
  without first admitting a task whose executor is Brainstorming: slice
  production (already), guarantee calibration and `need_rethink` (today
  attached), and any direct order. The task is the receipt and the account;
  the session is the executor's own record.
- **The standalone Brainstorming ordering surface is retired**: the panel's
  Brainstorming form and the public create route stop being a way to order
  work. Ordering goes through the task order — panel or API — with executor
  `brainstorming` and its `max_rounds` / `closure_policy`.
- **The engine and its controls stay, as executor internals**: sessions,
  turns, ballots, the KV records under `brainstorming/…`, the transcript, the
  floor and external interventions, the view. They are how one watches and
  talks to a running Brainstorming task; a task of that executor opens to its
  session.
- **One list**: the panel lists tasks (per project, per run, standalone), each
  Brainstorming task openable to its chat. No separate session list is needed
  for ordering or overview.
- Existing sessions and closed runs are history; nothing is rewritten.

## Not in scope

- The staffing of seats (the router decides that).
- Any change to how a session discusses, votes, or applies its agreement.

## Companions queued alongside (small, separate)

- Producer override as an operator note (side file read at admission, like
  `acts.json`), replacing the state-lock write that returns
  `task_update_busy` during any long call.
- Dante's exit rule hardened: when the positions' last turns agree, or no
  question would change what is built, "No further questions" — at most two
  questions per turn, only on what the last round disputed.
- Executor choice for the skeleton unit (worker vs Brainstorming), through the
  same producer channel, once the skeleton producer's structured plan
  hand-off is settled.

## Queued behind it (operator, 2026-08-20)

- **Question redesign**: rethink admission and design discussions pay the
  damage battery before opening (who is the victim, what observable damage);
  no victim → the worker takes the conservative reading, records it in the
  note, and continues. Scope to be defined by the operator after the
  staffing-router milestone.
