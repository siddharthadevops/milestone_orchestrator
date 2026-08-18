"""Slice 4a: the milestone driver's single-seat calls, and the run binding.

After this cut every worker call the driver makes for a unit's own work —
the skeleton draft, the slice-note draft, the implementation, the fixer, the
failure classifier, the debt rater and the fixer's consultation — takes its
family, model and effort from the run's staffing session and from nothing
else. The run gets that session at launch, or at the first resume that finds
none (amendment A2).

Review rounds and delta reviews still rotate over the run's configured
families here; the review seats, the split-family check before a review
dispatch and the rounds-time projection are the second part of this slice.
"""

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
# a family rather than repeating a literal. Reviews are deliberately absent:
# they are still family-rotated in this cut.

PLAN = ("claude", "claude-fable-5", "max")
DRAFT = ("codex", "gpt-5.6-sol", "xhigh")
IMPLEMENT = ("claude", "claude-fable-5", "max")
FIX = ("codex", "gpt-5.6-sol", "xhigh")
CLASSIFY = ("codex", "gpt-5.6-sol", "xhigh")
CONSULT = ("claude", "claude-opus-5", "xhigh")


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


# ---------------------------------------------------------------------------
# Every driver-made call asks the router


class DriverCallsAskTheRouter(StaffingCutoverTestCase):
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
            # Delta review still follows the FIXER's family (unchanged law),
            # and the skeleton's fixer is now the `plan` seat.
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
        # No role outside the driver's own worker calls, and no request
        # carries a material or a brief before slice 9.
        self.assertEqual(
            sorted({role for role, _index, _round in seats}),
            ["consult", "draft", "fix", "implement", "plan"],
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
# The two conditions, and everything that is not one


class StoppingConditions(StaffingCutoverTestCase):
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
