"""Task controls read only their owners until family quiescence is needed."""

import copy
from contextlib import contextmanager
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import registry, task_api, tasks
from orchestrator.tests.test_tasks import task_order, task_result


class TaskPointReadTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="orch-task-point-reads-")
        self.addCleanup(temporary.cleanup)
        self.home = os.path.join(temporary.name, "home")
        self.primary = temporary.name
        self.store = task_api.StandaloneTaskStore(self.home)
        self.host = task_api.DirectTaskHost(self.home, store=self.store)

    def _admit(self, parent=None):
        order = task_order(work_area={
            "workspace_path": self.primary,
            "primary": self.primary,
            "additional": [],
        })
        if parent is None:
            return self.store.admit(order, {}, self.primary)
        with registry.locked(self.home):
            return self.store.admit_related_locked(
                parent["id"], "implementation", "a", order, {}, self.primary,
            )

    def _rewrite(self, identity, change):
        key = task_api.task_key(identity)
        current = self.store._store.read(key)
        document = copy.deepcopy(current["value"])
        change(document)
        self.assertTrue(self.store._store.cas(
            key, current["revision"], document,
        ).ok)

    @contextmanager
    def _point_reads(self):
        with mock.patch.object(
            self.store, "_load", side_effect=AssertionError("full task load"),
        ), mock.patch.object(
            self.store._store, "list_entries",
            side_effect=AssertionError("full task listing"),
        ), mock.patch.object(
            self.store._store, "read", wraps=self.store._store.read,
        ) as reads:
            yield reads

    def test_record_reads_one_key_and_returns_detached_data(self):
        target = self._admit()
        for _ in range(8):
            self._admit()
        with self._point_reads() as reads:
            record = self.store.record(target["id"])
            self.assertEqual(record, target)
            reads.assert_called_once_with(task_api.task_key(target["id"]))
            record["order"]["request"]["context"]["nested"].append("changed")
            self.assertEqual(self.store.record(target["id"]), target)

    def test_record_rejects_unknown_or_invalid_identity(self):
        for identity in (None, "", "missing-task"):
            with self.subTest(identity=identity), self._point_reads():
                with self.assertRaises(tasks.TaskRecordError):
                    self.store.record(identity)

    def test_record_rejects_mismatched_identity_and_malformed_document(self):
        record = self._admit()
        self._rewrite(record["id"], lambda document: document["record"].update(
            id="different-task",
        ))
        with self._point_reads(), self.assertRaisesRegex(
            tasks.TaskRecordError, "unknown task",
        ):
            self.store.record(record["id"])
        self._rewrite(record["id"], lambda document: document.update(
            schema_version=-1,
        ))
        with self._point_reads(), self.assertRaisesRegex(
            tasks.TaskRecordError, "malformed",
        ):
            self.store.record(record["id"])

    def test_owner_chain_reads_each_ancestor_once(self):
        root = self._admit()
        child = self._admit(root)
        grandchild = self._admit(child)
        for _ in range(8):
            self._admit()
        with self._point_reads() as reads:
            chain = self.store.owner_chain(grandchild["id"])
            self.assertEqual(chain, [grandchild, child, root])
            self.assertEqual(reads.call_args_list, [
                mock.call(task_api.task_key(record["id"]))
                for record in (grandchild, child, root)
            ])

    def test_owner_chain_stops_at_missing_parent_and_cycles(self):
        root = self._admit()
        child = self._admit(root)
        for parent_id in ("missing-parent", child["id"]):
            with self.subTest(parent_id=parent_id):
                self._rewrite(root["id"], lambda document: document["record"].update(
                    parent={"task_id": parent_id, "phase": "implementation", "part": "a"},
                ))
                with self._point_reads() as reads:
                    chain = self.store.owner_chain(child["id"])
                    self.assertEqual([record["id"] for record in chain], [
                        child["id"], root["id"],
                    ])
                    self.assertLessEqual(reads.call_count, 3)
        with self._point_reads(), self.assertRaisesRegex(
            tasks.TaskRecordError, "unknown task",
        ):
            self.store.owner_chain("missing-task")

    def test_owner_chain_does_not_hide_a_malformed_existing_parent(self):
        root = self._admit()
        child = self._admit(root)
        self._rewrite(root["id"], lambda document: document.update(
            schema_version=-1,
        ))
        with self._point_reads(), self.assertRaisesRegex(
            tasks.TaskRecordError, "malformed",
        ):
            self.store.owner_chain(child["id"])

    def test_terminal_child_controls_keep_owner_without_loading_family(self):
        root = self._admit()
        child = self._admit(root)
        self._admit()
        self.store.record_result(child["id"], task_result())
        with self._point_reads() as reads, mock.patch.object(
            self.host, "_family", side_effect=AssertionError("family not needed"),
        ):
            lifecycle = self.host.lifecycle(child["id"])
            self.assertEqual(lifecycle["root_task_id"], root["id"])
            self.assertEqual(lifecycle["status"], "success")
            self.assertFalse(lifecycle["can_pause"])
            self.assertFalse(lifecycle["can_resume"])
            self.assertIsNone(lifecycle["blocked_reason"])
            self.assertLessEqual(reads.call_count, 3)
            self.assertEqual({call.args[0] for call in reads.call_args_list}, {
                task_api.task_key(root["id"]), task_api.task_key(child["id"]),
            })

    def test_running_child_controls_inherit_owner_stop_without_loading_family(self):
        root = self._admit()
        child = self._admit(root)
        self._admit()
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                if stopped:
                    with registry.locked(self.home):
                        self.store.record_stop_locked(root["id"], "operator stopped owner")
                with self._point_reads() as reads, mock.patch.object(
                    self.host, "_family", side_effect=AssertionError("family not needed"),
                ):
                    lifecycle = self.host.lifecycle(child["id"])
                    self.assertEqual(lifecycle["root_task_id"], root["id"])
                    self.assertEqual(lifecycle["status"], "running")
                    self.assertEqual(lifecycle["can_pause"], not stopped)
                    self.assertFalse(lifecycle["can_resume"])
                    if stopped:
                        self.assertIn("Cancellation is pending", lifecycle["blocked_reason"])
                    else:
                        self.assertIsNone(lifecycle["blocked_reason"])
                    self.assertLessEqual(reads.call_count, 7)
                    self.assertEqual({call.args[0] for call in reads.call_args_list}, {
                        task_api.task_key(root["id"]), task_api.task_key(child["id"]),
                    })

    def test_paused_controls_check_quiescence_of_terminal_descendants(self):
        root = self._admit()
        child = self._admit(root)
        grandchild = self._admit(child)
        self.store.record_result(grandchild["id"], task_result())
        identities = [root["id"], child["id"], grandchild["id"]]
        for pending, busy in ((False, False), (False, True), (True, False)):
            with self.subTest(pending=pending, busy=busy):
                with registry.locked(self.home):
                    self.store.pause_locked(root["id"], "operator paused owner", pending=pending)
                with mock.patch.object(
                    self.host, "_family", wraps=self.host._family,
                ) as family, mock.patch.object(
                    self.host, "_discussions_quiescent", return_value=True,
                ) as discussions, mock.patch.object(
                    self.host, "_ensure_workers_quiescent",
                    side_effect=task_api.ExecutionBusy("worker still stopping") if busy else None,
                ) as workers:
                    lifecycle = self.host.lifecycle(root["id"])
                    family.assert_called_once_with(root["id"])
                    for check in (discussions, workers):
                        self.assertEqual(check.call_count, 1)
                        self.assertEqual([
                            record["id"] for record in check.call_args.args[0]
                        ], identities)
                    self.assertEqual(lifecycle["status"], "pausing" if pending else "paused")
                    self.assertEqual(lifecycle["can_resume"], not (pending or busy))
                    self.assertFalse(lifecycle["can_pause"])
                    self.assertEqual(lifecycle["blocked_reason"],
                                     "worker still stopping" if busy else None)


if __name__ == "__main__":
    unittest.main()
