"""Focused proof of the skeleton-backed canonical slice plan."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from orchestrator import canonical_plan, gitops
from orchestrator import state as st


def slice_plan(slice_id=1, **changes):
    value = {
        "id": slice_id,
        "title": "A bounded slice",
        "intent": "Deliver one reviewed outcome.",
        "producer_task_executor": {
            "draft_slice_note": "agent_call",
            "implement": "agent_call",
        },
    }
    value.update(changes)
    return value


def framed(payload):
    if not isinstance(payload, bytes):
        payload = payload.encode("utf-8")
    return (
        b"# Reviewed skeleton\n\n"
        b"## Canonical slice plan\n```json\n"
        + payload
        + b"\n```\n\n## Register 2\n"
    )


def document(slices):
    return framed(
        json.dumps(
            {"slices": slices},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def changed(source, operation):
    value = copy.deepcopy(source)
    operation(value)
    return document(value)


class CanonicalPlanContractTest(unittest.TestCase):
    def test_block_preservation_replaces_only_the_authoritative_span(self):
        old = document([slice_plan(title="Old")])
        new = document([slice_plan(title="New")])
        inert_example = (
            b"````markdown\n"
            + canonical_plan.canonical_block_bytes(old)
            + b"\n````\n\n"
        )
        baseline = inert_example + old
        accepted = inert_example + new

        preserved = canonical_plan.preserve_canonical_block(
            baseline, accepted
        )

        self.assertEqual(preserved, inert_example + new)
        self.assertEqual(
            canonical_plan.canonical_block_bytes(preserved),
            canonical_plan.canonical_block_bytes(new),
        )

    def test_canonical_plan_block_and_closed_schema(self):
        slices = [slice_plan()]
        valid = document(slices)
        result = canonical_plan.validate_canonical_plan(valid)
        self.assertEqual(result["slices"], slices)
        self.assertEqual(
            result["projection"][0]["producer_task_executor"],
            {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "agent_call"},
            },
        )
        preceded_by_example = (
            b"````markdown\nexample\n````\n\n" + valid
        )
        self.assertEqual(
            canonical_plan.validate_canonical_plan(preceded_by_example)[
                "slices"
            ],
            slices,
        )

        variants = {
            "missing": b"# Reviewed skeleton without a plan\n",
            "quoted plan": b"````markdown\n" + valid + b"````\n",
            "duplicate": valid + b"\n" + valid,
            "separated": valid.replace(
                b"## Canonical slice plan\n```json",
                b"## Canonical slice plan\n\n```json",
            ),
            "wrong fence": valid.replace(b"```json", b"```JSON", 1),
            "malformed": framed('{"slices":['),
            "wrong root": framed('{"plan":[]}'),
            "root extra": framed('{"slices":[],"other":true}'),
            "duplicate JSON key": framed('{"slices":[],"slices":[]}'),
            "slice extra": changed(
                slices, lambda value: value[0].__setitem__("other", True)
            ),
            "empty title": changed(
                slices, lambda value: value[0].__setitem__("title", " ")
            ),
            "empty intent": changed(
                slices, lambda value: value[0].__setitem__("intent", "")
            ),
            "retired material": changed(
                slices,
                lambda value: value[0].__setitem__("material", "document"),
            ),
            "boolean id": changed(
                slices, lambda value: value[0].__setitem__("id", True)
            ),
            "duplicate id": document([slice_plan(), slice_plan()]),
            "missing producer": changed(
                slices,
                lambda value: value[0]["producer_task_executor"].pop(
                    "implement"
                ),
            ),
            "configuration": changed(
                slices,
                lambda value: value[0]["producer_task_executor"].__setitem__(
                    "implement",
                    {
                        "task_executor": "agent_call",
                        "configuration": {"role": "implement"},
                    },
                ),
            ),
            "unknown executor": changed(
                slices,
                lambda value: value[0]["producer_task_executor"].__setitem__(
                    "implement", "unknown"
                ),
            ),
        }
        for name, candidate in variants.items():
            with self.subTest(name=name):
                with self.assertRaises(canonical_plan.CanonicalPlanError):
                    canonical_plan.validate_canonical_plan(candidate)

    def test_historical_material_reads_but_new_authorship_refuses_it(self):
        legacy_slices = [slice_plan(material="document")]
        legacy_document = document(legacy_slices)

        with self.assertRaises(canonical_plan.CanonicalPlanError):
            canonical_plan.validate_canonical_plan(legacy_document)

        read = canonical_plan.read_canonical_plan(legacy_document)
        self.assertNotIn("material", read["slices"][0])
        self.assertNotIn("material", read["projection"][0])
        self.assertEqual(read["block"], canonical_plan.canonical_block_bytes(
            legacy_document
        ))

    def test_anchored_executor_spelling_is_read_compatible_only(self):
        legacy = [
            slice_plan(
                producer_task_executor={
                    "draft_slice_note": "worker",
                    "implement": "worker",
                }
            )
        ]
        legacy_document = document(legacy)
        with self.assertRaises(canonical_plan.CanonicalPlanError):
            canonical_plan.validate_canonical_plan(legacy_document)

        retained = canonical_plan.validate_canonical_plan(
            legacy_document,
            anchored_document=legacy_document,
        )
        self.assertEqual(
            retained["slices"][0]["producer_task_executor"],
            legacy[0]["producer_task_executor"],
        )
        self.assertEqual(
            retained["projection"][0]["producer_task_executor"],
            {
                "draft_slice_note": {"task_executor": "agent_call"},
                "implement": {"task_executor": "agent_call"},
            },
        )

        new_legacy = legacy + [
            slice_plan(
                2,
                producer_task_executor={
                    "draft_slice_note": "worker",
                    "implement": "worker",
                },
            )
        ]
        with self.assertRaises(canonical_plan.CanonicalPlanError):
            canonical_plan.validate_canonical_plan(
                document(new_legacy), anchored_document=legacy_document
            )

        current_anchor = document([slice_plan()])
        changed_spelling = changed(
            [slice_plan()],
            lambda value: value[0]["producer_task_executor"].__setitem__(
                "implement", "worker"
            ),
        )
        with self.assertRaises(canonical_plan.CanonicalPlanError):
            canonical_plan.validate_canonical_plan(
                changed_spelling, anchored_document=current_anchor
            )

        current = canonical_plan.validate_canonical_plan(
            document(
                [
                    slice_plan(
                        producer_task_executor={
                            "draft_slice_note": "brainstorming",
                            "implement": "agent_call",
                        }
                    )
                ]
            )
        )
        for selection in current["projection"][0][
            "producer_task_executor"
        ].values():
            self.assertEqual(set(selection), {"task_executor"})


class CanonicalPlanGitBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="orch-canonical-plan-")
        self.workspace = os.path.join(self.temp.name, "workspace")
        os.mkdir(self.workspace)
        self.skeleton = "docs/skeleton.md"
        os.makedirs(os.path.join(self.workspace, "docs"))
        self.state_path = os.path.join(self.temp.name, "state.json")
        self.git("init", "-q")
        self.git("config", "user.name", "Canonical Plan Test")
        self.git("config", "user.email", "canonical-plan@example.invalid")

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ("git",) + args,
            cwd=self.workspace,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write_skeleton(self, content):
        with open(
            os.path.join(self.workspace, self.skeleton), "wb"
        ) as handle:
            handle.write(content)

    def commit_skeleton(self, content, message="canonical plan"):
        self.write_skeleton(content)
        self.git("add", self.skeleton)
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def save_stale_state(self):
        state = st.new_state("Exercise the plan.", self.workspace, {})
        state["milestone"]["slices"] = [
            {"id": 99, "title": "Stale state"}
        ]
        st.save_new(self.state_path, state)

    def establish(self):
        slices = [slice_plan(2), slice_plan(1, material="implementation")]
        revision = self.commit_skeleton(document(slices))
        self.save_stale_state()
        anchor = canonical_plan.anchor_current_plan(
            self.state_path, self.skeleton
        )
        return slices, revision, anchor

    def test_first_anchor_projects_before_plan_use_and_survives_reload(self):
        _slices, revision, anchor = self.establish()
        self.assertEqual(anchor, {"path": self.skeleton, "revision": revision})
        reloaded = st.load(self.state_path)
        self.assertEqual(
            reloaded["milestone"][canonical_plan.ANCHOR_KEY], anchor
        )
        self.assertEqual(
            [item["id"] for item in reloaded["milestone"]["slices"]],
            [2, 1],
        )
        self.assertEqual(
            st.planned_units(reloaded)[:5],
            [
                (st.UNIT_SKELETON, None),
                (st.UNIT_SLICE_DOC, 2),
                (st.UNIT_SLICE_IMPL, 2),
                (st.UNIT_SLICE_DOC, 1),
                (st.UNIT_SLICE_IMPL, 1),
            ],
        )
        committed = gitops.show_file(self.workspace, revision, self.skeleton)
        with open(
            os.path.join(self.workspace, self.skeleton), "rb"
        ) as handle:
            worktree = handle.read()
        self.assertEqual(
            canonical_plan.canonical_block_bytes(committed),
            canonical_plan.canonical_block_bytes(worktree),
        )

        with open(os.path.join(self.workspace, "unrelated.txt"), "w") as handle:
            handle.write("unrelated\n")
        self.git("add", "unrelated.txt")
        self.git("commit", "-q", "-m", "unrelated change")
        self.assertEqual(
            canonical_plan.anchor_current_plan(
                self.state_path, self.skeleton
            ),
            anchor,
        )
        self.assertEqual(
            st.load(self.state_path)["milestone"][canonical_plan.ANCHOR_KEY],
            anchor,
        )

    def test_predispatch_guard_refuses_drift_without_rebaseline(self):
        slices, revision, anchor = self.establish()
        state = st.load(self.state_path)
        dispatch = mock.Mock(return_value="dispatched")
        with mock.patch.object(
            canonical_plan,
            "validate_canonical_plan",
            side_effect=AssertionError("unchanged plans are not revalidated"),
        ):
            self.assertEqual(
                canonical_plan.guarded_dispatch(state, dispatch),
                "dispatched",
            )
        dispatch.assert_called_once_with()

        baseline = copy.deepcopy(state["milestone"])
        drifted = changed(
            slices, lambda value: value[0].__setitem__("title", "Drifted")
        )
        for name, candidate in (
            ("valid-looking", drifted),
            ("malformed", framed('{"slices":[')),
            ("missing", b"# plan removed\n"),
        ):
            with self.subTest(name=name):
                self.write_skeleton(candidate)
                probe = mock.Mock()
                with self.assertRaises(canonical_plan.CanonicalPlanDrift):
                    canonical_plan.guarded_dispatch(state, probe)
                probe.assert_not_called()
                self.assertEqual(st.load(self.state_path)["milestone"], baseline)

        state = st.load(self.state_path)
        state["milestone"][canonical_plan.RECONCILIATION_KEY] = {
            "status": "open",
            "source_base_revision": "repair-base",
            "accepted_revision": revision,
        }
        st.save(self.state_path, state)
        repair = mock.Mock(return_value="repair dispatched")
        self.assertEqual(
            canonical_plan.guarded_dispatch(
                st.load(self.state_path),
                repair,
                reconciliation_accepted_revision=revision,
            ),
            "repair dispatched",
        )
        repair.assert_called_once_with()
        after = st.load(self.state_path)["milestone"]
        self.assertEqual(after[canonical_plan.ANCHOR_KEY], anchor)
        self.assertEqual(after["slices"], baseline["slices"])

        wrong = mock.Mock()
        with self.assertRaises(canonical_plan.CanonicalPlanDrift):
            canonical_plan.guarded_dispatch(
                st.load(self.state_path),
                wrong,
                reconciliation_accepted_revision="not-the-anchor",
            )
        wrong.assert_not_called()

    def test_snapshot_window_rechecks_live_plan_before_dispatch(self):
        slices, _revision, _anchor = self.establish()
        state = st.load(self.state_path)
        original_snapshot = gitops.snapshot_worktree_tree
        drifted = changed(
            slices, lambda value: value[0].__setitem__("title", "Late drift")
        )

        def snapshot_then_drift(workspace):
            tree = original_snapshot(workspace)
            self.write_skeleton(drifted)
            return tree

        with mock.patch.object(
            gitops,
            "snapshot_worktree_tree",
            side_effect=snapshot_then_drift,
        ):
            with self.assertRaises(canonical_plan.CanonicalPlanDrift):
                canonical_plan.begin_author_call(state, self.skeleton)

        self.assertEqual(
            state["milestone"][canonical_plan.ANCHOR_KEY]["revision"],
            self.git(
                "rev-parse",
                gitops.canonical_plan_anchor_ref(self.skeleton),
            ),
        )

    def test_first_physical_draft_projects_a_ref_pinned_anchor(self):
        head = self.commit_skeleton(b"# Skeleton pending\n", "baseline")
        self.save_stale_state()
        state = st.load(self.state_path)
        snapshot = canonical_plan.begin_author_call(
            state, self.skeleton, allow_unanchored=True
        )
        planned = [slice_plan(3), slice_plan(1)]
        self.write_skeleton(document(planned))

        result = canonical_plan.complete_author_call(
            state, snapshot, message="physical draft plan"
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["source_base_revision"], head)
        self.assertEqual(
            self.git("rev-parse", "HEAD"), result["accepted_revision"]
        )
        self.assertEqual(
            self.git(
                "rev-parse",
                gitops.canonical_plan_anchor_ref(self.skeleton),
            ),
            result["anchor"]["revision"],
        )
        self.assertEqual(
            [item["id"] for item in state["milestone"]["slices"]],
            [3, 1],
        )

    def test_valid_physical_change_projects_a_ref_pinned_commit_anchor(self):
        slices, head, old_anchor = self.establish()
        state = st.load(self.state_path)
        snapshot = canonical_plan.begin_author_call(state, self.skeleton)
        changed_slices = copy.deepcopy(slices)
        for slice_plan_value in changed_slices:
            slice_plan_value.pop("material", None)
        changed_slices.append(slice_plan(3))
        self.write_skeleton(document(changed_slices))

        result = canonical_plan.complete_author_call(state, snapshot)

        self.assertTrue(result["changed"])
        self.assertEqual(result["source_base_revision"], head)
        self.assertEqual(
            self.git("rev-parse", "HEAD"), result["accepted_revision"]
        )
        self.assertNotEqual(result["anchor"], old_anchor)
        self.assertEqual(
            self.git(
                "rev-parse",
                gitops.canonical_plan_anchor_ref(self.skeleton),
            ),
            result["anchor"]["revision"],
        )
        self.assertEqual(
            [item["id"] for item in state["milestone"]["slices"]],
            [2, 1, 3],
        )
        accepted = gitops.show_file(
            self.workspace,
            result["anchor"]["revision"],
            self.skeleton,
        )
        self.assertEqual(
            canonical_plan.canonical_block_bytes(accepted),
            canonical_plan.canonical_block_bytes(document(changed_slices)),
        )

    def test_unchanged_physical_call_keeps_the_existing_anchor(self):
        _slices, head, anchor = self.establish()
        state = st.load(self.state_path)
        snapshot = canonical_plan.begin_author_call(state, self.skeleton)

        with mock.patch.object(
            canonical_plan,
            "validate_canonical_plan",
            side_effect=AssertionError("unchanged plans are not revalidated"),
        ):
            result = canonical_plan.complete_author_call(state, snapshot)

        self.assertFalse(result["changed"])
        self.assertEqual(result["anchor"], anchor)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_invalid_change_restores_proportional_repository_boundary(self):
        _slices, head, anchor = self.establish()
        staged = os.path.join(self.workspace, "staged.txt")
        with open(staged, "w", encoding="utf-8") as handle:
            handle.write("pre-call index\n")
        self.git("add", "staged.txt")
        with open(staged, "w", encoding="utf-8") as handle:
            handle.write("pre-call worktree\n")
        untracked = os.path.join(self.workspace, "untracked.txt")
        with open(untracked, "w", encoding="utf-8") as handle:
            handle.write("pre-call untracked\n")
        state = st.load(self.state_path)

        snapshot = canonical_plan.begin_author_call(state, self.skeleton)
        repository = snapshot["repository"]
        self.assertEqual(
            set(repository),
            {"workspace", "sym", "head", "index_tree", "worktree_tree"},
        )
        self.assertNotEqual(repository["head"], head)
        self.assertEqual(self.git("status", "--short"), "")
        anchor_ref = gitops.canonical_plan_anchor_ref(self.skeleton)
        self.git("update-ref", "-d", anchor_ref)
        self.write_skeleton(framed('{"slices":['))
        with open(
            os.path.join(self.workspace, "worker-only.txt"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("discard me\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "worker commit")

        with self.assertRaisesRegex(
            canonical_plan.CanonicalPlanError, "snapshot was restored"
        ):
            canonical_plan.complete_author_call(state, snapshot)

        self.assertEqual(self.git("rev-parse", "HEAD"), repository["head"])
        self.assertEqual(
            gitops.snapshot_index_tree(self.workspace),
            repository["index_tree"],
        )
        self.assertEqual(
            gitops.snapshot_worktree_tree(self.workspace),
            repository["worktree_tree"],
        )
        self.assertEqual(self.git("status", "--short"), "")
        with open(staged, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "pre-call worktree\n")
        with open(untracked, "r", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "pre-call untracked\n")
        self.assertEqual(
            state["milestone"][canonical_plan.ANCHOR_KEY], anchor
        )
        self.assertEqual(
            self.git("rev-parse", anchor_ref), anchor["revision"]
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.workspace, "worker-only.txt"))
        )

    def test_trusted_observer_projects_a_valid_block_without_policing_bytes(self):
        slices, head, _anchor = self.establish()
        state = st.load(self.state_path)
        snapshot = canonical_plan.begin_author_call(state, self.skeleton)
        changed_slices = copy.deepcopy(slices)
        for slice_plan_value in changed_slices:
            slice_plan_value.pop("material", None)
        changed_slices.append(slice_plan(3))
        self.write_skeleton(document(changed_slices))
        unrelated = os.path.join(self.workspace, "trusted-output.txt")
        with open(unrelated, "w", encoding="utf-8") as handle:
            handle.write("left by the trusted judgment\n")

        result = canonical_plan.complete_observed_call(state, snapshot)

        self.assertTrue(result["changed"])
        self.assertEqual(result["source_base_revision"], head)
        self.assertEqual(
            self.git("rev-parse", "HEAD"), result["accepted_revision"]
        )
        self.assertTrue(os.path.exists(unrelated))
        self.assertEqual(
            [item["id"] for item in state["milestone"]["slices"]],
            [2, 1, 3],
        )

    def test_unchanged_trusted_observer_captures_a_only_before_dispatch(self):
        _slices, _head, anchor = self.establish()
        state = st.load(self.state_path)
        snapshot_worktree_tree = gitops.snapshot_worktree_tree
        with mock.patch.object(
            gitops,
            "snapshot_worktree_tree",
            side_effect=snapshot_worktree_tree,
        ) as capture:
            snapshot = canonical_plan.begin_author_call(state, self.skeleton)
            result = canonical_plan.complete_observed_call(state, snapshot)

        self.assertEqual(capture.call_count, 1)
        self.assertFalse(result["changed"])
        self.assertEqual(result["anchor"], anchor)

    def test_trusted_observer_leaves_invalid_worker_state_untouched(self):
        _slices, head, anchor = self.establish()
        state = st.load(self.state_path)
        snapshot = canonical_plan.begin_author_call(state, self.skeleton)
        invalid = framed('{"slices":[')
        self.write_skeleton(invalid)
        unrelated = os.path.join(self.workspace, "trusted-output.txt")
        with open(unrelated, "w", encoding="utf-8") as handle:
            handle.write("not restored\n")

        with self.assertRaisesRegex(
            canonical_plan.CanonicalPlanError, "invalid canonical plan"
        ):
            canonical_plan.complete_observed_call(state, snapshot)

        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(
            state["milestone"][canonical_plan.ANCHOR_KEY], anchor
        )
        with open(
            os.path.join(self.workspace, self.skeleton), "rb"
        ) as handle:
            self.assertEqual(handle.read(), invalid)
        self.assertTrue(os.path.exists(unrelated))


if __name__ == "__main__":
    unittest.main()
