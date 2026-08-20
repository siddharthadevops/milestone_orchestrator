"""Focused tests for Slice 2's current-state model-profile resolver."""

import contextlib
import copy
import io
import json
import os
import shlex
import subprocess
import tempfile
import time
import types
import unittest
from unittest import mock

from orchestrator import contracts, driver, gitops
from orchestrator import model_profiles
from orchestrator import brainstorming_lifecycle
from orchestrator import prompts, registry, runners, service, staffing
from orchestrator import state, tasks
from orchestrator import verifiers


def profile(name, medium):
    return {
        "name": name,
        "examples": ["runtime test"],
        "configurations": {"low": {}, "medium": medium, "high": {}},
    }


class CurrentModelProfileRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(
            prefix="orch-current-model-profile-"
        )
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.workspace = os.path.join(self.tmp.name, "workspace")
        os.makedirs(self.workspace)

    def init(self, workspace=None, with_home=True, config=None):
        workspace = workspace or self.workspace
        os.makedirs(workspace, exist_ok=True)
        return driver.init_run(
            "current model profile",
            workspace,
            config=copy.deepcopy(config or driver.DEFAULT_CONFIG),
            model_profiles_home=self.home if with_home else None,
        )

    def runtime_path(self, state_path, name):
        return os.path.join(os.path.dirname(state_path), name)

    def write_runtime(self, state_path, name, value):
        path = self.runtime_path(state_path, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        os.replace(tmp, path)

    def bind_owner_session(self, state_path):
        """Bind one staffing session to a run, as a launch or resume does."""
        run_state = state.load(state_path)
        bound = state.staffing_session(run_state)
        if bound:
            return bound
        record = staffing.create_session(self.home, {
            "work_area": {"workspace_path": self.workspace},
            "families": list(driver.DEFAULT_CONFIG["families_order"]),
            "document": staffing.DEFAULT_DOCUMENT_NAME,
            "rigor": "medium",
        })
        state.bind_staffing_session(run_state, record["id"])
        state.save(state_path, run_state)
        return record["id"]

    def resolver(self, state_path, runner=None):
        return driver.Driver(
            state_path,
            runner=runner or runners.MockRunner([]),
            model_profiles_home=self.home,
        )

    def test_old_and_new_unselected_runs_use_current_default(self):
        old_config = copy.deepcopy(driver.DEFAULT_CONFIG)
        old_config["acts"]["fixer"] = "claude"
        old_path = self.init(with_home=False, config=old_config)
        model_profiles.ensure_default(self.home)
        d = self.resolver(old_path)
        # Pre-feature config acts have no recoverable origin and remain
        # baseline; the current profile governs old and new runs alike.
        self.assertEqual(d._act_profile("fixer")[0], "codex")

        edited = model_profiles.load(self.home, "default")
        edited["configurations"]["medium"]["fixer"] = {
            "agent": "claude", "model": "claude-sonnet-5",
            "effort": "high",
        }
        model_profiles.save(self.home, edited)
        expected = ("claude", "claude-sonnet-5", "high")
        self.assertEqual(d._act_profile("fixer"), expected)

        new_workspace = os.path.join(self.tmp.name, "new-workspace")
        new_path = self.init(workspace=new_workspace)
        self.assertEqual(self.resolver(new_path)._act_profile("fixer"),
                         expected)
        self.assertFalse(os.path.exists(
            self.runtime_path(old_path, "model_profile.json")
        ))
        self.assertFalse(os.path.exists(
            self.runtime_path(new_path, "model_profile.json")
        ))

    def test_execution_entrypoints_seed_validate_and_supply_catalogue_home(self):
        cli_workspace = os.path.join(self.tmp.name, "cli-workspace")
        config_path = os.path.join(self.tmp.name, "cli-config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump({
                "git": {"enabled": False},
                "acts": {"fixer": "claude"},
            }, fh)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = driver.main([
                "init", "--goal", "cli current profile",
                "--workspace", cli_workspace,
                "--config", config_path,
                "--model-profiles-home", self.home,
            ])
        self.assertEqual(code, 0)
        self.assertEqual(model_profiles.load(self.home, "default")["name"],
                         "default")
        path = output.getvalue().strip().removeprefix("initialized: ")
        with open(self.runtime_path(path, "acts.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"fixer": "claude"})
        self.assertEqual(self.resolver(path)._act_profile("fixer")[0],
                         "claude")

        default_path = os.path.join(
            self.home, "model_profiles", "default.json"
        )
        with open(default_path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        invalid_workspace = os.path.join(self.tmp.name, "invalid-startup")
        with self.assertRaises(model_profiles.ModelProfileError):
            self.init(workspace=invalid_workspace)
        self.assertFalse(os.path.exists(
            driver.default_state_path(invalid_workspace)
        ))

        refused_workspace = os.path.join(self.tmp.name, "invalid-cli-acts")
        refused_config = os.path.join(self.tmp.name, "invalid-cli-acts.json")
        with open(refused_config, "w", encoding="utf-8") as fh:
            json.dump({"acts": {
                "review_codex": {"agent": "claude", "model": "x"}
            }}, fh)
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = driver.main([
                "init", "--goal", "invalid creation acts",
                "--workspace", refused_workspace,
                "--config", refused_config,
                "--model-profiles-home", self.home,
            ])
        self.assertEqual(code, 2)
        self.assertIn("not honored", error.getvalue())
        self.assertFalse(os.path.exists(
            driver.default_state_path(refused_workspace)
        ))

    def test_creation_authority_validation_refuses_before_state_creation(self):
        model_profiles.ensure_default(self.home)
        invalid = (
            {"review_codex": {"agent": "codex", "model": "review"}},
            {"consultation": {"agent": "claude", "effort": "high"}},
            {"fixer": {"agent": "codex", "reasoning": "high"}},
        )
        for index, creation_acts in enumerate(invalid):
            with self.subTest(creation_acts=creation_acts):
                workspace = os.path.join(
                    self.tmp.name, "invalid-creation-%d" % index
                )
                os.makedirs(workspace)
                config = copy.deepcopy(driver.DEFAULT_CONFIG)
                config["acts"].update(copy.deepcopy(creation_acts))
                state_path = driver.default_state_path(workspace)
                with self.assertRaisesRegex(ValueError, "creation act overrides"):
                    driver.init_run(
                        "invalid creation",
                        workspace,
                        config=config,
                        model_profiles_home=self.home,
                        creation_acts=creation_acts,
                    )
                self.assertFalse(os.path.exists(state_path))
                self.assertFalse(os.path.exists(os.path.join(
                    os.path.dirname(state_path), "acts.json"
                )))

    def test_profile_selection_and_override_are_last_write_wins(self):
        model_profiles.ensure_default(self.home)
        model_profiles.save(self.home, profile("work", {
            "fixer": {"agent": "claude", "model": "profile-v1",
                      "effort": "medium"},
        }))
        model_profiles.save(self.home, profile("other", {
            "fixer": {"agent": "codex", "model": "other-profile",
                      "effort": "low"},
        }))
        path = self.init()
        run_id = "runtime-surface"
        registry.add(self.home, registry.new_entry(
            run_id, "runtime", self.workspace, path
        ))
        d = self.resolver(path)
        self.write_runtime(
            path, "model_profile.json", {"name": "work", "rigor": "medium"}
        )
        dispatched = d._act_profile("fixer")
        self.assertEqual(dispatched, ("claude", "profile-v1", "medium"))

        edited = model_profiles.load(self.home, "work")
        edited["configurations"]["medium"]["fixer"]["model"] = "profile-v2"
        service.save_model_profile(self.home, edited)
        self.assertEqual(d._act_profile("fixer"),
                         ("claude", "profile-v2", "medium"))
        self.assertEqual(dispatched, ("claude", "profile-v1", "medium"))

        self.write_runtime(
            path, "model_profile.json", {"name": "other", "rigor": "medium"}
        )
        self.assertEqual(d._act_profile("fixer"),
                         ("codex", "other-profile", "low"))

        self.write_runtime(
            path, "acts.json",
            {"fixer": {"agent": "codex", "model": "override",
                       "effort": "high"}},
        )
        self.assertEqual(d._act_profile("fixer"),
                         ("codex", "override", "high"))
        self.write_runtime(path, "acts.json", {})
        self.assertEqual(d._act_profile("fixer"),
                         ("codex", "other-profile", "low"))

    def test_explicit_empty_uses_structural_family_default_not_profile(self):
        for index, empty in enumerate((None, "", {})):
            with self.subTest(empty=empty):
                workspace = os.path.join(self.tmp.name, "empty-%d" % index)
                os.makedirs(workspace)
                config = copy.deepcopy(driver.DEFAULT_CONFIG)
                config["acts"]["implementer"] = copy.deepcopy(empty)
                path = driver.init_run(
                    "empty creation override",
                    workspace,
                    config=config,
                    model_profiles_home=self.home,
                    creation_acts={"implementer": copy.deepcopy(empty)},
                )
                with open(self.runtime_path(path, "acts.json"),
                          encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh), {"implementer": empty})
                self.assertEqual(
                    self.resolver(path)._act_profile("implementer"),
                    ("codex", None, None),
                )

        workspace = os.path.join(self.tmp.name, "empty-whole-map")
        os.makedirs(workspace)
        config = copy.deepcopy(driver.DEFAULT_CONFIG)
        config["acts"] = None
        path = driver.init_run(
            "empty whole map",
            workspace,
            config=config,
            model_profiles_home=self.home,
            creation_acts=None,
        )
        d = self.resolver(path)
        self.assertEqual(d._act_profile("implementer"),
                         ("codex", None, None))
        self.assertEqual(d._act_profile("reclassifier"),
                         ("codex", None, None))

    def test_status_does_not_require_catalogue_readiness(self):
        path = self.init(with_home=False)
        run_state = state.load(path)
        unit = state.current_unit(run_state)
        unit["status"] = state.U_ROUNDS
        unit["family_index"] = 0
        state.save(path, run_state)

        homes = (
            os.path.join(self.tmp.name, "missing-catalogue"),
            os.path.join(self.tmp.name, "corrupt-catalogue"),
        )
        os.makedirs(os.path.join(homes[1], "model_profiles"))
        with open(os.path.join(homes[1], "model_profiles", "default.json"),
                  "w", encoding="utf-8") as fh:
            fh.write("{broken")

        for home in homes:
            with self.subTest(home=home):
                output = io.StringIO()
                args = types.SimpleNamespace(
                    state=path,
                    workspace=None,
                    json=True,
                    model_profiles_home=home,
                )
                with contextlib.redirect_stdout(output):
                    self.assertEqual(driver.cmd_status(args), 0)
                shown = json.loads(output.getvalue())
                self.assertEqual(shown["current_unit_status"], state.U_ROUNDS)
                self.assertEqual(
                    service.load_summary(
                        path, model_profiles_home=home
                    )["current_unit_status"],
                    state.U_ROUNDS,
                )

    def test_catalogue_failure_does_not_suppress_generic_recovery(self):
        subprocess.run(
            ["git", "init", "-q", self.workspace],
            check=True,
            capture_output=True,
            text=True,
        )
        config = copy.deepcopy(driver.DEFAULT_CONFIG)
        config["git"] = {"enabled": True}
        path = self.init(config=config)
        active = self.resolver(path)
        run_state = state.load(path)
        state.current_unit(run_state)["status"] = state.U_ROUNDS
        state.save(path, run_state)
        usage = {
            "input_tokens": 11,
            "cached_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "total_tokens": 14,
        }
        self.assertTrue(active._mark_busy(
            "completed-before-restart",
            contracts.KIND_REVIEW_ROUND,
            "codex",
            model="gpt-5.6-sol",
            effort="high",
        ))
        completed = runners.RunnerResult(
            "{}", 0, 2.5, token_usage=usage, cost_payloads=[usage]
        )
        self.assertTrue(active._update_busy_accounting(completed))
        worker_junk = os.path.join(
            self.workspace, "interrupted-worker-output.txt"
        )
        with open(worker_junk, "w", encoding="utf-8") as fh:
            fh.write("partial worker output\n")

        default_path = os.path.join(
            self.home, "model_profiles", "default.json"
        )
        with open(default_path, "w", encoding="utf-8") as fh:
            fh.write("{broken")

        # A damaged catalogue no longer stops a homed run: nothing this
        # driver dispatches resolves through a profile any more, so the
        # start does its generic recovery and the run keeps staffing every
        # seat from its own staffing session.
        restarted = self.resolver(path)
        self.assertEqual(
            restarted._staff("implement")[0],
            staffing.resolve(
                self.home,
                state.staffing_session(restarted.state),
                "implement",
                families=list(driver.DEFAULT_CONFIG["families_order"]),
            ).answer["agent"],
        )

        recovered = state.load(path)
        incidents = [
            event for event in recovered["events"]
            if event.get("type") == "worker_interrupted"
            and event.get("label") == "completed-before-restart"
        ]
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["duration_s"], 2.5)
        self.assertEqual(incidents[0]["token_usage"], usage)
        self.assertIsNotNone(incidents[0]["cost"])
        self.assertIsNone(recovered["failure"])
        # The operator's bytes are left exactly as they are.
        with open(default_path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{broken")
        self.assertFalse(os.path.exists(worker_junk))
        self.assertTrue(any(
            event.get("type") == "unclean_stop_restored"
            for event in recovered["events"]
        ))
        self.assertFalse(os.path.exists(
            self.runtime_path(path, "current.json")
        ))

    def test_damaged_default_profile_seeds_no_durable_default_document(self):
        """A fault never becomes the operator's converted `default`.

        Not gating the call on a damaged profile is this slice's licence;
        writing a durable document from that fault is not. `ensure_documents`
        skips the profile it cannot read, so with no `default` document to
        find it would seed the in-code `default` over a stored `default`
        profile that merely cannot be read — and conversion is missing-only,
        so repairing the profile afterwards would never convert it. The
        resolver's mandatory fallback answers the same seat from the same
        seed meanwhile, and says so.
        """
        path = self.init()
        # Today's stored `default` is what conversion must not lose: it
        # differs from the in-code seed on the seat asserted below.
        stored = model_profiles.load(self.home, "default")
        stored["configurations"]["medium"]["implementer"] = {
            "agent": "claude", "model": "claude-sonnet-5", "effort": "low",
        }
        model_profiles.save(self.home, stored)
        converted = staffing.convert_profile(stored)

        # A home that has not converted yet — the pre-cutover state the
        # conversion rule governs — whose `default` profile is unreadable.
        for name in staffing.document_names(self.home):
            os.remove(os.path.join(
                staffing.staffing_documents_dir(self.home), "%s.json" % name
            ))
        default_path = os.path.join(
            self.home, "model_profiles", "default.json"
        )
        with open(default_path, "w", encoding="utf-8") as fh:
            fh.write("{broken")

        restarted = self.resolver(path)
        # Nothing durable was written from the fault, so the operator's own
        # `default` still converts once the profile is readable again.
        self.assertEqual(staffing.document_names(self.home), [])
        answered = staffing.resolve(
            self.home,
            state.staffing_session(restarted.state),
            "implement",
            families=list(driver.DEFAULT_CONFIG["families_order"]),
        )
        self.assertEqual(
            answered.staffing_fallback,
            staffing.STAFFING_FALLBACK_DEFAULT_DOCUMENT,
        )
        self.assertEqual(
            restarted._staff("implement")[0], answered.answer["agent"]
        )
        self.assertIsNone(state.load(path)["failure"])

        # Repair, restart: the conversion the fault deferred now happens,
        # and it is the operator's profile that sources `default`.
        model_profiles.save(self.home, stored)
        self.resolver(path)
        self.assertEqual(staffing.load(self.home, "default"), converted)
        self.assertNotEqual(converted, staffing.default_document_seed())

    def test_purged_legacy_run_does_not_supply_next_run_current_settings(self):
        model_profiles.ensure_default(self.home)
        model_profiles.save(self.home, profile("prior", {
            "fixer": {
                "agent": "claude",
                "model": "prior-run-model",
                "effort": "high",
            },
        }))
        config = {"git": {"enabled": False}, "docs_dir": "docs"}
        first = service.create_run(self.home, {
            "workspace": self.workspace,
            "goal": "first legacy run",
            "autostart": False,
            "config": config,
        })
        self.write_runtime(first["state_path"], "model_profile.json", {
            "name": "prior", "rigor": "medium"
        })
        self.assertEqual(
            self.resolver(first["state_path"])._act_profile("fixer"),
            ("claude", "prior-run-model", "high"),
        )
        self.write_runtime(first["state_path"], "acts.json", {
            "fixer": {
                "agent": "claude",
                "model": "deleted-run-override",
                "effort": "low",
            },
        })
        self.assertEqual(
            self.resolver(first["state_path"])._act_profile("fixer"),
            ("claude", "deleted-run-override", "low"),
        )

        purged = service.delete_run(self.home, first["id"], purge=True)
        selection_path = self.runtime_path(
            first["state_path"], "model_profile.json"
        )
        acts_path = self.runtime_path(first["state_path"], "acts.json")
        for discarded_path in (selection_path, acts_path):
            self.assertIn(discarded_path, purged["purged"])
            self.assertFalse(os.path.exists(discarded_path))

        second = service.create_run(self.home, {
            "workspace": self.workspace,
            "goal": "second legacy run",
            "autostart": False,
            "config": config,
        })
        self.assertEqual(second["state_path"], first["state_path"])
        self.assertIsNone(driver.read_current_model_profile_selection(
            second["state_path"]
        ))
        self.assertEqual(
            self.resolver(second["state_path"])._act_profile("fixer"),
            ("codex", None, None),
        )

    def test_profile_and_override_authority_matrix_share_one_result(self):
        model_profiles.ensure_default(self.home)
        model_profiles.save(self.home, profile("matrix", {}))
        path = self.init()
        self.write_runtime(
            path, "model_profile.json",
            {"name": "matrix", "rigor": "medium"},
        )
        run_id = "matrix-run"
        registry.add(
            self.home,
            registry.new_entry(
                run_id, "authority matrix", self.workspace, path
            ),
        )
        subject = self.resolver(path)

        full_values = {
            "agent": "claude",
            "model": "matrix-model",
            "effort": "high",
        }
        full_objects = [
            {key: value for bit, (key, value) in enumerate(full_values.items())
             if mask & (1 << bit)}
            for mask in range(1, 1 << len(full_values))
        ]
        model_effort_values = {
            "model": "matrix-model",
            "effort": "high",
        }
        model_effort_objects = [
            {key: value
             for bit, (key, value) in enumerate(model_effort_values.items())
             if mask & (1 << bit)}
            for mask in range(1, 1 << len(model_effort_values))
        ]
        family_policies = (
            "codex", "claude", "self", "opposite", "future-family",
        )
        cases = [
            (act, copy.deepcopy(entry))
            for act in model_profiles.FULL_POLICY_ACTS
            for entry in family_policies + tuple(full_objects)
        ] + [
            (act, copy.deepcopy(entry))
            for act in model_profiles.MODEL_EFFORT_ACTS
            for entry in model_effort_objects
        ] + [
            ("consultation", entry) for entry in family_policies
        ]

        def effective_result(act):
            if act == "review_codex":
                return ("codex",) + subject._review_profile("codex")
            if act == "review_claude":
                return ("claude",) + subject._review_profile("claude")
            if act == "brainstorming_counterpart":
                resolved = driver.resolve_current_brainstorming_profile(
                    path, self.home, counterpart=True
                )
                return (
                    resolved["agent"], resolved["model"], resolved["effort"]
                )
            if act == "consultation":
                return (subject._resolve_act(act, "codex"),)
            return subject._act_profile(act, origin_family="codex")

        real_seam = driver._resolve_act_from_layers
        for act, entry in cases:
            with self.subTest(act=act, entry=entry):
                model_profiles.save(
                    self.home,
                    profile("matrix", {act: copy.deepcopy(entry)}),
                )
                self.write_runtime(path, "acts.json", {})
                with mock.patch.object(
                    driver, "_resolve_act_from_layers", wraps=real_seam
                ) as seam:
                    from_profile = effective_result(act)
                    profile_hits = seam.call_count
                    self.assertGreater(profile_hits, 0)

                    model_profiles.save(self.home, profile("matrix", {}))
                    self.write_runtime(
                        path, "acts.json", {act: copy.deepcopy(entry)}
                    )
                    from_override = effective_result(act)
                    self.assertGreater(seam.call_count, profile_hits)

                self.assertEqual(from_override, from_profile)

        # The independently supervised Brainstorming dispatch consumes the
        # counterpart override, while its family remains structurally opposite.
        model_profiles.save(self.home, profile("matrix", {}))
        self.write_runtime(path, "acts.json", {
            "implementer": {
                "agent": "claude", "model": "lead-live", "effort": "high",
            },
            "fixer": {"agent": "claude", "effort": "high"},
            "brainstorming_counterpart": {
                "model": "counterpart-live", "effort": "low",
            },
            "review_codex": {"model": "review-live", "effort": "medium"},
            "consultation": "opposite",
        })
        lead, counterpart = driver.resolve_current_brainstorming_profiles(
            path, self.home
        )
        self.assertEqual(lead, {
            "agent": "claude", "model": "lead-live", "effort": "high",
        })
        self.assertEqual(counterpart, {
            "agent": "codex", "model": "counterpart-live", "effort": "low",
        })
        self.assertEqual(
            subject._delta_review_profile("codex"),
            ("codex", "review-live", "medium"),
        )
        # `consultation` remains an ACT the profile layer resolves; the
        # command line the fixer runs is the router's `consult` seat after
        # slice 4 and is pinned there, not here.
        self.assertEqual(subject._resolve_act("consultation", "claude"),
                         "codex")
        self.assertEqual(subject._act_profile("fixer"),
                         ("claude", None, "high"))

        malformed = (
            (
                "review", "review_codex",
                {"agent": "claude", "model": "illegal"},
                lambda current, _path: current._review_profile("codex"),
                driver.StopStep,
            ),
            (
                "delta", "delta_review",
                {"agent": "claude", "model": "illegal"},
                lambda current, _path: current._delta_review_profile("codex"),
                driver.StopStep,
            ),
            (
                "counterpart", "brainstorming_counterpart",
                {"agent": "codex", "model": "illegal"},
                lambda _current, current_path:
                    driver.resolve_current_brainstorming_profile(
                        current_path, self.home, counterpart=True
                    ),
                model_profiles.ModelProfileError,
            ),
            # `consultation` is deliberately absent: after slice 4 the
            # command line the fixer runs resolves through the run's
            # staffing session, so no profile act can make it raise.
        )
        for source in ("profile", "override"):
            for index, (seat, act, entry, resolve, error) in enumerate(
                malformed
            ):
                with self.subTest(source=source, seat=seat):
                    workspace = os.path.join(
                        self.tmp.name, "malformed-%s-%s" % (source, seat)
                    )
                    malformed_path = self.init(workspace=workspace)
                    runner = runners.MockRunner([])
                    current = self.resolver(malformed_path, runner)
                    if source == "profile":
                        name = "malformed-%d" % index
                        damaged = profile(name, {})
                        damaged["configurations"]["medium"][act] = (
                            copy.deepcopy(entry)
                        )
                        with open(
                            os.path.join(
                                model_profiles.model_profiles_dir(self.home),
                                "%s.json" % name,
                            ),
                            "w",
                            encoding="utf-8",
                        ) as fh:
                            json.dump(damaged, fh)
                        self.write_runtime(
                            malformed_path, "model_profile.json",
                            {"name": name, "rigor": "medium"},
                        )
                    else:
                        self.write_runtime(
                            malformed_path, "acts.json",
                            {act: copy.deepcopy(entry)},
                        )

                    with self.assertRaises(error):
                        resolve(current, malformed_path)
                    self.assertEqual(runner.calls, [])

    def test_current_precedence_and_structural_authority(self):
        model_profiles.ensure_default(self.home)
        model_profiles.save(self.home, profile("structure", {
            "implementer": {"agent": "claude", "effort": "high"},
            "review_codex": {"model": "review-model", "effort": "low"},
            "brainstorming_counterpart": {
                "model": "counterpart-model", "effort": "medium"
            },
            "consultation": "self",
        }))
        path = self.init()
        self.write_runtime(
            path, "model_profile.json",
            {"name": "structure", "rigor": "medium"},
        )
        d = self.resolver(path)
        self.assertEqual(d._review_profile("codex"),
                         ("review-model", "low"))
        lead, counterpart = d._brainstorming_profiles()
        self.assertEqual(lead["agent"], "claude")
        self.assertEqual(counterpart,
                         {"agent": "codex", "model": "counterpart-model",
                          "effort": "medium"})
        self.assertEqual(d._resolve_act("consultation", "claude"), "claude")

    def test_brainstorming_turns_read_current_profile_and_overrides(self):
        model_profiles.ensure_default(self.home)
        edited = model_profiles.load(self.home, "default")
        edited["configurations"]["medium"].update({
            "implementer": {
                "agent": "claude",
                "model": "lead-v1",
                "effort": "medium",
            },
            "brainstorming_counterpart": {
                "model": "counterpart-v1",
                "effort": "medium",
            },
        })
        model_profiles.save(self.home, edited)
        path = self.init()

        self.assertEqual(
            driver.resolve_current_brainstorming_profile(path, self.home),
            {"agent": "claude", "model": "lead-v1", "effort": "medium"},
        )
        edited["configurations"]["medium"]["implementer"].update({
            "agent": "codex",
            "model": "lead-v2",
            "effort": "high",
        })
        model_profiles.save(self.home, edited)
        self.write_runtime(path, "acts.json", {
            "brainstorming_counterpart": {
                "model": "counterpart-live",
                "effort": "low",
            }
        })

        # A fresh resolver, matching lifecycle restart, sees only current
        # state and does not consult the session's creation-time roster.
        self.assertEqual(
            driver.resolve_current_brainstorming_profile(path, self.home),
            {"agent": "codex", "model": "lead-v2", "effort": "high"},
        )
        self.assertEqual(
            driver.resolve_current_brainstorming_profile(
                path, self.home, counterpart=True
            ),
            {
                "agent": "claude",
                "model": "counterpart-live",
                "effort": "low",
            },
        )

    def test_brainstorming_restart_uses_ephemeral_generic_run_attachment(self):
        path = self.init()
        run_state = state.load(path)
        state.current_unit(run_state)["brainstorming_wait"] = {
            "session_id": "legacy-session"
        }
        state.save(path, run_state)
        legacy_record = {
            "caller": "milestone:current-model-profile:slice_impl-02-b",
            "execution_context": {"workspace_path": self.workspace},
            "runtime": {"executors": {"lead": {
                "model_family": "claude", "model": "old", "effort": "max"
            }}},
        }

        # An unregistered milestone session has no authoritative current-state
        # attachment.  It must refuse rather than launch with its old roster.
        service_home = os.path.join(self.tmp.name, "service-home")
        self.assertEqual(registry.load(service_home)["runs"], [])
        with self.assertRaises(service.ApiError) as raised:
            service._attached_brainstorming_staffing_session(
                service_home, "legacy-session", record=legacy_record
            )
        self.assertEqual(raised.exception.status, 503)

        # The ordinary service run attachment already identifies the state;
        # the active service home supplies the catalogue only for this launch.
        registry.add(
            service_home,
            registry.new_entry(
                "run-1",
                "current model profile",
                self.workspace,
                path,
            ),
        )
        with mock.patch.object(
            service.st,
            "load",
            side_effect=OSError("registered run state is unreadable"),
        ):
            with self.assertRaises(service.ApiError) as raised:
                service._attached_brainstorming_staffing_session(
                    service_home, "legacy-session", record=legacy_record
                )
        self.assertEqual(raised.exception.status, 503)

        # Corruption in another registered run sharing the workspace does not
        # mask the one readable state that actually exposes the attachment.
        unreadable_path = os.path.join(
            self.tmp.name, "unrelated-run", "state.json"
        )
        registry.add(
            service_home,
            registry.new_entry(
                "run-unreadable",
                "unrelated run",
                self.workspace,
                unreadable_path,
            ),
        )
        real_load = service.st.load

        def load_readable_attachment(state_path):
            if state_path == unreadable_path:
                raise OSError("unrelated registered state is unreadable")
            return real_load(state_path)

        # The attached session resolves through the run's OWN staffing
        # session, read live from the state the attachment finds.
        owner_session = self.bind_owner_session(path)
        with mock.patch.object(
            service.st, "load", side_effect=load_readable_attachment
        ):
            self.assertEqual(
                service._attached_brainstorming_staffing_session(
                    service_home, "legacy-session", record=legacy_record
                ),
                owner_session,
            )

        lifecycle_record = {
            "id": "legacy-session",
            "pid": None,
            **legacy_record,
        }
        document = {"sessions": [lifecycle_record]}
        snapshot = types.SimpleNamespace(state={"status": "running"})
        store = mock.Mock()
        store.read.return_value = snapshot
        launch = mock.Mock()
        launch.process.pid = 12345
        validate_launch = mock.Mock(
            side_effect=lambda record: (
                service._attached_brainstorming_staffing_session(
                    service_home, "legacy-session", record=record
                )
            )
        )
        with (
            mock.patch.object(
                service.st, "load", side_effect=load_readable_attachment
            ),
            mock.patch.object(
                brainstorming_lifecycle,
                "_record_by_id",
                return_value=lifecycle_record,
            ),
            mock.patch.object(
                brainstorming_lifecycle,
                "_locked_registry",
                return_value=contextlib.nullcontext(),
            ),
            mock.patch.object(
                brainstorming_lifecycle, "_load_registry",
                return_value=document,
            ),
            mock.patch.object(
                brainstorming_lifecycle, "_process_alive",
                return_value=False,
            ),
            mock.patch.object(
                brainstorming_lifecycle, "_launch_lifecycle_process",
                return_value=launch,
            ) as launch_process,
            mock.patch.object(
                brainstorming_lifecycle.brainstorming,
                "SessionStore", return_value=store,
            ),
            mock.patch.object(brainstorming_lifecycle, "_save_registry"),
            mock.patch.object(brainstorming_lifecycle, "_track_child"),
            mock.patch.object(
                brainstorming_lifecycle, "_projection", return_value={}
            ),
        ):
            brainstorming_lifecycle.start_session(
                service_home,
                "legacy-session",
                lambda _record: None,
                resolve_staffing_session=validate_launch,
            )
        validate_launch.assert_called_once_with(lifecycle_record)
        launch_process.assert_called_once_with(
            service_home,
            "legacy-session",
            staffing_session=owner_session,
        )

    def test_brainstorming_monitoring_uses_current_or_actual_staffing(self):
        path = self.init()
        run_state = state.load(path)
        state.current_unit(run_state)["brainstorming_wait"] = {
            "session_id": "current-view"
        }
        state.save(path, run_state)
        registry.add(
            self.home,
            registry.new_entry(
                "run-current-view",
                "current model profile",
                self.workspace,
                path,
            ),
        )
        participants = [
            {
                "id": "lead", "role": "initial_position",
                "delivery": "llm", "executor_ref": "old-lead",
                "model_family": "codex",
            },
            {
                "id": "critic", "role": "contrary_position",
                "delivery": "llm", "executor_ref": "old-critic",
                "model_family": "claude",
            },
        ]
        session_state = {"run_config": {"participants": participants}}
        record = {
            "id": "current-view",
            "caller": "milestone:current-model-profile:slice_impl-02-b",
            "created_at": "2026-08-10T08:00:00+0000",
            "execution_context": {"workspace_path": self.workspace},
            "runtime": {
                "executors": {
                    "old-lead": {
                        "model_family": "codex", "model": "creation-lead",
                        "effort": "medium",
                    },
                    "old-critic": {
                        "model_family": "claude",
                        "model": "creation-counterpart", "effort": "medium",
                    },
                },
                "model_defaults": copy.deepcopy(
                    driver.DEFAULT_CONFIG["model_defaults"]
                ),
            },
        }
        self.bind_owner_session(path)
        owner_session = service._attached_brainstorming_staffing_session(
            self.home, record["id"], record=record
        )
        binding = {"home": self.home, "session": owner_session}
        projected = brainstorming_lifecycle._view_participants(
            record, session_state, staffing_binding=binding
        )
        # The view is the LIVE router answer for each roster seat, never the
        # creation roster the record still carries.
        self.assertEqual(
            [
                (item["model_family"], item["model"], item["effort"])
                for item in projected
            ],
            [
                tuple(
                    staffing.resolve(
                        self.home, owner_session, "brainstorm", index=index
                    ).answer[key]
                    for key in ("agent", "model", "effort")
                )
                for index in (1, 2)
            ],
        )

        run_state = state.load(path)
        task = tasks.admit_task(
            run_state,
            {
                "task_executor": "brainstorming",
                "request": {
                    "work_area": {
                        "workspace_path": self.workspace,
                        "primary": self.workspace,
                        "additional": [],
                    },
                    "request": "Use current task staffing.",
                    "context": {},
                    "reference_documents": [],
                },
            },
            {"dispatch_authority": "current_profile", "participants": []},
            primary_workspace=self.workspace,
        )
        state.save(path, run_state)
        task_record = copy.deepcopy(record)
        task_record.update({
            "id": "task-current-view",
            "caller": (
                brainstorming_lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX
                + task["id"]
            ),
        })
        self.assertEqual(
            service._attached_brainstorming_staffing_session(
                self.home, task_record["id"], record=task_record
            ),
            owner_session,
        )
        self.assertEqual(
            brainstorming_lifecycle._view_participants(
                task_record, session_state, staffing_binding=binding
            ),
            projected,
        )
        terminal = state.load(path)
        tasks.record_task_result(terminal, task["id"], {
            "status": "failure",
            "reason": "Brainstorming session start failed: unavailable",
            "duration_s": 0.0,
            "token_usage": None,
            "token_usage_partial": True,
            "cost": None,
            "cost_partial": True,
            "native_result": None,
        })
        state.save(path, terminal)
        with self.assertRaises(service.ApiError) as terminal_attachment:
            service._attached_brainstorming_staffing_session(
                self.home, task_record["id"], record=task_record
            )
        self.assertEqual(terminal_attachment.exception.status, 503)

        missing_task = copy.deepcopy(task_record)
        missing_task["caller"] = (
            brainstorming_lifecycle.CURRENT_PROFILE_TASK_CALLER_PREFIX
            + "missing-task"
        )
        with self.assertRaises(service.ApiError):
            service._attached_brainstorming_staffing_session(
                self.home, missing_task["id"], record=missing_task
            )

        store = mock.Mock()
        store.read_activity.return_value = None
        store.read_external_intervention.return_value = None
        store.read_turn_attempt.return_value = {
            "token": "active-call",
            "participant_id": "lead",
            "completed_turn_count": 0,
            "quiescent": False,
            "provider_attempt": 1,
            "started_at": time.time(),
        }
        with mock.patch.object(
            brainstorming_lifecycle, "_process_alive", return_value=True
        ):
            active = brainstorming_lifecycle._activity_projection(
                store, record, session_state
            )["in_flight"]
        self.assertEqual(active["participant_id"], "lead")
        self.assertIsNone(active["model_family"])
        self.assertIsNone(active["model"])
        self.assertIsNone(active["effort"])

        # With no binding at all — an unattached record, or an owning run
        # the lookup cannot reach — the view omits staffing rather than
        # showing the creation roster the next dispatch would contradict.
        without_attachment = copy.deepcopy(record)
        without_attachment["id"] = "unattached"
        omitted = brainstorming_lifecycle._view_participants(
            without_attachment, session_state
        )
        self.assertTrue(all(
            item["model_family"] is None
            and item["model"] is None
            and item["effort"] is None
            for item in omitted
        ))

    def test_noop_brainstorming_start_does_not_validate_attachment(self):
        for status, process_alive in (("success", False), ("running", True)):
            with self.subTest(status=status, process_alive=process_alive):
                lifecycle_record = {"id": "legacy-session", "pid": 12345}
                document = {"sessions": [lifecycle_record]}
                snapshot = types.SimpleNamespace(state={"status": status})
                store = mock.Mock()
                store.read.return_value = snapshot
                validate_launch = mock.Mock(
                    side_effect=AssertionError("attachment lookup is not due")
                )
                with (
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_record_by_id",
                        return_value=lifecycle_record,
                    ),
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_locked_registry",
                        return_value=contextlib.nullcontext(),
                    ),
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_load_registry",
                        return_value=document,
                    ),
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_process_alive",
                        return_value=process_alive,
                    ),
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_launch_lifecycle_process",
                    ) as launch_process,
                    mock.patch.object(
                        brainstorming_lifecycle.brainstorming,
                        "SessionStore",
                        return_value=store,
                    ),
                    mock.patch.object(
                        brainstorming_lifecycle,
                        "_projection",
                        return_value={"process": "unchanged"},
                    ),
                ):
                    projected = brainstorming_lifecycle.start_session(
                        self.home,
                        "legacy-session",
                        lambda _record: None,
                        resolve_staffing_session=validate_launch,
                    )
                self.assertEqual(projected, {"process": "unchanged"})
                validate_launch.assert_not_called()
                launch_process.assert_not_called()

    def test_counterpart_dispatch_reads_one_profile_generation(self):
        path = self.init()
        original = model_profiles.resolve_selection
        reads = []

        def counted(home, selection=None):
            reads.append(copy.deepcopy(selection))
            return original(home, selection)

        with mock.patch.object(
            model_profiles, "resolve_selection", side_effect=counted
        ):
            resolved = driver.resolve_current_brainstorming_profile(
                path, self.home, counterpart=True
            )
        self.assertEqual(len(reads), 1)
        self.assertNotEqual(resolved["agent"], "claude")

    def test_secondary_dispatches_reresolve_current_staffing(self):
        model_profiles.ensure_default(self.home)
        current = model_profiles.load(self.home, "default")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "first-model", "effort": "low"
        }
        model_profiles.save(self.home, current)
        path = self.init()

        def select_second(_workspace):
            edited = model_profiles.load(self.home, "default")
            edited["configurations"]["medium"]["implementer"] = {
                "agent": "claude",
                "model": "second-model",
                "effort": "high",
            }
            model_profiles.save(self.home, edited)

        provider = runners.MockRunner([
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "expect_family": "codex",
                "response": "not contract json",
                "side_effect": select_second,
            },
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "expect_family": "claude",
                "response": {
                    "status": "ok",
                    "kind": contracts.KIND_IMPLEMENT,
                    "files_changed": [],
                },
            },
        ])
        subject = self.resolver(path, provider)
        output, result, _raw = subject._call(
            "codex",
            "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
            "secondary dispatch test" % self.workspace,
            contracts.KIND_IMPLEMENT,
            "secondary-dispatch",
            dispatch_resolver=subject._dispatch_for_act("implementer"),
        )
        self.assertEqual(output["status"], "ok")
        self.assertEqual(
            [(item["family"], item["model"], item["effort"])
             for item in provider.call_meta],
            [
                ("codex", "first-model", "low"),
                ("claude", "second-model", "high"),
            ],
        )
        self.assertEqual(result.resolved_family, "claude")
        self.assertEqual(result.repair["family"], "codex")
        self.assertIn("\nFAMILY: codex\n", provider.calls[0][2])
        self.assertIn("\nFAMILY: claude\n", provider.calls[1][2])
        self.assertNotIn("\nFAMILY: codex\n", provider.calls[1][2])

        continuation = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "expect_family": "claude",
            "response": {
                "status": "ok",
                "kind": contracts.KIND_IMPLEMENT,
                "files_changed": [],
            },
        }])
        continued = self.resolver(path, continuation)
        continued._call(
            "codex",
            "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
            "post discussion continuation" % self.workspace,
            contracts.KIND_IMPLEMENT,
            "post-discussion",
            session_ref="old-codex-session",
            continuation_family="codex",
            dispatch_resolver=continued._dispatch_for_act("implementer"),
        )
        self.assertEqual(
            continuation.session_calls[0][:2], ("start", "claude")
        )
        self.assertIn("\nFAMILY: claude\n", continuation.calls[0][2])

    def test_consultation_command_round_trips_spaced_paths(self):
        spaced_home = os.path.join(self.tmp.name, "profile home")
        spaced_workspace = os.path.join(self.tmp.name, "run workspace")
        model_profiles.ensure_default(spaced_home)
        path = driver.init_run(
            "spaced consultation",
            spaced_workspace,
            config=copy.deepcopy(driver.DEFAULT_CONFIG),
            model_profiles_home=spaced_home,
        )
        subject = driver.Driver(
            path,
            runner=runners.MockRunner([]),
            model_profiles_home=spaced_home,
        )
        argv = subject._consultation_command("claude", "high")
        block = prompts._consultation_block("claude", argv)
        rendered = block.split("Command (prompt on stdin):\n  ", 1)[1].split(
            "\n", 1
        )[0]
        self.assertEqual(shlex.split(rendered), argv)

    def test_infrastructure_retry_reresolves_current_staffing(self):
        model_profiles.ensure_default(self.home)
        current = model_profiles.load(self.home, "default")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "retry-v1", "effort": "low"
        }
        model_profiles.save(self.home, current)
        path = self.init()

        def select_second():
            edited = model_profiles.load(self.home, "default")
            edited["configurations"]["medium"]["implementer"] = {
                "agent": "claude", "model": "retry-v2", "effort": "high"
            }
            model_profiles.save(self.home, edited)

        class BusyThenOk:
            def __init__(self):
                self.calls = []

            def call(inner, family, _prompt, _workspace,
                     model=None, effort=None, **_kwargs):
                inner.calls.append((family, model, effort, _prompt))
                if len(inner.calls) == 1:
                    select_second()
                    raise runners.RunnerError("server busy")
                return runners.RunnerResult(
                    json.dumps({
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    }),
                    0,
                    0.01,
                )

        provider = BusyThenOk()
        subject = self.resolver(path, provider)
        subject.config["infra_retry_backoff_s"] = [0]
        output, result, _raw = subject._call(
            "codex",
            "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
            "infrastructure retry test" % self.workspace,
            contracts.KIND_IMPLEMENT,
            "infrastructure-retry",
            dispatch_resolver=subject._dispatch_for_act("implementer"),
        )
        self.assertEqual(output["status"], "ok")
        self.assertEqual([call[:3] for call in provider.calls], [
            ("codex", "retry-v1", "low"),
            ("claude", "retry-v2", "high"),
        ])
        self.assertIn("\nFAMILY: codex\n", provider.calls[0][3])
        self.assertIn("\nFAMILY: claude\n", provider.calls[1][3])
        self.assertEqual(result.resolved_family, "claude")

    def test_cutoff_stabilizer_reresolves_current_staffing(self):
        model_profiles.ensure_default(self.home)
        current = model_profiles.load(self.home, "default")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "before-cutoff", "effort": "low"
        }
        model_profiles.save(self.home, current)
        path = self.init()
        provider = runners.MockRunner([{
            "expect_kind": contracts.KIND_IMPLEMENT,
            "expect_family": "claude",
            "response": {
                "status": "ok",
                "kind": contracts.KIND_IMPLEMENT,
                "files_changed": [],
            },
        }])
        subject = self.resolver(path, provider)
        stale = subject._act_profile("implementer")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "claude", "model": "after-cutoff", "effort": "high"
        }
        model_profiles.save(self.home, current)

        output, result, _raw, marker, stabilized = (
            subject._call_implementation(
                stale[0],
                "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
                "cutoff stabilization" % self.workspace,
                "cutoff-stabilize",
                stale[1],
                stale[2],
                None,
                None,
                None,
                True,
                None,
                stabilizing=True,
                dispatch_resolver=subject._dispatch_for_act("implementer"),
                continuation_family=stale[0],
            )
        )

        self.assertEqual(output["status"], "ok")
        self.assertIsNone(marker)
        self.assertTrue(stabilized)
        self.assertEqual(
            provider.call_meta[0],
            {
                "family": "claude",
                "kind": contracts.KIND_IMPLEMENT,
                "model": "after-cutoff",
                "effort": "high",
            },
        )
        self.assertEqual(result.resolved_family, "claude")

    def test_error_classifier_paths_use_current_resolver(self):
        path = self.init()
        subject = self.resolver(path)
        resolutions = []

        def classify_driver(_exc, **kwargs):
            resolutions.append(("driver", kwargs["resolve_dispatch"]()))
            return "unknown", None, "test"

        with mock.patch.object(
            driver.errclass,
            "classify_worker_failure",
            side_effect=classify_driver,
        ):
            subject._classify_failure(
                "codex", runners.RunnerError("mystery"), "classifier-test"
            )
        # Both classifiers are the router's `classify` seat: which family
        # types a failure is the document's choice, not the family opposite
        # the call that failed.
        self.assertEqual(resolutions.pop(0),
                         ("driver", subject._staff("classify")))

        participant = {
            "id": "lead",
            "role": "initial_position",
            "delivery": "llm",
            "executor_ref": "lead-seat",
            "model_family": "codex",
        }
        snapshot = types.SimpleNamespace(state={
            "run_config": {"participants": [participant]},
            "participant_sessions": {},
            "request": {"workspace_path": self.workspace},
        })

        class Store:
            def read(_self, _session_id):
                return snapshot

            def read_activity(_self, _session_id):
                return None

        record = {
            "id": "session",
            "runtime": {
                "families_order": ["codex", "claude"],
                "commands": copy.deepcopy(driver.DEFAULT_CONFIG["commands"]),
                "model_defaults": copy.deepcopy(
                    driver.DEFAULT_CONFIG["model_defaults"]
                ),
                "executors": {
                    "lead-seat": {
                        "model_family": "codex",
                        "model": "lead-model",
                        "effort": "medium",
                    }
                },
            },
        }
        participant_execution = brainstorming_lifecycle._participant_execution(
            Store(),
            record,
            None,
            staffing_binding={
                "home": self.home,
                "session": state.staffing_session(state.load(path)),
            },
        )

        def classify_brainstorming(_exc, **kwargs):
            resolutions.append(
                ("brainstorming", kwargs["resolve_dispatch"]())
            )
            return "unknown", None, "test"

        with mock.patch.object(
            brainstorming_lifecycle.errclass,
            "classify_worker_failure",
            side_effect=classify_brainstorming,
        ):
            participant_execution.failure_classifier(
                "session",
                participant,
                participant_execution.executors["lead-seat"],
                runners.RunnerError("mystery"),
            )

        self.assertEqual(
            resolutions, [("brainstorming", subject._staff("classify"))]
        )

    def test_predispatch_failure_preserves_completed_malformed_attempt(self):
        usage = {
            "input_tokens": 10,
            "cached_input_tokens": 2,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "total_tokens": 13,
        }
        path = self.init()
        current_profile = model_profiles.load(self.home, "default")
        current_profile["configurations"]["medium"]["implementer"] = {
            "agent": "codex",
            "model": "gpt-5.6-sol",
            "effort": "high",
        }
        model_profiles.save(self.home, current_profile)

        class MalformedThenInvalid:
            def __init__(inner):
                inner.calls = 0

            def call(inner, family, _prompt, _workspace,
                     model=None, effort=None, **_kwargs):
                inner.calls += 1
                self.write_runtime(
                    path,
                    "model_profile.json",
                    {"name": "missing", "rigor": "medium"},
                )
                result = runners.RunnerResult(
                    "paid malformed output",
                    0,
                    2.5,
                    token_usage=usage,
                    cost_payloads=[usage],
                )
                return result

        provider = MalformedThenInvalid()
        subject = self.resolver(path, provider)
        with self.assertRaises(driver.StopStep):
            subject._call(
                "codex",
                "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
                "preserve the first attempt" % self.workspace,
                contracts.KIND_IMPLEMENT,
                "predispatch-profile-failure",
                dispatch_resolver=subject._dispatch_for_act("implementer"),
            )

        self.assertEqual(provider.calls, 1)
        current = state.load(path)
        incidents = [
            event for event in current["events"]
            if event.get("type") == "worker_malformed"
            and event.get("label") == "predispatch-profile-failure"
        ]
        self.assertEqual(len(incidents), 1)
        incident = incidents[0]
        self.assertEqual(incident["duration_s"], 2.5)
        self.assertEqual(incident["token_usage"], usage)
        self.assertIsNotNone(incident["cost"])
        self.assertIn("JSON", incident["error"])
        with open(
            os.path.join(self.workspace, incident["raw_path"]),
            encoding="utf-8",
        ) as handle:
            self.assertEqual(handle.read(), "paid malformed output")
        self.assertIn(
            "model-profile resolution failed",
            current["failure"]["reason"],
        )

    def test_nonrepairable_verifier_failure_keeps_dispatch_identities(self):
        first_usage = {
            "input_tokens": 1_000_000,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 1_000_000,
        }
        second_usage = {
            "input_tokens": 7,
            "cached_input_tokens": 0,
            "output_tokens": 3,
            "reasoning_output_tokens": 0,
            "total_tokens": 10,
        }
        path = self.init()
        current = model_profiles.load(self.home, "default")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "gpt-5.6-sol", "effort": "low"
        }
        model_profiles.save(self.home, current)

        class MalformedThenRejected:
            def __init__(inner):
                inner.calls = []

            def call(inner, family, _prompt, _workspace,
                     model=None, effort=None, **_kwargs):
                inner.calls.append((family, model, effort))
                if len(inner.calls) == 1:
                    edited = model_profiles.load(self.home, "default")
                    edited["configurations"]["medium"]["implementer"] = {
                        "agent": "claude",
                        "model": "claude-opus-5",
                        "effort": "high",
                    }
                    model_profiles.save(self.home, edited)
                    return runners.RunnerResult(
                        "malformed",
                        0,
                        2.0,
                        token_usage=first_usage,
                        cost_payloads=[first_usage],
                    )
                return runners.RunnerResult(
                    json.dumps({
                        "status": "ok",
                        "kind": contracts.KIND_IMPLEMENT,
                        "files_changed": [],
                    }),
                    0,
                    3.0,
                    token_usage=second_usage,
                    cost_payloads=[{"total_cost_usd": 2.5}],
                )

        provider = MalformedThenRejected()
        subject = self.resolver(path, provider)
        with mock.patch(
            "orchestrator.verifiers.validate_merged_output",
            side_effect=verifiers.OperationalError("operator root unavailable"),
        ):
            with self.assertRaises(driver.StopStep):
                subject._call(
                    "codex",
                    "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
                    "verifier identity" % self.workspace,
                    contracts.KIND_IMPLEMENT,
                    "verifier-identity",
                    extensions=[object()],
                    roots=[self.workspace],
                    dispatch_resolver=subject._dispatch_for_act("implementer"),
                )

        self.assertEqual(provider.calls, [
            ("codex", "gpt-5.6-sol", "low"),
            ("claude", "claude-opus-5", "high"),
        ])
        rejected = [
            event for event in state.load(path)["events"]
            if event.get("type") == "worker_unaccepted"
            and event.get("label") == "verifier-identity"
        ]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["family"], "claude")
        self.assertEqual(rejected[0]["model"], "claude-opus-5")
        self.assertEqual(rejected[0]["effort"], "high")
        self.assertEqual(rejected[0]["duration_s"], 5.0)
        self.assertEqual(rejected[0]["cost"], {
            "api_usd": 7.5,
            "real_usd": 0.0,
        })

    def test_double_malformed_family_change_records_each_dispatch_identity(
        self,
    ):
        config = copy.deepcopy(driver.DEFAULT_CONFIG)
        config["error_classifier"] = False
        path = self.init(config=config)
        current = model_profiles.load(self.home, "default")
        current["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "gpt-5.6-sol", "effort": "low"
        }
        model_profiles.save(self.home, current)
        first_usage = {
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "output_tokens": 2,
            "reasoning_output_tokens": 0,
            "total_tokens": 12,
        }
        second_usage = {
            "input_tokens": 20,
            "cached_input_tokens": 5,
            "output_tokens": 3,
            "reasoning_output_tokens": 1,
            "total_tokens": 23,
        }

        def select_second(_workspace):
            edited = model_profiles.load(self.home, "default")
            edited["configurations"]["medium"]["implementer"] = {
                "agent": "claude",
                "model": "claude-opus-5",
                "effort": "high",
            }
            model_profiles.save(self.home, edited)

        class AccountedMockRunner(runners.MockRunner):
            def __init__(inner, script):
                super().__init__(script)
                inner.usages = [first_usage, second_usage]

            def call(inner, *args, **kwargs):
                result = super().call(*args, **kwargs)
                usage = inner.usages[len(inner.calls) - 1]
                result.token_usage = copy.deepcopy(usage)
                result.cost_payloads = [copy.deepcopy(usage)]
                return result

        provider = AccountedMockRunner([
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "expect_family": "codex",
                "response": "first malformed",
                "side_effect": select_second,
            },
            {
                "expect_kind": contracts.KIND_IMPLEMENT,
                "expect_family": "claude",
                "response": "second malformed",
            },
        ])
        subject = self.resolver(path, provider)
        with self.assertRaises(driver.StopStep):
            subject._call(
                "codex",
                "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
                "double malformed" % self.workspace,
                contracts.KIND_IMPLEMENT,
                "double-malformed-identity",
                dispatch_resolver=subject._dispatch_for_act("implementer"),
            )

        incidents = [
            event for event in state.load(path)["events"]
            if event.get("type") == "worker_malformed"
            and event.get("label") == "double-malformed-identity"
        ]
        self.assertEqual(len(incidents), 2)
        self.assertEqual(
            [(event["family"], event["model"], event["effort"])
             for event in incidents],
            [
                ("codex", "gpt-5.6-sol", "low"),
                ("claude", "claude-opus-5", "high"),
            ],
        )
        self.assertEqual(
            [event["token_usage"] for event in incidents],
            [first_usage, second_usage],
        )
        self.assertEqual(
            [event["fatal"] for event in incidents], [False, True]
        )
        self.assertNotIn("family codex", incidents[1]["error"])
        for expected, event in zip(
            ("first malformed", "second malformed"), incidents
        ):
            with open(
                os.path.join(self.workspace, event["raw_path"]),
                encoding="utf-8",
            ) as handle:
                self.assertEqual(handle.read(), expected)

    def test_double_malformed_same_family_change_keeps_each_identity(self):
        cases = (
            (
                "model",
                {"agent": "codex", "model": "gpt-5.6-luna",
                 "effort": "low"},
            ),
            (
                "effort",
                {"agent": "codex", "model": "gpt-5.6-sol",
                 "effort": "high"},
            ),
        )
        for index, (changed_field, second_entry) in enumerate(cases):
            with self.subTest(changed_field=changed_field):
                workspace = os.path.join(
                    self.tmp.name, "same-family-%d" % index
                )
                config = copy.deepcopy(driver.DEFAULT_CONFIG)
                config["error_classifier"] = False
                path = self.init(workspace=workspace, config=config)
                current = model_profiles.load(self.home, "default")
                current["configurations"]["medium"]["implementer"] = {
                    "agent": "codex", "model": "gpt-5.6-sol",
                    "effort": "low",
                }
                model_profiles.save(self.home, current)

                def select_second(_workspace):
                    edited = model_profiles.load(self.home, "default")
                    edited["configurations"]["medium"]["implementer"] = (
                        copy.deepcopy(second_entry)
                    )
                    model_profiles.save(self.home, edited)

                provider = runners.MockRunner([
                    {
                        "expect_kind": contracts.KIND_IMPLEMENT,
                        "expect_family": "codex",
                        "response": "first malformed",
                        "side_effect": select_second,
                    },
                    {
                        "expect_kind": contracts.KIND_IMPLEMENT,
                        "expect_family": "codex",
                        "response": "second malformed",
                    },
                ])
                subject = self.resolver(path, provider)
                label = "same-family-%s-change" % changed_field
                with self.assertRaises(driver.StopStep):
                    subject._call(
                        "codex",
                        "KIND: implement\nFAMILY: codex\nWORKSPACE: %s\n\n"
                        "double malformed" % workspace,
                        contracts.KIND_IMPLEMENT,
                        label,
                        dispatch_resolver=subject._dispatch_for_act(
                            "implementer"
                        ),
                    )

                incidents = [
                    event for event in state.load(path)["events"]
                    if event.get("type") == "worker_malformed"
                    and event.get("label") == label
                ]
                self.assertEqual(len(incidents), 2)
                self.assertEqual(
                    [(event["family"], event["model"], event["effort"])
                     for event in incidents],
                    [
                        ("codex", "gpt-5.6-sol", "low"),
                        (
                            second_entry["agent"],
                            second_entry["model"],
                            second_entry["effort"],
                        ),
                    ],
                )
                self.assertEqual(
                    [event["fatal"] for event in incidents], [False, True]
                )

    def test_invalid_current_selection_or_profile_fails_without_fallback(self):
        path = self.init()
        mock_runner = runners.MockRunner([])
        d = self.resolver(path, mock_runner)
        self.write_runtime(
            path, "model_profile.json", {"name": "missing", "rigor": "medium"}
        )
        with self.assertRaises(driver.StopStep):
            d._act_profile("fixer")
        self.assertEqual(mock_runner.calls, [])
        self.assertIn("model-profile resolution failed",
                      state.load(path)["failure"]["reason"])

        model_profiles.save(self.home, profile("broken", {"fixer": "claude"}))
        other_workspace = os.path.join(self.tmp.name, "invalid-profile")
        other_path = self.init(workspace=other_workspace)
        other_runner = runners.MockRunner([])
        other = self.resolver(other_path, other_runner)
        self.write_runtime(
            other_path, "model_profile.json",
            {"name": "broken", "rigor": "medium"},
        )
        stored = os.path.join(self.home, "model_profiles", "broken.json")
        with open(stored, "w", encoding="utf-8") as fh:
            fh.write("{not-json")
        with self.assertRaises(driver.StopStep):
            other._act_profile("fixer")
        self.assertEqual(other_runner.calls, [])

    def test_dangling_current_state_links_fail_without_fallback(self):
        path = self.init()
        config = state.load(path)["config"]
        runtime_dir = os.path.dirname(path)

        for filename, message in (
            ("model_profile.json", "selection is unavailable"),
            ("acts.json", "act overrides are unavailable"),
        ):
            with self.subTest(filename=filename):
                link = os.path.join(runtime_dir, filename)
                os.symlink(os.path.join(self.tmp.name, "missing-" + filename),
                           link)
                try:
                    with self.assertRaisesRegex(
                            model_profiles.ModelProfileError, message):
                        driver.resolve_current_act(
                            path, config, self.home, "fixer"
                        )
                finally:
                    os.unlink(link)

    def test_invalid_unrequested_live_act_fails_before_dispatch(self):
        path = self.init()
        for overlay in (
            {"implemeter": "codex"},
            {"review_codex": {"agent": "claude", "model": "x"}},
        ):
            with self.subTest(overlay=overlay):
                self.write_runtime(path, "acts.json", overlay)
                run_state = state.load(path)
                run_state["failure"] = None
                state.save(path, run_state)
                mock_runner = runners.MockRunner([])
                subject = self.resolver(path, mock_runner)
                with self.assertRaises(driver.StopStep):
                    subject._act_profile("fixer")
                self.assertEqual(mock_runner.calls, [])
                self.assertIn(
                    "model-profile resolution failed",
                    state.load(path)["failure"]["reason"],
                )

    def test_stale_binding_and_attribution_data_are_ignored(self):
        path = self.init()
        recorded = state.load(path)
        recorded["model_profile"] = {"name": "missing", "rigor": "high"}
        recorded["units"][0]["model_profile_binding"] = {
            "name": "missing", "hash": "obsolete"
        }
        state.save(path, recorded)
        before_events = list(recorded["events"])

        d = self.resolver(path)
        self.assertEqual(d._act_profile("fixer")[0], "codex")
        after = state.load(path)
        # The resume derivation appends its own binding event (amendment A2)
        # and nothing else: no event is written for the stale binding data,
        # and no recorded event is rewritten.
        self.assertEqual(after["events"][:len(before_events)], before_events)
        self.assertEqual(
            [event["type"] for event in after["events"][len(before_events):]],
            ["staffing_session_bound"],
        )
        self.assertEqual(after["model_profile"]["name"], "missing")

    def test_summary_projection_is_the_router_and_profiles_decide_nothing(self):
        """The rounds-time projection names the NEXT review round's staffing.

        It reads the same router that dispatch will read — the run's
        session, its document's `review` seats and the seat the cycle
        stands on — so the summary and the call agree without any
        intervening change. The model profile and the acts sidecar that
        used to decide this projection now decide nothing.
        """
        model_profiles.ensure_default(self.home)
        model_profiles.save(self.home, profile("other", {
            "review_codex": {"model": "selection-model", "effort": "low"},
        }))
        path = self.init()
        run_state = state.load(path)
        unit = state.current_unit(run_state)
        unit["status"] = state.U_ROUNDS
        unit["family_index"] = 0
        state.save(path, run_state)

        # No session bound yet, so the resolver's default-document fallback
        # answers here exactly as it would answer a dispatch.
        seat_one = driver.resolve_current_review_model(path, self.home)
        self.assertEqual(seat_one[0], "codex")  # `default` review seat 1
        summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertEqual(
            (summary["current_family"], summary["current_model"]), seat_one
        )

        # Neither the profile the run selects nor its acts sidecar moves it.
        self.write_runtime(
            path, "model_profile.json", {"name": "other", "rigor": "medium"}
        )
        self.write_runtime(path, "acts.json", {
            "review_codex": {"model": "override-model", "effort": "medium"}
        })
        summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertEqual(
            (summary["current_family"], summary["current_model"]), seat_one
        )
        self.assertEqual(
            driver.resolve_current_review_model(path, self.home), seat_one
        )

        # Standing on the second seat projects the second seat.
        run_state = state.load(path)
        state.current_unit(run_state)["family_index"] = 1
        state.save(path, run_state)
        seat_two = driver.resolve_current_review_model(path, self.home)
        self.assertEqual(seat_two[0], "claude")  # `default` review seat 2
        self.assertNotEqual(seat_two, seat_one)
        summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertEqual(
            (summary["current_family"], summary["current_model"]), seat_two
        )

        # Past the last assigned seat there is no round to project, and the
        # summary keeps working without one.
        run_state = state.load(path)
        state.current_unit(run_state)["family_index"] = 7
        state.save(path, run_state)
        self.assertIsNone(
            driver.resolve_current_review_model(path, self.home)
        )
        summary = service.load_summary(path, model_profiles_home=self.home)
        self.assertIsNone(summary["current_family"])


if __name__ == "__main__":
    unittest.main()
