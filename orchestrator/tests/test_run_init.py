"""Run-init project resolution + the `project_resolved` ledger event
(slice 5).

Pins the init seam's observable contracts: the optional (project,
work_area) binding resolved ONCE at init through Slice 2's sealed
READY-gated store seam; `primary.path` as the executed repo (derived
workspace, strict cross-check, no fabricated directories); the state
project block Slices 6 and 8 consume; the frozen `project_resolved`
payload recorded exactly once per run; fail-closed refusals that create
nothing; read-only resolution; post-init stability against store
mutations; and project defaults merging beneath per-launch intent.

Stores live in real tempfile directories and are seeded through Slice 2's
declare/confirm (the file-backed lesson from Slice 1's seal history);
exactly-once and stability drive the real Driver over MockRunner.
"""

import json
import os
import tempfile
import unittest

from orchestrator import driver as drv
from orchestrator import kvstore
from orchestrator import ledgers
from orchestrator import projects
from orchestrator import runners
from orchestrator import state as st
from orchestrator import workareas
from orchestrator.tests.test_driver_mock import (
    git_init_workspace,
    make_config,
    ok,
    report,
    step,
    write_file,
)

GOAL = "Exercise run-init project resolution"

A = kvstore.Atom



def _ws_states(workspace):
    """All run states under `workspace`, both layouts (existence probe:
    the per-milestone layout moved states from <ws>/.orchestrator into
    <milestone>/.run, so a bare default_state_path check goes stale)."""
    out = []
    legacy = drv.default_state_path(workspace)
    if os.path.isfile(legacy):
        out.append(legacy)
    for root, dirs, files in os.walk(workspace):
        if os.path.basename(root) == ".run" and "state.json" in files:
            out.append(os.path.join(root, "state.json"))
            dirs[:] = []
    return out


def _ws_state(workspace):
    """The single run state under `workspace`, either layout."""
    states = _ws_states(workspace)
    assert len(states) == 1, "expected exactly one state, got %r" % states
    return states[0]


def draft_step():
    """A scripted skeleton draft: the one MockRunner step AC1 needs to
    show a project-bound run is drivable."""
    response = ok(
        "draft_skeleton",
        artifact="pending",
    )

    def write_skeleton(workspace):
        document = st.load(_ws_state(workspace))
        artifact = ledgers.skeleton_path(document)
        response["artifact"] = artifact
        write_file(
            artifact,
            "# Skeleton\n\n## Canonical slice plan\n```json\n%s\n```\n"
            % json.dumps({
                "slices": [{
                    "id": 1,
                    "title": "One",
                    "intent": "Exercise bound run initialization.",
                    "producer_task_executor": {
                        "draft_slice_note": "agent_call",
                        "implement": "agent_call",
                    },
                }],
            }),
        )(workspace)

    return step(
        "draft_skeleton",
        response,
        family="codex",
        side_effect=write_skeleton,
    )


def mock_config():
    """Deterministic driver config for bound runs."""
    return make_config(git={"enabled": True})


class RunInitTestCase(unittest.TestCase):
    PROJECT = "life-prod"
    WORK_AREA = "main"
    EXECUTOR = "local-orchestrator"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-run-init-")
        root = self._tmp.name
        self.store_base = os.path.join(root, "stores")
        self.repo = os.path.join(root, "repo")
        self.lib = os.path.join(root, "lib")
        os.makedirs(self.repo)
        os.makedirs(self.lib)
        git_init_workspace(self.repo)
        self.primary = {"path": self.repo, "device": 1}
        self.additional = [{"path": self.lib, "device": "dev-lib"}]

    def tearDown(self):
        self._tmp.cleanup()

    def store(self, project=None):
        return workareas.WorkAreaStore(
            self.store_base, project or self.PROJECT
        )

    def seed(self, name=None, primary=None, additional=None, confirm=True):
        """Declare (and by default confirm to READY) a work area through
        Slice 2's seams — the only way production records come to exist."""
        name = name or self.WORK_AREA
        primary = primary or self.primary
        additional = self.additional if additional is None else additional
        store = self.store()
        declared = store.declare(name, primary, additional, self.EXECUTOR)
        self.assertTrue(declared.ok, declared.reason)
        if confirm:
            confirmed = store.confirm(
                name, primary, additional, self.EXECUTOR
            )
            self.assertTrue(confirmed.ok, confirmed.reason)
        return store

    def binding(self, work_area=None, project=None, directory=None,
                defaults=None):
        b = {
            "directory": directory or self.store_base,
            "project": project or self.PROJECT,
            "work_area": work_area or self.WORK_AREA,
        }
        if defaults is not None:
            b["defaults"] = defaults
        return b

    def kv_path(self, project=None):
        return os.path.join(
            self.store_base, project or self.PROJECT, kvstore.STORE_FILENAME
        )

    def kv_bytes(self):
        with open(self.kv_path(), "rb") as fh:
            return fh.read()

    def store_snapshot(self):
        """Everything AC4 pins as byte-unchanged: the raw store file, the
        full listing, the raw work-area record (domain version included),
        and the meta family."""
        store = self.store()
        return (
            self.kv_bytes(),
            store.client.list_entries(include_values=True),
            store.client.get(kvstore.raw_work_area_key(self.WORK_AREA)),
            store.read_meta(self.WORK_AREA),
        )

    def resolved_events(self, path):
        return [
            e
            for e in st.load(path)["events"]
            if e["type"] == "project_resolved"
        ]

    def assert_refused(self, cause, *, workspace=None, binding=None,
                       config_override=None):
        """Refusals raise the dedicated type with a distinct cause and
        create nothing at the would-be state path."""
        b = binding or self.binding()
        with self.assertRaises(drv.ProjectResolutionError) as ctx:
            drv.init_run(
                GOAL,
                workspace,
                project=b,
                config_override=config_override,
            )
        self.assertEqual(ctx.exception.cause, cause)
        self.assertFalse(bool(_ws_states(self.repo)))
        if workspace:
            self.assertFalse(
                bool(_ws_states(workspace))
            )
        return ctx.exception


# ---------------------------------------------------------------------------
# AC1: happy path — derived workspace, exact state block, drivable run


class TestHappyPath(RunInitTestCase):
    def test_bound_init_derives_workspace_and_records_the_block(self):
        self.seed()
        path = drv.init_run(GOAL, project=self.binding())
        self.assertEqual(path, _ws_state(self.repo))
        state = st.load(path)
        self.assertEqual(state["workspace"], self.repo)
        # Exactly {directory, project, work_area, primary, additional},
        # roots verbatim in Slice 2's public {path, device} shape
        # (device rides along uninterpreted).
        self.assertEqual(
            state["project"],
            {
                "directory": os.path.abspath(self.store_base),
                "project": self.PROJECT,
                "work_area": self.WORK_AREA,
                "primary": {"path": self.repo, "device": 1},
                "additional": [{"path": self.lib, "device": "dev-lib"}],
            },
        )

    def test_bound_run_is_drivable(self):
        self.seed()
        path = drv.init_run(
            GOAL, project=self.binding(), config_override=mock_config()
        )
        driver = drv.Driver(path, runner=runners.MockRunner([draft_step()]))
        action, _note = driver.step()
        self.assertEqual(action.type, drv.A_DRAFT)
        state = st.load(path)
        self.assertIsNone(state["failure"])
        self.assertEqual(state["units"][0]["status"], st.U_PRE_REVIEW_VERIFY)
        self.assertEqual(
            state["units"][0]["artifact"], ledgers.skeleton_path(state)
        )


# ---------------------------------------------------------------------------
# AC2: the frozen event payload, exactly once across the run's life


class TestProjectResolvedEvent(RunInitTestCase):
    def test_frozen_payload_exactly_once_across_lifecycle(self):
        self.seed()
        path = drv.init_run(
            GOAL, project=self.binding(), config_override=mock_config()
        )
        events = self.resolved_events(path)
        self.assertEqual(len(events), 1)
        # Payload keys exactly {project, work_area} plus the seq/at/type
        # envelope every event carries.
        self.assertEqual(
            set(events[0]), {"seq", "at", "type", "project", "work_area"}
        )
        self.assertEqual(events[0]["project"], self.PROJECT)
        self.assertEqual(events[0]["work_area"], self.WORK_AREA)

        # Driver construction, a step, a recorded failure, and a
        # resume_run cycle append no second event.
        mock = runners.MockRunner([
            draft_step(),
            step(
                "review_round",
                {
                    "status": "blocked",
                    "kind": "review_round",
                    "blocked_reason": "operator input needed",
                },
                family="codex",
            ),
        ])
        driver = drv.Driver(path, runner=mock)
        driver.step()  # draft
        driver.step()  # pre-review verification gate
        driver.step()  # blocked review -> recorded run failure
        self.assertEqual(mock.script, [])
        state = st.load(path)
        self.assertIsNotNone(state["failure"])
        self.assertEqual(len(self.resolved_events(path)), 1)

        st.resume_run(state)
        st.save(path, state)
        driver2 = drv.Driver(
            path,
            runner=runners.MockRunner(
                [step("review_round", report("review_round"),
                      family="codex")]
            ),
        )
        driver2.step()
        final = st.load(path)
        self.assertIsNone(final["failure"])
        self.assertIn("resumed", [e["type"] for e in final["events"]])
        self.assertEqual(len(self.resolved_events(path)), 1)


# ---------------------------------------------------------------------------
# AC3: project-less inertness (the pre-existing suite is the regression
# body; here: no new key, no event, no store required)


class TestProjectlessInertness(RunInitTestCase):
    def test_no_binding_means_no_project_key_no_event_no_store(self):
        ws = os.path.join(self._tmp.name, "plain-ws")
        path = drv.init_run(GOAL, ws)
        state = st.load(path)
        self.assertNotIn("project", state)  # absent, not present-null
        self.assertEqual(self.resolved_events(path), [])
        # Exactly today's document: same top-level keys, same default
        # config, and the workspace still gets created (makedirs kept).
        self.assertEqual(
            set(state), set(st.new_state(GOAL, ws, drv.load_config(None)))
        )
        self.assertEqual(state["config"], drv.load_config(None))
        self.assertTrue(os.path.isdir(ws))
        # No store directory exists anywhere: nothing consulted one.
        self.assertFalse(os.path.exists(self.store_base))


# ---------------------------------------------------------------------------
# AC4: resolution is read-only


class TestReadOnlyResolution(RunInitTestCase):
    def test_successful_init_leaves_the_store_byte_unchanged(self):
        store = self.seed()
        store.put_meta(
            self.WORK_AREA,
            {
                "reuse_sources": [
                    {
                        "root": self.lib,
                        "inventory": "packages/",
                        "registry": "docs/registry.md",
                        "consumption": "path dep",
                    }
                ]
            },
        )
        before = self.store_snapshot()
        # Sanity: READY at domain version 2 (declare 1 -> confirm 2).
        self.assertEqual(before[2][A("status")], "ready")
        self.assertEqual(before[2][A("version")], 2)

        drv.init_run(GOAL, project=self.binding())

        self.assertEqual(self.store_snapshot(), before)


# ---------------------------------------------------------------------------
# AC5: readiness is VERIFIED here, never consulted. The stored status
# records what some launcher once found; what decides a launch is whether
# the descriptor's roots are on this filesystem right now, and a missing
# one refuses with its own cause instead of a generic not-ready.


class TestRootsAreVerifiedNotConsulted(RunInitTestCase):
    def test_pending_record_resolves(self):
        # Declared and never confirmed: no launch has run here yet, which
        # says nothing about whether the roots exist. They do.
        self.seed(confirm=False)  # declared -> pending
        path = drv.init_run(GOAL, project=self.binding())
        self.assertTrue(os.path.exists(path))

    def test_unavailable_record_resolves_once_the_roots_are_back(self):
        # A stale absence verdict does not outrank the filesystem.
        store = self.seed()
        key = kvstore.raw_work_area_key(self.WORK_AREA)
        raw = dict(store.client.get(key))
        raw[A("status")] = "unavailable"
        raw[A("version")] = raw[A("version")] + 1
        store.client.put(key, raw)
        path = drv.init_run(GOAL, project=self.binding())
        self.assertTrue(os.path.exists(path))

    def test_resolution_records_nothing(self):
        # Verification here is read-only: recording what was found is the
        # service launcher's half, not the init seam's.
        self.seed(confirm=False)
        before = self.kv_bytes()
        drv.init_run(GOAL, project=self.binding())
        self.assertEqual(self.kv_bytes(), before)

    def test_missing_additional_root_refuses_with_its_own_cause(self):
        ghost = os.path.join(self._tmp.name, "ghost-lib")
        self.seed(additional=[{"path": ghost, "device": "dev-lib"}])
        self.assert_refused(drv.MISSING_ADDITIONAL_ROOT)
        self.assertFalse(os.path.exists(ghost))


# ---------------------------------------------------------------------------
# AC6: unknown/malformed/invalid refusals reuse Slice 2's vocabulary


class TestUnknownAndMalformedRefusals(RunInitTestCase):
    def test_never_declared_name_refuses_unknown(self):
        self.seed()
        self.assert_refused(
            workareas.UNKNOWN, binding=self.binding(work_area="ghost")
        )

    def test_tombstoned_work_area_refuses_unknown(self):
        store = self.seed()
        self.assertTrue(store.delete(self.WORK_AREA).ok)
        self.assert_refused(workareas.UNKNOWN)

    def test_missing_store_directory_refuses_unknown_creating_nothing(self):
        # No store was ever created anywhere.
        self.assert_refused(workareas.UNKNOWN)
        self.assertFalse(os.path.exists(self.store_base))

        # An existing base without THIS project's store refuses the same
        # way, and the refused project's directory does not materialize.
        other = workareas.WorkAreaStore(self.store_base, "other-project")
        self.assertTrue(
            other.declare("x", self.primary, [], self.EXECUTOR).ok
        )
        self.assert_refused(workareas.UNKNOWN)
        self.assertFalse(
            os.path.exists(os.path.join(self.store_base, self.PROJECT))
        )

    def test_malformed_record_refuses_without_repair_write(self):
        store = self.seed()
        key = kvstore.raw_work_area_key(self.WORK_AREA)
        # Outside the agent_99 domain: not the full record key set.
        store.client.put(key, {A("name"): self.WORK_AREA, A("version"): 1})
        before = self.kv_bytes()
        self.assert_refused(workareas.MALFORMED)
        self.assertEqual(self.kv_bytes(), before)  # fail-closed, no repair

    def test_invalid_slug_and_name_reuse_slice2_reasons(self):
        self.seed()
        self.assert_refused(
            workareas.INVALID_PROJECT,
            binding=self.binding(project="has/slash"),
        )
        self.assert_refused(
            workareas.INVALID_PROJECT, binding=self.binding(project="..")
        )
        self.assert_refused(
            workareas.INVALID_NAME, binding=self.binding(work_area="a/b")
        )
        self.assert_refused(
            workareas.INVALID_NAME, binding=self.binding(work_area="   ")
        )


# ---------------------------------------------------------------------------
# AC7 (+AC8): workspace ≡ primary.path, missing primary, nothing created


class TestWorkspaceCrossCheck(RunInitTestCase):
    def test_supplied_equal_workspace_succeeds(self):
        self.seed()
        path = drv.init_run(GOAL, self.repo, project=self.binding())
        self.assertEqual(st.load(path)["workspace"], self.repo)

    def test_supplied_different_workspace_refuses(self):
        self.seed()
        other = os.path.join(self._tmp.name, "elsewhere")
        os.makedirs(other)
        self.assert_refused(drv.WORKSPACE_MISMATCH, workspace=other)
        self.assertEqual(os.listdir(other), [])

    def test_equivalent_but_unequal_path_refuses(self):
        # Strict equality: ambiguity refuses, nothing normalizes.
        self.seed()
        self.assert_refused(
            drv.WORKSPACE_MISMATCH, workspace=self.repo + "/"
        )

    def test_missing_primary_directory_refuses_and_is_not_created(self):
        ghost = os.path.join(self._tmp.name, "ghost-repo")
        self.seed(primary={"path": ghost, "device": 1})
        self.assert_refused(drv.MISSING_PRIMARY_PATH)
        self.assertFalse(os.path.exists(ghost))  # no makedirs on the
        # bound path: init never fabricates the executed repo

    def test_existing_state_raises_file_exists_not_resolution_error(self):
        # Under the per-milestone layout a second init UNIQUIFIES its
        # milestone dir and coexists (one repo hosts many runs) — so the
        # FileExistsError contract survives only where states can truly
        # collide: the legacy workspace-root docs_dir. Both truths pinned;
        # the dedicated resolution-error type stays for resolution
        # refusals only (D).
        self.seed()
        first = drv.init_run(GOAL, project=self.binding())
        second = drv.init_run(GOAL, project=self.binding())
        self.assertNotEqual(first, second)
        for path in (first, second):
            self.assertTrue(os.path.isfile(path))
        legacy_cfg = make_config(docs_dir="docs")
        drv.init_run(GOAL, project=self.binding(),
                     config_override=legacy_cfg)
        with self.assertRaises(FileExistsError):
            drv.init_run(GOAL, project=self.binding(),
                         config_override=legacy_cfg)


# ---------------------------------------------------------------------------
# AC9: the binding is resolved once and stable for the run's life


class TestStabilityAfterInit(RunInitTestCase):
    def test_store_mutations_never_rebind_a_live_run(self):
        store = self.seed()
        path = drv.init_run(
            GOAL, project=self.binding(), config_override=mock_config()
        )
        recorded = st.load(path)["project"]

        # Relabel, replace the descriptor with different roots confirmed
        # to READY, then check the run saw none of it.
        self.assertTrue(store.relabel(self.WORK_AREA, "Renamed").ok)
        replacement = os.path.join(self._tmp.name, "replacement-repo")
        os.makedirs(replacement)
        new_primary = {"path": replacement, "device": 9}
        self.assertTrue(
            store.declare(self.WORK_AREA, new_primary, [],
                          self.EXECUTOR).ok
        )
        self.assertTrue(
            store.confirm(self.WORK_AREA, new_primary, [],
                          self.EXECUTOR).ok
        )
        state = st.load(path)
        self.assertEqual(state["project"], recorded)
        self.assertEqual(state["workspace"], self.repo)

        # Steps after the mutations — and after deleting the work area
        # entirely — neither re-resolve nor append any project event.
        driver = drv.Driver(path, runner=runners.MockRunner([draft_step()]))
        driver.step()  # draft
        self.assertTrue(store.delete(self.WORK_AREA).ok)
        driver.step()  # verification gate, work area now tombstoned
        final = st.load(path)
        self.assertIsNone(final["failure"])
        self.assertEqual(final["project"], recorded)
        self.assertEqual(final["workspace"], self.repo)
        self.assertEqual(len(self.resolved_events(path)), 1)


# ---------------------------------------------------------------------------
# AC10: project defaults apply at init, beneath operator intent


class TestDefaultsPrecedence(RunInitTestCase):
    def test_creation_acts_are_single_homed_without_staffing_drift(self):
        self.seed()
        home = os.path.join(self._tmp.name, "profile-home")
        path = drv.init_run(
            GOAL,
            project=self.binding(defaults={
                "acts": {"drafter": "claude", "fixer": "claude"}
            }),
            config_override={"acts": {"fixer": "codex"}},
            model_profiles_home=home,
        )

        with open(os.path.join(os.path.dirname(path), "acts.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {
                "drafter": "claude", "fixer": "codex"
            })
        self.assertEqual(
            st.load(path)["config"]["acts"], drv.DEFAULT_CONFIG["acts"]
        )

    def test_higher_object_replaces_lower_whole_map_clear(self):
        self.seed()
        home = os.path.join(self._tmp.name, "clear-profile-home")
        path = drv.init_run(
            GOAL,
            project=self.binding(defaults={"acts": None}),
            config_override={"acts": {"fixer": "claude"}},
            model_profiles_home=home,
        )
        with open(os.path.join(os.path.dirname(path), "acts.json"),
                  encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"fixer": "claude"})

    def test_project_default_applies_when_launch_does_not_set_it(self):
        self.seed()
        path = drv.init_run(
            GOAL,
            name="My Feature",
            project=self.binding(defaults={"docs_dir": "notes/{slug}"}),
        )
        state = st.load(path)
        self.assertEqual(state["config"]["docs_dir"], "notes/{slug}")
        self.assertEqual(state["docs_dir"], "notes/my-feature")

    def test_default_docs_dir_participates_in_slug_uniquification(self):
        self.seed()
        os.makedirs(os.path.join(self.repo, "notes", "my-feature"))
        path = drv.init_run(
            GOAL,
            name="My Feature",
            project=self.binding(defaults={"docs_dir": "notes/{slug}"}),
        )
        self.assertEqual(st.load(path)["docs_dir"], "notes/my-feature-2")

    def test_launch_explicit_value_wins_over_the_default(self):
        self.seed()
        path = drv.init_run(
            GOAL,
            name="My Feature",
            project=self.binding(defaults={"docs_dir": "notes/{slug}"}),
            config_override={"docs_dir": "docs"},
        )
        state = st.load(path)
        self.assertEqual(state["config"]["docs_dir"], "docs")
        self.assertEqual(state["docs_dir"], "docs")

    def test_dict_valued_defaults_merge_key_wise(self):
        self.seed()
        path = drv.init_run(
            GOAL,
            project=self.binding(
                defaults={"acts": {"drafter": "claude", "fixer": "claude"}}
            ),
            config_override={"acts": {"fixer": "codex-mini"}},
        )
        acts = st.load(path)["config"]["acts"]
        base = drv.DEFAULT_CONFIG["acts"]
        self.assertEqual(acts["drafter"], "claude")    # default applies
        self.assertEqual(acts["fixer"], "codex-mini")  # launch wins
        self.assertNotIn("delta_review", acts)
        self.assertNotIn("delta_review", base)
        self.assertNotIn("consultation", acts)
        self.assertNotIn("consultation", base)

    def test_absent_defaults_effective_config_is_exactly_todays(self):
        self.seed()
        override = mock_config()
        path = drv.init_run(
            GOAL, project=self.binding(), config_override=override
        )
        expected = drv.load_config(None)
        drv.merge_config(expected, override)
        self.assertEqual(st.load(path)["config"], expected)

    def test_no_defaults_no_override_is_the_default_config(self):
        self.seed()
        path = drv.init_run(GOAL, project=self.binding())
        self.assertEqual(st.load(path)["config"], drv.load_config(None))

    def test_invalid_defaults_refuse_creating_nothing(self):
        self.seed()
        before = self.kv_bytes()
        for bad in (
            ["not", "an", "object"],
            "docs",
            7,
            None,  # carrying the key demands an object
            {"acts": {"drafter": object()}},   # not JSON-plain
            {"weird": float("nan")},           # not serialization-stable
        ):
            with self.subTest(bad=bad):
                b = self.binding()
                b["defaults"] = bad
                self.assert_refused(projects.INVALID_DEFAULTS, binding=b)
        self.assertEqual(self.kv_bytes(), before)


# ---------------------------------------------------------------------------
# The seam's own guards: the launch override arrives distinguishably


class TestBindingSeamGuards(RunInitTestCase):
    def test_premerged_config_with_a_binding_is_refused(self):
        self.seed()
        with self.assertRaises(ValueError):
            drv.init_run(
                GOAL, config=drv.load_config(None), project=self.binding()
            )
        self.assertFalse(bool(_ws_states(self.repo)))

    def test_config_override_without_a_binding_is_refused(self):
        ws = os.path.join(self._tmp.name, "plain-ws")
        with self.assertRaises(ValueError):
            drv.init_run(GOAL, ws, config_override={"docs_dir": "docs"})
        self.assertFalse(bool(_ws_states(ws)))

    def test_malformed_binding_shapes_are_caller_errors(self):
        self.seed()
        for bad in (
            "not-a-dict",
            {"project": self.PROJECT, "work_area": self.WORK_AREA},
            dict(self.binding(), extra=1),
            dict(self.binding(), directory=""),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    drv.init_run(GOAL, project=bad)
        self.assertFalse(bool(_ws_states(self.repo)))


if __name__ == "__main__":
    unittest.main()
