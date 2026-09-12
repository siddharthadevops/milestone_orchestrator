"""Execute the task control presenters, not only their source spelling."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TaskControlsPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (Path(__file__).resolve().parents[1] / "static" /
                     "panel.html").read_text(encoding="utf-8")
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node is required for executable panel checks")

    def javascript(self, checks, functions=()):
        names = (
            "taskWorkArea", "taskExecutor", "taskLifecycleActive",
            "taskStateClassName", "taskStaffingLine", "taskSessionId",
            "renderTaskPage", "taskState", "taskRow", "sidebarItems",
            "taskStatusClock", "deepTaskPipeline", "reviewedTaskPipeline",
            "taskControlHistory", "creativityProgress", "creativityProposals",
            "creativityResult", "taskPhysicalCalls", "esc", "fmtTokenCount",
            "fmtTokenUsage", "costReading", "costHtml", "tokenUsageHtml",
        ) + functions
        sources = []
        for name in names:
            match = re.search(
                r"(?:async )?function " + name + r"\([^\n]*\) \{.*?\n\}",
                self.panel, re.S,
            )
            self.assertIsNotNone(match, name)
            sources.append(match.group(0))
        setup = r"""
const assert = require('node:assert/strict');
const escJsSq = value => String(value).replaceAll("'", "\\'");
const requestTitle = esc;
const spinEl = () => '<spin/>';
const fmtAdmitted = value => value;
const fmtDHMS = value => String(value);
const liveClock = (completed, inFlight) => JSON.stringify({completed, inFlight});
const ICONS = {task: 'task', brainstorm: 'brainstorm', ellipsis: '...'};
let fullRequestText, lastBilling, lastWebBase;
let selectedTask = 'task-1', taskPageRunId = null;
let taskMenuOpen = false, taskDeleting = false, taskStopping = false;
let taskControlPending = null, taskStopNotice = '', lastTaskPageSession = null;
let lastTaskLifecycle = null;
const renderSlicePipeline = (_slice, units, _activity, _running, options) =>
  ({html: JSON.stringify({units, options})});
const pipelineCategoryRow = (label, _title, status) => label + ':' + status;
const pipelineUnitRow = (unit, _activity, running) =>
  JSON.stringify({status: unit.status, running});
function record(executor = 'agent_call') {
  return {id: 'task-1', order: {task_executor: executor,
    request: {request: 'A bounded task', work_area: {}, context: {}}},
    resolved_staffing: {}, result: null};
}
"""
        result = subprocess.run(
            [self.node, "-e", setup + "\n" + "\n".join(sources) + "\n" + checks],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_paused_types_render_resume_cancel_and_failure_without_spinner(self):
        self.javascript(r"""
for (const executor of ['agent_call', 'reviewed_task', 'deep_task', 'creativity']) {
  lastTaskLifecycle = {status: 'paused', revision: 7, source: 'error', history: [],
    reason: 'review quota <exhausted>', can_resume: true};
  const html = renderTaskPage(record(executor), 'today');
  assert(html.includes('>Resume</button>'));
  assert(html.includes('>Cancel task</button>'));
  assert(html.includes('Paused after a failure'));
  assert(html.includes('review quota &lt;exhausted&gt;'));
  assert(!html.includes('<spin/>'));
  assert(!html.includes('<h3>Result</h3>'));
  assert(!html.includes('>Pause</button>'));
}
""")

    def test_pausing_and_live_worker_block_do_not_offer_unsafe_resume(self):
        self.javascript(r"""
lastTaskLifecycle = {status: 'pausing', revision: 2, source: 'operator', history: [],
  reason: 'Please wait', can_resume: false};
for (const executor of ['agent_call', 'reviewed_task', 'deep_task', 'creativity']) {
  const html = renderTaskPage(record(executor), null);
  assert(html.includes('<spin/>'));
  assert(html.includes('Pausing safely'));
  assert(/<button class="btn" disabled\s+onclick="controlSelectedTask\('pause'\)">Pausing…/.test(html));
  assert(!html.includes('>Resume</button>'));
  assert(html.includes('>Cancel task</button>'));
}
lastTaskLifecycle = {status: 'paused', revision: 3, can_resume: false,
  blocked_reason: 'Previous worker is still alive'};
const html = renderTaskPage(record(), null);
assert(html.includes('Previous worker is still alive'));
assert(/<button class="btn primary" disabled\s+onclick="controlSelectedTask\('resume'\)">Resume/.test(html));
""")

    def test_running_and_terminal_controls_preserve_brainstorming_behavior(self):
        self.javascript(r"""
lastTaskLifecycle = {status: 'running', revision: 1, can_pause: true};
let html = renderTaskPage(record(), null);
assert(html.includes('>Pause</button>'));
assert(html.includes('<spin/>'));
lastTaskLifecycle = null;
html = renderTaskPage(record('brainstorming'), null);
assert(html.includes('>Stop task</button>'));
assert(!html.includes('>Pause</button>'));
const ended = record();
ended.result = {status: 'failure', reason: 'Historical failure'};
html = renderTaskPage(ended, null);
assert(html.includes('Historical failure'));
assert(html.includes('<h3>Result</h3>'));
assert(!html.includes('>Resume</button>'));
""")

    def test_sidebar_uses_lifecycle_and_stops_live_clock_while_paused(self):
        self.javascript(r"""
const row = {record: record(), admitted_at: 'today', process: 'running',
  lifecycle: {status: 'paused'}, work_duration_s: 12,
  in_flight: {started_at: 123}};
assert(taskRow(row).includes('agent_call · paused · today'));
const items = sidebarItems([], [row]);
assert.equal(items[0].running, false);
assert.equal(items[0].closed, false);
assert.deepEqual(JSON.parse(taskStatusClock(row)), {completed: 12, inFlight: null});
""")

    def test_pausing_keeps_in_flight_clock_and_active_sidebar_ranking(self):
        self.javascript(r"""
const row = {record: record(), admitted_at: '2026-09-01', process: 'running',
  lifecycle: {status: 'pausing'}, work_duration_s: 12,
  in_flight: {started_at: 123}};
assert(taskRow(row).includes('agent_call · pausing · 2026-09-01'));
const pausedRow = {...row, admitted_at: '2026-09-06', lifecycle: {status: 'paused'}};
const items = sidebarItems([], [row, pausedRow]);
assert.equal(items[0].running, true);
assert.equal(items[0].closed, false);
assert.equal(itemStateRank(items[0]), 0);
assert.equal(itemStateRank(items[1]), 1);
assert(compareItemsForSidebar(items[0], items[1]) < 0);
assert.deepEqual(JSON.parse(taskStatusClock(row)),
  {completed: 12, inFlight: row.in_flight});
// A process that has really stopped must not acquire activity from pausing.
row.process = 'stopped';
assert.equal(sidebarItems([], [row])[0].running, false);
assert.deepEqual(JSON.parse(taskStatusClock(row)), {completed: 12, inFlight: null});
""", ("itemStateRank", "itemEpoch", "compareItemsForSidebar"))

    def test_reviewed_children_and_parent_pipeline_show_paused(self):
        self.javascript(r"""
const lifecycle = {status: 'paused'};
const activity = {process: 'running', unit: {unit: 'slice_doc-01', status: 'failure'}};
const deep = JSON.parse(deepTaskPipeline({status: 'paused', lifecycle,
  children: [{id: 'child', phase: 'documentation', status: 'paused', lifecycle, activity}]})
  .replace('<div class="card"><h3>Pipeline</h3>', '').replace('</div>', ''));
assert.equal(deep.options.status, 'paused');
assert.equal(deep.units[0].status, 'paused');
assert.equal(deep.units[0].running, false);
const reviewed = reviewedTaskPipeline({status: 'paused', lifecycle, activity});
assert(reviewed.includes('Reviewed task:paused'));
assert(reviewed.includes('"status":"paused","running":false'));
""")

    def test_pausing_reviewed_and_deep_children_keep_live_pipeline_activity(self):
        self.javascript(r"""
const lifecycle = {status: 'pausing'};
const activity = {process: 'running', unit: {unit: 'slice_doc-01', status: 'fixing'}};
const deep = JSON.parse(deepTaskPipeline({status: 'pausing', lifecycle,
  children: [{id: 'child', phase: 'documentation', status: 'pausing', lifecycle, activity}]})
  .replace('<div class="card"><h3>Pipeline</h3>', '').replace('</div>', ''));
assert.equal(deep.options.status, 'pausing');
assert.equal(deep.units[0].status, 'pausing');
assert.equal(deep.units[0].running, true);
const reviewed = reviewedTaskPipeline({status: 'pausing', lifecycle, activity});
assert(reviewed.includes('Reviewed task:pausing'));
assert(reviewed.includes('"status":"pausing","running":true'));
""")

    def test_resume_posts_exact_revision_and_duplicate_click_is_ignored(self):
        self.javascript(r"""
let resolveRequest;
const sent = [];
const postJSON = (path, body) => {
  sent.push({path, body});
  return new Promise(resolve => { resolveRequest = resolve; });
};
const paintTaskPage = () => {};
const refreshTaskPage = () => {};
const refreshRuns = () => {};
(async () => {
  lastTaskLifecycle = {status: 'paused', revision: 18};
  const first = controlSelectedTask('resume');
  await controlSelectedTask('resume');
  assert.deepEqual(sent, [{path: '/api/tasks/task-1/resume', body: {revision: 18}}]);
  resolveRequest({lifecycle: {status: 'running', revision: 19}});
  await first;
  assert.equal(taskControlPending, null);
  assert.equal(lastTaskLifecycle.status, 'running');
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("controlSelectedTask",))

    def test_recovery_history_is_compact_and_paused_accounting_remains_visible(self):
        self.javascript(r"""
lastTaskLifecycle = {status: 'paused', revision: 3, source: 'error',
  history: [{status: 'paused', at: '2026-09-06', source: 'error', reason: 'quota <limit>',
    attempt: {native_result: 'HUGE SECRET OUTPUT'}},
    {status: 'running', at: '2026-09-07'}],
  accounting: {duration_s: 12, cost: {api_usd: 3.2, real_usd: 3.2}, cost_partial: false}};
const html = renderTaskPage(record(), null);
assert(html.includes('Pause and recovery history (2)'));
assert(html.includes('quota &lt;limit&gt;'));
assert(html.includes('2026-09-07'));
assert(!html.includes('HUGE SECRET OUTPUT'));
assert(html.includes('work 12'));
assert(html.includes('$3.20'));
assert(html.includes('Work so far'));
""")

    def test_delayed_control_reply_does_not_mutate_another_task_page(self):
        self.javascript(r"""
let resolveRequest;
const postJSON = () => new Promise(resolve => { resolveRequest = resolve; });
const paintTaskPage = () => {};
const refreshTaskPage = () => {};
const refreshRuns = () => {};
(async () => {
  lastTaskLifecycle = {status: 'running', revision: 1};
  const pending = controlSelectedTask('pause');
  selectedTask = 'another-task';
  taskControlPending = null;
  lastTaskLifecycle = {status: 'running', revision: 42};
  resolveRequest({lifecycle: {status: 'paused', revision: 2}});
  await pending;
  assert.equal(lastTaskLifecycle.revision, 42);
  assert.equal(taskControlPending, null);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("controlSelectedTask",))

    def test_creativity_task_page_presents_progress_results_and_controls(self):
        from orchestrator.tests.test_task_api import TaskApiTest

        source = TaskApiTest()
        self.addCleanup(source.doCleanups)
        pages, _ = source.creativity_projection_pages()
        self.javascript("const pages = " + json.dumps(pages) + ";\n" + r"""
function render(data) {
  lastTaskLifecycle = data.lifecycle;
  return renderTaskPage(data.task, 'today', data.creativity);
}
assert(render(pages.no_progress).includes('No saved progress available'));
assert(render(pages.genes).includes('Best evaluation: unavailable · reference: unavailable'));
assert(render(pages.batch).includes('Accepted candidate evaluations: 1 / 20'));
assert(render(pages.comparison).includes('Best evaluation: 0.4 · reference: 0.4'));
assert(render(pages.rebaseline).includes('Reassessing candidates'));
assert(render(pages.rebaseline).includes('Best evaluation: unavailable'));
assert(render(pages.expansion).includes('Job: expand genes'));
assert(render(pages.expansion).includes('patience window complete'));
assert(render(pages.expanded).includes('Expansion interventions: 1 · consecutive: 1 / 1'));
assert(render(pages.paused).includes('Provider quota &lt;exhausted&gt;'));
assert(render(pages.paused).includes('>Resume</button>'));
assert(render(pages.prepared).includes('awaiting task completion'));
assert(!render(pages.prepared).includes('<h3>Result</h3>'));
assert(render(pages.prepared).includes('>Pause</button>'));
let html = render(pages.terminal);
for (const text of ['proposals', 'generation_limit', 'not probabilities of success',
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;', 'A second line.',
    'Fits the objective &amp; constraints.', 'Readers have time.', 'Budget holds.',
    'tokens unknown', 'cost unknown', 'some calls are still unpriced, so this is a floor'])
  assert(html.includes(text), text);
assert(!html.includes('<img'));
const native = pages.terminal.task.result.native_result;
let previous = -1;
for (const proposal of native.proposals) {
  const position = html.indexOf(esc(proposal.candidate_id), previous + 1);
  assert(position > previous);
  previous = position;
  for (const part of proposal.components) {
    const component = html.indexOf(`<li><b>${esc(part.dimension)}</b> · ${esc(part.variant)}`, previous);
    assert(component > previous);
    previous = component;
  }
}
const receipts = pages.terminal.lifecycle.history.filter(event => event.physical_dispatch);
assert(html.includes(`Physical calls (${receipts.length})`));
assert(!html.includes('Pause and recovery history'));
for (const event of receipts) {
  const call = event.physical_dispatch, context = call.call_context, attempt = event.attempt;
  for (const value of [event.call_id, context.job, `generation ${context.generation}`,
      `batch ${context.batch}`, call.family, call.model, call.effort,
      `prompt-set fallback: ${call.prompt_set_fallback}`, `duration ${attempt.duration_s}`,
      fmtTokenUsage(attempt.token_usage, attempt.token_usage_partial),
      costReading(attempt.cost, attempt.cost_partial).text]) assert(html.includes(esc(value)), value);
}
const unconfirmed = structuredClone(pages.paused);
const pendingCall = unconfirmed.lifecycle.history.find(event => event.physical_dispatch);
Object.assign(pendingCall.physical_dispatch, {completed: false, duration_s: null});
pendingCall.attempt.duration_s = 0; // Pending receipts contribute no known duration yet.
html = render(unconfirmed);
assert(html.includes('duration unknown'));
assert(html.includes('completion unconfirmed'));
assert(!html.includes('in flight'));
for (const reason of ['generation_limit', 'evaluation_budget', 'persistent_stagnation', 'repertoire_exhausted']) {
  const ended = structuredClone(pages.terminal);
  ended.task.result.native_result.stop_reason = reason;
  assert(render(ended).includes(`Stop reason: ${reason}`));
  ended.task.result.native_result.outcome = 'no_valid_candidates';
  ended.task.result.native_result.proposals = [];
  html = render(ended);
  assert(html.includes('No valid proposal was found.'));
  assert(html.includes('success'));
  assert(!html.includes('A useful proposal'));
}
const failed = structuredClone(pages.terminal);
failed.task.result = {...failed.task.result, status: 'failure', native_result: null, reason: 'Cancelled by operator'};
taskMenuOpen = true;
html = render(failed);
assert(html.includes('Cancelled by operator'));
assert(html.includes('Delete task…'));
assert(!html.includes('>Resume</button>'));
const sent = [], polls = [pages.batch, pages.rebaseline, pages.prepared, pages.terminal];
const api = async path => { sent.push({method: 'GET', path}); return polls.shift(); };
const postJSON = async (path, body) => { sent.push({method: 'POST', path, body}); throw Error('stale Resume'); };
const detail = {innerHTML: '', querySelectorAll: () => []};
const document = {getElementById: () => detail};
const syncRequestMore = () => {}, updateBottomJump = () => {}, refreshRuns = () => {};
const requestAnimationFrame = callback => callback();
let lastTaskPage = null, lastTaskPipeline = null, taskPageSeq = 0, pendingLanding = null;
const lastTaskRows = [];
selectedTask = pages.terminal.task.id;
(async () => {
  for (const expected of ['evaluations: 1 / 20', 'Reassessing candidates', 'awaiting task completion', '<h3>Result</h3>']) {
    await refreshTaskPage();
    assert(detail.innerHTML.includes(expected), expected);
  }
  await refreshTaskPage();
  assert.equal(sent.length, 4);
  assert(sent.every(item => item.method === 'GET'));
  lastTaskPage = pages.paused.task;
  lastTaskLifecycle = pages.paused.lifecycle;
  polls.push(pages.paused);
  await controlSelectedTask('resume');
  assert.deepEqual(sent[4], {method: 'POST', path: `/api/tasks/${selectedTask}/resume`,
    body: {revision: pages.paused.lifecycle.revision}});
  assert(detail.innerHTML.includes('stale Resume'));
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("refreshTaskPage", "paintTaskPage", "controlSelectedTask"))


if __name__ == "__main__":
    unittest.main()
