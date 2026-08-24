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
        "material": "document",
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
            "empty material": changed(
                slices, lambda value: value[0].__setitem__("material", "")
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


if __name__ == "__main__":
    unittest.main()
