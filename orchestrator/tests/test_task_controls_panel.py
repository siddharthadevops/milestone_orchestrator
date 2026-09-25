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
            "creativitySearchMaterial", "creativityCandidateEvaluations",
            "creativityResult", "duelCandidates", "duelProgress", "duelResult",
            "taskPhysicalCalls", "esc", "fmtTokenCount",
            "fmtTokenUsage", "costReading", "costHtml", "tokenUsageHtml",
            "modelEffort", "shortModel",
        ) + functions
        sources = []
        for name in ("MODEL_LABELS", "EFFORT_LABELS"):
            match = re.search(
                r"const " + name + r" = Object\.freeze\(\{.*?\n\}\);",
                self.panel, re.S,
            )
            self.assertIsNotNone(match, name)
            sources.append(match.group(0))
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

    def test_creativity_live_staffing_and_rigors_are_available_until_completion(self):
        self.javascript(r"""
const task = record('creativity');
task.order.staffing_session = 'stf-live';
for (const status of ['running', 'pausing', 'paused']) {
  lastTaskLifecycle = {status};
  const html = renderTaskPage(task, null);
  assert(html.includes('onclick="openTaskStaffing()">Staffing…'));
  assert(html.includes('onclick="openCreativityRigor()">Rigors…'));
}
delete task.order.staffing_session;
let html = renderTaskPage(task, null);
assert(html.includes('No staffing session is bound to this task.'));
assert(!html.includes('onclick="openTaskStaffing()"'));
assert(html.includes('onclick="openCreativityRigor()"'));
task.result = {status: 'failure', native_result: {}};
html = renderTaskPage(task, null);
assert(!html.includes('onclick="openTaskStaffing()"'));
assert(!html.includes('onclick="openCreativityRigor()"'));
task.result = null;
taskPageRunId = 'attached-run';
assert(!renderTaskPage(task, null).includes('onclick="openCreativityRigor()"'));
taskPageRunId = null;
assert(!renderTaskPage(record('duel'), null).includes('onclick="openCreativityRigor()"'));
""")
        self.assertLess(self.panel.index('<dialog id="creativityrigordlg">'),
                        self.panel.index('<script>'))
        self.assertIn('<label>Compose candidates</label>', self.panel)
        self.assertIn('<select id="cr_compose_candidates">', self.panel)
        self.assertIn('<label>Evaluation</label>', self.panel)
        self.assertNotIn('Composition and evaluation', self.panel)
        self.assertIn('Changes apply to subsequent calls; running calls keep', self.panel)

    def test_creativity_page_shows_the_stored_session_mode(self):
        self.javascript(r"""
for (const mode of ['fresh', 'persistent']) {
  const task = record('creativity');
  task.order.configuration = {session_mode: mode};
  const html = renderTaskPage(task, null);
  assert(html.includes('initial configuration'));
  assert(html.includes('session_mode: ' + mode));
}
const legacy = record('creativity');
assert(!renderTaskPage(legacy, null).includes('session_mode: persistent'));
""")

    def test_creativity_staffing_reuses_its_bound_session_editor(self):
        self.javascript(r"""
let lastTaskPage = record('creativity');
lastTaskPage.order.staffing_session = 'stf-bound';
const opened = [];
const refreshTaskPage = () => {};
const openStaffingSession = async (id, afterSave) => opened.push({id, afterSave});
(async () => {
  await openTaskStaffing();
  assert.deepEqual(opened, [{id: 'stf-bound', afterSave: refreshTaskPage}]);
  delete lastTaskPage.order.staffing_session;
  await openTaskStaffing();
  lastTaskPage.order.staffing_session = 'stf-bound';
  lastTaskPage.result = {status: 'success'};
  await openTaskStaffing();
  lastTaskPage.result = null;
  taskPageRunId = 'attached-run';
  await openTaskStaffing();
  assert.equal(opened.length, 1);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("openTaskStaffing",))

    def test_creativity_rigors_read_live_and_clear_overrides_without_mutating_order(self):
        self.javascript(r"""
let lastTaskPage = record('creativity');
lastTaskPage.order.configuration = {rigor: {default: 'high'}};
let openedCreativityRigorTask = null, creativityRigorSaving = false;
const STANDALONE_RIGORS = ['low', 'medium', 'high'];
const fields = Object.fromEntries(['cr_default', 'cr_create_genes',
  'cr_compose_candidates', 'cr_evaluate_candidates', 'cr_error', 'cr_save'].map(id => [id, {value: ''}]));
let shown = 0, closed = 0, refreshed = 0;
fields.creativityrigordlg = {showModal: () => shown++, close: () => closed++};
const document = {getElementById: id => fields[id]};
const sent = [];
const api = async path => {
  sent.push({method: 'GET', path});
  return {ok: true, rigor: {default: 'low', compose_candidates: 'high', evaluate_candidates: 'medium'}};
};
const postJSON = async (path, body) => {
  sent.push({method: 'POST', path, body});
  return {ok: true, rigor: body.rigor};
};
const refreshTaskPage = () => refreshed++;
const alert = message => { throw Error(message); };
(async () => {
  await openCreativityRigor();
  assert.equal(shown, 1);
  assert.equal(fields.cr_default.value, 'low');
  assert.equal(fields.cr_create_genes.value, '');
  assert.equal(fields.cr_compose_candidates.value, 'high');
  assert.equal(fields.cr_evaluate_candidates.value, 'medium');
  assert.deepEqual(sent, [{method: 'GET', path: '/api/tasks/task-1/creativity-rigor'}]);
  fields.cr_default.value = '';
  fields.cr_create_genes.value = 'high';
  fields.cr_compose_candidates.value = 'medium';
  fields.cr_evaluate_candidates.value = 'low';
  await saveCreativityRigor();
  assert.deepEqual(sent[1], {method: 'POST', path: '/api/tasks/task-1/creativity-rigor',
    body: {rigor: {create_genes: 'high', compose_candidates: 'medium', evaluate_candidates: 'low'}}});
  assert.deepEqual(lastTaskPage.order.configuration, {rigor: {default: 'high'}});
  fields.cr_create_genes.value = '';
  fields.cr_compose_candidates.value = '';
  fields.cr_evaluate_candidates.value = '';
  await saveCreativityRigor();
  assert.deepEqual(sent[2].body, {rigor: {}});
  assert.equal(closed, 2);
  assert.equal(refreshed, 2);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("openCreativityRigor", "saveCreativityRigor"))

    def test_creativity_rigors_keep_refusals_and_do_not_duplicate_saves(self):
        self.javascript(r"""
let lastTaskPage = record('creativity');
let openedCreativityRigorTask = 'task-1', creativityRigorSaving = false;
const fields = Object.fromEntries(['cr_default', 'cr_create_genes',
  'cr_compose_candidates', 'cr_evaluate_candidates', 'cr_error', 'cr_save'].map(id => [id, {value: ''}]));
let closed = 0, refreshed = 0;
fields.creativityrigordlg = {close: () => closed++};
const document = {getElementById: id => fields[id]};
const sent = [];
let rejectRequest;
const postJSON = (path, body) => {
  sent.push({path, body});
  return new Promise((resolve, reject) => { rejectRequest = reject; });
};
const refreshTaskPage = () => refreshed++;
(async () => {
  const first = saveCreativityRigor();
  await saveCreativityRigor();
  assert.equal(sent.length, 1);
  assert.equal(fields.cr_save.disabled, true);
  rejectRequest(Error('task is already complete'));
  await first;
  assert.equal(fields.cr_error.textContent, 'task is already complete');
  assert.equal(fields.cr_save.disabled, false);
  assert.equal(creativityRigorSaving, false);
  assert.equal(closed, 0);
  assert.equal(refreshed, 0);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("saveCreativityRigor",))

    def test_creativity_rigor_read_does_not_open_for_a_different_selected_task(self):
        self.javascript(r"""
let lastTaskPage = record('creativity');
let openedCreativityRigorTask = null, creativityRigorSaving = false;
let resolveRequest;
const api = () => new Promise(resolve => { resolveRequest = resolve; });
const document = {getElementById: () => { throw Error('stale dialog was opened'); }};
const alert = message => { throw Error(message); };
(async () => {
  const opening = openCreativityRigor();
  selectedTask = 'task-2';
  resolveRequest({ok: true, rigor: {default: 'low'}});
  await opening;
  assert.equal(openedCreativityRigorTask, null);
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("openCreativityRigor",))

    def test_paused_types_render_resume_cancel_and_failure_without_spinner(self):
        self.javascript(r"""
for (const executor of ['agent_call', 'reviewed_task', 'deep_task', 'creativity', 'duel']) {
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
for (const executor of ['agent_call', 'reviewed_task', 'deep_task', 'creativity', 'duel']) {
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

    def test_physical_calls_are_compact_and_only_current_pending_calls_tick(self):
        self.javascript(r"""
const receipt = {
  status: 'running', at: '2026-09-24T10:00:00.123456+0000',
  call_id: '019a7bd7-39d1-7097-87dc-280c381ae1b3',
  physical_dispatch: {
    call_context: {job: 'evaluate_candidates', generation: 3,
      batch: '6b63c56a-d4ba-48fb-ac2b-fbefa28e1255'},
    family: 'codex', model: 'gpt-6-astra', effort: 'xhigh',
    prompt_set_fallback: null, completed: true, duration_s: 42, error: null,
  },
  attempt: {cost: {api_usd: 0.75, real_usd: 0.25}, cost_partial: false,
    token_usage: {input_tokens: 100, output_tokens: 50, total_tokens: 150},
    token_usage_partial: false},
};
const callSummary = (html, id = receipt.call_id) => {
  const row = html.split(`data-task-detail-key="physical-call:${id}"`)[1];
  assert(row, 'every call has its own disclosure');
  return row.match(/<summary>(.*?)<\/summary>/s)[1];
};
const visible = html => html.replace(/<[^>]*>/g, '');
let html = taskPhysicalCalls({status: 'success', history: [receipt]});
let summary = callSummary(html);
assert(visible(summary).includes('evaluate candidates · generation 3'));
assert(visible(summary).includes('Astra-X'));
assert(summary.includes('physical-call-status success'));
assert(summary.includes('&#10003;'));
assert(visible(summary).includes('42'));
for (const detail of [receipt.call_id, receipt.physical_dispatch.call_context.batch,
    '$0.25', 'input 100', 'prompt-set fallback: none']) {
  assert(html.includes(detail), 'details retain ' + detail);
  assert(!summary.includes(detail), 'summary hides ' + detail);
}
assert(!visible(summary).includes('gpt-6-astra'));
const duel = structuredClone(receipt);
duel.physical_dispatch.call_context = {job: 'author_candidate', candidate_id: 'a', round: 2};
Object.assign(duel.physical_dispatch, {family: 'claude', model: 'claude-opus-5-5', effort: 'high'});
summary = callSummary(taskPhysicalCalls({status: 'running', history: [duel]}));
assert(visible(summary).includes('author candidate · candidate A · round 2'));
assert(visible(summary).includes('Opus-H'));
const failed = structuredClone(receipt);
failed.physical_dispatch.error = 'Provider <failed>';
html = taskPhysicalCalls({status: 'failure', history: [failed]});
summary = callSummary(html);
assert(summary.includes('physical-call-status failed'));
assert(!summary.includes('&#10003;'));
assert(visible(summary).includes('42'));
assert(html.includes('Provider &lt;failed&gt;'));
const pending = structuredClone(receipt);
Object.assign(pending.physical_dispatch, {completed: false, duration_s: null});
const expectedClock = JSON.stringify({completed: 0,
  inFlight: {started_at: Date.parse(pending.at) / 1000}});
for (const status of ['running', 'pausing']) {
  summary = callSummary(taskPhysicalCalls({status, history: [pending]}));
  assert(summary.includes('physical-call-status running'));
  assert(summary.includes(expectedClock), 'live time starts at the receipt timestamp');
  assert(!summary.includes('&#10003;'));
}
for (const status of ['paused', 'success', 'failure']) {
  summary = callSummary(taskPhysicalCalls({status, history: [pending]}));
  assert(summary.includes('physical-call-status unknown'));
  assert(!summary.includes(expectedClock), 'inactive receipts must not tick');
}
const latest = structuredClone(pending);
latest.call_id = 'new-dispatch';
latest.at = '2026-09-24T10:02:00.123456+0000';
html = taskPhysicalCalls({status: 'running', history: [pending,
  {status: 'paused', at: '2026-09-24T10:00:30+0000'},
  {status: 'running', at: '2026-09-24T10:01:00+0000'}, latest]});
assert(callSummary(html).includes('physical-call-status unknown'));
assert(!callSummary(html).includes(expectedClock), 'resume must not restart old clocks');
assert(callSummary(html, latest.call_id).includes('physical-call-status running'));
assert(callSummary(html, latest.call_id).includes(JSON.stringify({completed: 0,
  inFlight: {started_at: Date.parse(latest.at) / 1000}})));
""")

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
assert(render(pages.genes).includes('Best retained evaluation: unavailable · reference: unavailable'));
assert(render(pages.batch).includes('Accepted candidate evaluations: 1 / 20'));
assert(render(pages.comparison).includes('Best retained evaluation: 0.4 (valid) · reference: 0.4'));
assert(render(pages.rebaseline).includes('Reassessing candidates'));
assert(render(pages.rebaseline).includes('Best retained evaluation: unavailable'));
assert(render(pages.expansion).includes('Job: expand genes'));
assert(render(pages.expansion).includes('patience window complete'));
assert(render(pages.expanded).includes('Expansion interventions: 1 · consecutive: 1 / 1'));
assert(render(pages.paused).includes('Provider quota &lt;exhausted&gt;'));
assert(render(pages.paused).includes('>Resume</button>'));
assert(render(pages.prepared).includes('awaiting task completion'));
assert(!render(pages.prepared).includes('<h3>Result</h3>'));
assert(render(pages.prepared).includes('>Pause</button>'));
let html = render(pages.terminal);
const repeated = pages.terminal.creativity.candidate_evaluations.find(
  (item, index, items) => items.slice(0, index).some(previous =>
    previous.candidate_id === item.candidate_id &&
    previous.regime_revision !== item.regime_revision)
);
assert(repeated, 'fixture must exercise a survivor evaluated under two regimes');
for (const data of [pages.expansion, pages.expanded, pages.prepared,
    pages.terminal, pages.paused]) {
  const rendered = render(data);
  const detailKeys = [...rendered.matchAll(/data-task-detail-key="([^"]+)"/g)]
    .map(match => match[1]);
  assert.equal(new Set(detailKeys).size, detailKeys.length,
    'every rendered disclosure key must be unique');
}
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
  ended.creativity.best_candidates = [];
  ended.creativity.best_candidate_valid = false;
  for (const item of ended.creativity.candidate_evaluations) {
    item.constraint_valid = false;
    item.constraint_violations = ['budget'];
  }
  html = render(ended);
  assert(html.includes('No valid proposal was found.'));
  assert(html.includes('success'));
  assert(html.includes('Evaluated candidates'));
  assert(html.includes('constraint-invalid'));
  assert(html.includes('A useful proposal')); // Retained as diagnostic evidence, not a proposal.
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
let lastTaskPage = null, lastTaskPipeline = null, taskPageSeq = 0;
let taskPagePaintSeq = 0, pendingLanding = null;
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

    def test_sparse_evidence_rendering(self):
        from orchestrator.tests.test_task_api import TaskApiTest

        for mode, all_zero in (("fixed", False), ("interchangeable", True)):
            with self.subTest(mode=mode, all_zero=all_zero):
                source = TaskApiTest()
                self.addCleanup(source.doCleanups)
                pages, _ = source.creativity_projection_pages(sparse=True, order_mode=mode, all_zero=all_zero)
                self.javascript("const pages = " + json.dumps(pages) + ";\n" +
                                "const allInvalid = " + json.dumps(all_zero) + ";\n" + r"""
function render(data) {
  lastTaskLifecycle = data.lifecycle;
  return renderTaskPage(data.task, 'today', data.creativity);
}
assert(render(pages.no_progress).includes('No saved progress available'));
assert(render(pages.genes).includes('The generator has not returned search material yet'));
assert(render(pages.batch).includes('Best candidates from all accepted evaluations'));
const batchHTML = render(pages.batch);
if (allInvalid) {
  assert.equal(pages.batch.creativity.best_candidates.length, 0);
  assert(batchHTML.includes('No valid proposals available yet.'));
  assert(!batchHTML.includes('Proposal 1'));
  assert(batchHTML.includes('Evaluated candidates (1)'));
  assert(batchHTML.includes('A useful proposal.')); // Invalid work remains inspectable evidence.
} else {
  assert.equal(pages.batch.creativity.best_candidates.length, 1);
  assert(batchHTML.includes('Proposal 1'));
}
assert(render(pages.paused).includes('>Resume</button>'));
assert(render(pages.prepared).includes('awaiting task completion'));
assert(!render(pages.prepared).includes('<h3>Result</h3>'));
assert(render(pages.terminal).includes('<h3>Result</h3>'));
const material = pages.terminal.creativity.search_material;
const materialHTML = creativitySearchMaterial(material, true);
for (const value of [material.objective, material.context_summary, material.composition_guidance,
    material.order_semantics, ...material.facts, ...material.assumptions, ...material.unknowns,
    ...material.constraints.flatMap(item => [item.id, item.text]),
    ...material.criteria.flatMap(item => [item.id, item.text]),
    ...material.dimensions.flatMap(item => [item.id, item.meaning])])
  assert(materialHTML.includes(esc(value)), value);
assert.equal(materialHTML.split('Shared repertoire').length - 1, 1);
for (const variant of material.variants)
  assert.equal(materialHTML.split(esc(variant.text)).length - 1, 1);
assert(!materialHTML.includes('<Action') && !materialHTML.includes('<Focus'));
for (const data of Object.values(pages)) {
  const html = render(data), view = data.creativity;
  assert(!html.includes('<img'));
  for (const retired of ['reference:', 'patience window', 'Expansion interventions',
      'expansion interventions:', 'Reassessing candidates', 'Historical evaluator regime'])
    assert(!html.includes(retired), retired);
  if (!view) continue;
  assert(html.includes(`Accepted candidate evaluations: ${view.evaluated_candidates} / ${view.evaluation_budget}`));
  assert(html.includes(`${view.generations_completed} completed`));
  assert(html.includes(`Best retained evaluation: ${view.best_score === null ? 'unavailable' : view.best_score}`));
  assert.equal(html.includes('Stop reason:'), view.stop_reason !== null);
  if (view.stop_reason !== null) assert(html.includes(`Stop reason: ${view.stop_reason}`));
  const evaluations = creativityCandidateEvaluations(view.candidate_evaluations, true);
  assert(html.includes(evaluations));
  for (const item of view.candidate_evaluations) {
    for (const value of [item.candidate_id, item.proposal, item.reason, ...item.assumptions,
        ...item.constraint_violations, item.call_id, item.prompt_path, ...Object.values(item.regime)])
      assert(evaluations.includes(esc(value)), value);
    assert(evaluations.includes(`${item.active_count} active · ${item.omitted_count} omitted`));
    assert(evaluations.includes(`score ${item.score} · ${item.constraint_valid ? 'valid' : 'constraint-invalid'}`));
    let previous = evaluations.indexOf(esc(item.candidate_id));
    for (const component of item.components) {
      const position = evaluations.indexOf(`<li><b>${esc(component.dimension)}</b> · ${esc(component.variant)}`, previous);
      assert(position > previous);
      previous = position;
    }
  }
  const proposals = data.task.result ? data.task.result.native_result.proposals : view.best_candidates;
  const ranked = creativityProposals(proposals, view.search_material, true);
  assert(html.includes(ranked));
  let previous = -1;
  for (const item of proposals) {
    const position = ranked.indexOf(esc(item.candidate_id), previous + 1);
    assert(position > previous);
    previous = position;
    assert(ranked.includes(`${item.components.length} active · ${10 - item.components.length} omitted`));
    assert(ranked.includes(`evaluation ${item.score}`));
    assert(ranked.includes(item.constraint_valid ? 'valid' : 'constraint-invalid'));
    assert(ranked.includes(esc(item.constraint_violations.join(', ') || 'None')));
  }
}
const terminal = render(pages.terminal);
for (const text of ['3 active · 7 omitted', '10 active · 0 omitted', 'assessment retained in ranking',
    'constraint-invalid', 'Constraint violations', '__insufficient_detail__', 'not probabilities of success or proof of creativity',
    'tokens unknown', 'cost unknown', 'some calls are still unpriced, so this is a floor'])
  assert(terminal.includes(text), text);
const native = pages.terminal.task.result.native_result;
if (allInvalid) {
  assert.equal(native.outcome, 'no_valid_candidates');
  assert.deepEqual(native.proposals, []);
  assert(terminal.includes('No valid proposal was found.'));
  assert(!terminal.includes('Proposal 1'));
} else {
  assert.equal(native.outcome, 'proposals');
  assert(native.proposals.every(item => item.constraint_valid));
  assert(terminal.includes('Proposal 1'));
}
const polls = [pages.batch, pages.paused, pages.prepared, pages.terminal], reads = [];
const api = async path => { reads.push(path); return polls.shift(); };
const detail = {innerHTML: '', querySelectorAll: () => []};
const document = {getElementById: () => detail};
const syncRequestMore = () => {}, updateBottomJump = () => {}, refreshRuns = () => {};
const requestAnimationFrame = callback => callback();
let lastTaskPage = null, lastTaskPipeline = null, taskPageSeq = 0;
let taskPagePaintSeq = 0, pendingLanding = null;
const lastTaskRows = [];
selectedTask = pages.terminal.task.id;
(async () => {
  for (const text of [allInvalid ? 'No valid proposals available yet.' : 'Proposal 1',
      '>Resume</button>', 'awaiting task completion', '<h3>Result</h3>']) {
    await refreshTaskPage();
    assert(detail.innerHTML.includes(text), text);
  }
  await refreshTaskPage();
  assert.deepEqual(reads, Array(4).fill(`/api/tasks/${selectedTask}`));
})().catch(error => { console.error(error); process.exitCode = 1; });
""", ("refreshTaskPage", "paintTaskPage"))

    def test_task_repaint_preserves_reading_position_and_keyed_details(self):
        self.javascript(r"""
const detailNode = (key, open) => ({
  dataset: {taskDetailKey: key}, open,
});
const detail = {
  scrollTop: 640,
  nodes: [
    detailNode('creativity-search', false),
    detailNode('creativity-candidate:1:survivor', true),
    detailNode('creativity-candidate:2:survivor', false),
    detailNode('physical-calls', true),
  ],
  querySelectorAll(selector) {
    assert.equal(selector, 'details[data-task-detail-key]');
    return this.nodes;
  },
  set innerHTML(value) {
    this.html = value;
    this.nodes = [
      detailNode('creativity-search', true),
      detailNode('creativity-candidate:1:survivor', false),
      detailNode('creativity-candidate:2:survivor', true),
      // Newly arrived content keeps its markup default.
      detailNode('creativity-candidate:2:new', false),
      detailNode('physical-calls', false),
    ];
  },
  get innerHTML() { return this.html; },
};
const document = {getElementById: id => {
  assert.equal(id, 'detail');
  return detail;
}};
let lastTaskPage = {}, lastTaskPipeline = null, pendingLanding = null;
let taskPagePaintSeq = 0;
const lastTaskRows = [];
const syncRequestMore = () => {};
const frames = [];
const requestAnimationFrame = callback => frames.push(callback);
let bottomUpdates = 0;
const updateBottomJump = () => { bottomUpdates += 1; };
renderTaskPage = () => '<main>updated</main>';

paintTaskPage();
assert.equal(detail.scrollTop, 640);
assert.deepEqual(detail.nodes.map(node => [node.dataset.taskDetailKey, node.open]), [
  ['creativity-search', false],
  ['creativity-candidate:1:survivor', true],
  ['creativity-candidate:2:survivor', false],
  ['creativity-candidate:2:new', false],
  ['physical-calls', true],
]);
assert.equal(frames.length, 1);
detail.scrollTop = 900;
frames.shift()();
assert.equal(detail.scrollTop, 640);
assert.equal(bottomUpdates, 1);

// Opening a different task must not inherit the previous page position,
// including after the deferred layout pass.
pendingLanding = 'top';
detail.scrollTop = 700;
paintTaskPage();
assert.equal(detail.scrollTop, 0);
detail.scrollTop = 80;
frames.shift()();
assert.equal(detail.scrollTop, 0);

// A deferred callback from the task page must not touch the shared pane
// after the operator has navigated elsewhere.
pendingLanding = null;
detail.scrollTop = 300;
paintTaskPage();
assert.equal(frames.length, 1);
selectedTask = 'another-task';
detail.scrollTop = 27;
frames.shift()();
assert.equal(detail.scrollTop, 27);
assert.equal(bottomUpdates, 2);
""", ("paintTaskPage",))


if __name__ == "__main__":
    unittest.main()
