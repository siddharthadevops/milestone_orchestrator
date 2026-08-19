"""Focused executable evidence for staffing-router slice 07.

Standalone work and the operator's git alignment stop choosing their own
intelligence from the first configured family. A task order carries the
session its owner already holds, an agent-call order says which process
step it performs, and both physical calls — the direct host's one call and
the alignment's one call — ask the router immediately before making it.

What a call actually ran on is what the marker and the alignment outcome
say. A record admitted before this cutover carries no session field at all,
and that absence keeps it running exactly the staffing frozen on it.
"""

import copy
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

from orchestrator import access, contracts, gitsync, runners, service
from orchestrator import brainstorming_tasks as bs_tasks
from orchestrator import staffing as stf
from orchestrator import state as st
from orchestrator import task_api, tasks
from orchestrator import driver as drv


# ---------------------------------------------------------------------------
# Documents a test can name an exact answer from.
#
# One family slot carrying exactly one model and one effort, and every role
# on rank [1, 1]: the answer is the ladder itself, so an assertion says
# WHICH document staffed a call rather than repeating a rung arithmetic.


def role_document(name, family, model, effort):
    """A complete document answering *family/model/effort* for every role."""
    document = stf.default_document_seed()
    document["name"] = name
    document["families"] = {
        "1": {"name": family, "models": [model], "efforts": [effort]}
    }
    document["roles"] = {role: {} for role in stf.ROLES}
    for rigor in document["tuning"]:
        document["tuning"][rigor] = {
            "1": {role: [1, 1] for role in stf.ROLES}
        }
    document["assignment"] = {role: {"1": 1} for role in stf.ROLES}
    return document


def split_document(name, role):
    """A document declaring a split *role* that one family cannot honour.

    Two seats on the one slot: whatever the document numbers them, they
    collapse onto one family, which is `distinct_families_unsatisfiable`
    for the dispatches that role affects and for nothing else.
    """
    document = role_document(name, "codex", "gpt-5.6-luna", "low")
    document["roles"][role] = {"distinct_families": True}
    document["assignment"][role] = {"1": 1, "2": 1}
    return document


LUNA = ("codex", "gpt-5.6-luna", "low")
FABLE = ("claude", "claude-fable-5", "max")


def answer_of(resolution):
    return (
        resolution.answer["agent"],
        resolution.answer["model"],
        resolution.answer["effort"],
    )


class RecordingRunner:
    """One provider seam that records the staffing its call was given."""

    def __init__(self, calls, text="native text", error=None):
        self.calls = calls
        self.text = text
        self.error = error

    def call(self, family, prompt, workspace, model=None, effort=None):
        self.calls.append({
            "family": family, "prompt": prompt, "workspace": workspace,
            "model": model, "effort": effort,
        })
        if self.error is not None:
            raise self.error
        return runners.RunnerResult(self.text, 0, 1.0)


class StandaloneCutoverTestCase(unittest.TestCase):
    """A served home, one direct host, and a controlled standing config."""

    MEMBER = access.USER_EMAILS[1]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="orch-standalone-")
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = self.directory("workspace")
        self.additional = self.directory("additional")
        self.calls = []
        self.runner = RecordingRunner(self.calls)
        self.config = service.driver.load_config(None)
        self.config["families_order"] = ["codex", "claude"]
        self.config["billing"] = {"codex": "subscription",
                                  "claude": "subscription"}
        self.host = task_api.DirectTaskHost(
            self.home,
            runner_factory=lambda _config, _workspace: self.runner,
            poll_interval=0.01,
        )
        self.start_server()
        patch = mock.patch.object(
            service,
            "_direct_task_config",
            side_effect=lambda *_a, **_kw: copy.deepcopy(self.config),
        )
        patch.start()
        self.addCleanup(patch.stop)

    # -- harness ---------------------------------------------------------

    def directory(self, name):
        path = os.path.join(self.tmp.name, name)
        os.makedirs(path, exist_ok=True)
        return path

    def start_server(self):
        server = service.make_server(self.home, 0, task_host=self.host)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop)
        self.base = "http://127.0.0.1:%d" % server.server_address[1]

    def request(self, method, path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path, data=data, method=method
        )
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def member_headers(self, email=None):
        return {
            "Host": "example.ngrok-free.dev",
            access.REMOTE_HEADER: access.REMOTE_MARKER,
            access.USER_HEADER: email or self.MEMBER,
        }

    # -- fixtures --------------------------------------------------------

    def order(self, executor="agent_call", **changes):
        body = {
            "task_executor": executor,
            "request": {
                "work_area": {
                    "workspace_path": self.workspace,
                    "primary": self.workspace,
                    "additional": [self.additional],
                },
                "request": "Do exactly the caller-authored work.",
                "context": {"source": "slice-07"},
                "reference_documents": [],
            },
        }
        body.update(changes)
        return body

    def save(self, document):
        stf.save(self.home, document)
        return document["name"]

    def session(self, document, work_area=None, families=("codex", "claude")):
        return stf.create_session(self.home, {
            "work_area": work_area or {"workspace_path": self.workspace},
            "families": list(families),
            "document": document,
            "rigor": "medium",
        })["id"]

    def store(self):
        return task_api.StandaloneTaskStore(self.home)

    def records(self):
        return self.store().records()

    def admit(self, **changes):
        """Admit one order without letting the host start it yet.

        Admission and execution are one request in production. A test that
        has to change the session BETWEEN them suppresses only the
        automatic hand-off and then starts the very same host itself, so
        what runs is the production path with a seam to stand in.
        """
        with mock.patch.object(self.host, "start", return_value=None):
            status, body = self.request(
                "POST", "/api/tasks", self.order(**changes)
            )
        self.assertEqual(status, 201, body)
        return body["task"]

    def run_task(self, task_id):
        """Hand one admitted record to the direct host and wait it out."""
        self.host.start(
            self.store().record(task_id), lambda: copy.deepcopy(self.config)
        )
        return self.terminal(task_id)

    def terminal(self, task_id):
        deadline = time.time() + 10
        while time.time() < deadline:
            record = self.store().record(task_id)
            if record["result"] is not None:
                return record
            time.sleep(0.01)
        self.fail("task %s never became terminal" % task_id)

    def marker(self, task_id):
        try:
            return task_api.read_worker_marker(self.home, task_id)
        except OSError:
            return None

    def resolved(self, session, role="implement", **kwargs):
        return answer_of(stf.resolve(
            self.home, session, role,
            families=list(self.config["families_order"]), **kwargs
        ))


# ---------------------------------------------------------------------------
# One milestone run, built directly at the order-construction seam.


def milestone_state(workspace, unit_kind, status=st.U_PENDING):
    """One run state whose current unit is *unit_kind* at *status*."""
    os.makedirs(os.path.join(workspace, "docs"), exist_ok=True)
    config = copy.deepcopy(drv.DEFAULT_CONFIG)
    config.update({
        "git": {"enabled": False},
        "verification": [],
        "guarantee_calibration": {"enabled": False},
        "error_classifier": False,
    })
    state = st.new_state("Cut standalone staffing over.", workspace, config)
    state["milestone"]["slices"] = [{"id": 1, "title": "One"}]
    skeleton = st._new_unit(st.UNIT_SKELETON, None)
    skeleton.update({"status": st.U_SEALED, "artifact": "docs/skeleton.md"})
    note = st._new_unit(st.UNIT_SLICE_DOC, 1)
    note.update({"status": st.U_SEALED, "artifact": "docs/note.md"})
    implementation = st._new_unit(st.UNIT_SLICE_IMPL, 1)
    implementation["status"] = status
    if unit_kind == st.UNIT_SKELETON:
        skeleton.update({"status": status, "artifact": None})
        state["milestone"]["slices"] = []
        state["units"] = [skeleton]
    elif unit_kind == st.UNIT_SLICE_DOC:
        note.update({"status": status, "artifact": None})
        state["units"] = [skeleton, note, implementation]
    else:
        state["units"] = [skeleton, note, implementation]
    for relative, text in (
        ("docs/skeleton.md", "# Skeleton\n"), ("docs/note.md", "# Note\n"),
    ):
        with open(os.path.join(workspace, relative), "w",
                  encoding="utf-8") as handle:
            handle.write(text)
    path = drv.default_state_path(workspace)
    st.save(path, state)
    return path


class OrderContextAndRoleTest(StandaloneCutoverTestCase):
    """Every new order carries ONE session and the role its step performs."""

    def test_task_orders_carry_one_session_and_owned_role(self):
        self._catalogue_offers_the_closed_role_choice()
        self._direct_orders_persist_the_supplied_or_default_session()
        self._named_session_is_authorized_before_admission()
        self._milestone_orders_record_the_step_that_owns_them()

    # -- the catalogue ---------------------------------------------------

    def _catalogue_offers_the_closed_role_choice(self):
        status, body = self.request("GET", "/api/task-executors")
        self.assertEqual(status, 200, body)
        entry = body["task_executors"][0]
        self.assertEqual(entry["id"], "agent_call")
        self.assertEqual(
            entry["configuration_schema"],
            {
                "role": {
                    "type": "choice",
                    "choices": [
                        "plan", "draft", "implement", "fix", "classify",
                        "review", "brainstorm", "consult", "sync",
                    ],
                    "default": "implement",
                },
            },
        )
        self.assertEqual(
            entry["configuration_schema"]["role"]["choices"],
            list(stf.ROLES),
        )
        # A seat and a round are consumer facts, never order input.
        for refused in ({"role": "reviewer"}, {"role": "review", "index": 2},
                        {"role": "review", "round": 3}):
            with self.subTest(configuration=refused):
                before = len(self.records())
                status, body = self.request(
                    "POST", "/api/tasks", self.order(configuration=refused)
                )
                self.assertEqual(
                    (status, body["error"]),
                    (400, tasks.INVALID_TASK_REQUEST),
                    body,
                )
                self.assertEqual(len(self.records()), before)

    # -- the direct order ------------------------------------------------

    def _direct_orders_persist_the_supplied_or_default_session(self):
        named = self.session(stf.DEFAULT_DOCUMENT_NAME)
        cases = (
            ("supplied", {"staffing_session": named}, named),
            ("omitted", {}, None),
            ("explicit null", {"staffing_session": None}, None),
        )
        opened = sorted(os.listdir(stf.staffing_sessions_dir(self.home)))
        for label, changes, expected in cases:
            with self.subTest(session=label):
                task = self.admit(**changes)
                stored = self.store().record(task["id"])["order"]
                self.assertEqual(stored["staffing_session"], expected)
                self.assertEqual(
                    tasks.order_staffing_session(stored), (True, expected)
                )
                # The default is a CHOICE, not a session: nothing opened one.
                self.assertEqual(
                    sorted(os.listdir(stf.staffing_sessions_dir(self.home))),
                    opened,
                )
                # One staffing field and no second one anywhere in the order.
                self.assertEqual(
                    sorted(stored),
                    ["configuration", "request", "staffing_session",
                     "task_executor"],
                )
                self.assertEqual(stored["configuration"], {"role": "implement"})
        # The role travels beside it, from the caller's own choice.
        chosen = self.admit(
            staffing_session=named, configuration={"role": "consult"}
        )
        self.assertEqual(
            self.store().record(chosen["id"])["order"]["configuration"],
            {"role": "consult"},
        )

    def _named_session_is_authorized_before_admission(self):
        before = len(self.records())
        status, unknown = self.request(
            "POST", "/api/tasks",
            self.order(staffing_session="stf-" + "0" * 32),
        )
        self.assertEqual(
            (status, unknown["error"]),
            (404, service.UNKNOWN_STAFFING_SESSION),
            unknown,
        )

        # A session bound to another project is refused for a caller who may
        # not read it, through that session route's own classification.
        service.create_project(self.home, {"slug": "alpha"})
        service.update_project_users(
            self.home, "alpha", {"users": [self.MEMBER]}
        )
        service.declare_work_area(self.home, "alpha", {
            "name": "main", "primary_path": self.workspace,
            "additional_paths": [],
        })
        service.create_project(self.home, {"slug": "beta"})
        foreign = self.session(
            stf.DEFAULT_DOCUMENT_NAME,
            work_area={"project": "beta", "work_area": "main"},
        )
        status, refused = self.request(
            "POST", "/api/tasks",
            self.order(
                staffing_session=foreign,
                request=dict(
                    self.order()["request"],
                    work_area={"project": "alpha", "work_area": "main"},
                ),
            ),
            headers=self.member_headers(),
        )
        self.assertEqual(
            (status, refused["error"]), (403, service.FORBIDDEN), refused
        )
        self.assertEqual(len(self.records()), before)

    # -- the milestone order ---------------------------------------------

    def _milestone_orders_record_the_step_that_owns_them(self):
        bound = self.session(stf.DEFAULT_DOCUMENT_NAME)
        cases = (
            ("plan", st.UNIT_SKELETON, contracts.KIND_DRAFT_SKELETON),
            ("plan", st.UNIT_SKELETON, contracts.KIND_FIX_FINDINGS),
            ("draft", st.UNIT_SLICE_DOC, contracts.KIND_DRAFT_SLICE_NOTE),
            ("implement", st.UNIT_SLICE_IMPL, contracts.KIND_IMPLEMENT),
            ("fix", st.UNIT_SLICE_IMPL, contracts.KIND_FIX_FINDINGS),
            ("review", st.UNIT_SLICE_IMPL, contracts.KIND_REVIEW_ROUND),
            ("review", st.UNIT_SLICE_IMPL, contracts.KIND_DELTA_REVIEW),
        )
        for number, (role, unit_kind, kind) in enumerate(cases):
            with self.subTest(kind=kind, unit=unit_kind):
                path = milestone_state(
                    self.directory("run-%d" % number), unit_kind
                )
                state = st.load(path)
                st.bind_staffing_session(state, bound)
                st.save(path, state)
                driver = drv.Driver(
                    path,
                    runner=runners.MockRunner([]),
                    model_profiles_home=self.home,
                )
                record = driver._admit_worker_task(
                    st.current_unit(driver.state), kind, "prompt", "codex"
                )
                self.assertEqual(
                    record["order"]["configuration"], {"role": role}
                )
                self.assertEqual(record["order"]["staffing_session"], bound)

        # A prospective producer choice may pick the executor; it may never
        # pick the process step a milestone dispatch performs.
        path = milestone_state(
            self.directory("run-producer"), st.UNIT_SLICE_IMPL
        )
        driver = drv.Driver(
            path, runner=runners.MockRunner([]), model_profiles_home=self.home
        )
        driver.state["milestone"]["slices"][0]["producer_task_executor"] = {
            contracts.KIND_IMPLEMENT: {
                "task_executor": "agent_call",
                "configuration": {"role": "plan"},
            },
        }
        record = driver._admit_worker_task(
            st.current_unit(driver.state),
            contracts.KIND_IMPLEMENT,
            "prompt",
            "codex",
        )
        self.assertEqual(
            record["order"]["configuration"], {"role": "implement"}
        )
        self.assertEqual(
            record["order"]["staffing_session"],
            st.staffing_session(driver.state),
        )

        # A run holding no session records the absence as the deliberate
        # value it is, and never as the missing key a pre-cutover record has.
        unbound = drv.Driver(
            milestone_state(self.directory("run-unbound"), st.UNIT_SKELETON),
            runner=runners.MockRunner([]),
        )
        order = unbound._admit_worker_task(
            st.current_unit(unbound.state),
            contracts.KIND_DRAFT_SKELETON,
            "prompt",
            "codex",
        )["order"]
        self.assertIsNone(st.staffing_session(unbound.state))
        self.assertEqual(tasks.order_staffing_session(order), (True, None))


class DirectCallStaffingTest(StandaloneCutoverTestCase):
    """The one direct call is staffed live, by the router, and only by it."""

    def test_direct_agent_call_resolves_live_and_ignores_snapshot(self):
        self.save(role_document("luna-only", *LUNA))
        self.save(role_document("fable-only", *FABLE))
        session = self.session("luna-only")

        requests = []
        real = stf.resolve

        def record(home, session_id, role, index=1, round=1, material=None,
                   brief=None, families=()):
            requests.append({
                "session": session_id, "role": role, "index": index,
                "round": round, "material": material, "brief": brief,
            })
            return real(home, session_id, role, index=index, round=round,
                        material=material, brief=brief, families=families)

        task = self.admit(
            staffing_session=session, configuration={"role": "consult"}
        )
        # An edit landing between admission and the call is the one the call
        # runs on: the order froze nothing.
        stf.edit_session(self.home, session, {"document": "fable-only"})
        # Both retired selectors are poisoned. Neither may reach the call.
        self.config["families_order"] = ["codex"]
        self.config["model_defaults"]["codex"] = {
            "model": "poisoned-model", "effort": "poisoned-effort",
        }
        poisoned = self.store().records()
        for entry in poisoned:
            if entry["id"] == task["id"]:
                entry["resolved_staffing"] = {
                    "agent_call": {"agent": "codex", "model": "poisoned-model",
                                   "effort": "poisoned-effort"},
                }
        self.store()._save(poisoned)

        with mock.patch.object(stf, "resolve", side_effect=record):
            record_out = self.run_task(task["id"])

        self.assertEqual(record_out["result"]["status"], "success",
                         record_out["result"])
        # Exactly one router request, and exactly what the order says: the
        # stored role, the role's first seat, its first round, no material,
        # and the task's own text as the best-effort brief.
        self.assertEqual(requests, [{
            "session": session, "role": "consult", "index": 1, "round": 1,
            "material": None,
            "brief": "Do exactly the caller-authored work.",
        }])
        self.assertEqual(len(self.calls), 1)
        answer = self.resolved(session, role="consult")
        self.assertEqual(answer, FABLE)
        self.assertEqual(
            (self.calls[0]["family"], self.calls[0]["model"],
             self.calls[0]["effort"]),
            FABLE,
        )
        marker = self.marker(task["id"])
        self.assertEqual(
            (marker["family"], marker["model"], marker["effort"]), FABLE
        )
        self.assertNotIn("staffing_fallback", marker)
        # The order's own bookkeeping is unchanged and decided nothing.
        self.assertEqual(
            record_out["resolved_staffing"]["agent_call"]["model"],
            "poisoned-model",
        )

    def test_admission_snapshot_failure_cannot_refuse_the_order(self):
        """Order bookkeeping is not an availability gate over the call.

        The refusal this forbids is the one a configuration can cause: the
        snapshot cannot be derived, so there is none, and the order is
        admitted anyway. `worker_staffing` answers every configuration
        value that way — it returns `{}` rather than raising — which is why
        the second half below has to REPLACE it to see an exception at all.
        """
        # A configuration the snapshot cannot be read from. This is the
        # reachable failure, and it admits: 201, no snapshot, and the call
        # still made on the router's answer.
        session = self.session(self.save(role_document("luna-only", *LUNA)))
        self.config["model_defaults"] = True
        task = self.admit(staffing_session=session)
        self.assertEqual(task["resolved_staffing"], {})

        # A defect injected INTO the bookkeeping seam, which no caller,
        # configuration or session can produce. It is not a snapshot
        # failure, and the service does not disguise it as one: it surfaces
        # as an internal error, and admission writes nothing.
        with mock.patch.object(
            task_api, "worker_staffing",
            side_effect=AssertionError("admission snapshot exploded"),
        ):
            status, body = self.request(
                "POST", "/api/tasks",
                self.order(staffing_session=session),
            )
        self.assertEqual(status, 500, body)
        self.assertEqual(len(self.records()), 1)

        # The call the admitted order does make is the router's answer, with
        # no snapshot to have taken it from.
        self.run_task(task["id"])
        self.assertEqual(
            (self.calls[0]["family"], self.calls[0]["model"],
             self.calls[0]["effort"]),
            LUNA,
        )


class DirectFallbackAndMarkerTest(StandaloneCutoverTestCase):
    """What an unreadable input costs, what a refused one prevents, and
    what a lost marker may never take away.

    Three claims, and they pull in different directions on purpose. An
    input nobody can read must not stop a call — the default document
    answers and the marker says it did. A SURFACED condition must stop it,
    before any provider and leaving no marker to correct. And the marker
    itself is evidence: losing either of its two writes cannot reach back
    and replace what the call actually produced.
    """

    def test_direct_fallback_conditions_and_marker_posture(self):
        self._unreadable_inputs_still_call_on_the_default_document()
        self._each_surfaced_condition_refuses_before_the_provider()
        self._losing_either_marker_write_keeps_the_native_result()

    # -- the mandatory fallback ------------------------------------------

    def _unreadable_inputs_still_call_on_the_default_document(self):
        # The default answers something no other document here does, so
        # every assertion below says WHICH document staffed the call
        # rather than repeating one seat's arithmetic.
        self.save(role_document(stf.DEFAULT_DOCUMENT_NAME, *LUNA))
        self.save(role_document("owner-document", *FABLE))
        deleted = self.session("owner-document")
        damaged = self.session("owner-document")
        readable = self.session("owner-document")

        cases = (
            # Omitted: no session was ever named, so there is none to read.
            ("omitted", self.admit()),
            # Absent: the record this id names is gone.
            ("absent session", self.admit(staffing_session=deleted)),
            # Unreadable: the session reads, the document it names does not.
            ("damaged document", self.admit(staffing_session=damaged)),
        )
        control = self.admit(staffing_session=readable)

        # A control first, while every input still reads: the session's own
        # document governs and NOTHING marks a fallback. That is what makes
        # the field below evidence rather than decoration.
        self.assertEqual(self.resolved(readable), FABLE)
        self.assertEqual(self.run_task(control["id"])["result"]["status"],
                         "success")
        marker = self.marker(control["id"])
        self.assertEqual(
            (marker["family"], marker["model"], marker["effort"]), FABLE
        )
        self.assertNotIn("staffing_fallback", marker)

        os.unlink(os.path.join(
            stf.staffing_sessions_dir(self.home), "%s.json" % deleted
        ))
        with open(stf._path(self.home, "owner-document"), "w",
                  encoding="utf-8") as handle:
            handle.write("{ this is not a document")

        for label, task in cases:
            with self.subTest(input=label):
                del self.calls[:]
                record = self.run_task(task["id"])
                self.assertEqual(record["result"]["status"], "success",
                                 record["result"])
                self.assertEqual(record["result"]["native_result"],
                                 "native text")
                # One call, made on the DEFAULT document's answer.
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(
                    (self.calls[0]["family"], self.calls[0]["model"],
                     self.calls[0]["effort"]),
                    LUNA,
                )
                marker = self.marker(task["id"])
                self.assertEqual(
                    (marker["family"], marker["model"], marker["effort"]),
                    LUNA,
                )
                # The exact field, with the router's own token as value.
                self.assertEqual(
                    marker["staffing_fallback"],
                    stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT,
                )
                self.assertEqual(marker["staffing_fallback"],
                                 "default_document")

    # -- the two surfaced conditions -------------------------------------

    def _each_surfaced_condition_refuses_before_the_provider(self):
        # No slot this machine can run: the document names one family and
        # the session has the other, so there is no answer to give.
        self.save(role_document("claude-only", *FABLE))
        nobody = self.session("claude-only", families=("codex",))
        # A declared split one family cannot honour, on the role a direct
        # order defaults to.
        self.save(split_document("split-implement", "implement"))
        collapsed = self.session("split-implement")

        for token, session in (
            (stf.STAFFING_UNAVAILABLE, nobody),
            (stf.DISTINCT_FAMILIES_UNSATISFIABLE, collapsed),
        ):
            with self.subTest(condition=token):
                del self.calls[:]
                task = self.admit(staffing_session=session)
                record = self.run_task(task["id"])
                result = record["result"]
                self.assertEqual(result["status"], "failure", result)
                # The public token, named in the task's own reason.
                self.assertIn(token, result["reason"])
                self.assertIsNone(result["native_result"])
                # Nothing was dispatched and nothing was marked: the marker
                # is written only once a call is actually staffed, so there
                # is no evidence of a call to have to correct.
                self.assertEqual(self.calls, [])
                self.assertIsNone(self.marker(task["id"]))

    # -- best-effort evidence --------------------------------------------

    def _losing_either_marker_write_keeps_the_native_result(self):
        session = self.session(stf.DEFAULT_DOCUMENT_NAME)
        cases = (
            # The write attempted BEFORE the provider call, so a call in
            # flight is visible. Losing it must not gate the call.
            ("the pre-provider write", 1, True),
            # The terminal write, which carries the accounting.
            ("the terminal write", 2, False),
        )
        for label, failing, completed in cases:
            with self.subTest(marker=label):
                del self.calls[:]
                task = self.admit(staffing_session=session)
                attempts = []
                real = task_api._write_worker_marker

                def write(home, task_id, marker, _real=real, _fail=failing):
                    attempts.append(copy.deepcopy(marker))
                    if len(attempts) == _fail:
                        raise OSError("the marker store is unwritable")
                    return _real(home, task_id, marker)

                with mock.patch.object(
                    task_api, "_write_worker_marker", side_effect=write
                ):
                    record = self.run_task(task["id"])

                # Both phases were attempted, one of them lost.
                self.assertEqual(len(attempts), 2)
                self.assertEqual(record["result"]["status"], "success",
                                 record["result"])
                self.assertEqual(record["result"]["native_result"],
                                 "native text")
                self.assertEqual(len(self.calls), 1)
                # The surviving phase is exactly the one that did not fail,
                # and the loss stops there: the result is untouched.
                surviving = self.marker(task["id"])
                self.assertEqual(surviving["task_id"], task["id"])
                if completed:
                    self.assertTrue(surviving["completed"])
                    self.assertIn("duration_s", surviving)
                else:
                    self.assertNotIn("completed", surviving)


class GitAlignmentStaffingTest(StandaloneCutoverTestCase):
    """The operator's alignment asks the router only for a call it makes.

    Everything the work area already refuses it still refuses, unchanged
    and first: a session the caller may not read, a worktree somebody owns,
    a directory that is not a repository root. Only once one physical call
    is actually eligible does `sync` get staffed — live, at seat 1 — and
    what ran comes back on the `sync` object beside the verdict the agent's
    own report decides.
    """

    SLUG = "aligned prod"
    AREA = "main area"

    def setUp(self):
        super().setUp()
        self.repo = self.git_repository("repo")
        self.sync_calls = []
        self.report = "merged both sides\nRESULT: aligned"
        self.exit_code = 0
        self.declare(self.SLUG, self.repo,
                     users=[self.MEMBER], admins=[self.MEMBER])

    # -- harness ---------------------------------------------------------

    def git_repository(self, name):
        path = self.directory(name)
        subprocess.run(["git", "init", "-q", path], check=True)
        return path

    def declare(self, slug, primary, users=None, admins=None):
        """One declared, confirmed work area on a project this home serves."""
        service.create_project(self.home, {"slug": slug})
        if users is not None:
            service.update_project_users(self.home, slug, {
                "users": list(users), "admins": list(admins or []),
            })
        record = service.declare_work_area(self.home, slug, {
            "name": self.AREA,
            "primary_path": primary,
            "additional_paths": [],
        })["record"]
        self.assertTrue(service._work_area_store(self.home, slug).confirm(
            self.AREA,
            record["primary"],
            record["additional"],
            service._executor_id(self.home),
        ).ok)

    def sync(self, slug=None, area=None, headers=None, **body):
        path = "/api/projects/%s/git-sync" % urllib.parse.quote(
            slug or self.SLUG, safe=""
        )
        payload = {"work_area": self.AREA if area is None else area}
        payload.update(body)
        return self.request("POST", path, payload, headers=headers)

    def aligning(self):
        """The real `run_sync`, over a runner that records its staffing.

        Only the provider process is stood in for: the mandate, the exit
        code, the verdict reader and the outcome shape are the operation's
        own, so a test can hold them equal while the staffing changes.
        """
        outer = self
        real = gitsync.run_sync

        class Result:
            text = property(lambda _self: outer.report)
            exit_code = property(lambda _self: outer.exit_code)
            duration_s = 1.0
            token_usage = None

        class Runner:
            def call(_self, family, prompt, workspace, model=None,
                     effort=None):
                outer.sync_calls.append({
                    "family": family, "prompt": prompt,
                    "workspace": workspace, "model": model, "effort": effort,
                })
                return Result()

        def aligned(commands, timeouts, family, workspace, **kwargs):
            return real(commands, timeouts, family, workspace,
                        runner=Runner(), **kwargs)

        return mock.patch.object(gitsync, "run_sync", side_effect=aligned)

    def refusing_to_staff(self):
        """A router that fails the test if this request reaches it."""
        return mock.patch.object(
            stf, "resolve",
            side_effect=AssertionError(
                "a refused alignment asked the router to staff it"
            ),
        )

    def recording_resolutions(self, requests):
        real = stf.resolve

        def record(home, session, role, index=1, round=1, material=None,
                   brief=None, families=()):
            requests.append({
                "session": session, "role": role, "index": index,
                "round": round, "material": material, "brief": brief,
            })
            return real(home, session, role, index=index, round=round,
                        material=material, brief=brief, families=families)

        return mock.patch.object(stf, "resolve", side_effect=record)

    # -- the acceptance row ----------------------------------------------

    def test_git_sync_resolves_live_after_ownership_checks(self):
        self._named_sessions_keep_the_existing_access_classifications()
        self._an_ineligible_work_area_asks_for_no_staffing()
        self._an_eligible_call_is_staffed_live_at_sync_seat_one()
        self._each_surfaced_condition_runs_no_agent()
        self._the_verdict_law_is_unchanged()

    # -- access ----------------------------------------------------------

    def _named_sessions_keep_the_existing_access_classifications(self):
        # A control first: this caller IS this project's admin, which is
        # the rung git alignment needs, so every refusal below is the
        # SESSION's classification and not the route's.
        with self.aligning():
            status, allowed = self.sync(headers=self.member_headers())
        self.assertEqual(status, 200, allowed)
        self.assertEqual(len(self.sync_calls), 1)
        del self.sync_calls[:]

        with self.refusing_to_staff(), self.aligning() as never:
            status, unknown = self.sync(
                staffing_session="stf-" + "0" * 32
            )
            self.assertEqual(
                (status, unknown["error"]),
                (404, service.UNKNOWN_STAFFING_SESSION),
                unknown,
            )

            # A session bound to a project this caller cannot reach.
            service.create_project(self.home, {"slug": "beta"})
            foreign = self.session(
                stf.DEFAULT_DOCUMENT_NAME,
                work_area={"project": "beta", "work_area": "main"},
            )
            status, refused = self.sync(
                staffing_session=foreign, headers=self.member_headers()
            )
            self.assertEqual(
                (status, refused["error"]), (403, service.FORBIDDEN), refused
            )
        never.assert_not_called()
        self.assertEqual(self.sync_calls, [])

    # -- eligibility first -----------------------------------------------

    def _an_ineligible_work_area_asks_for_no_staffing(self):
        session = self.session(self.save(role_document("sync-doc", *FABLE)))
        unusable = self.directory("plain")
        self.declare("nested prod", unusable)

        with self.refusing_to_staff(), self.aligning() as never:
            # Busy: a live milestone driver owns this worktree.
            with mock.patch.object(
                service, "driver_alive", return_value=True
            ), mock.patch.object(
                service.registry, "load",
                return_value={"runs": [{
                    "id": "r1", "name": "live", "workspace": self.repo,
                }]},
            ):
                status, busy = self.sync(staffing_session=session)
            self.assertEqual(
                (status, busy["error"]), (409, service.WORK_AREA_BUSY), busy
            )

            # Unusable: the area is a directory, not a repository root.
            status, nested = self.sync(slug="nested prod",
                                       staffing_session=session)
            self.assertEqual(
                (status, nested["error"]),
                (400, service.PRIMARY_NOT_REPO_ROOT),
                nested,
            )

            # And an area this project never declared.
            status, unknown = self.sync(area="no such area",
                                        staffing_session=session)
            self.assertEqual(
                (status, unknown["error"]), (404, service.workareas.UNKNOWN),
                unknown,
            )
        never.assert_not_called()
        self.assertEqual(self.sync_calls, [])

    # -- the one physical call -------------------------------------------

    def _an_eligible_call_is_staffed_live_at_sync_seat_one(self):
        self.save(role_document(stf.DEFAULT_DOCUMENT_NAME, *LUNA))
        session = self.session("sync-doc")
        requests = []

        with self.recording_resolutions(requests), self.aligning():
            status, body = self.sync(staffing_session=session)
        self.assertEqual(status, 200, body)
        # Exactly one router request, and exactly the alignment's own seat:
        # `sync`, its first, its first round, with no material or brief.
        self.assertEqual(requests, [{
            "session": session, "role": "sync", "index": 1, "round": 1,
            "material": None, "brief": None,
        }])
        self.assertEqual(len(self.sync_calls), 1)
        self.assertEqual(
            (self.sync_calls[0]["family"], self.sync_calls[0]["model"],
             self.sync_calls[0]["effort"]),
            FABLE,
        )
        # What ran, on the response's own `sync` object.
        self.assertEqual(
            (body["sync"]["family"], body["sync"]["model"],
             body["sync"]["effort"]),
            FABLE,
        )
        self.assertNotIn("staffing_fallback", body["sync"])
        self.assertEqual(
            os.path.realpath(self.sync_calls[0]["workspace"]),
            os.path.realpath(self.repo),
        )

        # An edit completed after the last alignment reaches the next one.
        del self.sync_calls[:]
        stf.edit_session(self.home, session,
                         {"document": stf.DEFAULT_DOCUMENT_NAME})
        with self.aligning():
            status, body = self.sync(staffing_session=session)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            (self.sync_calls[0]["family"], self.sync_calls[0]["model"],
             self.sync_calls[0]["effort"]),
            LUNA,
        )

        # Naming no session takes the default document, and says so.
        for label, payload in (("omitted", {}),
                               ("explicit null", {"staffing_session": None})):
            with self.subTest(session=label):
                del self.sync_calls[:]
                with self.aligning():
                    status, body = self.sync(**payload)
                self.assertEqual(status, 200, body)
                self.assertEqual(
                    (self.sync_calls[0]["family"], self.sync_calls[0]["model"],
                     self.sync_calls[0]["effort"]),
                    LUNA,
                )
                self.assertEqual(
                    body["sync"]["staffing_fallback"],
                    stf.STAFFING_FALLBACK_DEFAULT_DOCUMENT,
                )

        # So does one whose document stopped being readable after it was
        # named: the alignment still runs, and the field says which
        # document actually staffed it.
        del self.sync_calls[:]
        with open(stf._path(self.home, "sync-doc"), "w",
                  encoding="utf-8") as handle:
            handle.write("{ this is not a document")
        damaged = self.session("sync-doc")
        with self.aligning():
            status, body = self.sync(staffing_session=damaged)
        self.assertEqual(status, 200, body)
        self.assertEqual(
            (self.sync_calls[0]["family"], self.sync_calls[0]["model"],
             self.sync_calls[0]["effort"]),
            LUNA,
        )
        self.assertEqual(body["sync"]["staffing_fallback"], "default_document")

    # -- the two surfaced conditions -------------------------------------

    def _each_surfaced_condition_runs_no_agent(self):
        self.save(role_document("claude-only", *FABLE))
        nobody = self.session("claude-only", families=("codex",))
        self.save(split_document("split-sync", "sync"))
        collapsed = self.session("split-sync")

        del self.sync_calls[:]
        for status_code, token, session in (
            (503, stf.STAFFING_UNAVAILABLE, nobody),
            (409, stf.DISTINCT_FAMILIES_UNSATISFIABLE, collapsed),
        ):
            with self.subTest(condition=token):
                with self.aligning() as never:
                    status, body = self.sync(staffing_session=session)
                self.assertEqual((status, body["error"]),
                                 (status_code, token), body)
                never.assert_not_called()
        self.assertEqual(self.sync_calls, [])

    # -- the outcome law -------------------------------------------------

    def _the_verdict_law_is_unchanged(self):
        cases = (
            ("aligned", "merged both sides\nRESULT: aligned", 0),
            ("stopped", "the remote refused me\nRESULT: stopped", 0),
            ("unknown", "I merged everything", 0),
            # A failing process is stopped whatever it printed.
            ("stopped", "RESULT: aligned", 3),
        )
        for verdict, report, code in cases:
            with self.subTest(report=report, exit_code=code):
                self.report, self.exit_code = report, code
                with self.aligning():
                    status, body = self.sync()
                self.assertEqual(status, 200, body)
                outcome = body["sync"]
                self.assertEqual(outcome["outcome"], verdict)
                self.assertEqual(
                    outcome["outcome"], gitsync.read_outcome(report, code)
                )
                self.assertEqual(outcome["report"], report.strip())
                self.assertEqual(outcome["exit_code"], code)
                self.assertEqual(outcome["clean_exit"], code == 0)
                # The alignment's own envelope is unchanged beside it.
                self.assertEqual(body["work_area"], self.AREA)
                self.assertEqual(os.path.realpath(body["workspace"]),
                                 os.path.realpath(self.repo))


class TaskCompatibilityBoundaryTest(StandaloneCutoverTestCase):
    """One key's PRESENCE is the whole boundary between old work and new.

    An order admitted since the cutover always carries `staffing_session`
    — an id, or the explicit null that deliberately chooses the default
    document — and that selection follows the work everywhere it is
    launched again. An order admitted BEFORE it carries no such key, and
    that absence keeps it on the dispatch authority already frozen on it,
    under either executor name. Nothing migrates either shape: the stored
    bytes below are compared whole.
    """

    STATIC_PINS = {
        "dispatch_authority": "static",
        "participants": [
            {"id": "initial-position", "role": "initial_position",
             "delivery": "llm", "model_family": "codex",
             "model": "gpt-5.6-luna", "effort": "low"},
            {"id": "contrary-position", "role": "contrary_position",
             "delivery": "llm", "model_family": "claude",
             "model": "claude-sonnet-5", "effort": "medium"},
        ],
    }
    FROZEN_CALL = {
        "agent": "claude", "model": "claude-sonnet-5", "effort": "medium",
    }

    def test_direct_task_compatibility_boundary_is_field_presence(self):
        self._new_brainstorming_orders_carry_their_one_selection()
        self._a_missing_field_static_task_keeps_its_pins()
        self._missing_field_agent_calls_run_their_frozen_snapshot()

    # -- harness ---------------------------------------------------------

    def age_record(self, task_id, **changes):
        """Rewrite one stored record into the shape a pre-cutover order has.

        The key is REMOVED, not nulled: an explicit null is today's
        deliberate default and a missing key is yesterday's silence, and
        separating them is the entire compatibility rule.
        """
        records = self.records()
        for entry in records:
            if entry["id"] != task_id:
                continue
            entry["order"].pop("staffing_session", None)
            entry["order"].update(changes.pop("order", {}))
            entry.update(changes)
        self.store()._save(records)
        stored = self.store().record(task_id)
        self.assertEqual(tasks.order_staffing_session(stored["order"]),
                         (False, None))
        return stored

    @staticmethod
    def bytes_of(record):
        """One record's stored bytes, with only its result factored out.

        A task record's sole legal mutation is null-to-terminal, so the
        result is the one thing executing a fixture is allowed to add;
        everything else — the order, its executor name, the staffing
        frozen beside it — is compared whole.
        """
        return json.dumps(dict(record, result=None), sort_keys=True)

    def terminal_result(self):
        return {
            "status": "success", "duration_s": 1.0, "token_usage": None,
            "token_usage_partial": True, "cost": None, "cost_partial": True,
            "native_result": {"agreement": "kept opaque"},
        }

    def run_discussion(self, record, session_id):
        """Drive the host's Brainstorming branch through start and effect.

        Only the two boundaries this row is about are stood in for: the
        session the launch creates, and the agreed production effect. What
        reaches each of them is the host's own wiring.
        """
        created, effects = [], []

        def create(_home, body, _caller, _context, _config, **kwargs):
            created.append((body, kwargs))
            return {"id": session_id, "state": {"status": "running"}}

        def finish(state, task_id, _home, _session, apply_effects):
            self.assertTrue(apply_effects({
                "request": {"request": "Produce the agreed effects."},
                "agreement": {},
            })["completed"])
            return tasks.record_task_result(
                state, task_id, self.terminal_result()
            )

        def effect(_home, _session, _task_id, _request, **kwargs):
            effects.append(kwargs)
            return {"completed": True}

        with mock.patch.object(
            bs_tasks.lifecycle, "create_resolved_session", side_effect=create
        ), mock.patch.object(
            bs_tasks, "finish_task", side_effect=finish
        ), mock.patch.object(
            bs_tasks, "apply_agreed_effects", side_effect=effect
        ):
            self.host._run_brainstorming(
                record, lambda: copy.deepcopy(self.config)
            )
        self.assertEqual(len(created), 1)
        self.assertEqual(len(effects), 1)
        return created[0], effects[0]

    def restart_session(self, task_id, session_id, caller_prefix):
        """Explicitly restart the discussion one open task owns."""
        session_record = {
            "id": session_id,
            "caller": caller_prefix + task_id,
            "project": None,
            "execution_context": {"workspace_path": self.workspace},
        }
        restarted = []

        def restart(state, task, _config, _home, session_id=None, **options):
            restarted.append((task, session_id, options))
            return {"id": session_record["id"], "state": {"status": "running"}}

        with mock.patch.object(
            service.brainstorming_lifecycle, "_record_by_id",
            return_value=session_record,
        ), mock.patch.object(
            service.brainstorming_lifecycle, "inspect_session",
            return_value={"state": {"status": "running"},
                          "process": "stopped"},
        ), mock.patch.object(
            bs_tasks, "start_task", side_effect=restart
        ), mock.patch.object(self.host, "start", return_value=None):
            status, body = self.request(
                "POST",
                "/api/brainstorming/sessions/%s/start" % session_id,
                {},
            )
        self.assertEqual(status, 200, body)
        self.assertEqual(len(restarted), 1)
        task, attached, options = restarted[0]
        self.assertEqual((task, attached), (task_id, session_id))
        return options

    # -- today's orders --------------------------------------------------

    def _new_brainstorming_orders_carry_their_one_selection(self):
        named = self.session(self.save(role_document("owner-document",
                                                     *FABLE)))
        for label, changes, expected in (
            ("supplied", {"staffing_session": named}, named),
            ("explicit null", {"staffing_session": None}, None),
        ):
            with self.subTest(session=label):
                # Admission: the order records the selection, and records
                # NO seat — the router answers every call this discussion
                # makes, immediately before it makes it.
                task = self.admit(executor="brainstorming", **changes)
                stored = self.store().record(task["id"])
                self.assertEqual(
                    tasks.order_staffing_session(stored["order"]),
                    (True, expected),
                )
                self.assertEqual(
                    stored["resolved_staffing"]["dispatch_authority"],
                    "current_profile",
                )
                for seat in stored["resolved_staffing"]["participants"]:
                    for pin in ("model_family", "model", "effort"):
                        self.assertNotIn(pin, seat)

                # Explicit restart, while the task is still open: the same
                # reference, read back off the order rather than re-derived.
                self.assertEqual(
                    self.restart_session(
                        task["id"],
                        "restart-%s" % label.replace(" ", "-"),
                        bs_tasks.lifecycle.
                        CURRENT_PROFILE_TASK_CALLER_PREFIX,
                    ),
                    {"staffing_selection": {"session": expected}},
                )

                # Initial start, and the agreed production effect.
                (_body, launch), effect = self.run_discussion(
                    stored, "session-%s" % label.replace(" ", "-")
                )
                self.assertEqual(launch["staffing_selection"],
                                 {"session": expected})
                self.assertNotIn("static_binding", launch)
                self.assertEqual(effect["staffing_selection"],
                                 {"session": expected})
                self.assertEqual(effect["dispatch_authority"],
                                 "current_profile")
                self.assertEqual(
                    self.store().record(task["id"])["result"]["native_result"],
                    {"agreement": "kept opaque"},
                )

    # -- yesterday's records ---------------------------------------------

    def _a_missing_field_static_task_keeps_its_pins(self):
        state = {"tasks": self.records()}
        with mock.patch.object(
            bs_tasks, "resolve_staffing",
            return_value=copy.deepcopy(self.STATIC_PINS),
        ):
            admitted = bs_tasks.admit_task(
                state, self.order("brainstorming"), self.config,
                self.workspace,
            )
        self.store()._save(state["tasks"])
        record = self.age_record(admitted["id"])
        before = self.bytes_of(record)

        (body, launch), effect = self.run_discussion(record, "static-session")
        # The pins are the launch: no selection reaches it, and the seats
        # are the ones frozen on the record itself.
        self.assertNotIn("staffing_selection", launch)
        self.assertTrue(launch["static_binding"])
        self.assertEqual(body["participants"],
                         self.STATIC_PINS["participants"])
        # The effect runs under the authority frozen on the record. There
        # is no session on the order to forward, so the selection beside it
        # names none — and the stored `static` authority is what decides.
        self.assertEqual(effect["dispatch_authority"], "static")
        self.assertEqual(effect["staffing_selection"], {"session": None})

        after = self.store().record(admitted["id"])
        self.assertEqual(self.bytes_of(after), before)
        self.assertNotIn("staffing_session", after["order"])

    def _missing_field_agent_calls_run_their_frozen_snapshot(self):
        # The default document answers something else entirely, so a call
        # that took the router's answer instead of its own snapshot would
        # be visible rather than coincidentally equal.
        self.save(role_document(stf.DEFAULT_DOCUMENT_NAME, *LUNA))
        cases = (
            ("agent_call", "agent_call", "agent_call"),
            # The retired name, still run from disk exactly as stored.
            ("retired worker", "worker", "worker"),
        )
        for label, executor, snapshot_key in cases:
            with self.subTest(record=label):
                task = self.admit()
                record = self.age_record(
                    task["id"],
                    order={"task_executor": executor},
                    resolved_staffing={
                        snapshot_key: dict(self.FROZEN_CALL)
                    },
                )
                before = self.bytes_of(record)

                del self.calls[:]
                with mock.patch.object(
                    stf, "resolve",
                    side_effect=AssertionError(
                        "a pre-cutover record asked the router"
                    ),
                ):
                    executed = self.run_task(task["id"])

                self.assertEqual(executed["result"]["status"], "success",
                                 executed["result"])
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(
                    (self.calls[0]["family"], self.calls[0]["model"],
                     self.calls[0]["effort"]),
                    (self.FROZEN_CALL["agent"], self.FROZEN_CALL["model"],
                     self.FROZEN_CALL["effort"]),
                )
                # The marker still names what actually ran, and nothing
                # here fell back on anything.
                marker = self.marker(task["id"])
                self.assertEqual(
                    (marker["family"], marker["model"], marker["effort"]),
                    (self.FROZEN_CALL["agent"], self.FROZEN_CALL["model"],
                     self.FROZEN_CALL["effort"]),
                )
                self.assertNotIn("staffing_fallback", marker)
                # And the record itself is untouched but for its result.
                self.assertEqual(self.bytes_of(executed), before)
                self.assertEqual(executed["order"]["task_executor"], executor)
                self.assertEqual(list(executed["resolved_staffing"]),
                                 [snapshot_key])
