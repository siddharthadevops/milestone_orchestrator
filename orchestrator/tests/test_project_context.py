"""PROJECT CONTEXT block + `project_safeguard_seen` (slice 6).

Pins the activation slice's observable contracts: every worker prompt of a
project-bound run carries exactly one PROJECT CONTEXT block (ecosystem map
from the state project block, live reuse-source roles, live-selected
safeguards at operator-amendment authority, the frozen precedence text);
the frozen `project_safeguard_seen {policy_id, version, text[:300]}` ledger
event with first-seen-per-(id, version) dedup and re-record on bump; the
rendered obligation ≡ enforced obligation rule over the recorded grant
universe (Slice 4's seam activated on the same call); the seal attempt's
shared half snapshot; the fail-closed matrix for unreadable/malformed
standing law; and project-less byte-identity.

Stores live in real tempfile directories seeded through Slice 2's
declare/confirm and Slice 3's PolicyStore; project-bound runs are created
through Slice 5's init_run and driven over MockRunner. Policies here are
ILLUSTRATIVE (slice-03's rule): the real reuse-audit content is Slice 10's.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver as drv
from orchestrator import kvstore
from orchestrator import projects
from orchestrator import prompts
from orchestrator import runners
from orchestrator import state as st
from orchestrator import workareas
from orchestrator.tests import test_prompts as tp
from orchestrator.tests.test_driver_mock import (
    append_file,
    finding,
    fix_ok,
    git_init_workspace,
    make_config,
    ok,
    report,
    step,
    triaged,
    write_file,
)
from orchestrator.tests.test_prompts import normalized

GOAL = "Exercise the project context block"


def policy_value(pid="ctx-guard", version=1, enabled=True,
                 kinds=("draft_skeleton",), unit_kinds=("skeleton",),
                 prompt="Enumerate the shared surfaces you checked.",
                 field="context_ack", entry=None, checks=None):
    """An illustrative Slice-3-valid policy; tests override the piece
    under study."""
    if entry is None:
        entry = {"note": {"type": "string"}}
    if checks is None:
        checks = [{"kind": "non_empty", "field": "note"}]
    return {
        "id": pid,
        "version": version,
        "enabled": enabled,
        "scope": {"kinds": list(kinds), "unit_kinds": list(unit_kinds)},
        "prompt": prompt,
        "contract": {
            "field": field,
            "required": True,
            "entry": entry,
            "checks": checks,
        },
    }


def make_context(safeguards=(), reuse_sources=None,
                 primary_path="/eco/repo", additional_paths=("/eco/lib",)):
    """A driver-shaped project_context input for builder-level tests."""
    return {
        "project": "life-prod",
        "work_area": "main",
        "primary": {"path": primary_path, "device": 1},
        "additional": [
            {"path": path, "device": "dev"} for path in additional_paths
        ],
        "reuse_sources": list(reuse_sources) if reuse_sources else None,
        "safeguards": list(safeguards),
    }


def build_all_bound(project_context, amendments=None):
    """All seven builders with the same project context, argument-for-
    argument the calls of test_prompts.build_all (so the None case can be
    compared byte-for-byte against the unmodified convention)."""
    kw = {"project_context": project_context}
    if amendments is not None:
        kw["amendments"] = amendments
    return {
        "draft_skeleton": prompts.build_draft_skeleton(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, **kw
        ),
        "draft_slice_note": prompts.build_draft_slice_note(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.SLICE, "docs/skeleton.md",
            **kw
        ),
        "implement": prompts.build_implement(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.SLICE, "docs/slice-01.md",
            ["make test"], **kw
        ),
        "review_round": prompts.build_review_round(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.UNIT, "docs/slice-01.md",
            [], **kw
        ),
        "delta_review": prompts.build_delta_review(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.UNIT,
            "diff --git a/x b/x\n", [], **kw
        ),
        "seal_half": prompts.build_seal_half(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.UNIT, "docs/slice-01.md",
            [], **kw
        ),
        "fix_findings": prompts.build_fix_findings(
            tp.FAMILY,
            tp.WORKSPACE,
            tp.GOAL,
            tp.UNIT,
            tp.FINDINGS,
            [],
            "claude",
            ["claude", "-p"],
            **kw
        ),
    }


def skeleton_ok(**extra):
    return ok(
        "draft_skeleton",
        artifact="docs/skeleton.md",
        slices=[{"id": 1, "title": "One"}],
        **extra
    )


def skeleton_draft_step(**extra):
    return step(
        "draft_skeleton",
        skeleton_ok(**extra),
        side_effect=write_file("docs/skeleton.md", "# Skeleton\n"),
    )


# ---------------------------------------------------------------------------
# Builder-level: block presence, map content, rendering, authority (AC1-AC3)


class TestBlockAcrossBuilders(unittest.TestCase):
    def test_all_seven_builders_render_exactly_one_block(self):
        built = build_all_bound(make_context(safeguards=[policy_value()]))
        self.assertEqual(sorted(built), sorted(contracts.KINDS))
        for kind, prompt in built.items():
            self.assertEqual(prompt.count("PROJECT CONTEXT"), 1, kind)

    def test_none_input_is_byte_identical_to_unmodified_builders(self):
        self.assertEqual(tp.build_all(), build_all_bound(None))
        for kind, prompt in build_all_bound(None).items():
            self.assertNotIn("PROJECT CONTEXT", prompt, kind)


class TestEcosystemMap(unittest.TestCase):
    def one_prompt(self, ctx):
        return prompts.build_review_round(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.UNIT, "docs/slice-01.md",
            [], project_context=ctx,
        )

    def test_map_names_handles_and_roots(self):
        flat = normalized(self.one_prompt(make_context()))
        self.assertIn(
            "bound to project 'life-prod', work area 'main'", flat
        )
        self.assertIn(
            "PRIMARY ROOT /eco/repo — the repo you execute in", flat
        )
        self.assertIn("ADDITIONAL ROOT /eco/lib — a READ-ONLY grant", flat)

    def test_reuse_source_roles_render_beside_roots(self):
        ctx = make_context(
            reuse_sources=[
                {
                    "root": "/eco/lib",
                    "inventory": "list packages/ subdirs",
                    "registry": "REGISTRY.md rows",
                    "consumption": "submodule + path dep",
                }
            ]
        )
        flat = normalized(self.one_prompt(ctx))
        self.assertIn(
            "- /eco/lib: inventory: list packages/ subdirs | registry: "
            "REGISTRY.md rows | consumption: submodule + path dep",
            flat,
        )

    def test_reuse_source_roles_do_not_create_audit_duties(self):
        ctx = make_context(
            reuse_sources=[
                {
                    "root": "/eco/lib",
                    "inventory": "list packages/ subdirs",
                    "registry": "REGISTRY.md rows",
                    "consumption": "submodule + path dep",
                }
            ]
        )
        flat = normalized(self.one_prompt(ctx))
        self.assertIn("Reuse-source roles recorded for these roots", flat)
        self.assertNotIn("enumerate and cite", flat)
        self.assertNotIn("before inventing", flat)

    def test_reuse_source_roles_render_recorded_descriptor_text(self):
        long_inventory = "inventory-" + (
            "x" * (prompts.AMENDMENT_TEXT_CLIP + 20)
        )
        prompt = self.one_prompt(
            make_context(
                reuse_sources=[
                    {
                        "root": "/eco/lib",
                        "inventory": long_inventory,
                        "registry": "REGISTRY.md rows",
                        "consumption": "submodule + path dep",
                    }
                ]
            )
        )
        self.assertIn(long_inventory, prompt)

    def test_absent_meta_renders_map_without_roles(self):
        prompt = self.one_prompt(make_context(reuse_sources=None))
        self.assertEqual(prompt.count("PROJECT CONTEXT"), 1)
        self.assertNotIn("Reuse-source roles", prompt)
        self.assertNotIn("inventory:", prompt)


class TestSafeguardRendering(unittest.TestCase):
    FULL = policy_value(
        pid="ctx-guard",
        version=3,
        prompt="Check the shared surfaces first.",
        field="context_ack",
        entry={
            "source": {"type": "string"},
            "decision": {"enum": ["adopt", "gap", "reject"]},
            "evidence": {"type": "citation"},
        },
        checks=[
            {"kind": "non_empty", "field": "source"},
            {"kind": "enum", "field": "decision",
             "values": ["adopt", "gap", "reject"]},
            {"kind": "citation_exists", "field": "evidence"},
            {"kind": "dir_listing_matches", "root": "pkgs",
             "match_field": "source"},
        ],
    )

    def one_prompt(self, ctx):
        return prompts.build_implement(
            tp.FAMILY, tp.WORKSPACE, tp.GOAL, tp.SLICE, "docs/slice-01.md",
            ["make test"], project_context=ctx,
        )

    def test_renders_id_version_text_obligation_and_checks(self):
        flat = normalized(self.one_prompt(make_context(safeguards=[self.FULL])))
        self.assertIn("SAFEGUARD ctx-guard v3", flat)
        self.assertIn("Check the shared surfaces first.", flat)
        self.assertIn("REQUIRED OUTPUT FIELD 'context_ack'", flat)
        self.assertIn("source: a string", flat)
        self.assertIn("decision: one of ['adopt', 'gap', 'reject']", flat)
        self.assertIn('evidence: a "<path>:<line>" citation', flat)
        self.assertIn("non_empty(field=source)", flat)
        self.assertIn(
            "enum(field=decision, values=['adopt', 'gap', 'reject'])", flat
        )
        self.assertIn("citation_exists(field=evidence)", flat)
        self.assertIn(
            "dir_listing_matches(match_field=source, root=pkgs)", flat
        )

    def test_long_operator_text_clips_like_amendments(self):
        long_text = "x" * (prompts.AMENDMENT_TEXT_CLIP + 500)
        ctx = make_context(safeguards=[policy_value(prompt=long_text)])
        flat = normalized(self.one_prompt(ctx))
        self.assertIn("x" * (prompts.AMENDMENT_TEXT_CLIP - 3) + "...", flat)
        self.assertNotIn(long_text, flat)

    def test_none_in_scope_renders_map_alone(self):
        prompt = self.one_prompt(make_context(safeguards=[]))
        self.assertEqual(prompt.count("PROJECT CONTEXT"), 1)
        self.assertNotIn("SAFEGUARD", prompt)
        self.assertNotIn(
            "OPERATOR AMENDMENTS WIN", normalized(prompt)
        )


class TestAuthorityAndPrecedence(unittest.TestCase):
    def test_phrases_in_every_kind_with_a_safeguard_in_scope(self):
        built = build_all_bound(make_context(safeguards=[policy_value()]))
        for kind, prompt in built.items():
            flat = normalized(prompt)
            self.assertIn("bind like the TASK itself", flat, kind)
            self.assertIn(
                "a safeguard violation in the reviewed artifact is a "
                "finding, exactly like an amendment violation",
                flat,
                kind,
            )
            self.assertIn(
                "run-scoped OPERATOR AMENDMENTS WIN over project "
                "safeguards",
                flat,
                kind,
            )

    def test_amendments_and_project_blocks_coexist(self):
        built = build_all_bound(
            make_context(safeguards=[policy_value()]),
            amendments=[{"id": "A1", "text": "Prefer streaming writes."}],
        )
        for kind, prompt in built.items():
            self.assertIn("OPERATOR AMENDMENTS (binding", prompt, kind)
            self.assertIn("[A1] Prefer streaming writes.", prompt, kind)
            self.assertEqual(prompt.count("PROJECT CONTEXT"), 1, kind)


# ---------------------------------------------------------------------------
# Driver-level harness


class ProjectRunTestCase(unittest.TestCase):
    PROJECT = "life-prod"
    WORK_AREA = "main"
    EXECUTOR = "local-orchestrator"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-project-ctx-")
        root = self._tmp.name
        self.store_base = os.path.join(root, "stores")
        self.repo = os.path.join(root, "repo")
        self.lib = os.path.join(root, "lib")
        os.makedirs(self.repo)
        os.makedirs(self.lib)
        self.primary = {"path": self.repo, "device": 1}
        self.additional = [{"path": self.lib, "device": "dev-lib"}]
        store = self.work_areas()
        declared = store.declare(
            self.WORK_AREA, self.primary, self.additional, self.EXECUTOR
        )
        self.assertTrue(declared.ok, declared.reason)
        confirmed = store.confirm(
            self.WORK_AREA, self.primary, self.additional, self.EXECUTOR
        )
        self.assertTrue(confirmed.ok, confirmed.reason)

    def tearDown(self):
        self._tmp.cleanup()

    def work_areas(self):
        return workareas.WorkAreaStore(self.store_base, self.PROJECT)

    def policy_store(self):
        return projects.PolicyStore(self.store_base, self.PROJECT)

    def put_policy(self, **kw):
        record = self.policy_store().put(policy_value(**kw))
        self.assertTrue(record["exists?"])
        return record

    def binding(self):
        return {
            "directory": self.store_base,
            "project": self.PROJECT,
            "work_area": self.WORK_AREA,
        }

    def init_bound(self, git=False):
        if git:
            git_init_workspace(self.repo)
        cfg = make_config(git={"enabled": git}, docs_dir="docs")
        return drv.init_run(GOAL, project=self.binding(), config_override=cfg)

    def make_driver(self, path, script):
        return drv.Driver(path, runner=runners.MockRunner(list(script)))

    def drive_steps(self, driver, n):
        for _ in range(n):
            driver.step()

    def seen_events(self, state):
        return [
            e
            for e in state["events"]
            if e["type"] == "project_safeguard_seen"
        ]

    def seen_pairs(self, state):
        return [
            (e["policy_id"], e["version"]) for e in self.seen_events(state)
        ]


# ---------------------------------------------------------------------------
# AC4/AC5: the frozen event payload and the dedup / re-record matrix


class TestSeenEvents(ProjectRunTestCase):
    def test_payload_exactness_and_text_clip(self):
        text = "Standing law. " * 40  # > 300 characters
        self.put_policy(prompt=text)
        path = self.init_bound()
        driver = self.make_driver(
            path, [skeleton_draft_step(context_ack=[{"note": "done"}])]
        )
        driver.step()
        events = self.seen_events(driver.state)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(
            set(event), {"seq", "at", "type", "policy_id", "version", "text"}
        )
        self.assertEqual(event["policy_id"], "ctx-guard")
        self.assertEqual(event["version"], 1)
        self.assertEqual(event["text"], text[:300])
        self.assertEqual(len(self.seen_events(st.load(path))), 1)

    def test_same_pair_rendered_again_appends_nothing(self):
        self.put_policy(kinds=("review_round",), unit_kinds=("skeleton",))
        path = self.init_bound()
        ack = {"context_ack": [{"note": "checked"}]}
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round") | ack,
                     family="codex"),
                step("review_round", report("review_round") | ack,
                     family="claude"),
            ],
        )
        self.drive_steps(driver, 4)  # draft, verify, codex round, claude round
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])

    def test_version_bump_re_records_under_new_version(self):
        self.put_policy(kinds=("review_round",), unit_kinds=("skeleton",))
        path = self.init_bound()
        ack = {"context_ack": [{"note": "checked"}]}
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round") | ack,
                     family="codex"),
                step("review_round", report("review_round") | ack,
                     family="claude"),
            ],
        )
        self.drive_steps(driver, 3)  # draft, verify, codex round
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])
        self.put_policy(
            version=2, kinds=("review_round",), unit_kinds=("skeleton",)
        )
        driver.step()  # claude round renders v2
        self.assertEqual(
            self.seen_pairs(driver.state), [("ctx-guard", 1), ("ctx-guard", 2)]
        )
        flat = normalized(driver.runner.calls[-1][2])
        self.assertIn("SAFEGUARD ctx-guard v2", flat)

    def test_disabled_and_out_of_scope_render_nothing_and_record_zero(self):
        self.put_policy(pid="disabled-p", enabled=False)
        self.put_policy(pid="wrong-kind-p", kinds=("implement",))
        self.put_policy(
            pid="wrong-unit-p",
            kinds=("draft_skeleton", "review_round"),
            unit_kinds=("slice_impl",),
        )
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ],
        )
        self.drive_steps(driver, 4)
        self.assertEqual(self.seen_events(driver.state), [])
        for _family, _kind, prompt in driver.runner.calls:
            self.assertEqual(prompt.count("PROJECT CONTEXT"), 1)
            self.assertNotIn("SAFEGUARD", prompt)

    def test_seal_attempt_records_at_most_one_event_across_halves(self):
        self.put_policy(kinds=("seal_half",), unit_kinds=("skeleton",))
        path = self.init_bound()
        ack = {"context_ack": [{"note": "checked"}]}
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step("seal_half", report("seal_half") | ack, family="codex"),
                step("seal_half", report("seal_half") | ack, family="claude"),
            ],
        )
        # draft, verify, 2 rounds, pre-seal verify, seal attempt
        self.drive_steps(driver, 6)
        unit = driver.state["units"][0]
        self.assertEqual(unit["status"], st.U_SEALED)
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])
        for _family, kind, prompt in driver.runner.calls:
            if kind == "seal_half":
                self.assertIn(
                    "SAFEGUARD ctx-guard v1", normalized(prompt)
                )

    def test_failed_call_still_leaves_seen_event_in_persisted_state(self):
        self.put_policy()
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                step("draft_skeleton", "not json"),
                step("draft_skeleton", "still not json"),
            ],
        )
        driver.step()
        disk = st.load(path)
        self.assertIsNotNone(disk["failure"])
        self.assertEqual(self.seen_pairs(disk), [("ctx-guard", 1)])


# ---------------------------------------------------------------------------
# AC6: rendered obligation ≡ enforced obligation over the recorded universe


class TestEnforcementBinding(ProjectRunTestCase):
    def cite_policy(self, **kw):
        base = {
            "pid": "cite-guard",
            "kinds": ("draft_skeleton",),
            "unit_kinds": ("skeleton",),
            "field": "context_ack",
            "entry": {"evidence": {"type": "citation"}},
            "checks": [{"kind": "citation_exists", "field": "evidence"}],
        }
        base.update(kw)
        return self.put_policy(**base)

    def lib_citation(self, name="shared.py", line=1):
        path = os.path.join(self.lib, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# shared\n")
        return "%s:%d" % (path, line)

    def test_missing_field_gets_exactly_one_repair_then_proceeds(self):
        self.cite_policy()
        citation = self.lib_citation()
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                step("draft_skeleton", skeleton_ok()),  # omits context_ack
                skeleton_draft_step(context_ack=[{"evidence": citation}]),
            ],
        )
        driver.step()
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(len(driver.runner.calls), 2)
        self.assertIn("REPAIR", driver.runner.calls[1][2])
        self.assertIn(
            "context_ack", driver.runner.calls[1][2]
        )  # the repair names the missing slot
        self.assertEqual(
            driver.state["units"][0]["status"], st.U_PRE_REVIEW_VERIFY
        )
        # The repair retry re-renders the same prompt: one seen event only.
        self.assertEqual(self.seen_pairs(driver.state), [("cite-guard", 1)])

    def test_citation_outside_every_recorded_root_fails_twice_then_run(self):
        self.cite_policy()
        outside = os.path.join(self._tmp.name, "outside.py")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("# real but ungranted\n")
        bad = skeleton_ok(context_ack=[{"evidence": outside + ":1"}])
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [step("draft_skeleton", bad), step("draft_skeleton", bad)],
        )
        driver.step()
        failure = driver.state["failure"]
        self.assertIsNotNone(failure)
        self.assertIn("contract-violating output twice", failure["reason"])
        self.assertIn("escapes every granted work-area root",
                      failure["reason"])

    def test_citation_into_additional_root_passes_containment(self):
        self.cite_policy()
        citation = self.lib_citation(name="adopted.py", line=7)
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [skeleton_draft_step(context_ack=[{"evidence": citation}])],
        )
        driver.step()
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(len(driver.runner.calls), 1)
        self.assertEqual(
            driver.state["units"][0]["status"], st.U_PRE_REVIEW_VERIFY
        )

    def test_blocked_output_is_exempt_from_extension_enforcement(self):
        self.cite_policy()
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                step(
                    "draft_skeleton",
                    {
                        "status": "blocked",
                        "kind": "draft_skeleton",
                        "blocked_reason": "cannot proceed",
                    },
                )
            ],
        )
        driver.step()
        failure = driver.state["failure"]
        self.assertIsNotNone(failure)
        self.assertIn("worker blocked: cannot proceed", failure["reason"])
        self.assertNotIn("contract-violating", failure["reason"])
        self.assertEqual(len(driver.runner.calls), 1)  # no repair burned

    def test_descriptor_replacement_mid_run_changes_nothing(self):
        self.cite_policy(kinds=("review_round",))
        citation = self.lib_citation()
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step(
                    "review_round",
                    report("review_round")
                    | {"context_ack": [{"evidence": citation}]},
                    family="codex",
                ),
            ],
        )
        self.drive_steps(driver, 2)  # draft, verify
        # Replace the stored descriptor with different roots, confirmed
        # READY — the run's map and containment universe must not move.
        lib2 = os.path.join(self._tmp.name, "lib2")
        os.makedirs(lib2)
        new_additional = [{"path": lib2, "device": "dev-lib2"}]
        store = self.work_areas()
        declared = store.declare(
            self.WORK_AREA, self.primary, new_additional, self.EXECUTOR
        )
        self.assertTrue(declared.ok, declared.reason)
        confirmed = store.confirm(
            self.WORK_AREA, self.primary, new_additional, self.EXECUTOR
        )
        self.assertTrue(confirmed.ok, confirmed.reason)
        driver.step()  # codex round: original-universe citation passes
        self.assertIsNone(driver.state["failure"])
        prompt = driver.runner.calls[-1][2]
        self.assertIn("ADDITIONAL ROOT %s" % self.lib, prompt)
        self.assertNotIn(lib2, prompt)

    def test_no_obligation_call_validates_base_only(self):
        # Bound run, empty policy store: an output with no extension
        # fields passes exactly the base contract.
        path = self.init_bound()
        driver = self.make_driver(path, [skeleton_draft_step()])
        driver.step()
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(self.seen_events(driver.state), [])


# ---------------------------------------------------------------------------
# AC7: live re-read of law (ordinary calls and seal attempts)


class TestLiveness(ProjectRunTestCase):
    def test_put_mid_run_binds_the_next_call(self):
        path = self.init_bound()  # no policy at init
        ack = {"context_ack": [{"note": "checked"}]}
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round") | ack,
                     family="codex"),
            ],
        )
        self.drive_steps(driver, 2)  # draft, verify
        self.assertNotIn("SAFEGUARD", driver.runner.calls[0][2])
        self.assertEqual(self.seen_events(driver.state), [])
        self.put_policy(kinds=("review_round",), unit_kinds=("skeleton",))
        driver.step()  # codex round renders and records the new law
        self.assertIn(
            "SAFEGUARD ctx-guard v1", normalized(driver.runner.calls[-1][2])
        )
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])

    def test_disable_mid_run_stops_rendering_and_enforcement(self):
        self.put_policy(kinds=("review_round",), unit_kinds=("skeleton",))
        path = self.init_bound()
        ack = {"context_ack": [{"note": "checked"}]}
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round") | ack,
                     family="codex"),
                # claude round: no extension field — passes base validation
                step("review_round", report("review_round"),
                     family="claude"),
            ],
        )
        self.drive_steps(driver, 3)  # draft, verify, codex round
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])
        self.put_policy(
            version=2,
            enabled=False,
            kinds=("review_round",),
            unit_kinds=("skeleton",),
        )
        driver.step()  # claude round: disabled law neither renders nor binds
        self.assertIsNone(driver.state["failure"])
        self.assertNotIn("SAFEGUARD", driver.runner.calls[-1][2])
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])

    def test_edit_between_halves_binds_next_call_not_second_half(self):
        path = self.init_bound()
        ack = {"context_ack": [{"note": "checked"}]}
        scope = {
            "kinds": ("seal_half", "draft_slice_note"),
            "unit_kinds": ("skeleton", "slice_doc"),
        }

        def bump_policy(_workspace):
            self.put_policy(pid="law-p", version=2, **scope)

        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                # First half edits the store mid-attempt (outside the
                # workspace, so no tamper check fires)...
                step("seal_half", report("seal_half") | ack, family="codex",
                     side_effect=bump_policy),
                # ...the second half still runs under the attempt snapshot.
                step("seal_half", report("seal_half") | ack, family="claude"),
                step(
                    "draft_slice_note",
                    ok("draft_slice_note", artifact="docs/slice-01.md")
                    | ack,
                    side_effect=write_file("docs/slice-01.md", "# Note\n"),
                ),
            ],
        )
        # draft, verify, 2 rounds, pre-seal verify
        self.drive_steps(driver, 5)
        # A put AFTER init and rounds binds the next seal attempt's shared
        # half snapshot (live selection at attempt time, not at init).
        self.put_policy(pid="law-p", **scope)
        self.drive_steps(driver, 2)  # seal attempt, next slice-note draft
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(driver.state["units"][0]["status"], st.U_SEALED)
        first_half = normalized(driver.runner.calls[3][2])
        self.assertIn("SAFEGUARD law-p v1", first_half)
        second_half = normalized(driver.runner.calls[4][2])
        self.assertIn("SAFEGUARD law-p v1", second_half)
        self.assertNotIn("law-p v2", second_half)
        note_prompt = normalized(driver.runner.calls[5][2])
        self.assertIn("SAFEGUARD law-p v2", note_prompt)
        self.assertEqual(
            self.seen_pairs(driver.state), [("law-p", 1), ("law-p", 2)]
        )


# ---------------------------------------------------------------------------
# AC8: standing law fails closed, loudly, and resume recovers


class TestFailClosed(ProjectRunTestCase):
    def step_and_expect_failure(self, path, marker, script=()):
        driver = self.make_driver(path, script)
        driver.step()
        failure = driver.state["failure"]
        self.assertIsNotNone(failure)
        self.assertIn(marker, failure["reason"])
        disk = st.load(path)
        self.assertIsNotNone(disk["failure"])
        return driver

    def test_vocabulary_illegal_policy_fails_without_a_worker_call(self):
        self.put_policy(checks=[{"kind": "mystery", "field": "note"}])
        path = self.init_bound()
        driver = self.step_and_expect_failure(path, "unknown check kind")
        self.assertEqual(driver.runner.calls, [])

    def test_malformed_stored_policy_fails_without_a_worker_call(self):
        store = self.policy_store()
        store.envelopes.put(store.keys.policy("bad"), {"nope": 1})
        path = self.init_bound()
        driver = self.step_and_expect_failure(path, "malformed_policy")
        self.assertEqual(driver.runner.calls, [])

    def test_malformed_meta_fails_without_a_worker_call(self):
        wa = self.work_areas()
        wa.envelopes.put(
            wa.keys.work_area_meta(self.WORK_AREA), {"bad": True}
        )
        path = self.init_bound()
        driver = self.step_and_expect_failure(path, "work_area_meta")
        self.assertEqual(driver.runner.calls, [])

    def test_store_removed_after_init_fails_without_a_worker_call(self):
        path = self.init_bound()
        shutil.rmtree(os.path.join(self.store_base, self.PROJECT))
        driver = self.step_and_expect_failure(path, "no readable store")
        self.assertEqual(driver.runner.calls, [])

    def test_kv_file_removed_after_init_fails_without_a_worker_call(self):
        self.put_policy()
        path = self.init_bound()
        os.unlink(
            os.path.join(self.store_base, self.PROJECT, kvstore.STORE_FILENAME)
        )
        driver = self.step_and_expect_failure(path, "no readable KV file")
        self.assertEqual(driver.runner.calls, [])

    def test_policy_selection_io_error_fails_without_a_worker_call(self):
        self.put_policy()
        path = self.init_bound()
        with mock.patch.object(
            kvstore.LocalKVClient,
            "list_entries",
            side_effect=PermissionError("denied"),
        ):
            driver = self.step_and_expect_failure(path, "policy store")
        self.assertIn("unreadable while selecting safeguards",
                      driver.state["failure"]["reason"])
        self.assertEqual(driver.runner.calls, [])

    def test_meta_io_error_fails_without_a_worker_call(self):
        path = self.init_bound()
        original_get = kvstore.LocalKVClient.get

        def raise_for_meta(client, key):
            if "work_area_meta:" in key:
                raise PermissionError("denied")
            return original_get(client, key)

        with mock.patch.object(
            kvstore.LocalKVClient,
            "get",
            autospec=True,
            side_effect=raise_for_meta,
        ):
            driver = self.step_and_expect_failure(path, "work_area_meta")
        self.assertIn("unreadable", driver.state["failure"]["reason"])
        self.assertEqual(driver.runner.calls, [])

    def test_operational_fault_burns_no_repair_and_resume_recovers(self):
        self.put_policy(
            checks=[
                {"kind": "dir_listing_matches", "root": "pkgs",
                 "match_field": "note"}
            ]
        )
        path = self.init_bound()
        driver = self.step_and_expect_failure(
            path,
            "does not exist under the granted work-area roots",
            script=[step("draft_skeleton", skeleton_ok(context_ack=[]))],
        )
        # One worker call, no repair retry: the fault is the environment's.
        self.assertEqual(len(driver.runner.calls), 1)
        # Repair the environment, resume, and the step re-executes fresh.
        os.makedirs(os.path.join(self.repo, "pkgs"))
        state = st.load(path)
        st.resume_run(state)
        st.save(path, state)
        driver2 = self.make_driver(
            path, [skeleton_draft_step(context_ack=[])]
        )
        driver2.step()
        self.assertIsNone(driver2.state["failure"])
        self.assertEqual(
            driver2.state["units"][0]["status"], st.U_PRE_REVIEW_VERIFY
        )
        # Same (id, version) pair as the failed attempt: no duplicate event.
        self.assertEqual(self.seen_pairs(driver2.state), [("ctx-guard", 1)])

    def test_seal_half_verifier_error_fails_attempt_without_repair(self):
        os.makedirs(os.path.join(self.repo, "pkgs"))
        with open(os.path.join(self.repo, "pkgs", "shared"),
                  "w", encoding="utf-8") as fh:
            fh.write("ready\n")
        self.put_policy(
            kinds=("seal_half",),
            unit_kinds=("skeleton",),
            field="context_ack",
            entry={"note": {"type": "string"}},
            checks=[
                {"kind": "dir_listing_matches", "root": "pkgs",
                 "match_field": "note"}
            ],
        )

        def remove_listing_root(_workspace):
            shutil.rmtree(os.path.join(self.repo, "pkgs"))

        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
                step(
                    "seal_half",
                    report("seal_half") | {
                        "context_ack": [{"note": "shared"}]
                    },
                    family="codex",
                    side_effect=remove_listing_root,
                ),
            ],
        )

        self.drive_steps(driver, 6)
        failure = driver.state["failure"]
        self.assertIsNotNone(failure)
        self.assertIn(
            "seal_half call: project standing-law fault", failure["reason"]
        )
        self.assertIn(
            "does not exist under the granted work-area roots",
            failure["reason"],
        )
        unit = driver.state["units"][0]
        self.assertEqual(unit["status"], st.U_FAILED)
        self.assertEqual(unit["failed_from"], st.U_SEALING)
        self.assertEqual(unit["seals"], [])
        self.assertEqual(
            [(family, kind) for family, kind, _prompt in driver.runner.calls],
            [
                ("codex", "draft_skeleton"),
                ("codex", "review_round"),
                ("claude", "review_round"),
                ("codex", "seal_half"),
            ],
        )
        self.assertEqual(self.seen_pairs(driver.state), [("ctx-guard", 1)])


# ---------------------------------------------------------------------------
# AC9: project-less inertness (driver half; builder half above)


class TestProjectlessInertness(ProjectRunTestCase):
    def test_unbound_run_sees_no_block_no_events_no_enforcement(self):
        # A populated store somewhere on disk means nothing to a run
        # without a binding.
        self.put_policy()
        ws = os.path.join(self._tmp.name, "plain-ws")
        os.makedirs(ws)
        path = drv.init_run(
            GOAL, ws,
            config=make_config(git={"enabled": False}, docs_dir="docs"),
        )
        driver = self.make_driver(
            path,
            [
                skeleton_draft_step(),
                step("review_round", report("review_round"), family="codex"),
                step("review_round", report("review_round"), family="claude"),
            ],
        )
        self.drive_steps(driver, 4)
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(self.seen_events(driver.state), [])
        for _family, _kind, prompt in driver.runner.calls:
            self.assertNotIn("PROJECT CONTEXT", prompt)


# ---------------------------------------------------------------------------
# AC10 + AC1 end-to-end: a no-policy project across all seven worker kinds


class TestNoPolicyProjectEndToEnd(ProjectRunTestCase):
    def test_full_lifecycle_renders_map_in_all_seven_kinds(self):
        meta = self.work_areas().put_meta(
            self.WORK_AREA,
            {
                "reuse_sources": [
                    {
                        "root": self.lib,
                        "inventory": "list packages/",
                        "registry": "REGISTRY.md",
                        "consumption": "path dep",
                    }
                ]
            },
        )
        self.assertTrue(meta["exists?"])
        path = self.init_bound(git=True)
        script = [
            skeleton_draft_step(),
            step("review_round",
                 report("review_round", [finding("F1", "content gap")]),
                 family="codex"),
            step("fix_findings",
                 fix_ok([triaged("F1", "fixed")],
                        files_changed=["docs/skeleton.md"]),
                 side_effect=append_file("docs/skeleton.md", "more\n")),
            step("delta_review", report("delta_review")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
            step("draft_slice_note",
                 ok("draft_slice_note", artifact="docs/slice-01.md"),
                 side_effect=write_file("docs/slice-01.md", "# Note\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
            step("implement",
                 ok("implement", files_changed=["main.py"],
                    suite_command=None),
                 side_effect=write_file("main.py", "print('hi')\n")),
            step("review_round", report("review_round"), family="codex"),
            step("review_round", report("review_round"), family="claude"),
            step("seal_half", report("seal_half"), family="codex"),
            step("seal_half", report("seal_half"), family="claude"),
        ]
        driver = self.make_driver(path, script)
        for _ in range(60):
            action = drv.decide(driver.state)
            if action.type in (drv.A_DONE, drv.A_FAILED):
                break
            driver.step()
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(driver.run(), 0)
        self.assertEqual(driver.state["milestone"]["status"], st.M_CLOSED)
        kinds_called = {kind for _f, kind, _p in driver.runner.calls}
        self.assertEqual(kinds_called, set(contracts.KINDS))
        for _family, kind, prompt in driver.runner.calls:
            flat = normalized(prompt)
            self.assertEqual(prompt.count("PROJECT CONTEXT"), 1, kind)
            self.assertIn("PRIMARY ROOT %s" % self.repo, flat, kind)
            self.assertIn(
                "ADDITIONAL ROOT %s — a READ-ONLY grant" % self.lib,
                flat,
                kind,
            )
            self.assertIn("inventory: list packages/", flat, kind)
            self.assertNotIn("SAFEGUARD", prompt, kind)
            self.assertNotIn("enumerate and cite", flat, kind)
            self.assertNotIn("before inventing", flat, kind)
        self.assertEqual(self.seen_events(driver.state), [])


if __name__ == "__main__":
    unittest.main()
