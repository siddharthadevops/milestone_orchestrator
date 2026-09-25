"""Focused static contract checks for task ordering and plan display."""

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class TaskPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (
            Path(__file__).resolve().parents[1] / "static" / "panel.html"
        ).read_text(encoding="utf-8")
        cls.task_ui = cls.panel.split(
            "/* ---- standalone task ordering", 1
        )[1].split("/* ---- new brainstorming:", 1)[0]

    def test_duel_form_and_both_deliveries(self):
        from orchestrator import tasks

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for executable panel checks")
        names = (
            "esc", "taskExecutorEntry", "taskConfigurationApplicable",
            "taskConfigurationValue", "taskConfigurationOption", "taskConfigurationLabel",
            "renderTaskConfigurationSchema", "taskUsesExecutionBinding",
            "setTaskConfigurationValue", "currentTaskConfiguration", "submitTaskForm",
            "duelCandidates", "duelProgress", "duelResult",
        )
        sources = [re.search(r"(?:async )?function " + name + r"\([^\n]*\) \{.*?\n\}",
                             self.panel, re.S).group(0) for name in names]
        setup = "const taskExecutorCatalogue = " + json.dumps(tasks.task_executor_catalogue()) + ";\n"
        checks = r"""
const assert = require('node:assert/strict');
const taskExecutorSelected = 'duel', taskDialogSeq = 1, taskReferences = ['source.md'];
const taskProjects = [{families_order: ['codex']}], posts = [];
let taskSubmitPending = false, closed = 0;
const fields = Object.fromEntries(Object.entries({
  t_request: 'Develop this document.', t_output: 'deliveries', t_project: '0',
  t_prompt_set: 'literature',
}).map(([id, value]) => [id, {value}]));
fields.task_error = {textContent: '', style: {}};
fields.taskform = {close: () => closed++};
const controls = [{value: '1', checkValidity: () => true,
  dataset: {taskConfig: 'max_rounds', taskConfigType: 'integer'}}];
global.document = {getElementById: id => fields[id], querySelectorAll: () => controls};
const taskBinding = () => ({project: 'docs', work_area: 'main'});
const syncTaskSubmitDisabled = () => {};
const standaloneStaffingSession = async () => 'session';
const postJSON = async (path, payload) => posts.push({path, payload});
(async () => {
  const entry = taskExecutorEntry('duel');
  assert.equal(entry.name, 'Duel');
  assert.equal(taskUsesExecutionBinding('duel', 'strategy_profile'), false);
  const markup = renderTaskConfigurationSchema(entry.configuration_schema, {});
  assert.match(markup, /min="1"/);
  assert.match(markup, /value="10" data-task-config="max_rounds"/);
  for (const role of ['default', 'author', 'reviewer'])
    assert(markup.includes(`data-task-config="rigor.${role}"`));
  await submitTaskForm();
  assert.equal(closed, 1);
  assert.equal(taskSubmitPending, false);
  assert.deepEqual(posts, [{path: '/api/tasks', payload: {
    task_executor: 'duel', configuration: {max_rounds: 1}, prompt_set: 'literature',
    staffing_session: 'session', request: {work_area: taskBinding(), request: fields.t_request.value,
      context: '', reference_documents: ['source.md'], output_directory: 'deliveries'},
  }}]);
  const candidates = [
    {id: 'a', directory: '/docs/a', artifacts: ['/docs/a/chapter.md', '/docs/a/notes.md'],
     finished: true, score: 0, report_path: '/reports/<a>.md', production_round: 1, review_round: 1},
    {id: 'b', directory: '/docs/b', artifacts: ['/docs/b/chapter.md'], finished: false,
     score: 0.9, report_path: '/reports/b.md', production_round: 2, review_round: 2},
  ];
  const result = duelResult({stop_reason: 'round_limit', rounds_completed: 2, candidates}, 'task-id');
  assert.match(result, /Configured round limit reached/);
  assert.match(result, /2 rounds completed/);
  assert.match(result, /Candidate A/);
  assert.match(result, /Candidate B/);
  assert.match(result, /Score: 0/);
  assert.match(result, /showDoc/);
  assert.match(result, /duel:a:artifact:0/);
  assert.match(result, /duel:b:report/);
  assert.match(result, /task-id/);
  for (const path of ['/docs/a/chapter.md', '/docs/a/notes.md', '/docs/b/chapter.md', '/reports/b.md'])
    assert(result.includes(path));
  assert.match(result, /\/reports\/&lt;a&gt;\.md/);
  assert(!result.includes('/reports/<a>.md'));
  assert(result.indexOf('Candidate A') < result.indexOf('Candidate B'));
  assert(!/winner/i.test(result));
  assert.match(duelResult({stop_reason: 'both_finished', rounds_completed: 2, candidates}),
    /Both authors finished their versions/);
  const progress = duelProgress({round: 2, phase: 'review', rounds_completed: 1, candidates}, {max_rounds: 3});
  assert.match(progress, /Round 2 \/ 3/);
  assert.match(progress, /Finished by author/);
  assert.match(progress, /Open to improvement/);
  const shared = candidates.map(candidate => ({...candidate, report_path: '/reports/review.md'}));
  const joint = duelResult({stop_reason: 'round_limit', rounds_completed: 2, candidates: shared}, 'task-id');
  assert.equal((joint.match(/\/reports\/review\.md/g) || []).length, 1);
  assert.match(joint, /Shared comparative review/);
  assert.match(joint, /duel:a:report/);
  assert.match(joint, /Score: 0\.9/);
  assert.match(joint, /Candidate A/);
  assert.match(joint, /Candidate B/);
  assert.match(duelProgress(null, {max_rounds: 1}), /Preparing both candidates/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([node, "-e", setup + "\n".join(sources) + checks],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("data.duel || null", self.panel)
        self.assertTrue("duelProgress(taskPipeline, configuration, record.id)" in self.panel)
        self.assertTrue("duelResult(result.native_result, record.id)" in self.panel)

    def test_creativity_schema_form_submits_public_order(self):
        from orchestrator import staffing
        from orchestrator.tests.test_staffing_sessions import session_body
        from orchestrator.tests.test_task_api import TaskApiTest
        from orchestrator.tests.test_task_controls_api import HeldHost
        from orchestrator.tests.test_tasks import creativity_configuration

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for executable panel checks")
        server = TaskApiTest()
        server.setUp()
        self.addCleanup(server.doCleanups)
        host = HeldHost(server.home)
        # Admission holds the registry lock; close each fixture before the next order.
        host.start = lambda record, _resolve: host.store.record_result_locked(
            record["id"], host._deep_failure("Admission-only fixture completed"),
        )
        server.start_server(host)
        server.project("mine", server.primary)
        binding = {"project": "mine", "work_area": "main"}
        session = staffing.create_session(server.home, session_body(work_area=binding))["id"]
        configuration = creativity_configuration(
            max_evaluated_candidates=12, mutation_rate=0.25, session_mode="fresh",
        )
        names = (
            "esc", "taskExecutorEntry", "taskConfigurationApplicable", "taskConfigurationValue",
            "taskConfigurationOption", "taskConfigurationLabel", "renderTaskConfigurationSchema", "taskUsesExecutionBinding",
            "setTaskConfigurationValue", "currentTaskConfiguration", "submitTaskForm",
            "snapshotTaskExecutorConfiguration", "onTaskConfigurationChange",
            "taskConfigurationLayers", "renderTaskExecutorEditor", "onTaskExecutorChange",
            "loadTaskInitialGenesFile",
        )
        sources = [re.search(r"(?:async )?function " + name + r"\([^\n]*\) \{.*?\n\}",
                             self.panel, re.S).group(0) for name in names]
        initial_genes = {"gene_pool": ["Fragment %d" % i for i in range(10)]}
        setup = "const fixture = " + json.dumps({
            "base": server.base, "binding": binding, "session": session,
            "configuration": configuration, "initialGenes": initial_genes,
        }) + ";\n"
        checks = r"""
const assert = require('node:assert/strict');
let taskExecutorSelected = 'creativity', taskDialogSeq = 1, taskSubmitPending = false, taskAdvancedOpen = false;
let taskExecutorCatalogue, taskExecutorDrafts = {}, closed = 0, refusal = null;
const taskProjects = [{families_order: ['codex', 'claude']}];
const taskReferences = ['second.md', 'first.md'], posts = [];
const fields = Object.fromEntries(Object.entries({
  t_request: 'Find a useful possibility.', t_initial_genes: '',
  t_output: '', t_project: '0', t_prompt_set: 'default', t_executor: 'creativity',
}).map(([id, value]) => [id, {value}]));
fields.task_error = {textContent: '', style: {}};
fields.taskform = {close: () => closed++};
for (const id of ['t_profile_field', 'task_staffing', 't_prompt_set_field',
                  't_initial_genes_field']) fields[id] = {style: {}};
let controls = [];
fields.task_configuration = {
  markup: '',
  get innerHTML() { return this.markup; },
  set innerHTML(html) {
    this.markup = html;
    // Supply DOM controls from actual markup; native validity is browser-owned.
    controls = [...html.matchAll(/<input\b[^>]*>|<select\b[^>]*>[\s\S]*?<\/select>/g)].map(([tag]) => {
      const opening = tag.split('>')[0];
      const attrs = Object.fromEntries([...opening.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
      const dataset = Object.fromEntries(Object.entries(attrs).filter(([k]) => k.startsWith('data-'))
        .map(([k, v]) => [k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), v]));
      const options = [...tag.matchAll(/<option\b([^>]*)>/g)];
      const selected = options.find(option => /\bselected\b/.test(option[1])) || options[0];
      const value = selected ? selected[1].match(/value="([^"]*)"/)[1] : attrs.value || '';
      return {dataset, value, min: attrs.min || '', max: attrs.max || '',
        placeholder: attrs.placeholder || '', checkValidity: () => true};
    });
  },
};
global.document = {getElementById: id => fields[id], querySelectorAll: () => controls};
const control = path => controls.find(c => c.dataset.taskConfig === path);
const taskBinding = () => fixture.binding;
const standaloneStaffingSession = async () => fixture.session;
const syncTaskSubmitDisabled = () => {};
async function postJSON(path, payload) {
  posts.push(payload);
  if (refusal) throw new Error(refusal);
  const response = await fetch(fixture.base + path, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
  });
  const body = await response.json();
  assert.equal(response.status, 201, JSON.stringify(body));
  assert.equal(body.task.order.creativity_semantics, 'fragments_v3');
  assert.deepEqual(body.task.order.initial_genes, payload.initial_genes);
  const admitted = {...body.task.order.configuration};
  if (!Object.hasOwn(payload.configuration, 'max_evaluated_candidates')) {
    assert.equal(admitted.max_evaluated_candidates,
      payload.configuration.population_size * payload.configuration.generation_limit);
    delete admitted.max_evaluated_candidates;
  }
  assert.deepEqual(admitted, payload.configuration);
}
(async () => {
  taskExecutorCatalogue = (await (await fetch(fixture.base + '/api/task-executors')).json()).task_executors;
  const schema = taskExecutorEntry('creativity').configuration_schema;
  const defaults = Object.fromEntries(Object.entries(schema).filter(([, definition]) => definition.default !== undefined)
    .map(([key, definition]) => [key, definition.default]));
  renderTaskExecutorEditor();
  for (const key of ['patience_generations', 'minimum_improvement', 'max_stagnation_expansions',
                     'rigor.expand_genes']) assert.equal(control(key), undefined);
  assert.deepEqual(controls.filter(c => c.dataset.taskConfig.startsWith('rigor.'))
    .map(c => c.dataset.taskConfig).sort(),
    ['rigor.compose_candidates', 'rigor.create_genes', 'rigor.default', 'rigor.evaluate_candidates']);
  assert.match(fields.task_configuration.innerHTML, /Candidates per generation/);
  assert.match(fields.task_configuration.innerHTML, /Agent sessions/);
  assert.match(fields.task_configuration.innerHTML, />Fresh per call<\/option>/);
  assert.match(fields.task_configuration.innerHTML, />Keep agent sessions<\/option>/);
  assert.equal(control('session_mode').value, 'persistent');
  assert.equal(control('order_mode').value, 'interchangeable');
  for (const [key, value] of Object.entries(defaults)) assert.equal(control(key).value, String(value));
  assert.equal(control('max_evaluated_candidates').value, '');
  assert.equal(control('max_evaluated_candidates').dataset.taskConfigOptional, 'true');
  assert.equal(control('max_evaluated_candidates').placeholder, 'Automatic: population × generations');
  assert(fields.task_configuration.innerHTML.indexOf('data-task-config="max_evaluated_candidates"')
    > fields.task_configuration.innerHTML.indexOf('id="t_more"'));
  assert(controls.filter(c => c.dataset.taskConfig.startsWith('rigor.')).every(c => c.value === ''));
  assert.equal(control('mutation_rate').max, '1');
  assert.deepEqual(currentTaskConfiguration().configuration, defaults);
  await submitTaskForm();
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].configuration, defaults);
  assert.equal(fields.task_error.textContent, '');
  assert.equal(closed, 1);
  control('population_size').value = '8';
  onTaskConfigurationChange(control('population_size'));
  control('evaluation_batch_size').value = '8';
  onTaskConfigurationChange(control('evaluation_batch_size'));
  control('generation_limit').value = '10';
  onTaskConfigurationChange(control('generation_limit'));
  control('session_mode').value = 'fresh';
  onTaskConfigurationChange(control('session_mode'));
  assert.equal(control('max_evaluated_candidates').value, '');
  fields.t_executor.value = 'agent_call';
  onTaskExecutorChange();
  assert.equal(fields.t_initial_genes_field.style.display, 'none');
  fields.t_executor.value = 'creativity';
  onTaskExecutorChange();
  assert.equal(fields.t_initial_genes_field.style.display, '');
  assert.equal(control('max_evaluated_candidates').value, '');
  assert.equal(control('session_mode').value, 'fresh');
  const automatic = {...defaults, population_size: 8, generation_limit: 10,
    evaluation_batch_size: 8, session_mode: 'fresh'};
  assert.deepEqual(currentTaskConfiguration().configuration, automatic);
  await submitTaskForm();
  assert.deepEqual(posts[1].configuration, automatic);
  assert(!Object.hasOwn(posts[1].configuration, 'max_evaluated_candidates'));
  assert.equal(closed, 2);
  for (const [key, value] of Object.entries(fixture.configuration)) control(key).value = String(value);
  control('rigor.default').value = 'low';
  control('rigor.create_genes').value = 'high';
  control('rigor.compose_candidates').value = 'medium';
  control('rigor.evaluate_candidates').value = 'high';
  const configured = {...defaults, ...fixture.configuration};
  const expected = {...configured, rigor: {default: 'low', create_genes: 'high',
    compose_candidates: 'medium', evaluate_candidates: 'high'}};
  assert.deepEqual(currentTaskConfiguration().configuration, expected);
  for (const key of Object.keys(fixture.configuration)) {
    if (schema[key].optional || !['integer', 'number'].includes(schema[key].type)) continue;
    const input = control(key), saved = input.value;
    input.value = '';
    await submitTaskForm();
    assert.equal(posts.length, 2, key);
    input.value = saved;
  }
  control('population_size').value = '0';
  onTaskConfigurationChange(control('population_size'));
  assert.equal(control('population_size').value, '0');
  control('population_size').value = '2';
  await submitTaskForm();
  assert.deepEqual(posts[2], {task_executor: 'creativity', configuration: expected,
    staffing_session: fixture.session, prompt_set: 'default', request: {
      work_area: fixture.binding, request: fields.t_request.value, context: '',
      reference_documents: taskReferences,
    }});
  assert.equal(closed, 3);
  assert.equal(taskSubmitPending, false);
  for (const job of ['default', 'create_genes', 'compose_candidates', 'evaluate_candidates'])
    control('rigor.' + job).value = '';
  assert.deepEqual(currentTaskConfiguration().configuration, configured);
  refusal = 'invalid_task_request';
  await submitTaskForm();
  assert.equal(fields.task_error.textContent, refusal);
  assert.equal(closed, 3);
  assert.equal(taskSubmitPending, false);
  refusal = null;
  fields.t_initial_genes.value = JSON.stringify(fixture.initialGenes);
  await submitTaskForm();
  assert.deepEqual(posts.at(-1).initial_genes, fixture.initialGenes);
  const pastedGenes = posts.at(-1).initial_genes;
  fields.t_initial_genes.value = '{not valid JSON';
  const postCount = posts.length;
  await submitTaskForm();
  assert.equal(posts.length, postCount);
  assert.match(fields.task_error.textContent, /^initial genes JSON is invalid:/);
  fields.t_initial_genes.value = '   ';
  await submitTaskForm();
  assert.equal(Object.hasOwn(posts.at(-1), 'initial_genes'), false);
  const fileContents = JSON.stringify(fixture.initialGenes, null, 2);
  const fileInput = {files: [{name: 'genes.json', text: async () => fileContents}], value: 'chosen'};
  const beforeLoad = posts.length;
  await loadTaskInitialGenesFile(fileInput);
  assert.equal(posts.length, beforeLoad);
  assert.equal(fields.t_initial_genes.value, fileContents);
  assert.equal(fileInput.value, '');
  await submitTaskForm();
  assert.deepEqual(posts.at(-1).initial_genes, pastedGenes);
  let readWrongExtension = false;
  const wrongFile = {files: [{name: 'genes.txt', text: async () => {
    readWrongExtension = true; return '{}';
  }}], value: 'chosen'};
  await loadTaskInitialGenesFile(wrongFile);
  assert.equal(readWrongExtension, false);
  assert.equal(fields.task_error.textContent, 'choose a .json file');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([node, "-e", setup + "\n".join(sources) + checks],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_catalogue_drives_options_and_configuration(self):
        self.assertEqual(self.task_ui.count('api("/api/task-executors")'), 1)
        for member in (
            "id", "name", "configuration_schema", "execution_bindings",
        ):
            self.assertIn("entry.%s" % member, self.task_ui)
        for explanatory_member in (
            "description", "operating_mode", "usage_examples",
            "available_agent_configurations",
        ):
            self.assertNotIn("entry.%s" % explanatory_member, self.task_ui)
        self.assertNotIn("task_executor_details", self.panel)
        self.assertNotIn("profileDials(profile)", self.task_ui)
        self.assertNotIn("executor-config-note", self.task_ui)
        self.assertIn("Object.entries(schema)", self.task_ui)
        self.assertIn('definition.type === "integer"', self.task_ui)
        self.assertIn('min="${esc(definition.minimum)}"', self.task_ui)
        self.assertIn('onTaskConfigurationChange(this)', self.task_ui)
        self.assertIn('Number(control.value) < Number(control.min)',
                      self.task_ui)
        self.assertIn("definition.default", self.task_ui)
        self.assertIn('definition.type === "choice"', self.task_ui)
        self.assertIn("definition.choices || []", self.task_ui)
        self.assertIn('definition.type === "boolean"', self.task_ui)
        self.assertIn('definition.type === "number"', self.task_ui)
        self.assertIn('definition.type === "object"', self.task_ui)
        self.assertIn('definition.type === "task_executor"', self.task_ui)
        self.assertIn("data-task-config-optional", self.task_ui)
        self.assertIn("taskConfigurationApplicable", self.task_ui)
        self.assertIn("renderTaskConfigurationSchema", self.task_ui)
        self.assertIn("setTaskConfigurationValue", self.task_ui)
        self.assertNotIn("JSON.parse(value)", self.task_ui)
        self.assertIn('value === ""', self.task_ui)
        for copied_constant in (
            '"agent_call"', "max_rounds", "closure_policy",
        ):
            self.assertNotIn(copied_constant, self.task_ui)
        self.assertIn('id="t_profile"', self.panel)
        self.assertIn('id="t_prompt_set"', self.panel)
        self.assertIn("entry.execution_bindings", self.task_ui)
        self.assertIn("taskUsesExecutionBinding(entry.id", self.task_ui)
        self.assertIn("payload.profile = profile", self.task_ui)
        self.assertIn(
            'payload.prompt_set = document.getElementById("t_prompt_set")',
            self.task_ui,
        )
        task_dialog = re.search(
            r'<dialog id="taskform"(.*?)</dialog>', self.panel, re.S
        ).group(1)
        self.assertLess(
            task_dialog.index('id="t_profile_field"'),
            task_dialog.index('id="task_staffing"'),
        )
        self.assertLess(
            task_dialog.index('id="task_staffing"'),
            task_dialog.index('id="t_prompt_set_field"'),
        )
        self.assertLess(
            task_dialog.index('id="task_staffing"'),
            task_dialog.index('id="task_configuration"'),
        )

    def test_optional_configuration_uses_one_closed_advanced_layer(self):
        layers = re.search(
            r"function taskConfigurationLayers\(schema\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("Object.entries(schema || {})", layers)
        self.assertIn("definition.optional ? advanced : primary", layers)
        self.assertNotIn("reviewed_task", layers)
        self.assertNotIn("deep_task", layers)

        render = re.search(
            r"function renderTaskExecutorEditor\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("renderTaskConfigurationSchema(layers.primary", render)
        self.assertIn("renderTaskConfigurationSchema(layers.advanced", render)
        self.assertIn('id="t_more_btn"', render)
        self.assertIn('id="t_more"', render)
        self.assertIn(
            'style="display:${taskAdvancedOpen ? "block" : "none"}"',
            render,
        )
        self.assertNotIn("reviewed_task", render)
        self.assertNotIn("deep_task", render)
        self.assertIn("let taskAdvancedOpen = false;", self.task_ui)

        change = re.search(
            r"function onTaskConfigurationChange\(control\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertNotIn("taskAdvancedOpen = false", change)
        executor_change = re.search(
            r"function onTaskExecutorChange\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("taskAdvancedOpen = false", executor_change)
        self.assertGreaterEqual(
            self.task_ui.count("taskAdvancedOpen = false"), 2
        )
        self.assertIn(
            '"#task_configuration [data-task-config]"', self.task_ui
        )

    def test_reviewed_and_deep_share_profile_and_prompt_bindings(self):
        profile_loader = re.search(
            r"async function loadTaskProfiles\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("await loadProfiles()", profile_loader)
        self.assertIn("selectableLaunchProfiles(launchProfiles)", profile_loader)
        self.assertNotIn("legacy", profile_loader)

        execution_binding = re.search(
            r"function taskUsesExecutionBinding\(executor, binding\) "
            r"\{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("entry.execution_bindings", execution_binding)
        self.assertIn("bindings[binding] === true", execution_binding)
        self.assertNotIn("TASK_STRATEGY_PROFILE_EXECUTORS", self.task_ui)
        self.assertNotIn("TASK_PROMPT_SET_EXECUTORS", self.task_ui)

        submit = self.task_ui[
            self.task_ui.index("async function submitTaskForm"):
            self.task_ui.index("function taskContext")
        ]
        self.assertIn(
            'taskUsesExecutionBinding(taskExecutorSelected, "strategy_profile")',
            submit,
        )
        self.assertIn('error.textContent = "choose a strategy profile"', submit)
        self.assertIn("selectableLaunchProfiles(launchProfiles).some(", submit)
        self.assertIn("payload.profile = profile", submit)
        self.assertIn(
            'taskUsesExecutionBinding(taskExecutorSelected, "prompt_set")',
            submit,
        )
        self.assertIn(
            'taskUsesExecutionBinding(taskExecutorSelected, "staffing")',
            submit,
        )

    def test_direct_order_preserves_closed_project_bound_request(self):
        body = re.search(
            r"const requestDoc = \{(.*?)\n  \};", self.task_ui, re.S
        ).group(1)
        self.assertRegex(
            body,
            r'work_area: binding,\s+request,\s+context: "",\s+'
            r"reference_documents: taskReferences\.slice\(\),\s*$",
        )
        task_dialog = re.search(
            r'<dialog id="taskform"(.*?)</dialog>', self.panel, re.S
        ).group(1)
        self.assertNotIn('id="t_context"', task_dialog)
        self.assertNotIn("Background the executor should use", task_dialog)
        self.assertIn("requestDoc.output_directory = output", self.task_ui)
        self.assertIn("reference_documents: taskReferences.slice()", self.task_ui)
        self.assertIn("function moveTaskReference", self.task_ui)
        self.assertIn('path = "/api/tasks"', self.task_ui)
        self.assertEqual(self.task_ui.count("await postJSON(path, payload)"), 1)

    def test_creativity_initial_genes_uses_one_local_json_editor(self):
        task_dialog = re.search(
            r'<dialog id="taskform"(.*?)</dialog>', self.panel, re.S
        ).group(1)
        self.assertIn('id="t_initial_genes" class="mono"', task_dialog)
        self.assertIn('id="t_initial_genes_file" type="file"', task_dialog)
        self.assertIn('accept=".json,application/json"', task_dialog)
        self.assertIn("Load JSON file…", task_dialog)
        self.assertEqual(task_dialog.count('id="t_initial_genes"'), 1)
        self.assertIn('file.text()', self.task_ui)
        self.assertIn('document.getElementById("t_initial_genes").value = contents',
                      self.task_ui)
        self.assertIn('entry.id === "creativity"', self.task_ui)
        self.assertIn('payload.initial_genes = JSON.parse(initialGenesText)',
                      self.task_ui)
        self.assertIn('if (initialGenesText)', self.task_ui)
        self.assertIn('#t_initial_genes {', self.panel)
        self.assertIn("configured number of inspiration fragments", task_dialog)
        self.assertIn('return "Candidates per generation"', self.task_ui)

    def test_creativity_renders_search_genes_and_every_evaluation(self):
        for text in (
            "function creativitySearchMaterial",
            "Search genes (${dimensions.length})",
            "function creativityCandidateEvaluations",
            "Evaluated candidates (${items.length})",
            "constraint-invalid",
            "Constraint violations",
            "creativityCandidateEvaluations(view.candidate_evaluations, sparse)",
        ):
            self.assertIn(text, self.panel)

    def test_slice_plan_values_are_visible_and_read_only(self):
        self.assertIn("function slicePlanSummary(producerMap)",
                      self.panel)
        self.assertIn("choices.draft_slice_note", self.panel)
        self.assertIn("choices.implement", self.panel)
        self.assertNotIn("JSON.stringify(material)", self.panel)
        for retired in (
            "openProducerTask", "openSliceMaterial", "writeSliceMaterial",
            "slicematerialdlg", "/slices/${", "taskProducerTarget",
        ):
            self.assertNotIn(retired, self.panel)

    def test_writes_disable_once_and_surface_refusals_verbatim(self):
        self.assertIn("taskSubmitPending = true", self.task_ui)
        self.assertIn(
            "taskSubmitPending || !taskExecutorSelected", self.task_ui
        )
        self.assertIn(
            "taskSubmitPending = false;\n    syncTaskSubmitDisabled();",
            self.task_ui,
        )
        options = re.search(
            r"function taskExecutorOptions\(preferred\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("syncTaskSubmitDisabled()", options)
        self.assertNotIn(".disabled = !taskExecutorSelected", options)
        self.assertIn("error.textContent = e.message", self.task_ui)
        self.assertNotIn("setTimeout", self.task_ui)
        self.assertNotIn("setInterval", self.task_ui)

    def test_direct_order_cannot_close_while_pending_and_closes_on_success(self):
        task_dialog = re.search(
            r'<dialog id="taskform"(.*?)</dialog>', self.panel, re.S
        ).group(1)
        self.assertIn(
            'oncancel="if (taskSubmitPending) event.preventDefault()"',
            self.panel,
        )
        self.assertIn('id="task_close"', task_dialog)
        submit_guard = re.search(
            r"function syncTaskSubmitDisabled\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn(
            'document.getElementById("task_close").disabled = taskSubmitPending',
            submit_guard,
        )
        self.assertLess(
            self.task_ui.index("taskSubmitPending = true"),
            self.task_ui.index("await postJSON(path, payload)"),
        )
        self.assertLess(
            self.task_ui.index("await postJSON(path, payload)"),
            self.task_ui.index(
                'document.getElementById("taskform").close()'
            ),
        )
        self.assertLess(
            self.task_ui.index(
                'document.getElementById("taskform").close()'
            ),
            self.task_ui.rindex("taskSubmitPending = false"),
        )
        self.assertNotIn("task_accepted", self.panel)

    def test_task_history_and_chips_use_only_canonical_records(self):
        self.assertIn('onclick="newTask(event,', self.panel)
        self.assertIn('id="taskform"', self.panel)
        # No cross-project task list button any more (operator, 2026-08-18):
        # standalone tasks are listed in the sidebar, bounded and newest first,
        # and the dialog only ever shows one task.
        self.assertNotIn('id="taskHistoryBtn"', self.panel)
        self.assertNotIn("function openTaskHistory", self.panel)
        # A task opens as a page in the right pane (like a run or a
        # session), with Stop while it runs; the modal is gone.
        self.assertNotIn('id="taskhistorydialog"', self.panel)
        self.assertIn("function renderTaskPage", self.panel)
        self.assertIn('"/api/tasks/" + encodeURIComponent(selectedTask) + "/stop"',
                      self.panel)
        self.assertEqual(self.task_ui.count('api("/api/tasks")'), 0)
        self.assertIn(
            'api("/api/tasks/" + encodeURIComponent(id)', self.panel
        )
        # No per-run task record polling remains: nothing consumed it once
        # the unit "Tasks" chip line went. A run-scoped read happens only
        # when a task page is opened from inside a run.
        self.assertNotIn("function refreshSelectedTaskRecords", self.panel)
        self.assertNotIn('"/api/tasks?run_id="', self.panel)
        self.assertIn('"?run_id=" + encodeURIComponent(runId)', self.panel)
        # The per-unit "Tasks" chip line was dropped from the unit history
        # (operator, 2026-08-18): draft/round/verify/Brainstorming chips
        # already carry the same calls with more detail.
        self.assertNotIn('addLine("Tasks", "", taskChips)', self.panel)
        self.assertNotIn(".map(taskRecordById).filter(Boolean).map(taskChip)",
                         self.panel)
        self.assertNotIn("context.unit ===", self.task_ui)

    def test_run_detail_no_longer_polls_task_records(self):
        detail = self.panel.split(
            "async function refreshDetail() {", 1
        )[1].split("async function showStory", 1)[0]
        self.assertIn('const d = await api("/api/runs/" + runId)', detail)
        self.assertNotIn("refreshSelectedTaskRecords", detail)
        self.assertNotIn("refreshTaskHistory()", detail)
        # A terminal task page is not re-rendered by the tick (the operator
        # may be reading it); a running one refreshes and keeps its
        # <details> open state.
        page = self.panel.split("async function refreshTaskPage() {", 1)[1]
        page = page.split("\n}\n", 1)[0]
        self.assertIn("lastTaskPage.result !== null && !taskStopping) return", page)
        self.assertIn("paintTaskPage()", page)
        painter = re.search(
            r"function paintTaskPage\(\) \{(.*?)\n\}", self.panel, re.S
        ).group(1)
        self.assertIn("detailsOpen", painter)
        self.assertIn('details[data-task-detail-key]', painter)
        self.assertIn("node.dataset.taskDetailKey", painter)
        self.assertIn("detailsOpen.has(key)", painter)
        self.assertIn("paintSeq !== taskPagePaintSeq", painter)
        self.assertIn("selectedTask !== taskId", painter)
        self.assertIn("syncRequestMore(det)", painter)
        self.assertIn('pendingLanding === "top" ? 0 : det.scrollTop', painter)
        self.assertEqual(painter.count("det.scrollTop = top;"), 2)
        settled = painter.split("requestAnimationFrame(() => {", 1)[1]
        self.assertLess(
            settled.index("syncRequestMore(det);"),
            settled.index("det.scrollTop = top;"),
        )
        for key in (
            "task-control-history", "creativity-search",
            "creativity-evaluations", "creativity-candidate:",
            "physical-calls", "native-result",
        ):
            self.assertIn(f'data-task-detail-key="{key}', self.panel)

    def test_milestone_verification_renders_as_task_backed_peer(self):
        row = re.search(
            r"const verificationRow = u => \{(.*?)\n      \};",
            self.panel,
            re.S,
        ).group(1)
        for field in (
            "u.task", "task.task_executor", "task.status",
            "task.duration_s", "task.token_usage_partial",
            "task.cost_partial",
        ):
            self.assertIn(field, row)
        self.assertIn("pipelineCategoryRow(", row)
        self.assertIn("unitHistory(u, s, running)", row)
        self.assertIn("pipelineGitLink(u)", row)
        self.assertIn("openTaskDetail", row)
        self.assertNotIn("native_result", row)

        pipeline = self.panel.split("const verificationAfter = new Map();", 1)[1]
        pipeline = pipeline.split("<div class=\"card\"><h3>Pipeline", 1)[0]
        self.assertIn("appendVerifications(sl.id)", pipeline)
        self.assertIn("seen[u.unit] = 1", pipeline)
        self.assertLess(
            pipeline.index("appendVerifications(sl.id)"),
            pipeline.index("if (seen[u.unit]) return"),
        )

        detail = re.search(
            r"function renderTaskPage\(record, admittedAt, taskPipeline = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn('executor.replace(/_/g, " ")', detail)
        self.assertNotIn(
            'executor === "brainstorming" ? "brainstorming task" : "agent call"',
            detail,
        )

    def test_task_detail_preserves_native_result_and_accounting(self):
        detail = re.search(
            r"function renderTaskPage\(record, admittedAt, taskPipeline = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        for field in (
            "record.order", "taskStaffingLine(record)", "result.reason",
            "accounting.duration_s", "result.token_usage_partial",
            "result.cost_partial", "result.native_result",
        ):
            self.assertIn(field, detail)
        self.assertIn("record.resolved_staffing", self.panel)
        self.assertIn("costHtml(result.cost, result.cost_partial)", detail)
        self.assertIn(
            "tokenUsageHtml(result.token_usage, result.token_usage_partial)",
            detail,
        )
        self.assertIn("opaque TaskExecutor output", detail)
        self.assertNotIn("actual staffing", detail.lower())

    def test_task_request_and_reviewed_pipelines_reuse_existing_presenters(self):
        self.assertIn("-webkit-line-clamp: 2", self.panel)
        self.assertIn("clamp.scrollHeight > clamp.clientHeight + 1", self.panel)
        self.assertIn('onclick="openRequest()"', self.panel)
        self.assertIn("mdRender(fullRequestText)", self.panel)
        detail = re.search(
            r"function renderTaskPage\(record, admittedAt, taskPipeline = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn('fullRequestText = String(request.request || "")', detail)
        self.assertIn("requestTitle(fullRequestText)", detail)
        self.assertNotIn('<div class="card"><h3>Request</h3>', detail)
        self.assertIn('executor === "deep_task"', detail)
        self.assertIn("deepTaskPipeline(taskPipeline)", detail)
        self.assertIn('executor === "reviewed_task"', detail)
        self.assertIn("reviewedTaskPipeline(taskPipeline)", detail)

        shared = re.search(
            r"function renderSlicePipeline\(slice, units, activity, running, "
            r"options = \{\}\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("pipelineCategoryRow", shared)
        self.assertIn("pipelineUnitRow", shared)
        self.assertIn("pipelineGhostRow", shared)
        self.assertEqual(self.panel.count("renderSlicePipeline("), 3)

        deep = re.search(
            r"function deepTaskPipeline\(view\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("view.children", deep)
        self.assertIn("source_task_id", deep)
        self.assertIn("unit.part = child.part", deep)
        self.assertIn('label: "Deep task"', deep)
        self.assertIn("renderSlicePipeline(", deep)
        self.assertIn("lastTaskPipeline", self.panel)
        self.assertIn(
            "data.deep_task || data.reviewed_task || data.creativity || data.duel || null", self.panel
        )

        reviewed = re.search(
            r"function reviewedTaskPipeline\(view\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("pipelineCategoryRow(", reviewed)
        self.assertIn("pipelineUnitRow(", reviewed)
        self.assertIn("unit.source_task_id", reviewed)
        self.assertIn('activity.process === "running"', reviewed)
        self.assertIn('view.task_kind === "complete_verification"', reviewed)
        self.assertNotIn("renderSlicePipeline(", reviewed)

        unit_row = re.search(
            r"function pipelineUnitRow\(u, activity, running, scopeKey, "
            r"labelOverride = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("u.source_task_id", unit_row)
        self.assertIn('`Implementation${u.part ? ` ${u.part}` : ""}`', unit_row)
        self.assertIn("pipelineGitLink(u, taskId)", unit_row)
        self.assertIn("unitHistory(u, activity || {}, running, taskId)", unit_row)
        self.assertIn("task:${taskId}:unit:${u.unit}", unit_row)
        self.assertGreaterEqual(self.panel.count("evidenceTaskArg(taskId)"), 8)

        for viewer in ("showStory", "showDoc", "showCommit"):
            body = re.search(
                rf"async function {viewer}\(.*?\) \{{(.*?)\n\}}",
                self.panel,
                re.S,
            ).group(1)
            self.assertIn("/api/tasks/${encodeURIComponent(taskId)}", body)

    def test_failed_and_successor_tasks_are_not_collapsed(self):
        row = re.search(
            r"function taskRow\(row\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("record.id", row)
        self.assertIn("taskState(record, row.lifecycle)", row)
        self.assertIn("task_executor", row)
        self.assertIn("const total = taskStatusClock(row)", row)
        self.assertIn("${total}", row)
        self.assertIn(
            '<div class="run-info-row"><div class="activity-line sidebar">',
            row,
        )
        self.assertIn("<span>${esc(bits)}</span>", row)
        secondary = re.search(
            r"\n  \.activity-line\.sidebar \{(.*?)\}", self.panel, re.S
        ).group(1)
        self.assertIn("font-size: 10.5px", secondary)
        self.assertIn("white-space: nowrap", secondary)
        clock = re.search(
            r"function taskStatusClock\(row\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn("row.work_duration_s == null &&", clock)
        self.assertIn("Number(inFlight.started_at) > 0", clock)
        self.assertIn("row.work_duration_s == null ? 0", clock)
        self.assertIn('row.process === "running"', clock)
        self.assertIn("const inFlight = running ? row.in_flight : null", clock)
        self.assertIn('"run-total", "total task work"', clock)
        sidebar_items = re.search(
            r"function sidebarItems\(runs, taskRows\) \{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn('row.process === "running"', sidebar_items)
        self.assertIn(": record.result === null", sidebar_items)
        for forbidden in ("predecessor", "successor", "review number"):
            self.assertNotIn(forbidden, self.task_ui.lower())

    def test_existing_execution_and_non_task_activity_stays_additive(self):
        self.assertIn('d.task_id ? `task ${d.task_id}`', self.panel)
        self.assertIn('r.task_id ? `task ${r.task_id}`', self.panel)
        self.assertIn('b.task_id ? `task ${b.task_id}`', self.panel)
        for existing in (
            "verificationChip", "sealChip", "repairChip",
            "reclassifyHistoryChips", "brainstormChip", "draftChip",
            "roundChip",
        ):
            self.assertIn("function %s" % existing, self.panel)
        self.assertNotIn('addLine("Tasks", "", taskChips)', self.panel)

    def test_periodic_not_verified_has_distinct_chip_and_evidence(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for executable panel checks")
        names = ("esc", "sealVerificationText", "sealChip", "verificationChip", "showStory")
        sources = [re.search(
            r"(?:async )?function " + name + r"\([^\n]*\) \{.*?\n\}",
            self.panel, re.S,
        ).group(0) for name in names]
        checks = r"""
const assert = require('node:assert/strict');
const fmtDur = () => '', evidenceTaskArg = () => '';
const fmtTokenUsage = () => '', costHtml = () => '', tokenUsageHtml = () => '';
const selected = 'run', lastBilling = null;
const event = {story: 'verify', unit: 'slice_impl-04', seq: 7,
  status: 'not_verified', ok: false, stable: true, boundary: 'periodic',
  deferred_failures: [{command: 'run tests', owner_slice_id: 8,
    authorization: 'A1 <explicit>', evidence: 'unchanged test_store failure'}],
  results: [{command: 'run tests', exit_code: 1, evidence: 'old schema'}]};
const chip = verificationChip(event);
assert.match(chip, /chip sev23/);
assert.match(chip, /NOT VERIFIED/);
assert.doesNotMatch(chip, /chip pass|chip fail/);
assert.match(verificationChip({seq: 8, ok: true, stable: true}), /suite · passed/);
assert.match(verificationChip({seq: 9, ok: false, stable: true}), /suite · failed/);
const seal = {passed: true, verification_status: 'not_verified', verification_event_seq: 7};
assert.match(sealChip(seal, 'slice_impl-04'), /NOT VERIFIED/);
assert.doesNotMatch(sealVerificationText(seal), /verification passed/);
assert.match(sealVerificationText({verification_event_seq: 99}), /unavailable/);
const elements = {storyTitle: {}, storyBody: {}, story: {showModal() {}}};
global.document = {getElementById: id => elements[id]};
const api = async () => event;
(async () => {
  await showStory('verify:7');
  const body = elements.storyBody.innerHTML;
  assert.match(body, /NOT VERIFIED/);
  assert.match(body, /Slice 8 · run tests/);
  assert.match(body, /A1 &lt;explicit&gt;/);
  assert.match(body, /unchanged test_store failure/);
  assert.match(body, /exit 1/);
  assert.match(body, /full suite must pass at milestone closure/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        completed = subprocess.run(
            [node, "-e", "\n".join(sources) + checks],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_worker_output_banner_shows_scheduled_recovery(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for executable panel checks")
        esc = re.search(r"function esc\([^\n]*\) \{.*?\n\}", self.panel, re.S).group(0)
        banner = self.panel.split('    if (runView !== "edit" && s.failure_reason) {', 1)[1]
        banner = banner.split('    if (runView !== "edit")', 1)[0]
        source = esc + "\nfunction renderFailure(failure) {\n" + (
            "const sum = {failure}, s = {failure_reason: 'invalid contract'};\n"
            "let html = '';\n{\n" + banner + "\nreturn html;\n}\n"
        )
        checks = r"""
const assert = require('node:assert/strict');
const output = renderFailure({type: 'worker_output', resume_at: '2026-09-23T00:15:00+0000'});
assert.match(output, /worker_output/);
assert.match(output, /auto-resume at 00:15/);
assert.match(output, /chip sev23/);
assert.match(renderFailure({type: 'worker_output'}), /auto-resume pending/);
const protocol = renderFailure({type: 'worker_protocol', resume_at: '2026-09-23T00:15:00+0000'});
assert.doesNotMatch(protocol, /auto-resume/);
assert.match(protocol, /chip fail/);
"""
        completed = subprocess.run(
            [node, "-e", source + checks], capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
