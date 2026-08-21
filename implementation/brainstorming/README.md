# Brainstorming

Status: non-canonical planning

Product-neutral canon repository.

This directory is for tracked exploratory planning, not canon and not
implementation authority.

This directory may remain empty when there is no active planning material.

## Active goals

- [`brainstorming-orchestrator/goal.md`](brainstorming-orchestrator/goal.md) —
  generic standalone brainstorming process, initially integrated with
  milestone `need_rethink` routing and designed for later Agent99 capability
  adoption.
- [`model-profiles-and-strategy-configurator/goal.md`](model-profiles-and-strategy-configurator/goal.md)
  — named model profiles (kind of work + rigor) chosen when work is ordered
  and per slice inside a run, bound by a runtime document the operator edits
  live, and a configurator for the strategy the seed profiles hand-write today.
- [`milestone-tasks/goal.md`](milestone-tasks/goal.md) — milestones keep the
  law while each slice's content step becomes a self-described, pluggable
  task (worker call, general-purpose Brainstorming, future types),
  launchable from a milestone or standalone, typed at planning time under
  operator control.
- [`staffing-router/goal.md`](staffing-router/goal.md) — one router service
  decides agent, model, and effort for every call (milestone, Brainstorming,
  standalone, calling product) from owner-opened sessions: numeric families,
  per-family tuning, per-role assignment, materials as overrides, programmable
  rules; `worker` renamed to `agent_call`.
- [`brainstorming-is-a-task.md`](brainstorming-is-a-task.md) — every
  Brainstorming session is owned by a task; the standalone Brainstorming
  ordering surface (panel form, public create route) is retired and the
  engine stays as executor internals. Queued after staffing-router, with
  small companions (producer override as a note, Dante exit rule, skeleton
  executor choice).
