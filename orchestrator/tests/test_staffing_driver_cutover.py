"""Slice 4: the milestone driver's cutover, and the run binding.

Every worker call the driver makes takes its family, model and effort from
the run's staffing session and from nothing else — the skeleton draft, the
slice-note draft, the implementation, the fixer, the failure classifier, the
debt rater, the fixer's consultation, every review round and every delta
review. The run gets that session at launch, or at the first resume that
finds none (amendment A2).

Part 4a built the single-seat calls and the binding. Part 4b is here too:
the review cycle is the document's assigned `review` seats in index order,
the split-family check runs before each review dispatch, and the run
summary's rounds-time projection names the seat the next round would run on.
"""

import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import contracts
from orchestrator import current_model_call
from orchestrator import driver as drv
from orchestrator import model_profiles
from orchestrator import registry
from orchestrator import runners
from orchestrator import service
from orchestrator import staffing as stf
from orchestrator import state as st
from orchestrator import task_api
from orchestrator import tasks

from orchestrator.tests.test_driver_mock import (
    DriverTestCase,
    finding,
    fix_ok,
    init_state,
    make_config,
    ok,
    report,
    step,
    triaged,
    write_file,
)


# ---------------------------------------------------------------------------
# What the converted `default` document staffs, so a test says WHY it expects
# a family rather than repeating a literal.

PLAN = ("claude", "claude-fable-5", "max")
DRAFT = ("codex", "gpt-5.6-sol", "xhigh")
IMPLEMENT = ("claude", "claude-fable-5", "max")
FIX = ("codex", "gpt-5.6-sol", "xhigh")
CLASSIFY = ("codex", "gpt-5.6-sol", "xhigh")
CONSULT = ("claude", "claude-opus-5", "xhigh")
# The two `review` seats the converted `default` assigns, in index order.
REVIEW_1 = ("codex", "gpt-5.6-sol", "xhigh")
REVIEW_2 = ("claude", "claude-opus-5", "xhigh")


def read_bytes(path):
    """The stored bytes of one file, for a "nothing was written" assertion."""
    with open(path, "rb") as handle:
        return handle.read()


def unstaffable_document(name="ghosts"):
    """A document whose every family slot names nobody this machine has."""
    document = stf.default_document_seed()
    document["name"] = name
    for slot in document["families"].values():
        slot["name"] = "ghost-%s" % slot["name"]
    return document


def split_classify_document(name="split-classify"):
    """A document whose `classify` role demands two distinct families.

    Nothing in the seed declares that, but a document owner may: `classify`
    is the independence seat, so asking for it split is the obvious thing
    to write. On a machine with one family the two seats collapse onto it,
    which is `distinct_families_unsatisfiable` — for a classifier DISPATCH,
    and only for one.
    """
    document = stf.default_document_seed()
    document["name"] = name
    document["roles"]["classify"] = {"distinct_families": True}
    document["assignment"]["classify"] = {"1": 1, "2": 2}
    return document


def review_seats_document(name, families, distinct=False):
    """A document whose `review` seats are *families*, in index order.

    Built from the seed so it stays a complete document: one family slot
    per distinct name with that name's ladder (or a ladder of its own for a
    family the seed does not carry), one tuning column per slot, every
    other role on the first slot, and `review` assigned one seat per entry
    of *families* — so the same family may hold two seats. `distinct_families`
    is declared only where a test asks for it.
    """
    document = stf.default_document_seed()
    document["name"] = name
    ladders = {slot["name"]: slot for slot in document["families"].values()}
    order = []
    for family in families:
        if family not in order:
            order.append(family)
    document["families"] = {}
    for position, family in enumerate(order, start=1):
        document["families"][str(position)] = copy.deepcopy(
            ladders.get(family)
            or {"name": family,
                "models": ["%s-lite" % family, "%s-mid" % family,
                           "%s-pro" % family],
                "efforts": ["low", "medium", "high", "xhigh", "max"]}
        )
        document["families"][str(position)]["name"] = family
    for rigor, by_slot in list(document["tuning"].items()):
        document["tuning"][rigor] = {
            str(position): copy.deepcopy(by_slot["1"])
            for position in range(1, len(order) + 1)
        }
    document["roles"]["review"] = (
        {"distinct_families": True} if distinct else {}
    )
    slot_of = {family: position
               for position, family in enumerate(order, start=1)}
    document["assignment"] = {role: {"1": 1} for role in document["assignment"]}
    document["assignment"]["review"] = {
        str(index): slot_of[family]
        for index, family in enumerate(families, start=1)
    }
    return document


def capture_marker(into):
    """Side effect factory: copy the in-flight marker as the call runs."""

    def effect(workspace):
        with open(
            os.path.join(workspace, ".orchestrator", "current.json"),
            encoding="utf-8",
        ) as handle:
            into.update(json.load(handle))

    return effect


def one_review_seat(document):
    """The same document with `review` assigned a single seat.

    One assigned seat honours any declared split trivially, which is how a
    run whose available families are one reviews at all after this slice.
    """
    document["assignment"]["review"] = {"1": 1}
    return document


def restaffed_document(name, family):
    """A valid document that seats EVERY role on one family.

    Built from the seed so it stays a complete document: the slot keeps its
    numbering and tuning, only its name and ladders change.
    """
    document = stf.default_document_seed()
    document["name"] = name
    slot = document["families"]["1"]
    slot["name"] = family
    for role in document["assignment"]:
        document["assignment"][role] = {"1": 1}
    return document


class StaffingCutoverTestCase(DriverTestCase):
    """A homed run whose staffing comes from the store, as production's does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-cutover-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        model_profiles.ensure_default(self.home)

    def run_state(self, name="ws", **config_overrides):
        workspace = os.path.join(self.tmp.name, name)
        os.makedirs(workspace, exist_ok=True)
        config = make_config(**config_overrides)
        return init_state(workspace, config)

    def driver_for(self, path, script=()):
        return drv.Driver(
            path,
            runner=runners.MockRunner(list(script)),
            model_profiles_home=self.home,
        )

    def session_of(self, path):
        return st.load(path)["staffing_session"]

    def sidecar(self, path, name, value):
        target = os.path.join(os.path.dirname(path), name)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        return target

    def captured(self):
        """Record every request the driver makes of the router."""
        real = stf.resolve
        requests = []

        def record(home, session, role, index=1, round=1, material=None,
                   brief=None, families=()):
            requests.append({
                "session": session, "role": role, "index": index,
                "round": round, "material": material, "brief": brief,
                "families": list(families),
            })
            return real(home, session, role, index=index, round=round,
                        material=material, brief=brief, families=families)

        return requests, mock.patch.object(stf, "resolve", side_effect=record)

    def bound_to(self, document, families=("codex", "claude"), name="ws"):
        """A homed run whose ONE session points at *document*."""
        stf.save(self.home, document)
        path = self.run_state(
            name,
            families_order=list(families),
            commands={family: ["fake-%s" % family] for family in families},
        )
        drv.open_run_staffing_session(
            path, self.home, document["name"], "medium"
        )
        return path

    def review_families_that_ran(self, subject):
        """The family each review round ran on, in call order."""
        return [
            call["family"] for call in subject.runner.call_meta
            if call["kind"] == contracts.KIND_REVIEW_ROUND
        ]

    def review_requests(self, requests):
        """(seat, round) of every `review` request, in request order."""
        return [
            (r["index"], r["round"]) for r in requests if r["role"] == "review"
        ]


# ---------------------------------------------------------------------------
# Every driver-made call asks the router


class DriverCallsAskTheRouter(StaffingCutoverTestCase):
    def test_every_driver_call_asks_the_router(self):
        path = self.run_state("ws-requests")
        script = [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "One"}]),
                 family=PLAN[0],
                 side_effect=write_file("docs/skeleton.md", "# Skeleton\n")),
            step("review_round",
                 report("review_round", [finding("F1", "no non-goals")]),
                 family="codex"),
            # The skeleton's fixer is the skeleton's own seat.
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "no non-goals")],
                        files_changed=["docs/skeleton.md"]),
                 family=PLAN[0],
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\n## Non-goals\n")),
            # The delta resolves the lowest-index `review` seat whose family
            # is the fixer's; the skeleton's fixer is the `plan` seat, whose
            # family the `default` document seats at review index 2.
            step("delta_review", report("delta_review"), family=PLAN[0]),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 family=DRAFT[0],
                 side_effect=write_file("docs/slice-01.md", "# Slice 01\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step("implement",
                 ok("implement", files_changed=["calculator.py"]),
                 family=IMPLEMENT[0],
                 side_effect=write_file("calculator.py", "x = 1\n")),
            step("review_round",
                 report("review_round", [finding("F2", "no docstring")]),
                 family="codex"),
            step("fix_findings",
                 fix_ok([triaged("F2", "fixed", "no docstring")],
                        files_changed=["calculator.py"]),
                 family=FIX[0],
                 side_effect=write_file("calculator.py", '"""C."""\nx = 1\n')),
        ]
        requests, patched = self.captured()
        subject = self.driver_for(path, script)
        with patched:
            self.step_until(
                subject,
                lambda state: any(
                    unit["kind"] == st.UNIT_SLICE_IMPL
                    and unit["status"] == st.U_DELTA_REVIEW
                    for unit in state["units"]
                ),
                max_steps=80,
            )

        session = self.session_of(path)
        seats = [(r["role"], r["index"], r["round"]) for r in requests]
        # Each call kind asked once per dispatch, at the seat this slice pins.
        self.assertIn(("plan", 1, 1), seats)      # skeleton draft AND its fix
        self.assertIn(("draft", 1, 1), seats)
        self.assertIn(("implement", 1, 1), seats)
        self.assertIn(("fix", 1, 1), seats)
        self.assertIn(("consult", 1, 1), seats)
        # Reviews ask for the seats the document assigns, in index order,
        # and a delta review asks at a review seat like any other review.
        self.assertIn(("review", 1, 1), seats)
        self.assertIn(("review", 2, 1), seats)
        # No role outside the driver's own worker calls, and no request
        # carries a material or a brief before slice 9.
        self.assertEqual(
            sorted({role for role, _index, _round in seats}),
            ["consult", "draft", "fix", "implement", "plan", "review"],
        )
        for request in requests:
            self.assertEqual(request["session"], session)
            self.assertIsNone(request["material"])
            self.assertIsNone(request["brief"])
            self.assertEqual(request["families"], ["codex", "claude"])

        # And what each call RAN on is the router's own answer.
        ran = {
            (call["kind"], call["family"], call["model"], call["effort"])
            for call in subject.runner.call_meta
        }
        self.assertIn((contracts.KIND_DRAFT_SKELETON,) + PLAN, ran)
        self.assertIn((contracts.KIND_DRAFT_SLICE_NOTE,) + DRAFT, ran)
        self.assertIn((contracts.KIND_IMPLEMENT,) + IMPLEMENT, ran)
        self.assertIn((contracts.KIND_FIX_FINDINGS,) + FIX, ran)
        self.assertIn((contracts.KIND_REVIEW_ROUND,) + REVIEW_1, ran)
        self.assertIn((contracts.KIND_REVIEW_ROUND,) + REVIEW_2, ran)
        self.assertIn((contracts.KIND_DELTA_REVIEW,) + REVIEW_2, ran)

    def test_unknown_slice_material_degrades_and_nonproduction_calls_stay_unset(
        self,
    ):
        document = stf.default_document_seed()
        document["name"] = "slice-material-boundary"
        document["materials"] = {
            "fallback": {"examples": ["The session's standing choice."]},
            "removed": {"examples": ["A choice later renamed away."]},
            "later": {"examples": ["The next production task's choice."]},
        }
        document["overrides"] = {
            "fallback": {"assignment": {"draft": {"1": 1}}},
            "removed": {"assignment": {"draft": {"1": 2}}},
            "later": {"assignment": {"draft": {"1": 2}}},
        }
        path = self.bound_to(document, name="ws-slice-material-boundary")
        session = self.session_of(path)
        stf.edit_session(self.home, session, {"material": "fallback"})

        state = st.load(path)
        state["milestone"]["slices"] = [{
            "id": 1,
            "title": "One",
            "material": "removed",
        }]
        state["units"][0].update({
            "status": st.U_SEALED,
            "artifact": "docs/skeleton.md",
        })
        unit = st.ensure_next_unit(state)
        st.save(path, state)

        subject = self.driver_for(path)
        unit = st.current_unit(subject.state)
        family, model, effort = subject._worker_staffing(
            unit, contracts.KIND_DRAFT_SLICE_NOTE
        )
        admitted = subject._admit_worker_task(
            unit,
            contracts.KIND_DRAFT_SLICE_NOTE,
            "KIND: draft_slice_note\n",
            family,
            model=model,
            effort=effort,
            dispatch_resolver=subject._dispatch_for_worker_kind(
                unit, contracts.KIND_DRAFT_SLICE_NOTE
            ),
        )
        self.assertEqual(
            tasks.order_staffing_material(admitted["order"]), "removed"
        )

        # The prospective plan moves on, while the admitted order does not.
        tasks.update_slice_material(
            subject.state, 1, {"material": "later"}
        )
        subject._save()

        # The admitted name then disappears from the live document. Existing
        # router law ignores it and falls through to the session default.
        del document["materials"]["removed"]
        del document["overrides"]["removed"]
        stf.save(self.home, document)
        expected = stf.resolve(
            self.home,
            session,
            "draft",
            material="removed",
            families=["codex", "claude"],
        ).answer
        mutable_plan_answer = stf.resolve(
            self.home,
            session,
            "draft",
            material="later",
            families=["codex", "claude"],
        ).answer
        self.assertNotEqual(expected, mutable_plan_answer)

        requests, patched = self.captured()
        restarted = self.driver_for(path)
        unit = st.current_unit(restarted.state)
        with patched:
            ran = restarted._dispatch_for_worker_kind(
                unit, contracts.KIND_DRAFT_SLICE_NOTE
            )()

            # Every adjacent driver call has no production material source.
            skeleton = restarted.state["units"][0]
            restarted._dispatch_for_worker_kind(
                skeleton, contracts.KIND_DRAFT_SKELETON
            )()
            restarted._dispatch_for_worker_kind(
                unit, contracts.KIND_FIX_FINDINGS
            )()
            restarted._dispatch_for_role("classify")()
            restarted._dispatch_for_role("consult")()
            # Full and delta review use the same material-free review seat
            # resolver; take one request for each reviewed call shape.
            restarted._review_dispatch(unit, 1)()
            restarted._review_dispatch(unit, 2)()

            standalone_order = tasks.validate_order({
                "task_executor": "agent_call",
                "configuration": {"role": "implement"},
                "staffing_session": session,
                "request": {
                    "work_area": {
                        "workspace_path": restarted.workspace,
                        "primary": restarted.workspace,
                        "additional": [],
                    },
                    "request": "Run one standalone task.",
                    "context": {},
                    "reference_documents": [],
                },
            })
            task_api._dispatch(
                self.home,
                {"order": standalone_order, "resolved_staffing": {}},
                restarted.config,
            )

            area_store = mock.Mock()
            area_store.read.return_value = mock.Mock(
                ok=True,
                value={"primary": {"path": restarted.workspace}},
            )
            with mock.patch.object(
                service, "_require_declared", return_value=("project", {})
            ), mock.patch.object(
                service.registry, "get_project", return_value={"defaults": {}}
            ), mock.patch.object(
                service, "read_staffing_session"
            ), mock.patch.object(
                service.workareas, "WorkAreaStore", return_value=area_store
            ), mock.patch.object(
                service.gitops, "is_repo_root", return_value=True
            ), mock.patch.object(
                service, "_require_unowned_workspace"
            ), mock.patch.object(
                service.driver,
                "load_config",
                return_value=copy.deepcopy(restarted.config),
            ), mock.patch.object(
                service.gitsync,
                "run_sync",
                return_value={"outcome": "aligned"},
            ):
                service.sync_project_git(
                    self.home,
                    "project",
                    {"work_area": "main", "staffing_session": session},
                    who={"admin": True},
                )

        self.assertEqual(
            ran, (expected["agent"], expected["model"], expected["effort"])
        )
        draft_requests = [
            request for request in requests if request["role"] == "draft"
        ]
        self.assertEqual(len(draft_requests), 1)
        self.assertEqual(draft_requests[0]["material"], "removed")
        adjacent = [
            request for request in requests if request["role"] != "draft"
        ]
        self.assertEqual(
            sorted(request["role"] for request in adjacent),
            [
                "classify", "consult", "fix", "implement", "plan",
                "review", "review", "sync",
            ],
        )
        self.assertTrue(all(
            request["material"] is None for request in adjacent
        ))

    def test_the_failure_classifier_asks_the_classify_seat(self):
        """The classifier is a `classify` seat, not the opposite of the
        family that failed — and it asks at DISPATCH time only.

        The LLM stage sits behind the deterministic patterns and behind
        `error_classifier`, so most failures never call a classifier at all:
        the seat travels as the dispatch hook and is carried, unresolved,
        past every failure that never reaches it.
        """
        path = self.run_state("ws-classifier", error_classifier=True)
        subject = self.driver_for(path)
        resolved = []

        def classify(_exc, **kwargs):
            resolved.append(
                (kwargs["opposite_family"], kwargs["classifier_model"],
                 kwargs["classifier_effort"], kwargs["resolve_dispatch"]())
            )
            return "unknown", None, "test"

        with mock.patch.object(
            drv.errclass, "classify_worker_failure", side_effect=classify
        ):
            subject._classify_failure(
                "claude", runners.RunnerError("mystery"), "classifier-test"
            )
        # Nothing is staffed up front; the hook answers the `classify` seat.
        self.assertEqual(resolved, [(None, None, None, CLASSIFY)])

    def test_a_seat_no_call_uses_is_never_resolved(self):
        """A failure the deterministic patterns type takes no classifier
        call, so it asks the router nothing — and a `classify` seat the
        machine cannot honour therefore stops nothing.

        The run keeps the failure it actually has, with its own auto-
        resumable type, instead of an `orchestrator` stop naming a seat no
        dispatch was ever going to use.
        """
        path = self.run_state(
            "ws-classify-unused", families_order=["codex"],
            fix_family="codex", error_classifier=False,
        )
        subject = self.driver_for(path)
        stf.save(self.home, split_classify_document())
        stf.edit_session(self.home, self.session_of(path),
                         {"document": "split-classify"})
        requests, patched = self.captured()
        with patched:
            verdict = subject._classify_failure(
                "codex",
                runners.RunnerError("quota exceeded: usage limit reached"),
                "classifier-unused",
            )
        self.assertEqual(verdict[:1], ("quota",))
        self.assertEqual(requests, [])
        self.assertIsNone(st.load(path)["failure"])
        self.assertEqual(subject.runner.calls, [])

    def test_a_resumed_fixer_asks_only_for_the_seat_it_runs_on(self):
        """The same rule on the fix path: an ADMITTED fixer reuses its
        frozen prompt, so it builds no consultation text and asks the
        router for `fix` alone.

        `consult` is resolved only to NAME the consulted family in a fix
        prompt this branch never builds; the command line the frozen
        prompt already carries resolves that seat when the fixer runs it.
        So a `consult` role this machine cannot split stops a resumed
        fixer no more than an unsatisfiable `classify` stops a failure the
        classifier never sees.
        """
        path = self.run_state(
            "ws-resumed-fixer", families_order=["codex"], fix_family="codex",
        )
        state = st.load(path)
        state["milestone"]["slices"] = [{"id": 1, "title": "impl"}]
        state["units"][0].update(
            {"status": st.U_SEALED, "artifact": "docs/skeleton.md"}
        )
        note = st.ensure_next_unit(state)
        note.update({"status": st.U_SEALED, "artifact": "docs/note.md"})
        unit = st.ensure_next_unit(state)
        unit["status"] = st.U_FIXING
        unit["fix_queue"] = [finding("F1", "repair it", severity="P1")]
        unit["fix_source"] = {
            "type": "round", "origin_type": "round", "family": "codex",
            "source_round_id": "slice_impl-01-codex-r1",
            "return_to": st.U_ROUNDS,
        }
        st.save(path, state)
        subject = self.driver_for(path)
        subject._admit_worker_task(
            st.current_unit(subject.state),
            contracts.KIND_FIX_FINDINGS,
            "frozen admitted prompt",
            "codex",
        )

        # A `consult` role the one available family cannot split. The fix
        # seat itself resolves; only the unused seat is unsatisfiable.
        document = stf.default_document_seed()
        document["name"] = "split-consult"
        document["roles"]["consult"] = {"distinct_families": True}
        document["assignment"]["consult"] = {"1": 1, "2": 2}
        stf.save(self.home, document)
        stf.edit_session(
            self.home, self.session_of(path), {"document": "split-consult"})

        resumed = self.driver_for(path)
        dispatched = []

        def reached(_family, prompt, *_args, **_kwargs):
            dispatched.append(prompt)
            raise RuntimeError("dispatch reached")

        requests, patched = self.captured()
        with (
            patched,
            mock.patch.object(resumed, "_call", side_effect=reached),
            self.assertRaisesRegex(RuntimeError, "dispatch reached"),
        ):
            resumed._do_fix()

        self.assertEqual([request["role"] for request in requests], ["fix"])
        self.assertTrue(dispatched[0].startswith("frozen admitted prompt"))
        self.assertIsNone(st.load(path)["failure"])

    def test_a_stuck_fixer_counts_its_round(self):
        """`fix` is the one driver role whose round is not always 1."""
        path = self.run_state("ws-fix-round")
        state = st.load(path)
        state["milestone"]["slices"] = [{"id": 1, "title": "impl"}]
        state["units"][0]["status"] = st.U_SEALED
        st.ensure_next_unit(state)["status"] = st.U_SEALED
        unit = st.ensure_next_unit(state)
        unit["fix_loop_rounds"] = 3
        st.save(path, state)
        subject = self.driver_for(path)
        self.assertEqual(
            subject._worker_role(unit, contracts.KIND_FIX_FINDINGS),
            ("fix", 4),
        )
        # Every other driver role is round 1, including a skeleton fix.
        skeleton = st.load(path)["units"][0]
        self.assertEqual(
            subject._worker_role(skeleton, contracts.KIND_FIX_FINDINGS),
            ("plan", 1),
        )


# ---------------------------------------------------------------------------
# Nothing else decides a driver call


class RetiredDispatchInputs(StaffingCutoverTestCase):
    def test_profiles_acts_and_config_decide_nothing(self):
        path = self.run_state("ws-retired")
        subject = self.driver_for(path)
        before = subject._staff("implement")
        self.assertEqual(before, IMPLEMENT)

        # A profile selection, a live act override and the config's own act
        # table: three inputs that decided a dispatch before this slice.
        model_profiles.save(self.home, {
            "name": "loud",
            "examples": ["loud"],
            "configurations": {
                "low": {}, "high": {},
                "medium": {"implementer": {
                    "agent": "codex", "model": "profile-model",
                    "effort": "low"}},
            },
        })
        self.sidecar(path, "model_profile.json",
                     {"name": "loud", "rigor": "medium"})
        self.sidecar(path, "acts.json", {
            "implementer": {"agent": "codex", "model": "act-model",
                            "effort": "low"},
        })
        subject.config["acts"]["implementer"] = {
            "agent": "codex", "model": "config-model", "effort": "low"}
        self.assertEqual(subject._staff("implement"), before)

        # A deliberately invalid selection and a dangling link no longer
        # fail a dispatch either; they are simply not read.
        self.sidecar(path, "model_profile.json",
                     {"name": "missing", "rigor": "medium"})
        self.assertEqual(subject._staff("implement"), before)
        self.sidecar(path, "acts.json", {"implementer": "not an act entry"})
        self.assertEqual(subject._staff("implement"), before)

    def test_the_debt_raters_builder_context_is_router_backed(self):
        """The rating's own prompt context is a driver-made read too.

        It names the run's REAL downstream builders, which after the
        cutover are the `draft` and `implement` seats — so no profile or
        act state decides it or stops the rating, and a condition on a seat
        this call does not dispatch withholds its line instead.
        """
        path = self.run_state("ws-builders")
        subject = self.driver_for(path)
        expected = (
            "slice docs drafted by %s (%s, %s effort); "
            "implementation built by %s (%s, %s effort)" % (DRAFT + IMPLEMENT)
        )
        self.assertEqual(subject._builders_desc(), expected)

        # A dangling profile link and a malformed act sidecar decide
        # nothing here either, and no longer fail the run before the call.
        self.sidecar(path, "model_profile.json",
                     {"name": "missing", "rigor": "medium"})
        self.sidecar(path, "acts.json", {"implementer": "not an act entry"})
        self.assertEqual(subject._builders_desc(), expected)
        self.assertIsNone(st.load(path)["failure"])

        # And an unstaffable seat withholds its line rather than stopping
        # the rating: only `classify`'s own resolution may do that.
        stf.save(self.home, unstaffable_document())
        stf.edit_session(
            self.home, self.session_of(path), {"document": "ghosts"})
        self.assertEqual(subject._builders_desc(), "")
        self.assertIsNone(st.load(path)["failure"])

    def test_brainstorming_seats_still_read_profiles(self):
        """The driver's Brainstorming seats are slice 6's, not this one's."""
        path = self.run_state("ws-brainstorming")
        self.driver_for(path)  # binds the session and seeds the documents
        model_profiles.save(self.home, {
            "name": "seats",
            "examples": ["seats"],
            "configurations": {
                "low": {}, "high": {},
                "medium": {"implementer": {
                    "agent": "claude", "model": "lead-model",
                    "effort": "high"}},
            },
        })
        self.sidecar(path, "model_profile.json",
                     {"name": "seats", "rigor": "medium"})
        lead, counterpart = self.driver_for(path)._brainstorming_profiles()
        self.assertEqual(lead["model"], "lead-model")
        self.assertEqual(counterpart["agent"], "codex")


# ---------------------------------------------------------------------------
# Live per dispatch


class ResolutionIsLive(StaffingCutoverTestCase):
    def test_session_and_document_edits_reach_the_next_call(self):
        path = self.run_state("ws-live")
        subject = self.driver_for(path)
        session = self.session_of(path)
        self.assertEqual(subject._staff("implement"), IMPLEMENT)

        # A session edit: same document, different rigor.
        stf.edit_session(self.home, session, {"rigor": "low"})
        low = subject._staff("implement")
        self.assertNotEqual(low, IMPLEMENT)
        self.assertEqual(low, stf.base_staffing(
            stf.load(self.home, "default"), "low", "implement"))

        # A document edit reaches the next call of every session on it.
        document = stf.load(self.home, "default")
        document["tuning"]["low"]["1"]["implement"] = [1, 1]
        document["assignment"]["implement"]["1"] = 1
        stf.save(self.home, document)
        self.assertEqual(
            subject._staff("implement"),
            stf.base_staffing(document, "low", "implement"),
        )

    def test_an_infrastructure_retry_resolves_again(self):
        path = self.run_state("ws-retry", infra_retry_backoff_s=[0])
        subject = self.driver_for(path)
        session = self.session_of(path)

        def repoint(_workspace):
            stf.save(self.home, restaffed_document("codex-only", "codex"))
            stf.edit_session(self.home, session, {"document": "codex-only"})

        subject.runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "expect_family": IMPLEMENT[0],
             "response": "not contract json",
             "side_effect": repoint},
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "expect_family": "codex",
             "response": ok(contracts.KIND_IMPLEMENT, files_changed=[])},
        ])
        output, _result, _raw = subject._call(
            IMPLEMENT[0],
            "KIND: implement\nFAMILY: %s\nWORKSPACE: %s\n\nlive"
            % (IMPLEMENT[0], subject.workspace),
            contracts.KIND_IMPLEMENT,
            "live-dispatch",
            dispatch_resolver=subject._dispatch_for_role("implement"),
        )
        self.assertEqual(output["status"], "ok")
        self.assertEqual(
            [call["family"] for call in subject.runner.call_meta],
            [IMPLEMENT[0], "codex"],
        )


# ---------------------------------------------------------------------------
# The review cycle IS the document's `review` seats


class ReviewCycleTestCase(StaffingCutoverTestCase):
    """Shared drive helpers for the review-cycle tests. No tests of its own."""

    THREE = ("codex", "claude", "gemini")

    def draft(self, family="codex"):
        return step(
            "draft_skeleton",
            ok("draft_skeleton", artifact="docs/skeleton.md",
               slices=[{"id": 1, "title": "One"}]),
            family=family,
            side_effect=write_file("docs/skeleton.md", "# Skeleton\n"),
        )

    def clean_rounds(self, families):
        return [
            step("review_round", report("review_round"), family=family)
            for family in families
        ]

    def sealed(self, state):
        return state["units"][0]["status"] == st.U_SEALED

    def in_rounds(self, state):
        return state["units"][0]["status"] == st.U_ROUNDS


class TheCycleReadAnswersWithoutDispatching(ReviewCycleTestCase):
    """`session_seat_families` is the third live document read over a
    session: the family each assigned seat of a role runs on, described
    without dispatching anything.

    It refuses nothing it can answer — a declared split this session cannot
    honour is the very list that judgement is made ON — and keeps
    `staffing_unavailable`, which is the one case leaving no answer to give.
    """

    def families_of(self, path, role="review", families=("codex", "claude")):
        return stf.session_seat_families(
            self.home, self.session_of(path), role, families=list(families)
        )

    def test_it_names_the_family_each_assigned_seat_runs_on(self):
        path = self.bound_to(
            review_seats_document("read-three", self.THREE),
            families=self.THREE, name="ws-read-three",
        )
        self.assertEqual(
            self.families_of(path, families=self.THREE), list(self.THREE)
        )

    def test_a_slot_this_machine_lacks_collapses_as_a_dispatch_would(self):
        """The read applies the same collapse `resolve` does, so the cycle
        a consumer walks is the one its dispatches would actually staff."""
        path = self.bound_to(
            review_seats_document("read-collapse", ("codex", "claude")),
            families=("codex",), name="ws-read-collapse",
        )
        self.assertEqual(
            self.families_of(path, families=("codex",)), ["codex", "codex"]
        )

    def test_a_split_it_cannot_honour_is_described_not_refused(self):
        document = review_seats_document("read-split", ("codex", "claude"))
        document["roles"]["review"] = {"distinct_families": True}
        document["assignment"]["review"] = {"1": 1, "2": 1}
        path = self.bound_to(
            document, families=("codex", "claude"), name="ws-read-split"
        )
        self.assertEqual(self.families_of(path), ["codex", "codex"])

        # The very same session refuses the DISPATCH the read describes.
        with self.assertRaises(stf.StaffingConditionError) as caught:
            stf.resolve(self.home, self.session_of(path), "review",
                        index=1, families=["codex", "claude"])
        self.assertEqual(
            caught.exception.code, stf.DISTINCT_FAMILIES_UNSATISFIABLE
        )

    def test_an_unreadable_document_describes_the_fallback_cycle(self):
        """The read falls back exactly as a dispatch does."""
        path = self.bound_to(
            review_seats_document("read-gone", ("codex", "claude")),
            families=("codex", "claude"), name="ws-read-gone",
        )
        stf.edit_session(
            self.home, self.session_of(path), {"document": "no-such-thing"}
        )
        seats = stf.session_seats(
            self.home, self.session_of(path), "review",
            families=["codex", "claude"],
        )
        families = self.families_of(path)
        self.assertEqual(len(families), len(seats))
        self.assertLessEqual(set(families), {"codex", "claude"})

    def test_no_family_available_leaves_no_answer_to_give(self):
        path = self.bound_to(
            unstaffable_document("read-ghosts"),
            families=("codex",), name="ws-read-ghosts",
        )
        with self.assertRaises(stf.StaffingConditionError) as caught:
            self.families_of(path, families=("codex",))
        self.assertEqual(caught.exception.code, stf.STAFFING_UNAVAILABLE)

    def test_an_unknown_role_is_an_input_error(self):
        path = self.bound_to(
            review_seats_document("read-role", ("codex",)),
            families=("codex",), name="ws-read-role",
        )
        with self.assertRaises(stf.StaffingError) as caught:
            self.families_of(path, role="reviewer", families=("codex",))
        self.assertNotIsInstance(
            caught.exception, stf.StaffingConditionError
        )


class ReviewCycleFollowsTheSeats(ReviewCycleTestCase):
    """Rotation, the cap, restarts and the seal predicate walk the seats the
    document assigns to `review`, in index order — not the run's configured
    family order."""

    def test_review_cycle_follows_assigned_seats(self):
        """Three assigned seats review in index order, and only then seal."""
        path = self.bound_to(
            review_seats_document("three-seats", self.THREE),
            families=self.THREE,
            name="ws-three",
        )
        requests, patched = self.captured()
        subject = self.driver_for(
            path, [self.draft()] + self.clean_rounds(self.THREE)
        )
        with patched:
            self.step_until(subject, self.sealed, max_steps=40)

        self.assertEqual(
            self.review_families_that_ran(subject), list(self.THREE)
        )
        self.assertEqual(subject.runner.script, [])
        # Every seat the document assigns was asked for, and no other.
        self.assertEqual(
            sorted({seat for seat, _round in self.review_requests(requests)}),
            [1, 2, 3],
        )

    def test_one_review_seat_seals_after_one_clean_round(self):
        path = self.bound_to(
            review_seats_document("one-seat", ["claude"]),
            name="ws-one-seat",
        )
        # One slot, so this document seats every other role on it too.
        subject = self.driver_for(
            path, [self.draft("claude")] + self.clean_rounds(["claude"])
        )
        self.step_until(subject, self.sealed, max_steps=40)
        self.assertEqual(self.review_families_that_ran(subject), ["claude"])
        self.assertEqual(subject.runner.script, [])

    def test_a_family_slot_no_review_seat_uses_adds_no_seat(self):
        """The cycle reads the ASSIGNMENT, not the family table.

        The document below carries three family slots and assigns two of
        them to `review`; the third stays a slot other roles could use and
        adds no review seat.
        """
        document = review_seats_document("slot-unused", self.THREE)
        document["assignment"]["review"] = {"1": 1, "2": 2}
        path = self.bound_to(
            document, families=self.THREE, name="ws-unused-slot"
        )
        self.assertEqual(len(document["families"]), 3)
        subject = self.driver_for(
            path, [self.draft()] + self.clean_rounds(["codex", "claude"])
        )
        self.step_until(subject, self.sealed, max_steps=40)
        self.assertEqual(
            self.review_families_that_ran(subject), ["codex", "claude"]
        )
        self.assertEqual(subject.runner.script, [])

    def recorded_rounds(self, path, family, count=2):
        """*count* clean review rounds for *family*, in the current cycle."""
        state = st.load(path)
        unit = state["units"][0]
        for _ in range(count):
            st.record_round(
                state, unit, family, contracts.KIND_REVIEW_ROUND,
                report("review_round"),
            )
        st.save(path, state)

    def two_recorded_rounds(self, path):
        """Two clean review rounds for the seat's family, in this cycle."""
        self.recorded_rounds(path, "codex")

    def test_a_seats_round_number_and_cap_count_its_familys_rounds(self):
        """The `review` request carries the seat family's rounds plus one,
        which is the very count the round cap takes."""
        path = self.bound_to(
            review_seats_document("counting", ["codex"]),
            families=("codex",), name="ws-count",
        )
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        self.two_recorded_rounds(path)

        requests, patched = self.captured()
        subject = self.driver_for(path, self.clean_rounds(["codex"]))
        with patched:
            subject.step()
        # Only the dispatch path ever asks beyond round 1: the cycle reads
        # that describe the seats always ask at round 1.
        self.assertIn((1, 3), self.review_requests(requests))

        # The same count is the cap. A run whose cap is already spent stops
        # before it dispatches, naming the family and the cap.
        path = self.bound_to(
            review_seats_document("capped", ["codex"]),
            families=("codex",), name="ws-cap",
        )
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        self.two_recorded_rounds(path)
        state = st.load(path)
        state["config"]["max_rounds_per_family"] = 2
        st.save(path, state)
        subject = self.driver_for(path, [])
        subject.step()
        self.assertIn(
            "max_rounds_per_family=2", st.load(path)["failure"]["reason"]
        )
        self.assertEqual(subject.runner.calls, [])

    def restaffing_seat_one(self, document, slot):
        """A document whose `review` seat 1 is *slot*, saved as a call runs.

        The whole point of a live seat: the document a dispatch resolves is
        the one on disk WHEN IT RESOLVES, not the one the cycle read while
        preparing the round.
        """
        swapped = copy.deepcopy(document)
        swapped["assignment"]["review"] = {"1": slot, "2": 3 - slot}
        return lambda _workspace: stf.save(self.home, swapped)

    def test_a_restaffed_seat_meets_the_cap_of_the_family_that_runs(self):
        """A save landing mid-call buys a capped family no extra round.

        A malformed answer makes the call resolve its seat again — the
        repair retry — and by then the saved document seats it on the other
        family. The round cap is the reviewing family's, so the dispatch
        takes it for the family it just resolved and not for the one the
        preparing read named, and this one has nothing left to spend.
        """
        document = review_seats_document("restaff-cap", ("codex", "claude"))
        path = self.bound_to(document, name="ws-restaff-cap")
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        # claude has spent this cycle's rounds; codex, the family seat 1
        # resolves to, has spent none.
        self.recorded_rounds(path, "claude", 2)
        state = st.load(path)
        state["config"]["max_rounds_per_family"] = 2
        st.save(path, state)

        subject = self.driver_for(path, [
            step("review_round", "not contract json", family="codex",
                 side_effect=self.restaffing_seat_one(document, 2)),
        ])
        subject.step()

        failure = st.load(path)["failure"]
        self.assertIn("family claude", failure["reason"])
        self.assertIn("max_rounds_per_family=2", failure["reason"])
        # The codex attempt ran; the claude one the save asked for did not.
        self.assertEqual(
            [call["family"] for call in subject.runner.call_meta], ["codex"]
        )

    def test_a_restaffed_seat_runs_at_its_own_familys_round(self):
        """And the round it runs at is that family's count too.

        `step_up` is what the round buys, so a dispatch that lands on
        another family must climb on ITS rounds: here claude's two make the
        retry round 3, which the document's rule steps up, where codex's
        none would have left it at round 1.
        """
        document = review_seats_document("restaff-round", ("codex", "claude"))
        document["rules"] = [
            {"type": "step_up", "role": "review", "min_round": 3}
        ]
        path = self.bound_to(document, name="ws-restaff-round")
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        self.recorded_rounds(path, "claude", 2)

        requests, patched = self.captured()
        subject = self.driver_for(path, [
            step("review_round", "not contract json", family="codex",
                 side_effect=self.restaffing_seat_one(document, 2)),
            step("review_round", report("review_round"), family="claude"),
        ])
        with patched:
            subject.step()

        session = self.session_of(path)
        swapped = stf.load(self.home, "restaff-round")
        stepped_up = stf.resolve(
            self.home, session, "review", index=1, round=3).answer
        self.assertNotEqual(
            stepped_up,
            stf.resolve(self.home, session, "review", index=1, round=1).answer,
        )
        self.assertEqual(swapped["assignment"]["review"]["1"], 2)
        self.assertEqual(
            subject.runner.call_meta[1],
            {"family": "claude", "kind": contracts.KIND_REVIEW_ROUND,
             "model": stepped_up["model"], "effort": stepped_up["effort"]},
        )
        # The preparing read asked at codex's round; the dispatch that
        # landed on claude asked again, at claude's.
        self.assertIn((1, 1), self.review_requests(requests))
        self.assertIn((1, 3), self.review_requests(requests))

    def test_a_flapping_document_runs_the_round_it_reports(self):
        """The staffing that runs is the answer FOR the round reported.

        A seat settles by asking, deriving the round its family wants, and
        asking again — so a document rewritten under consecutive asks can
        spend that bound: codex wants round 3 here and claude round 1, and
        the write moves the seat between them under every ask. What comes
        back is then the last family's round beside the answer FOR it, and
        never a rung resolved at a round already left behind: `step_up` at
        `min_round` 3 is what round 3 buys, and it is what runs.
        """
        document = review_seats_document("flapping", ("codex", "claude"))
        document["rules"] = [
            {"type": "step_up", "role": "review", "min_round": 3}
        ]
        path = self.bound_to(document, name="ws-flapping")
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        # codex wants round 3 and claude round 1, so the seat never settles
        # while the write keeps moving it between them.
        self.recorded_rounds(path, "codex", 2)

        real = stf.resolve
        reads = []

        def flapping(home, session, role, index=1, round=1, material=None,
                     brief=None, families=()):
            answer = real(home, session, role, index=index, round=round,
                          material=material, brief=brief, families=families)
            if role == "review":
                reads.append(round)
                if len(reads) <= drv._REVIEW_SEAT_SETTLE_READS:
                    moved = copy.deepcopy(document)
                    moved["assignment"]["review"] = (
                        {"1": 2, "2": 1} if len(reads) % 2
                        else {"1": 1, "2": 2}
                    )
                    stf.save(self.home, moved)
            return answer

        subject = self.driver_for(path, [])
        unit = subject.state["units"][0]
        with mock.patch.object(stf, "resolve", side_effect=flapping):
            round_number, resolution = subject._settled_review_seat(unit, 1)

        # Three asks that never settle, then one made AT the round returned.
        self.assertEqual(reads, [1, 3, 1, 3])
        self.assertEqual(round_number, 3)
        session = self.session_of(path)
        self.assertEqual(
            resolution.answer,
            stf.resolve(self.home, session, "review", index=1, round=3).answer,
        )
        # And round 3 really is a different rung, so the pairing is what the
        # provider runs on and not bookkeeping.
        self.assertNotEqual(
            resolution.answer,
            stf.resolve(self.home, session, "review", index=1, round=1).answer,
        )

    def writing_document_read(self, document):
        """Save *document* as the cycle's own document read answers.

        The write a torn cycle would need: it completes strictly INSIDE
        the read that describes the cycle, which is the only gap left.
        """
        real = stf._document_for
        reads = []

        def document_for(home, name):
            answer = real(home, name)
            reads.append(name)
            stf.save(self.home, document)
            return answer

        return reads, mock.patch.object(
            stf, "_document_for", side_effect=document_for
        )

    def test_the_cycle_is_read_from_one_document(self):
        """A write landing inside the read still describes one document.

        The cycle used to be read one seat at a time, so a save completing
        between two of those reads handed back a list built from BOTH — a
        seat-1 codex beside a seat-2 gemini, a pair NEITHER document
        assigns. Codex and gemini are clean and claude is not, so that pair
        would seal a unit the document before the write and the document
        after it both keep in review. One live read answers every seat from
        one document, so the torn pair is not constructible: what comes
        back is a cycle some document assigns, and a stale one is exactly
        what live seats mean — the write governs the next reading, whole.
        """
        before = review_seats_document("torn", ("codex", "claude"))
        path = self.bound_to(before, families=self.THREE, name="ws-torn")
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        self.recorded_rounds(path, "codex", 1)
        self.recorded_rounds(path, "gemini", 1)

        after = review_seats_document("torn", ("claude", "gemini"))
        reads, patched = self.writing_document_read(after)
        subject = self.driver_for(path, [])
        with patched:
            families = subject._review_families()
        unit = subject.state["units"][0]

        # One document read describes every seat, so the write has no gap
        # between two of them to land in.
        self.assertEqual(reads, ["torn"])
        self.assertEqual(families, ["codex", "claude"])
        self.assertIsNone(st.seal_predicate_reviews(unit, families))
        # The pair the torn reading would have sealed on.
        self.assertIsNotNone(
            st.seal_predicate_reviews(unit, ["codex", "gemini"])
        )
        # The completed write governs the next reading, whole.
        self.assertEqual(subject._review_families(), ["claude", "gemini"])

    def test_one_family_on_two_seats_is_read_as_the_document_wrote_it(self):
        """A document may seat one family twice, and that repeat is the
        cycle — the read answers one family per assigned seat, in seat
        order, and folds no repeat away."""
        path = self.bound_to(
            review_seats_document("twice", ("codex", "codex")),
            name="ws-twice",
        )
        subject = self.driver_for(path, [])
        self.assertEqual(subject._review_families(), ["codex", "codex"])

    def test_changed_bytes_restart_the_cycle_at_the_first_seat(self):
        """A fixer's accepted edit restarts the cycle at seat 1, and the
        earlier seats' clean rounds no longer satisfy the predicate."""
        path = self.bound_to(
            review_seats_document("restarting", self.THREE),
            families=self.THREE, name="ws-restart",
        )
        subject = self.driver_for(path, [
            self.draft(),
            step("review_round", report("review_round"), family="codex"),
            step("review_round",
                 report("review_round", [finding("F1", "no non-goals")]),
                 family="claude"),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "no non-goals")],
                        files_changed=["docs/skeleton.md"]),
                 family="codex",
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\n## Non-goals\n")),
            step("delta_review", report("delta_review"), family="codex"),
        ] + self.clean_rounds(self.THREE))
        self.step_until(subject, self.sealed, max_steps=60)
        # codex, claude, the fix and its delta, then a FULL fresh cycle.
        self.assertEqual(
            self.review_families_that_ran(subject),
            ["codex", "claude"] + list(self.THREE),
        )
        self.assertEqual(subject.runner.script, [])
        restarts = [
            event for event in st.load(path)["events"]
            if event["type"] == "review_cycle_restarted"
        ]
        self.assertTrue(restarts)

    def test_resume_amnesty_still_forgives_rounds_before_the_retry(self):
        """Amnesty is unchanged: it forgives rounds recorded before an
        operator retry, so the seat's next request counts from zero again."""
        path = self.bound_to(
            review_seats_document("amnesty", ["codex"]),
            families=("codex",), name="ws-amnesty",
        )
        subject = self.driver_for(path, [self.draft()])
        self.step_until(subject, self.in_rounds, max_steps=20)
        self.two_recorded_rounds(path)
        state = st.load(path)
        state["units"][0]["rounds_amnesty"] = len(state["units"][0]["rounds"])
        st.save(path, state)

        requests, patched = self.captured()
        subject = self.driver_for(path, self.clean_rounds(["codex"]))
        with patched:
            subject.step()
        self.assertEqual(
            [r for r in self.review_requests(requests) if r[1] > 1], []
        )
        self.assertIn((1, 1), self.review_requests(requests))


# ---------------------------------------------------------------------------
# A seat list that shrinks beneath the cycle stops no run


class AShrinkingSeatListStopsNoRun(ReviewCycleTestCase):
    def standing_on_the_third_seat(self, name):
        """A run whose first two of three review seats are clean."""
        path = self.bound_to(
            review_seats_document("shrinking", self.THREE),
            families=self.THREE, name=name,
        )
        subject = self.driver_for(path, [
            self.draft(),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
        ])
        self.step_until(
            subject,
            lambda state: state["units"][0].get("family_index") == 2,
            max_steps=30,
        )
        self.assertEqual(subject.runner.script, [])
        return path

    def test_review_cycle_survives_a_shrinking_seat_list(self):
        """Two ways the list shrinks, both sealing on the seats that remain.

        The cycle stands on seat 3; the seats it can still see are seat 1
        and seat 2, and both are clean on the current bytes, so the run
        continues through the ordinary pre-seal path and seals.
        """
        # (a) the document itself is edited down to two review seats.
        path = self.standing_on_the_third_seat("ws-shrink-edit")
        shrunk = review_seats_document("shrinking", self.THREE)
        shrunk["assignment"]["review"] = {"1": 1, "2": 2}
        stf.save(self.home, shrunk)
        subject = self.driver_for(path, [])
        self.step_until(subject, self.sealed, max_steps=20)
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(subject.runner.calls, [])

        # (b) the referenced document becomes unreadable, so the two-seat
        # `default` answers instead — the same seats, and the same seal.
        path = self.standing_on_the_third_seat("ws-shrink-unreadable")
        with open(os.path.join(stf.staffing_documents_dir(self.home),
                               "shrinking.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")
        subject = self.driver_for(path, [])
        self.step_until(subject, self.sealed, max_steps=20)
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(subject.runner.calls, [])

    def test_a_shrunken_cycle_restarts_when_a_current_seat_is_not_clean(self):
        """The other half of the same pre-seal path: a seat with no clean
        round in this cycle restarts it instead of sealing."""
        path = self.standing_on_the_third_seat("ws-shrink-restart")
        shrunk = review_seats_document("shrinking", ["claude", "gemini"])
        shrunk["name"] = "shrinking"
        stf.save(self.home, shrunk)
        subject = self.driver_for(path, self.clean_rounds(
            ["claude", "gemini"]
        ))
        self.step_until(subject, self.sealed, max_steps=30)
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(subject.runner.script, [])
        self.assertTrue([
            event for event in state["events"]
            if event["type"] == "review_cycle_restarted"
        ])

    def test_the_vanished_seat_s_admitted_review_is_abandoned(self):
        """A review admitted for the seat that shrinks away is failed.

        Its frozen request can never be dispatched — `review_round` is not
        continuable, and neither continuation runs it — so the exhausted
        cycle records the abandonment instead of carrying an open task
        reference onto a unit it is about to seal, where the supported
        repair reopen would then find no kind of its own to admit.
        """
        path = self.standing_on_the_third_seat("ws-shrink-admitted")
        # A crash after admission: the task is durable, the result is not.
        crashed = self.driver_for(path, [])
        admitted = crashed._admit_worker_task(
            st.current_unit(crashed.state),
            contracts.KIND_REVIEW_ROUND,
            "the third seat's frozen review prompt",
            "gemini",
        )
        shrunk = review_seats_document("shrinking", self.THREE)
        shrunk["assignment"]["review"] = {"1": 1, "2": 2}
        stf.save(self.home, shrunk)

        subject = self.driver_for(path, [])
        self.step_until(subject, self.sealed, max_steps=20)
        state = st.load(path)
        unit = state["units"][0]
        self.assertIsNone(state["failure"])
        self.assertEqual(subject.runner.calls, [])
        self.assertNotIn("active_task", unit)
        result = tasks.task_record(state, admitted["id"])["result"]
        self.assertEqual(result["status"], "failure")
        self.assertIsNone(result["native_result"])
        self.assertIn("shrank below the seat", result["reason"])

        # The sealed unit's supported repair admits its own successor.
        later = self.driver_for(path, [])
        sealed = later.state["units"][0]
        st.reopen_for_repair(
            later.state, sealed, {"classification": "gap"},
            reason="downstream reported a gap",
        )
        st.enter_fix_episode(
            later.state, sealed,
            [{"id": "G1", "severity": "P2", "summary": "gap"}],
            "repair", None, "%s-gap-repair" % st.unit_key(sealed),
            st.U_PRE_SEAL_VERIFY,
        )
        successor = later._admit_worker_task(
            sealed, contracts.KIND_FIX_FINDINGS, "repair the gap", "codex"
        )
        self.assertNotEqual(successor["id"], admitted["id"])


class ASurfacedConditionStopsOnlyADispatch(ReviewCycleTestCase):
    """Describing the review cycle is a read, and a read is not a call.

    `distinct_families_unsatisfiable` stops the review dispatches it
    affects and nothing else, so the cycle's own readers — the advance
    behind a finished round, the pre-seal seal predicate, and the
    checkpoint's current-family field — ANSWER under a declared split
    this session cannot honour. Refusing there
    failed a run that had dispatched nobody: it discarded a clean cycle
    the condition has no authority over and made the repaired document buy
    every round again.

    `staffing_unavailable` is the one condition a read still raises,
    because with no family available there is no cycle to describe. It
    stops the run without rewriting the cycle on its way out, so the
    repaired document seals on the rounds already earned.
    """

    TWO = ("codex", "claude")

    def at_pre_seal(self, name):
        """A run whose two assigned seats are both clean, awaiting its seal."""
        path = self.bound_to(
            review_seats_document("live", self.TWO),
            families=self.TWO, name=name,
        )
        subject = self.driver_for(
            path, [self.draft("codex")] + self.clean_rounds(list(self.TWO))
        )
        self.step_until(
            subject,
            lambda state: state["units"][0]["status"] == st.U_PRE_SEAL_VERIFY,
            max_steps=40,
        )
        self.assertEqual(subject.runner.script, [])
        return path

    def unsatisfiable_split(self):
        """The live document edited so `review`'s two seats collapse onto
        one slot while declaring the split — refused however this machine
        looks."""
        document = review_seats_document("live", self.TWO)
        document["roles"]["review"] = {"distinct_families": True}
        document["assignment"]["review"] = {"1": 1, "2": 1}
        return document

    def stopped(self, path, token):
        """The run stopped with *token*, and the cycle is where it was."""
        subject = self.driver_for(path, [])
        self.step_until(
            subject, lambda state: state["failure"] is not None, max_steps=10
        )
        state = st.load(path)
        unit = state["units"][0]
        self.assertIn(token, state["failure"]["reason"])
        self.assertEqual(subject.runner.calls, [])
        self.assertEqual(unit.get("review_cycle_start"), 0)
        self.assertEqual(unit.get("family_index"), 2)
        self.assertEqual(
            [event for event in state["events"]
             if event["type"] == "review_cycle_restarted"],
            [],
        )
        return unit

    def test_a_refused_split_seals_on_the_current_seats(self):
        """The seal read answers, so the earned rounds seal the unit.

        Both seats collapse onto codex, whose clean round is already in the
        ledger, so the currently assigned cycle is satisfied and the unit
        seals — the same pre-seal path a shrunken seat list takes. Nothing
        is dispatched, so nothing is refused.
        """
        path = self.at_pre_seal("ws-condition-split")
        stf.save(self.home, self.unsatisfiable_split())

        subject = self.driver_for(path, [])
        self.step_until(subject, self.sealed, max_steps=20)
        state = st.load(path)
        unit = state["units"][0]
        self.assertIsNone(state["failure"])
        self.assertEqual(subject.runner.calls, [])
        self.assertEqual(unit.get("review_cycle_start"), 0)
        self.assertEqual(
            [event for event in state["events"]
             if event["type"] == "review_cycle_restarted"],
            [],
        )

    def test_a_refused_split_lets_a_finished_round_advance_the_cycle(self):
        """The advance answers too, so the round that just landed stands.

        The document declares the split while the seat-1 reviewer is
        running, so the advance behind that round is the first reader to
        meet it. It moves the cycle to seat 2 instead of failing a run
        whose clean round is already recorded.
        """
        path = self.bound_to(
            review_seats_document("live", self.TWO),
            families=self.TWO, name="ws-condition-advance",
        )

        def declare_split(_workspace):
            stf.save(self.home, self.unsatisfiable_split())

        subject = self.driver_for(path, [
            self.draft("codex"),
            step("review_round", report("review_round"), family="codex",
                 side_effect=declare_split),
        ])
        self.step_until(
            subject,
            lambda state: state["units"][0].get("family_index") == 1,
            max_steps=40,
        )
        state = st.load(path)
        unit = state["units"][0]
        self.assertIsNone(state["failure"])
        self.assertEqual(self.review_families_that_ran(subject), ["codex"])
        self.assertEqual(unit.get("review_cycle_start"), 0)
        self.assertEqual(
            [r["family"] for r in unit["rounds"]
             if r["kind"] == contracts.KIND_REVIEW_ROUND],
            ["codex"],
        )

        # The checkpoint's current-family field is the third reader, and
        # `delta_checkpoint` has no other record of the seat a restarted
        # cycle stood on: under the split it names the described family
        # instead of the blank a refusing read used to leave behind.
        self.assertEqual(subject._current_review_family(unit), "codex")

        # (c) The condition appears once a review DISPATCH is attempted —
        # here seat 2, which the advance moved the cycle onto.
        self.step_until(
            subject, lambda state: state["failure"] is not None, max_steps=10
        )
        state = st.load(path)
        self.assertIn(
            stf.DISTINCT_FAMILIES_UNSATISFIABLE, state["failure"]["reason"]
        )
        self.assertEqual(self.review_families_that_ran(subject), ["codex"])
        self.assertEqual(state["units"][0].get("family_index"), 1)

    def test_no_family_available_stops_the_run_and_keeps_the_cycle(self):
        path = self.at_pre_seal("ws-condition-unavailable")
        stf.save(self.home, unstaffable_document("live"))
        self.stopped(path, stf.STAFFING_UNAVAILABLE)

    def test_the_repaired_document_seals_on_the_rounds_already_earned(self):
        """The whole point of keeping the cycle: no round is bought twice."""
        path = self.at_pre_seal("ws-condition-repair")
        stf.save(self.home, unstaffable_document("live"))
        self.stopped(path, stf.STAFFING_UNAVAILABLE)

        stf.save(self.home, review_seats_document("live", self.TWO))
        resumed = self.driver_for(path, [])
        st.resume_run(resumed.state)
        resumed._save()

        # Scripted rounds that must go unused: sealing may spend none.
        subject = self.driver_for(path, self.clean_rounds(list(self.TWO)))
        self.step_until(subject, self.sealed, max_steps=20)
        self.assertIsNone(st.load(path)["failure"])
        self.assertEqual(self.review_families_that_ran(subject), [])

    def outage_at(self, name, before):
        """A run stopped by an outage at the advance behind a clean round.

        *before* are the seats already clean when the document becomes
        unstaffable while the next seat's reviewer runs — so the first
        reader to find nobody to describe is that round's own advance.
        """
        path = self.bound_to(
            review_seats_document("live", self.TWO),
            families=self.TWO, name=name,
        )
        running = list(self.TWO)[len(before)]

        def go_unstaffable(_workspace):
            stf.save(self.home, unstaffable_document("live"))

        subject = self.driver_for(path, [self.draft("codex")]
                                  + self.clean_rounds(list(before))
                                  + [step("review_round",
                                          report("review_round"),
                                          family=running,
                                          side_effect=go_unstaffable)])
        self.step_until(
            subject, lambda state: state["failure"] is not None, max_steps=40
        )
        state = st.load(path)
        unit = state["units"][0]
        self.assertIn(stf.STAFFING_UNAVAILABLE, state["failure"]["reason"])
        self.assertEqual(subject.runner.script, [])
        # Every round earned stands, and nothing restarted the cycle.
        self.assertEqual(
            [r["family"] for r in unit["rounds"]
             if r["kind"] == contracts.KIND_REVIEW_ROUND],
            list(before) + [running],
        )
        self.assertEqual(unit.get("review_cycle_start"), 0)
        self.assertEqual(
            [event for event in state["events"]
             if event["type"] == "review_cycle_restarted"],
            [],
        )
        # The move the clean round earned happened before the stop.
        self.assertEqual(unit.get("family_index"), len(before) + 1)
        return path

    def repaired(self, path, script):
        """The repaired run, resumed and driven to its seal."""
        stf.save(self.home, review_seats_document("live", self.TWO))
        resumed = self.driver_for(path, [])
        st.resume_run(resumed.state)
        resumed._save()
        subject = self.driver_for(path, script)
        self.step_until(subject, self.sealed, max_steps=20)
        self.assertIsNone(st.load(path)["failure"])
        return subject

    def test_an_outage_at_the_advance_keeps_the_seat_it_earned(self):
        """The stop is not paid for with the round that just landed.

        The document goes unstaffable while the seat-1 reviewer runs, so
        the advance behind its clean round is the first reader with nobody
        to describe. It stops the run naming the token — after moving the
        cycle off the seat that round earned, because nothing skips a seat
        already clean and the repaired run would otherwise buy it again.
        """
        path = self.outage_at("ws-advance-outage", before=())

        # Only seat 2 is scripted: a re-bought seat 1 asks for codex and
        # the runner refuses the family it was not scripted for.
        subject = self.repaired(path, self.clean_rounds(["claude"]))
        self.assertEqual(self.review_families_that_ran(subject), ["claude"])
        self.assertEqual(
            [r["family"] for r in st.load(path)["units"][0]["rounds"]
             if r["kind"] == contracts.KIND_REVIEW_ROUND],
            ["codex", "claude"],
        )

    def test_an_outage_at_the_last_advance_reaches_pre_seal(self):
        """Same outage one seat later, where the move is into pre-seal.

        The cycle the last clean round exhausts is the cycle the repaired
        document seals on: it dispatches nobody and re-buys neither round.
        """
        path = self.outage_at("ws-advance-outage-last", before=("codex",))
        self.assertEqual(
            st.load(path)["units"][0].get("failed_from"), st.U_PRE_SEAL_VERIFY
        )

        subject = self.repaired(path, self.clean_rounds(list(self.TWO)))
        self.assertEqual(self.review_families_that_ran(subject), [])
        self.assertEqual(
            [r["family"] for r in st.load(path)["units"][0]["rounds"]
             if r["kind"] == contracts.KIND_REVIEW_ROUND],
            list(self.TWO),
        )


# ---------------------------------------------------------------------------
# The delta review's seat


class TheRoundsTimeProjectionIsBookkeeping(ReviewCycleTestCase):
    """The run summary's rounds-time review projection names the seat the
    next review round would run on — and never decides anything."""

    def test_marker_and_projection_are_best_effort(self):
        path = self.bound_to(
            review_seats_document("projected", ["gemini", "claude"]),
            families=self.THREE, name="ws-projection",
        )
        marker = {}
        subject = self.driver_for(path, [
            self.draft("gemini"),
            step("review_round", report("review_round"), family="gemini",
                 side_effect=capture_marker(marker)),
        ])
        self.step_until(subject, self.in_rounds, max_steps=20)

        # Standing on seat 1: the projection names that seat's family and
        # model, which the run's configured order (codex first) does not.
        projection = drv.resolve_current_review_model(path, self.home)
        self.assertEqual(projection[0], "gemini")
        summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertEqual(
            (summary["current_family"], summary["current_model"]), projection
        )
        self.assertNotEqual(summary["current_family"], "codex")

        # And it is exactly what the next round runs on.
        subject.step()
        self.assertEqual(
            (marker["family"], marker["model"]), projection
        )

        # Losing it changes nothing: the summary still loads, without a
        # rounds-time projection, and the run is unaffected.
        service._evict_summary(path)
        with mock.patch.object(stf, "session_seats", side_effect=OSError):
            self.assertIsNone(
                drv.resolve_current_review_model(path, self.home)
            )
            summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertIsNotNone(summary)
        self.assertIsNone(st.load(path)["failure"])


class DeltaReviewChoosesAReviewSeat(ReviewCycleTestCase):
    def dirty_then_fixed(self, plan_family, review_family):
        """A draft, one dirty round at review seat 1, and its fix.

        A fix on the SKELETON is the skeleton's own `plan` seat, so
        *plan_family* is both the drafting and the fixing family here, and
        *review_family* is what the document's review seat 1 resolves to.
        """
        return [
            self.draft(plan_family),
            step("review_round",
                 report("review_round", [finding("F1", "no non-goals")]),
                 family=review_family),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed", "no non-goals")],
                        files_changed=["docs/skeleton.md"]),
                 family=plan_family,
                 side_effect=write_file("docs/skeleton.md",
                                        "# Skeleton\n\n## Non-goals\n")),
        ]

    def test_delta_review_uses_the_fixers_review_seat(self):
        """The lowest-index review seat whose family is the fixer's."""
        document = review_seats_document(
            "delta-match", ["claude", "codex", "codex"]
        )
        # `fix 1` is on the first slot, which this document seats on claude,
        # so the fixer's family holds review seat 1 and codex holds 2 and 3.
        path = self.bound_to(document, name="ws-delta-match")
        marker = {}
        subject = self.driver_for(
            path,
            self.dirty_then_fixed("claude", "claude") + [
                step("delta_review", report("delta_review"), family="claude",
                     side_effect=capture_marker(marker)),
            ],
        )
        requests, patched = self.captured()
        with patched:
            self.step_until(
                subject,
                lambda state: any(
                    r["kind"] == contracts.KIND_DELTA_REVIEW
                    for r in state["units"][0]["rounds"]
                ),
                max_steps=40,
            )
        self.assertEqual(subject.runner.script, [])
        # The delta asked at a `review` seat, and the marker names who ran.
        self.assertEqual(marker["kind"], contracts.KIND_DELTA_REVIEW)
        self.assertEqual(marker["family"], "claude")
        self.assertIn(
            "review", {r["role"] for r in requests}
        )

    def test_with_no_matching_seat_the_delta_takes_the_lowest_one(self):
        document = review_seats_document(
            "delta-nomatch", ["claude", "gemini"], distinct=True
        )
        # A fix on the skeleton is its `plan` seat, so move `plan` onto a
        # third slot whose family no review seat holds.
        document["families"]["3"] = {
            "name": "codex",
            "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
            "efforts": ["low", "medium", "high", "xhigh", "max"],
        }
        for by_slot in document["tuning"].values():
            by_slot["3"] = copy.deepcopy(by_slot["1"])
        document["assignment"]["plan"] = {"1": 3}
        path = self.bound_to(
            document, families=("codex", "claude", "gemini"),
            name="ws-delta-nomatch",
        )
        marker = {}
        subject = self.driver_for(
            path,
            self.dirty_then_fixed("codex", "claude") + [
                step("delta_review", report("delta_review"), family="claude",
                     side_effect=capture_marker(marker)),
            ],
        )
        self.step_until(
            subject,
            lambda state: any(
                r["kind"] == contracts.KIND_DELTA_REVIEW
                for r in state["units"][0]["rounds"]
            ),
            max_steps=40,
        )
        self.assertEqual(subject.runner.script, [])
        self.assertEqual(marker["family"], "claude")  # review seat 1


# ---------------------------------------------------------------------------
# The two conditions, and everything that is not one


class StoppingConditions(StaffingCutoverTestCase):
    def test_a_split_review_the_machine_cannot_honour_stops_the_run(self):
        """The second condition, raised at the review dispatch and not before.

        The converted `default` declares `review` split across its two
        seats. A run whose available families are one collapses both onto
        that family, so the split cannot be honoured — and the run stops
        there, after its draft has already dispatched. A `review` role with
        one assigned seat honours any split trivially and runs normally.
        """
        path = self.run_state(
            "ws-split", families_order=["codex"], fix_family="codex",
            commands={"codex": ["fake-codex"]},
        )
        subject = self.driver_for(path, [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "One"}]),
                 family="codex",
                 side_effect=write_file("docs/skeleton.md", "# Skeleton\n")),
        ])
        self.step_until(
            subject,
            lambda state: state["failure"] is not None,
            max_steps=20,
        )
        state = st.load(path)
        self.assertIn(
            stf.DISTINCT_FAMILIES_UNSATISFIABLE, state["failure"]["reason"]
        )
        # The draft ran: the condition stopped the review dispatch alone.
        self.assertEqual(
            [call[1] for call in subject.runner.calls],
            [contracts.KIND_DRAFT_SKELETON],
        )

        # The same single-family run, under a `review` role with one seat.
        path = self.bound_to(
            one_review_seat(stf.default_document_seed()),
            families=("codex",), name="ws-split-one-seat",
        )
        subject = self.driver_for(path, [
            step("draft_skeleton",
                 ok("draft_skeleton", artifact="docs/skeleton.md",
                    slices=[{"id": 1, "title": "One"}]),
                 family="codex",
                 side_effect=write_file("docs/skeleton.md", "# Skeleton\n")),
            step("review_round", report("review_round"), family="codex"),
        ])
        self.step_until(
            subject,
            lambda state: state["units"][0]["status"] == st.U_SEALED,
            max_steps=30,
        )
        self.assertIsNone(st.load(path)["failure"])
        self.assertEqual(subject.runner.script, [])

    def test_no_family_available_stops_the_call(self):
        path = self.run_state("ws-unavailable")
        subject = self.driver_for(path)
        stf.save(self.home, unstaffable_document())
        stf.edit_session(
            self.home, self.session_of(path), {"document": "ghosts"})
        with self.assertRaises(drv.StopStep):
            subject._staff("implement")
        failure = st.load(path)["failure"]
        self.assertIn(stf.STAFFING_UNAVAILABLE, failure["reason"])
        self.assertEqual(subject.runner.calls, [])

    def test_unreadable_inputs_dispatch_on_the_default_document(self):
        path = self.run_state("ws-fallback")
        subject = self.driver_for(path)
        session = self.session_of(path)
        session_path = os.path.join(
            stf.staffing_sessions_dir(self.home), "%s.json" % session)
        document_path = os.path.join(
            stf.staffing_documents_dir(self.home), "default.json")
        stored_default = read_bytes(document_path)
        stored_session = read_bytes(session_path)

        def corrupt(target):
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("{ not json")

        cases = {
            "absent session": lambda: os.unlink(session_path),
            "corrupt session": lambda: corrupt(session_path),
            "absent referenced document": lambda: os.unlink(document_path),
            "corrupt referenced document": lambda: corrupt(document_path),
        }
        for label, damage in cases.items():
            with self.subTest(case=label):
                with open(session_path, "wb") as handle:
                    handle.write(stored_session)
                with open(document_path, "wb") as handle:
                    handle.write(stored_default)
                damage()
                resolver = subject._dispatch_for_role("implement")
                self.assertEqual(resolver(), IMPLEMENT)
                self.assertEqual(
                    resolver.staffing_fallback,
                    stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT,
                )
                self.assertIsNone(st.load(path)["failure"])

        # A damaged stored `default` is answered from the in-code seed and
        # is never repaired: the operator's bytes stay exactly as they are.
        corrupt(document_path)
        damaged = read_bytes(document_path)
        resolver = subject._dispatch_for_role("implement")
        self.assertEqual(resolver(), IMPLEMENT)
        self.assertEqual(resolver.staffing_fallback,
                         stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT)
        self.assertEqual(read_bytes(document_path), damaged)

        # And a run RESTARTED over that damaged `default` dispatches the
        # same way: start-up conversion refuses to count it, as loudly as
        # it always has, but the driver neither fails the run nor raises —
        # an unreadable input stops no dispatch and blocks no resume.
        restarted = self.driver_for(path)
        resolver = restarted._dispatch_for_role("implement")
        self.assertEqual(resolver(), IMPLEMENT)
        self.assertEqual(resolver.staffing_fallback,
                         stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT)
        self.assertIsNone(st.load(path)["failure"])
        self.assertEqual(read_bytes(document_path), damaged)
        self.assertEqual(self.session_of(path), session)

    def test_the_marker_carries_the_fallback_note(self):
        path = self.run_state("ws-marker")
        subject = self.driver_for(path)
        session_path = os.path.join(
            stf.staffing_sessions_dir(self.home),
            "%s.json" % self.session_of(path))
        stored = read_bytes(session_path)
        os.unlink(session_path)
        markers = []
        subject.runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "expect_family": IMPLEMENT[0],
             "response": ok(contracts.KIND_IMPLEMENT, files_changed=[]),
             "side_effect": lambda _ws: markers.append(subject._read_busy())},
        ])
        subject._call(
            IMPLEMENT[0],
            "KIND: implement\nFAMILY: %s\nWORKSPACE: %s\n\nmarker"
            % (IMPLEMENT[0], subject.workspace),
            contracts.KIND_IMPLEMENT,
            "marker-dispatch",
            dispatch_resolver=subject._dispatch_for_role("implement"),
        )
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["family"], IMPLEMENT[0])
        self.assertEqual(markers[0]["staffing_fallback"], "default_document")

        # A call that no longer falls back loses the note.
        subject.runner = runners.MockRunner([
            {"expect_kind": contracts.KIND_IMPLEMENT,
             "expect_family": IMPLEMENT[0],
             "response": ok(contracts.KIND_IMPLEMENT, files_changed=[]),
             "side_effect": lambda _ws: markers.append(subject._read_busy())},
        ])
        with open(session_path, "wb") as handle:
            handle.write(stored)
        subject._call(
            IMPLEMENT[0],
            "KIND: implement\nFAMILY: %s\nWORKSPACE: %s\n\nmarker"
            % (IMPLEMENT[0], subject.workspace),
            contracts.KIND_IMPLEMENT,
            "marker-dispatch-2",
            dispatch_resolver=subject._dispatch_for_role("implement"),
        )
        self.assertNotIn("staffing_fallback", markers[1])


# ---------------------------------------------------------------------------
# The consultation


class ConsultationCommand(StaffingCutoverTestCase):
    def test_the_command_resolves_the_consult_seat_when_it_runs(self):
        path = self.run_state("ws-consult")
        subject = self.driver_for(path)
        argv = subject._consultation_command("ignored", "ignored")
        self.assertEqual(argv[2:], [
            "--state", os.path.abspath(path),
            "--home", os.path.abspath(self.home),
        ])
        self.assertEqual(
            current_model_call.consultation_command(path, self.home),
            runners.apply_model_effort(
                subject.config["commands"][CONSULT[0]], CONSULT[1], CONSULT[2]),
        )

        # It resolves when the FIXER runs it, so a session edit reaches it.
        stf.save(self.home, restaffed_document("codex-only", "codex"))
        stf.edit_session(self.home, self.session_of(path),
                         {"document": "codex-only"})
        rebound = current_model_call.consultation_command(path, self.home)
        self.assertEqual(rebound[0], subject.config["commands"]["codex"][0])
        # The command line is unchanged: it never carried a family.
        self.assertEqual(
            subject._consultation_command("ignored", "ignored"), argv)

    def test_a_pre_cutover_command_line_still_runs(self):
        """A fixer admitted BEFORE the cutover keeps a runnable prompt.

        Its stored prompt is immutable and still passes the caller
        derivation this slice retired. The flags now decide nothing — the
        run's `consult` seat does — but they must not make the mandatory
        consultation unrunnable, or an obedient fixer returns the retry
        envelope forever from a prompt it cannot change.
        """
        path = self.run_state("ws-old-consult")
        subject = self.driver_for(path)
        expected = current_model_call.consultation_command(path, self.home)
        for legacy in (
            ["--caller-act", "fixer"],
            ["--caller-act", "skeletoner"],
            ["--caller-act", "fixer", "--caller-origin", "codex"],
        ):
            with self.subTest(argv=" ".join(legacy)):
                with mock.patch.object(
                    current_model_call.os, "execvp"
                ) as execvp:
                    current_model_call.main(
                        ["--state", path, "--home", self.home] + legacy
                    )
                execvp.assert_called_once_with(expected[0], expected)
        self.assertEqual(
            expected,
            runners.apply_model_effort(
                subject.config["commands"][CONSULT[0]], CONSULT[1],
                CONSULT[2]),
        )


# ---------------------------------------------------------------------------
# The run binding, and amendment A2


class RunBinding(StaffingCutoverTestCase):
    def test_resume_derives_a_session_and_carries_nothing_else(self):
        model_profiles.save(self.home, {
            "name": "chosen", "examples": ["chosen"],
            "configurations": {"low": {}, "medium": {}, "high": {}},
        })
        path = self.run_state("ws-resume")
        self.sidecar(path, "model_profile.json",
                     {"name": "chosen", "rigor": "high"})
        self.sidecar(path, "acts.json", {
            "implementer": {"agent": "codex", "model": "carried",
                            "effort": "low"},
        })
        acts_bytes = read_bytes(
            os.path.join(os.path.dirname(path), "acts.json"))
        profile_path = os.path.join(
            model_profiles.model_profiles_dir(self.home), "chosen.json")
        profile_bytes = read_bytes(profile_path)

        self.driver_for(path)
        record = stf.read_session(self.home, self.session_of(path))
        self.assertEqual(record["document"], "chosen")
        self.assertEqual(record["rigor"], "high")
        self.assertEqual(record["families"], ["codex", "claude"])
        self.assertEqual(
            record["work_area"],
            {"workspace_path": os.path.abspath(st.load(path)["workspace"])},
        )
        # Nothing else is derived: no override is written from acts.json,
        # and no profile file or act sidecar is edited or deleted.
        self.assertNotIn("overrides", record)
        self.assertNotIn("material", record)
        self.assertEqual(
            read_bytes(os.path.join(os.path.dirname(path), "acts.json")),
            acts_bytes)
        self.assertEqual(read_bytes(profile_path), profile_bytes)

        # Binding is once: a second resume reuses the same id.
        first = self.session_of(path)
        self.driver_for(path)
        self.assertEqual(self.session_of(path), first)
        self.assertEqual(
            len([event for event in st.load(path)["events"]
                 if event["type"] == "staffing_session_bound"]), 1)

    def test_an_unknown_profile_name_or_no_selection_gives_default(self):
        for label, selection, rigor in (
            ("unknown name", {"name": "missing", "rigor": "low"}, "low"),
            ("no selection", None, "medium"),
        ):
            with self.subTest(case=label):
                path = self.run_state("ws-derive-%s" % rigor)
                if selection is not None:
                    self.sidecar(path, "model_profile.json", selection)
                self.driver_for(path)
                record = stf.read_session(self.home, self.session_of(path))
                self.assertEqual(record["document"], "default")
                self.assertEqual(record["rigor"], rigor)

    def test_a_session_that_cannot_be_created_never_blocks_resume(self):
        path = self.run_state("ws-unbindable")
        with mock.patch.object(
            stf, "create_session",
            side_effect=stf.StaffingError("no session store"),
        ):
            subject = self.driver_for(path)
        self.assertIsNone(st.load(path).get("staffing_session"))
        # Every call still resolves — visibly, on the default document.
        resolver = subject._dispatch_for_role("implement")
        self.assertEqual(resolver(), IMPLEMENT)
        self.assertEqual(resolver.staffing_fallback,
                         stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT)

        # A catalogue the derivation cannot even LIST is the same story:
        # reading the stored names to check the selection is part of the
        # derivation and fails like the rest of it — unbound, never out of
        # the constructor, and never a failed run.
        path = self.run_state("ws-unlistable")
        self.sidecar(path, "model_profile.json",
                     {"name": "default", "rigor": "high"})
        documents = stf.staffing_documents_dir(self.home)
        real_listdir = os.listdir

        def unreadable(target, *args, **kwargs):
            if os.path.abspath(target) == os.path.abspath(documents):
                raise PermissionError(13, "Permission denied", target)
            return real_listdir(target, *args, **kwargs)

        with mock.patch.object(os, "listdir", side_effect=unreadable):
            subject = self.driver_for(path)
        self.assertIsNone(st.load(path).get("staffing_session"))
        self.assertIsNone(st.load(path)["failure"])
        resolver = subject._dispatch_for_role("implement")
        self.assertEqual(resolver(), IMPLEMENT)
        self.assertEqual(resolver.staffing_fallback,
                         stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT)

    def test_a_bound_runs_work_area_records_its_project(self):
        path = self.run_state("ws-project")
        state = st.load(path)
        state["project"] = {
            "directory": self.home, "project": "orchestrators",
            "work_area": "implementation", "primary": None,
            "additional": [],
        }
        st.save(path, state)
        self.driver_for(path)
        record = stf.read_session(self.home, self.session_of(path))
        self.assertEqual(record["work_area"]["project"], "orchestrators")
        self.assertEqual(record["work_area"]["work_area"], "implementation")
        self.assertIn("workspace_path", record["work_area"])


# ---------------------------------------------------------------------------
# The launch surface


class LaunchBinding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-cutover-launch-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        os.makedirs(self.home)
        self.server = service.make_server(self.home, 0)
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None):
        data = (json.dumps(payload).encode("utf-8")
                if payload is not None else None)
        request = urllib.request.Request(
            self.base + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def workspace(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        subprocess.run(["git", "init", "-q", path], check=True)
        return path

    def launch(self, name, **extra):
        payload = {
            "workspace": self.workspace(name), "goal": "staffed goal",
            "autostart": False, "config": {"docs_dir": "docs"},
        }
        payload.update(extra)
        return self.request("POST", "/api/runs", payload)

    def state_path_of(self, body):
        entry = registry.get(registry.load(self.home), body["run"]["id"])
        return entry["state_path"]

    def test_launch_binds_one_session(self):
        model_profiles.ensure_default(self.home)
        stf.ensure_documents(self.home)
        document = stf.default_document_seed()
        document["name"] = "house"
        document["materials"]["prose"] = {"examples": ["docs"]}
        stf.save(self.home, document)

        status, body = self.launch("ws-staffed", staffing={
            "document": "house", "rigor": "high", "material": "prose"})
        self.assertEqual(status, 201, body)
        path = self.state_path_of(body)
        record = stf.read_session(self.home, st.load(path)["staffing_session"])
        self.assertEqual(
            (record["document"], record["rigor"], record["material"]),
            ("house", "high", "prose"),
        )
        self.assertEqual(
            record["families"],
            drv.load_config(None)["families_order"],
        )

        # No `staffing` binds the default document at medium.
        status, body = self.launch("ws-plain")
        self.assertEqual(status, 201, body)
        plain = stf.read_session(
            self.home,
            st.load(self.state_path_of(body))["staffing_session"])
        self.assertEqual((plain["document"], plain["rigor"]),
                         ("default", "medium"))
        self.assertNotIn("material", plain)

    def test_a_launch_that_cannot_be_honoured_creates_nothing(self):
        for label, payload in (
            ("model_profile", {"model_profile": {"name": "x",
                                                 "rigor": "medium"}}),
            ("null model_profile", {"model_profile": None}),
            ("unknown rigor", {"staffing": {"document": "default",
                                            "rigor": "brutal"}}),
            ("unknown key", {"staffing": {"seats": {}}}),
            ("bad document name", {"staffing": {"document": "../escape",
                                                "rigor": "medium"}}),
            # A SUPPLIED selection must say what it selects. Omitting
            # `staffing` is the only launch that means `default@medium`; a
            # blank or half-filled one silently becoming that would bind the
            # whole run — once, with no route here to change it — to a
            # document the caller never named.
            ("null staffing", {"staffing": None}),
            ("empty staffing", {"staffing": {}}),
            ("blank document", {"staffing": {"document": "",
                                             "rigor": "high"}}),
            ("blank rigor", {"staffing": {"document": "default",
                                          "rigor": ""}}),
            ("no rigor", {"staffing": {"document": "default"}}),
            ("no document", {"staffing": {"rigor": "high"}}),
        ):
            with self.subTest(case=label):
                workspace = self.workspace("ws-refused-%s" % label.replace(
                    " ", "-"))
                status, body = self.request("POST", "/api/runs", dict(
                    {"workspace": workspace, "goal": "refused",
                     "autostart": False, "config": {"docs_dir": "docs"}},
                    **payload))
                self.assertEqual(status, 400, body)
                self.assertFalse(os.path.exists(
                    drv.default_state_path(workspace)))

    def test_attach_neither_takes_staffing_nor_needs_it(self):
        workspace = self.workspace("ws-attach")
        drv.init_run("attach", workspace,
                     state_path=drv.default_state_path(workspace))
        status, body = self.request("POST", "/api/runs", {
            "workspace": workspace, "attach": True, "autostart": False,
            "staffing": {"document": "default", "rigor": "low"},
        })
        self.assertEqual(status, 400, body)
        self.assertIn("attach", body["error"])

        status, body = self.request("POST", "/api/runs", {
            "workspace": workspace, "attach": True, "autostart": False,
        })
        self.assertEqual(status, 201, body)
        # Adopted as it is: the first resume derives its session (A2).
        self.assertIsNone(
            st.load(self.state_path_of(body)).get("staffing_session"))

    def test_the_binding_is_never_rewritten(self):
        model_profiles.ensure_default(self.home)
        stf.ensure_documents(self.home)
        _status, body = self.launch("ws-once", staffing={
            "document": "default", "rigor": "low"})
        path = self.state_path_of(body)
        bound = st.load(path)["staffing_session"]
        # A second binding attempt — a launch retry, or a resume — keeps it.
        self.assertEqual(
            drv.open_run_staffing_session(path, self.home, "default", "high"),
            bound,
        )
        drv.Driver(path, runner=runners.MockRunner([]),
                   model_profiles_home=self.home)
        self.assertEqual(st.load(path)["staffing_session"], bound)
        self.assertEqual(
            stf.read_session(self.home, bound)["rigor"], "low")

    def test_document_list_route_and_launch_selector(self):
        model_profiles.ensure_default(self.home)
        stf.ensure_documents(self.home)
        second = stf.default_document_seed()
        second["name"] = "aardvark"
        stf.save(self.home, second)

        status, body = self.request("GET", "/api/staffing/documents")
        self.assertEqual(status, 200, body)
        self.assertEqual([d["name"] for d in body["documents"]],
                         ["aardvark", "default"])

        # A damaged store fails loudly rather than looking merely shorter.
        with open(os.path.join(stf.staffing_documents_dir(self.home),
                               "aardvark.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        status, _body = self.request("GET", "/api/staffing/documents")
        self.assertEqual(status, 500)

        with urllib.request.urlopen(self.base + "/", timeout=10) as response:
            panel = response.read().decode("utf-8")
        self.assertIn('id="f_staffing_document"', panel)
        self.assertIn('id="f_staffing_rigor"', panel)
        self.assertIn('api("/api/staffing/documents")', panel)
        self.assertIn("payload.staffing = {", panel)
        self.assertNotIn('id="f_model_profile"', panel)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
