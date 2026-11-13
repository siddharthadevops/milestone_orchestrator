"""Exercise the opt-in round pause through the panel's actual launch form."""

import re
import shutil
import subprocess
import unittest
from pathlib import Path


class BrainstormingRoundPausePanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (Path(__file__).resolve().parents[1] / "static" /
                     "panel.html").read_text(encoding="utf-8")
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node is required for executable panel checks")

    def javascript(self, checks, names):
        sources = []
        for name in names:
            match = re.search(
                r"(?:async )?function " + name + r"\([^\n]*\) \{.*?\n\}",
                self.panel, re.S,
            )
            self.assertIsNotNone(match, name)
            sources.append(match.group(0))
        result = subprocess.run(
            [self.node, "-e", "\n".join(sources) + "\n" + checks],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mechanism_checkbox_renders_and_submits_boolean_values(self):
        self.javascript(r"""
const assert = require('node:assert/strict');
const schema = {pause_after_round: {type: 'boolean', default: false,
  label: 'Pause after every round', description: 'Intervene, then resume.'}};
let draft = {};
const entry = {configuration_schema: schema};
const taskExecutorEntry = () => entry;
const taskExecutorSelected = 'brainstorming';
const taskExecutorDrafts = {};
let controls = [];
const document = {querySelectorAll: () => controls};
function renderControl() {
  const markup = renderTaskConfigurationSchema(schema, draft);
  const tag = markup.match(/<input\b[^>]*>/)[0];
  assert.match(tag, /type="checkbox"/);
  assert.match(markup, /Intervene, then resume\./);
  return {type: 'checkbox', checked: /\schecked(?:\s|>)/.test(tag), value: 'on',
    dataset: {taskConfig: 'pause_after_round', taskConfigType: 'boolean'},
    checkValidity: () => true};
}
controls = [renderControl()];
assert.equal(controls[0].checked, false);
assert.deepEqual(currentTaskConfiguration().configuration, {pause_after_round: false});
controls[0].checked = true;
assert.deepEqual(currentTaskConfiguration().configuration, {pause_after_round: true});
snapshotTaskExecutorConfiguration('brainstorming');
draft = taskExecutorDrafts.brainstorming;
controls = [renderControl()];
assert.equal(controls[0].checked, true);
controls[0].checked = false;
snapshotTaskExecutorConfiguration('brainstorming');
draft = taskExecutorDrafts.brainstorming;
assert.equal(renderControl().checked, false);
const optional = renderTaskConfigurationSchema(
  {inherited: {type: 'boolean', optional: true}}, {});
assert.match(optional, /<select/);
assert.match(optional, /— inherit —/);
""", ("esc", "taskConfigurationApplicable", "taskConfigurationValue",
      "taskConfigurationOption", "taskConfigurationLabel",
      "taskConfigurationControlValue", "renderTaskConfigurationSchema",
      "snapshotTaskExecutorConfiguration", "setTaskConfigurationValue",
      "currentTaskConfiguration"))

    def test_round_pause_explains_how_to_intervene_and_resume(self):
        self.javascript(r"""
const assert = require('node:assert/strict');
const BS_TERMINAL = new Set(['success', 'failure', 'cancelled']);
let fullRequestText, sessionView = 'main', html;
const lastSessions = [];
const sessionStopping = false, sessionStarting = false;
const requestTitle = esc, spinEl = () => '', sessionChips = () => '';
const sessionClosingCard = () => '';
const paintSessionDetail = value => {html = value;};
const fmtTokenUsage = () => '';
const view = {id: 'session', request: 'Discuss', status: 'running',
  process: 'stopped', pause_after_round: true, paused_after_round: true,
  round: {current: 1, completed: 1, maximum: 3, remaining: 2},
  closure_policy: 'unanimity', result: null};
renderSessionDetail(view);
assert.match(html, /Paused after round 1/);
assert.match(html, /onclick="openFloorDialog\(\)">Intervene/);
assert.match(html, /onclick="startSelectedSession\(\)">Resume session/);
assert.match(html, /resume without adding a message/);
renderSessionDetail({...view, process: 'running'});
assert(!html.includes('Paused after round'));
assert.match(html, /Stop session/);
renderSessionDetail({...view, paused_after_round: false});
assert(!html.includes('Paused after round'));
assert.match(html, /Start session/);
""", ("esc", "renderSessionDetail"))

    def test_round_pause_is_opt_in_and_does_not_carry_into_the_next_session(self):
        self.javascript(r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById(id) {
  return fields[id] ||= {value: '', checked: false, showModal() {}, close() {}};
}};
const area = {record: {primary: {path: '/project'}, name: 'main'}};
const bsBoundArea = () => area;
let bsProjects = [{slug: 'project', families_order: ['codex']}];
let bsRoster = [], bsRefs = [], bsCreateParents = false;
const defaultBsRoster = () => [{role: 'initial_position', delivery: 'automatic'}];
const renderBsRoster = () => {}, renderBsRefs = () => {};
const loadBsProjects = () => {}, loadStandaloneStaffing = () => {};
const loadPromptSetSelect = () => {}, refreshRuns = () => {};
const standaloneStaffingSession = async () => 'staffing-1';
const requests = [];
const api = async (url, options) => {
  assert.equal(url, '/api/brainstorming/sessions');
  requests.push(JSON.parse(options.body));
};
function fillForm() {
  for (const [id, value] of Object.entries({b_project: '0', b_request: 'Request',
      b_brief: 'Context', b_target: 'DECISION.md', b_rounds: '3',
      b_policy: 'unanimity', b_prompt_set: 'default'}))
    document.getElementById(id).value = value;
}
(async () => {
  openBrainstormingForm();
  fillForm();
  await submitBrainstorming();
  assert.equal(requests.length, 1);
  assert.equal('pause_after_round' in requests[0].request, false);
  openBrainstormingForm();
  fillForm();
  document.getElementById('b_pause_after_round').checked = true;
  await submitBrainstorming();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].request.pause_after_round, true);
  openBrainstormingForm();
  assert.equal(document.getElementById('b_pause_after_round').checked, false);
  fillForm();
  await submitBrainstorming();
  assert.equal(requests.length, 3);
  assert.equal('pause_after_round' in requests[2].request, false);
})().catch(error => {console.error(error); process.exitCode = 1;});
""", ("openBrainstormingForm", "submitBrainstorming"))


if __name__ == "__main__":
    unittest.main()
