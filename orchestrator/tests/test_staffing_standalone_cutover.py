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
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from orchestrator import access, contracts, runners, service
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
