"""Focused static contract checks for the Slice 8 task panel."""

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
            '"worker"', '"brainstorming"', "max_rounds", "closure_policy",
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

    def test_slice_stops_before_task_history(self):
        self.assertIn('onclick="newTask(event,', self.panel)
        self.assertIn('id="taskform"', self.panel)
        self.assertNotIn('"/api/tasks/"', self.task_ui)
        for later_surface in ("task chip", "result polling", "accounting view"):
            self.assertNotIn(later_surface, self.task_ui.lower())


if __name__ == "__main__":
    unittest.main()
