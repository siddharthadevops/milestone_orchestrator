"""Focused static contract checks for task ordering and plan display."""

import re
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
            r"work_area: binding,\s+request,\s+context: .*?,\s+"
            r"reference_documents: taskReferences\.slice\(\),\s*$",
        )
        self.assertIn("requestDoc.output_directory = output", self.task_ui)
        self.assertIn("reference_documents: taskReferences.slice()", self.task_ui)
        self.assertIn("function moveTaskReference", self.task_ui)
        self.assertIn('path = "/api/tasks"', self.task_ui)
        self.assertEqual(self.task_ui.count("await postJSON(path, payload)"), 1)

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
        self.assertIn("wasOpen", painter)
        self.assertIn("syncRequestMore(det)", painter)

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
            r"function renderTaskPage\(record, admittedAt, deepTask = null\) "
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
            r"function renderTaskPage\(record, admittedAt, deepTask = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        for field in (
            "record.order", "taskStaffingLine(record)", "result.reason",
            "result.duration_s", "result.token_usage_partial",
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

    def test_task_request_and_deep_task_reuse_existing_presenters(self):
        self.assertIn("-webkit-line-clamp: 2", self.panel)
        self.assertIn("clamp.scrollHeight > clamp.clientHeight + 1", self.panel)
        self.assertIn('onclick="openRequest()"', self.panel)
        self.assertIn("mdRender(fullRequestText)", self.panel)
        detail = re.search(
            r"function renderTaskPage\(record, admittedAt, deepTask = null\) "
            r"\{(.*?)\n\}",
            self.panel,
            re.S,
        ).group(1)
        self.assertIn('fullRequestText = String(request.request || "")', detail)
        self.assertIn("requestTitle(fullRequestText)", detail)
        self.assertNotIn('<div class="card"><h3>Request</h3>', detail)
        self.assertIn('executor === "deep_task"', detail)
        self.assertIn("deepTaskPipeline(deepTask)", detail)

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
        self.assertIn("lastTaskDeep", self.panel)
        self.assertIn("data.deep_task || null", self.panel)

        unit_row = re.search(
            r"function pipelineUnitRow\(u, activity, running, scopeKey\) "
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
        self.assertIn("taskState(record)", row)
        self.assertIn("task_executor", row)
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


if __name__ == "__main__":
    unittest.main()
