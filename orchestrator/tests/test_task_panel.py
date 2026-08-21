"""Focused static contract checks for the Slice 8-9 task panel."""

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
            "/* ---- task ordering and slice producer selection", 1
        )[1].split("/* ---- new brainstorming:", 1)[0]

    def test_one_catalogue_drives_description_and_configuration(self):
        self.assertEqual(self.task_ui.count('api("/api/task-executors")'), 1)
        for member in (
            "id", "name", "description", "operating_mode",
            "usage_examples", "available_agent_configurations",
            "configuration_schema",
        ):
            self.assertIn("entry.%s" % member, self.task_ui)
        self.assertIn("Object.entries(schema)", self.task_ui)
        self.assertIn('definition.type === "integer"', self.task_ui)
        self.assertIn('min="${esc(definition.minimum)}"', self.task_ui)
        self.assertIn("definition.default", self.task_ui)
        self.assertIn('definition.type === "choice"', self.task_ui)
        self.assertIn("definition.choices || []", self.task_ui)
        for copied_constant in (
            '"agent_call"', '"brainstorming"', "max_rounds", "closure_policy",
        ):
            self.assertNotIn(copied_constant, self.task_ui)

    def test_direct_order_preserves_closed_project_bound_request(self):
        body = re.search(
            r"const requestDoc = \{(.*?)\n    \};", self.task_ui, re.S
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
        self.assertIn("`Task accepted · ${data.task.id}`", self.task_ui)
        self.assertEqual(self.task_ui.count("await postJSON(path, payload)"), 1)

    def test_each_slice_producer_is_confirmed_independently(self):
        self.assertEqual(self.task_ui.count("onclick=\"openProducerTask("), 2)
        self.assertIn("'draft_slice_note'", self.task_ui)
        self.assertIn("'implement'", self.task_ui)
        self.assertIn("payload.task_kind = producerTarget.taskKind", self.task_ui)
        self.assertIn(
            "/slices/${producerTarget.sliceId}/producer", self.task_ui
        )
        self.assertIn("data.producer_task_executor", self.task_ui)
        self.assertIn("applyConfirmedProducerMap", self.task_ui)
        self.assertIn("visibleProducerRunId !== selected", self.task_ui)

    def test_each_slice_material_is_visible_settable_and_clearable(self):
        # One control, beside the two producer choices, on the same row.
        controls = re.search(
            r"function producerControls\(sliceId, producerMap, material\) \{"
            r"(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("openProducerTask(${sliceId},'draft_slice_note')", controls)
        self.assertIn("openProducerTask(${sliceId},'implement')", controls)
        self.assertIn("openSliceMaterial(${sliceId})", controls)
        self.assertIn("sliceMaterialLabel(material)", controls)
        self.assertEqual(self.task_ui.count("onclick=\"openSliceMaterial("), 1)
        # The current value comes from confirmed state. Only ABSENCE reads
        # as the session's default; JSON string syntax distinguishes every
        # present string, including empty, literal "session default", CR/LF.
        self.assertIn(
            'if (sliceMaterialAbsent(material)) return "session default";',
            self.task_ui,
        )
        self.assertIn("return JSON.stringify(material);", self.task_ui)
        self.assertIn("material === null || material === undefined",
                      self.task_ui)
        self.assertIn("slice.id, slice.material,", self.panel)
        self.assertIn(
            'sliceMaterialAbsent(stored) ? "" : JSON.stringify(stored)',
            self.task_ui,
        )
        self.assertIn("visibleSliceMaterials.get(sliceId)", self.task_ui)
        self.assertIn("visibleProducerRunId !== selected", self.task_ui)

        # Set decodes the box's lossless JSON string representation; clear
        # is its own deliberate act.
        set_ = re.search(
            r"function saveSliceMaterial\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("material = JSON.parse(box)", set_)
        self.assertIn('typeof material !== "string"', set_)
        self.assertIn("writeSliceMaterial(material)", set_)
        self.assertNotIn("trim()", set_)
        self.assertNotIn("|| null", set_)
        # An untouched box posts the STORED string. Actual input is tracked
        # separately because blank means untouched absence while the JSON
        # spelling `""` is the valid explicit empty string.
        self.assertIn("!target.edited", set_)
        self.assertIn("writeSliceMaterial(target.stored)", set_)
        # The same untouched box on a slice that proposes NOTHING writes
        # nothing at all: `""` would author a proposal nobody typed and
        # null would record a withdrawal nobody asked for, and either one
        # would then read as an explicit operator write in plan review.
        # The absent branch closes the dialog ahead of every write call.
        absent = set_.split("if (sliceMaterialAbsent(target.stored))")[1]
        self.assertIn('getElementById("slicematerialdlg").close()',
                      absent.split("return writeSliceMaterial")[0])
        self.assertNotIn(
            "writeSliceMaterial",
            set_.split("if (sliceMaterialAbsent(target.stored))")[0],
        )
        opener = re.search(
            r"function openSliceMaterial\(sliceId\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn(
            "sliceMaterialTarget = {runId: selected, sliceId, stored, "
            "edited: false}",
            opener,
        )
        self.assertIn("box.value = sliceMaterialAbsent(stored)", opener)
        self.assertIn('oninput="markSliceMaterialEdited()"', self.panel)
        edited = re.search(
            r"function markSliceMaterialEdited\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("sliceMaterialTarget.edited = true", edited)
        clear = re.search(
            r"function clearSliceMaterial\(\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        self.assertIn("writeSliceMaterial(null)", clear)

        save = re.search(
            r"async function writeSliceMaterial\(material\) \{(.*?)\n\}",
            self.task_ui,
            re.S,
        ).group(1)
        # Exactly the material route, exactly one request, set or clear.
        self.assertIn("/slices/${\n        target.sliceId}/material", save)
        self.assertEqual(save.count("await postJSON("), 1)
        self.assertIn("{material: material}", save)
        self.assertNotIn("trim()", save)
        # Success renders CONFIRMED state; a refusal renders verbatim.
        self.assertIn("applyConfirmedSliceMaterial(target.sliceId, data.material)",
                      save)
        self.assertIn("error.textContent = e.message; return;", save)
        for forbidden in ("setTimeout", "setInterval", "retry",
                          "/api/staffing/sessions", "skeleton"):
            self.assertNotIn(forbidden, save)

        dialog = re.search(
            r'<dialog id="slicematerialdlg">(.*?)</dialog>', self.panel, re.S
        ).group(1)
        self.assertIn('id="sm_material"', dialog)
        self.assertIn('id="sm_error"', dialog)
        self.assertIn("saveSliceMaterial()", dialog)
        self.assertIn("clearSliceMaterial()", dialog)
        self.assertIn("Enter the kind of work as a JSON string", dialog)
        self.assertIn("preserve line breaks exactly", dialog)
        self.assertIn("Save writes the decoded\n      string unchanged", dialog)
        self.assertIn("leaves an untouched box's stored name exactly as it",
                      dialog)
        self.assertIn("a slice proposing nothing keeps none, and no save of"
                      " its own\n      creates one", dialog)

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

    def test_direct_acknowledgement_cannot_be_dismissed_while_pending(self):
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
                'setTaskMessage("task_accepted", `Task accepted'
            ),
        )
        self.assertLess(
            self.task_ui.index(
                'setTaskMessage("task_accepted", `Task accepted'
            ),
            self.task_ui.rindex("taskSubmitPending = false"),
        )

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
        self.assertIn("wasOpen", page)

    def test_task_detail_preserves_native_result_and_accounting(self):
        detail = re.search(
            r"function renderTaskPage\(record, admittedAt\) \{(.*?)\n\}",
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
