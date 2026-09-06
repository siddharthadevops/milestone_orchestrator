"""Execute the task control presenters, not only their source spelling."""

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
            "taskControlHistory",
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
const esc = value => String(value == null ? '' : value)
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;');
const escJsSq = value => String(value).replaceAll("'", "\\'");
const requestTitle = esc;
const spinEl = () => '<spin/>';
const fmtAdmitted = value => value;
const fmtDHMS = value => String(value);
const fmtTokenUsage = () => '';
const costHtml = () => '';
const tokenUsageHtml = () => '';
const costReading = () => ({known: true, text: '$3.20'});
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
for (const executor of ['agent_call', 'reviewed_task', 'deep_task']) {
  lastTaskLifecycle = {status: 'paused', revision: 7, source: 'error',
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
lastTaskLifecycle = {status: 'pausing', revision: 2, source: 'operator',
  reason: 'Please wait', can_resume: false};
for (const executor of ['agent_call', 'reviewed_task', 'deep_task']) {
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
  accounting: {duration_s: 12, cost: {api_usd: 3.2}, cost_partial: false}};
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


if __name__ == "__main__":
    unittest.main()
