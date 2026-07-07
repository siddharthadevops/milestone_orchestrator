"""Built-in reuse-audit safeguard template (slice 9).

Pins the final slice's concrete load on the already-sealed project policy
machinery: the two fixed policy objects, strict parameterization, the fixed
enable route, ordinary-law behavior after enablement, and live planning /
review enforcement through the driver path.
"""

import os
import urllib.request
import unittest

from orchestrator import contracts
from orchestrator import kvstore
from orchestrator import projects
from orchestrator import reuse_audit
from orchestrator import state as st
from orchestrator import verifiers
from orchestrator.tests.test_driver_mock import ok, report, step, write_file
from orchestrator.tests.test_project_context import ProjectRunTestCase
from orchestrator.tests.test_prompts import normalized
from orchestrator.tests.test_service_projects import (
    PROJECT,
    ProjectsServiceTestCase,
    policy_object,
)


PARAMS = {
    "source": "sentinel-source",
    "inventory": "sentinel-inventory",
    "registry": "sentinel-registry",
    "version": 7,
}


class TestReuseAuditTemplate(unittest.TestCase):
    def policies(self, params=None):
        return reuse_audit.instantiate(params or PARAMS)

    def test_pair_is_sealed_valid_and_compile_clean(self):
        planning, review = self.policies()
        self.assertEqual(
            [planning["id"], review["id"]],
            ["reuse-audit", "reuse-audit-review"],
        )
        self.assertEqual(
            planning["scope"],
            {
                "kinds": ["draft_skeleton", "draft_slice_note"],
                "unit_kinds": ["skeleton", "slice_doc"],
            },
        )
        self.assertEqual(
            review["scope"],
            {
                "kinds": list(contracts.REPORT_KINDS),
                "unit_kinds": ["skeleton", "slice_doc"],
            },
        )
        self.assertEqual(planning["contract"]["field"], "reuse_audit")
        self.assertEqual(review["contract"]["field"], "reuse_audit_review")
        self.assertEqual(
            planning["contract"]["entry"]["decision"]["enum"],
            ["adopt", "gap", "reject"],
        )
        self.assertEqual(
            review["contract"]["entry"]["decision"]["enum"],
            ["concur", "dissent"],
        )
        for policy in (planning, review):
            self.assertEqual(projects.validate_policy_value(policy), policy)
            self.assertEqual(
                policy["contract"]["checks"],
                [
                    {"kind": "citation_exists", "field": "evidence"},
                    {
                        "kind": "dir_listing_matches",
                        "root": PARAMS["inventory"],
                        "match_field": "package",
                    },
                ],
            )
        exts = verifiers.compile_extensions([planning, review])
        self.assertEqual([ext.field for ext in exts],
                         ["reuse_audit", "reuse_audit_review"])

    def test_parameter_validation_has_no_baked_in_defaults(self):
        defaulted = self.policies({
            "source": "S",
            "inventory": "I",
            "registry": "R",
        })
        self.assertEqual([p["version"] for p in defaulted], [1, 1])
        flat = normalized("\n".join(p["prompt"] for p in defaulted))
        for sentinel in ("S", "I", "R"):
            self.assertIn(sentinel, flat)
        self.assertNotIn("life_product_components", flat)

        valid = {"source": "S", "inventory": "I", "registry": "R"}
        bad_bodies = [
            None,
            {},
            {"source": "S", "inventory": "I"},
            dict(valid, source=" "),
            dict(valid, inventory=""),
            dict(valid, registry=5),
            dict(valid, version=0),
            dict(valid, version=True),
            dict(valid, extra="nope"),
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                with self.assertRaises(reuse_audit.TemplateParamError):
                    reuse_audit.instantiate(body)

    def test_prompt_phrases_are_pinned(self):
        planning, review = self.policies()
        pflat = normalized(planning["prompt"])
        for phrase in (
            "sentinel-source",
            "sentinel-inventory",
            "sentinel-registry",
            "enumerate the inventory",
            "read the registry rows",
            "one adopt/gap/reject decision per package",
            "file:line evidence",
            "audit as a TABLE",
            "P1 content gap",
            "consumer-needs channel, never to local reimplementation",
        ):
            self.assertIn(phrase, pflat)

        rflat = normalized(review["prompt"])
        for phrase in (
            "sentinel-source",
            "sentinel-inventory",
            "sentinel-registry",
            "READ-ONLY",
            "one concur/dissent entry per audited package",
            "your own file:line citation",
            "Every dissent must back a finding",
            "P1 duplication finding",
        ):
            self.assertIn(phrase, rflat)

    def test_readme_pins_example_and_version_default(self):
        readme = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                              "README.md")
        with open(readme, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("POST /api/projects/<slug>/policies/reuse-audit", text)
        self.assertIn("Omit `version` to use `1`.", text)
        self.assertIn("Illustration only, not a baked-in ecosystem", text)
        self.assertIn("V1 supports one audited source per project", text)
        self.assertIn("work_area_meta.reuse_sources", text)


class TestReuseAuditService(ProjectsServiceTestCase):
    def setUp(self):
        super().setUp()
        self.create_project()

    def reuse_path(self, slug=PROJECT):
        return self.project_path(slug, "policies") + "/reuse-audit"

    def policies_path(self, slug=PROJECT):
        return self.project_path(slug, "policies")

    def entry_policies(self, slug=PROJECT):
        return self.expect(
            200, "GET", self.project_path(slug)
        )["project"]["policy"]

    def store_bytes(self, slug=PROJECT):
        with open(self.kv_file(slug), "rb") as fh:
            return fh.read()

    def post_template(self, payload=None, slug=PROJECT):
        return self.expect(
            200, "POST", self.reuse_path(slug), payload or PARAMS
        )["policies"]

    def test_enable_route_writes_the_pair_and_no_control_revision(self):
        body = self.expect(200, "POST", self.reuse_path(), PARAMS)
        self.assertEqual(set(body), {"ok", "policies"})
        expected = reuse_audit.instantiate(PARAMS)
        self.assertEqual(body["policies"], expected)
        self.assertEqual(self.entry_policies(), expected)

    def test_route_refusals_write_nothing(self):
        self.refused(400, "invalid_project", "POST",
                     self.reuse_path(slug="a/b"), PARAMS)
        self.refused(404, "unknown_project", "POST",
                     self.reuse_path(slug="ghost"), PARAMS)
        self.refused(400, "invalid_template_params", "POST",
                     self.reuse_path(), {"source": "S"})
        self.assertEqual(self.entry_policies(), [])

        os.unlink(self.kv_file())
        self.refused(500, "missing_store", "POST",
                     self.reuse_path(), PARAMS)
        self.assertFalse(os.path.exists(self.kv_file()))

    def test_invalid_envelope_at_either_id_blocks_without_half_write(self):
        for policy_id in (
            reuse_audit.PLANNING_POLICY_ID,
            reuse_audit.REVIEW_POLICY_ID,
        ):
            slug = "bad-" + policy_id
            self.create_project(slug=slug)
            key = kvstore.KeyBuilder().policy(policy_id)
            kvstore.LocalKVClient(self.store_dir(slug)).put(
                key, {"revision": 3, "deleted?": False}
            )
            with self.subTest(policy_id=policy_id):
                before = self.store_bytes(slug)
                self.refused(500, "malformed_store", "POST",
                             self.reuse_path(slug), PARAMS)
                self.assertEqual(self.store_bytes(slug), before)

    def test_malformed_values_are_healed_by_reenable(self):
        key = kvstore.KeyBuilder().policy(reuse_audit.PLANNING_POLICY_ID)
        self.envelopes().put(key, {"not": "a policy"})
        self.refused(500, "malformed_policy", "GET", self.project_path())
        expected = reuse_audit.instantiate(PARAMS)
        self.assertEqual(self.post_template(), expected)
        self.assertEqual(self.entry_policies(), expected)

    def test_reenable_is_idempotent_and_overwrites_wholesale(self):
        first = self.post_template()
        self.assertEqual(self.post_template(), first)

        changed = dict(PARAMS, source="new-source", version=5)
        self.assertEqual(
            [p["version"] for p in self.post_template(changed)], [5, 5]
        )
        self.assertIn("new-source", self.entry_policies()[0]["prompt"])

        slug = "overwrite"
        self.create_project(slug=slug)
        hand_authored = policy_object(reuse_audit.PLANNING_POLICY_ID)
        self.expect(200, "POST", self.policies_path(slug), hand_authored)
        expected = reuse_audit.instantiate(PARAMS)
        self.assertEqual(self.post_template(slug=slug), expected)
        self.assertEqual(self.entry_policies(slug), expected)

    def test_delete_then_reenable_restores_the_pair(self):
        self.post_template()
        delete = (
            self.policies_path()
            + "?id="
            + self.q(reuse_audit.REVIEW_POLICY_ID)
        )
        self.expect(200, "DELETE", delete)
        self.assertEqual(
            [p["id"] for p in self.entry_policies()],
            [reuse_audit.PLANNING_POLICY_ID],
        )
        self.post_template()
        self.assertEqual(
            [p["id"] for p in self.entry_policies()],
            [reuse_audit.PLANNING_POLICY_ID, reuse_audit.REVIEW_POLICY_ID],
        )

    def test_pair_is_ordinary_policy_after_enable(self):
        self.post_template()
        planning = self.entry_policies()[0]
        flipped = dict(planning, enabled=False)
        body = self.expect(200, "POST", self.policies_path(), flipped)
        self.assertEqual((body["policy"]["version"], body["policy"]["enabled"]),
                         (PARAMS["version"], False))
        self.refused(409, "project_in_use", "DELETE", self.project_path())

        for policy_id in (
            reuse_audit.PLANNING_POLICY_ID,
            reuse_audit.REVIEW_POLICY_ID,
        ):
            self.expect(
                200,
                "DELETE",
                self.policies_path() + "?id=" + self.q(policy_id),
            )
        self.expect(200, "DELETE", self.project_path())

    def test_served_panel_carries_the_enable_affordance(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as resp:
            text = resp.read().decode("utf-8")
        self.assertIn("Enable reuse-audit", text)
        self.assertIn("/policies/reuse-audit", text)
        self.assertIn("reuseAuditParamsSeed", text)


class ReuseAuditRunTestCase(ProjectRunTestCase):
    PACKAGES = ("chat", "timeline")

    def setUp(self):
        super().setUp()
        self.inventory = "reuse_pkgs"
        self.registry = "REGISTRY.md"
        for package in self.PACKAGES:
            path = os.path.join(self.lib, self.inventory, package)
            os.makedirs(path)
            with open(os.path.join(path, "README.md"), "w",
                      encoding="utf-8") as fh:
                fh.write("%s package\n" % package)
        with open(os.path.join(self.lib, self.registry), "w",
                  encoding="utf-8") as fh:
            fh.write("registry rows\n")
        self.params = {
            "source": "lpc",
            "inventory": self.inventory,
            "registry": self.registry,
            "version": 1,
        }
        self.policies = reuse_audit.instantiate(self.params)
        for policy in self.policies:
            self.policy_store().put(policy)

    def put_template(self, **overrides):
        params = dict(self.params)
        params.update(overrides)
        self.policies = reuse_audit.instantiate(params)
        for policy in self.policies:
            self.policy_store().put(policy)
        return self.policies

    def planning_audit(self, packages=None, decision="adopt", evidence=None):
        packages = self.PACKAGES if packages is None else packages
        rows = []
        for package in packages:
            cite = evidence or "%s/%s/README.md:1" % (
                self.inventory, package
            )
            rows.append({
                "source": "lpc",
                "package": package,
                "decision": decision,
                "evidence": cite,
            })
        return rows

    def review_audit(self, packages=None, decision="concur"):
        return [
            dict(row, decision=decision)
            for row in self.planning_audit(packages=packages)
        ]

    def skeleton_output(self, audit=None):
        extra = {} if audit is None else {"reuse_audit": audit}
        return ok(
            "draft_skeleton",
            artifact="docs/skeleton.md",
            slices=[{"id": 1, "title": "One"}],
            **extra
        )

    def skeleton_step(self, audit=None):
        return step(
            "draft_skeleton",
            self.skeleton_output(audit),
            side_effect=write_file("docs/skeleton.md", "# Skeleton\n"),
        )

    def note_output(self, audit=None):
        extra = {} if audit is None else {"reuse_audit": audit}
        return ok("draft_slice_note", artifact="docs/slice-01.md", **extra)

    def note_step(self, audit=None):
        return step(
            "draft_slice_note",
            self.note_output(audit),
            side_effect=write_file("docs/slice-01.md", "# Note\n"),
        )

    def seen_pairs(self, state):
        return [
            (e["policy_id"], e["version"])
            for e in state["events"]
            if e["type"] == "project_safeguard_seen"
        ]


class TestReuseAuditDriverPlanning(ReuseAuditRunTestCase):
    def test_under_enumeration_gets_one_repair_then_proceeds(self):
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                self.skeleton_step(audit=self.planning_audit(("chat",))),
                self.skeleton_step(audit=self.planning_audit()),
            ],
        )
        driver.step()
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(len(driver.runner.calls), 2)
        first_prompt = normalized(driver.runner.calls[0][2])
        self.assertIn("SAFEGUARD reuse-audit v1", first_prompt)
        self.assertIn("P1 content gap", first_prompt)
        self.assertIn("REQUIRED OUTPUT FIELD 'reuse_audit'", first_prompt)
        self.assertIn(
            "dir_listing_matches(match_field=package, root=reuse_pkgs)",
            first_prompt,
        )
        self.assertIn("REPAIR", driver.runner.calls[1][2])
        self.assertIn("timeline", driver.runner.calls[1][2])
        self.assertEqual(
            driver.state["units"][0]["status"], st.U_PRE_REVIEW_VERIFY
        )
        self.assertEqual(self.seen_pairs(driver.state), [("reuse-audit", 1)])

    def test_second_under_enumeration_fails_the_call(self):
        path = self.init_bound()
        bad = self.skeleton_step(audit=self.planning_audit(("chat",)))
        driver = self.make_driver(path, [bad, bad])
        driver.step()
        self.assertIsNotNone(driver.state["failure"])
        self.assertIn(
            "contract-violating output twice",
            driver.state["failure"]["reason"],
        )
        self.assertIn("timeline", driver.state["failure"]["reason"])
        self.assertEqual(len(driver.runner.calls), 2)

    def test_bad_planning_values_fail_mechanically(self):
        ext = verifiers.compile_policy(self.policies[0])
        roots = [self.repo, self.lib]
        outside = os.path.join(self._tmp.name, "outside.md")
        with open(outside, "w", encoding="utf-8") as fh:
            fh.write("outside\n")
        cases = [
            ("missing field", {}),
            ("invented package", {
                "reuse_audit": self.planning_audit(self.PACKAGES + ("ghost",))
            }),
            ("bad enum", {
                "reuse_audit": self.planning_audit(decision="maybe")
            }),
            ("ill shaped citation", {
                "reuse_audit": self.planning_audit(evidence="no-line")
            }),
            ("escaping citation", {
                "reuse_audit": self.planning_audit(
                    evidence=outside + ":1"
                )
            }),
        ]
        for label, extra in cases:
            with self.subTest(label=label):
                with self.assertRaises(contracts.ContractError):
                    verifiers.validate_merged_output(
                        self.skeleton_output() | extra,
                        "draft_skeleton",
                        [ext],
                        roots,
                    )

    def test_blocked_output_is_exempt(self):
        ext = verifiers.compile_policy(self.policies[0])
        blocked = {
            "status": "blocked",
            "kind": "draft_skeleton",
            "blocked_reason": "operator stopped the run",
        }
        self.assertEqual(
            verifiers.validate_merged_output(
                blocked, "draft_skeleton", [ext], [self.repo, self.lib]
            ),
            blocked,
        )

    def test_slice_note_draft_and_version_bump_rerecord_end_to_end(self):
        path = self.init_bound()

        def bump_template(_workspace):
            self.put_template(version=2)

        driver = self.make_driver(
            path,
            [
                self.skeleton_step(audit=self.planning_audit()),
                step(
                    "review_round",
                    report("review_round")
                    | {"reuse_audit_review": self.review_audit()},
                    family="codex",
                ),
                step(
                    "review_round",
                    report("review_round")
                    | {"reuse_audit_review": self.review_audit()},
                    family="claude",
                ),
                step(
                    "seal_half",
                    report("seal_half")
                    | {"reuse_audit_review": self.review_audit()},
                    family="codex",
                ),
                step(
                    "seal_half",
                    report("seal_half")
                    | {"reuse_audit_review": self.review_audit()},
                    family="claude",
                    side_effect=bump_template,
                ),
                self.note_step(audit=self.planning_audit(("chat",))),
                self.note_step(audit=self.planning_audit()),
                step(
                    "review_round",
                    report("review_round")
                    | {"reuse_audit_review": self.review_audit()},
                    family="codex",
                ),
            ],
        )
        self.drive_steps(driver, 9)

        self.assertIsNone(driver.state["failure"])
        seal_prompt = normalized(driver.runner.calls[3][2])
        self.assertIn("SAFEGUARD reuse-audit-review v1", seal_prompt)
        note_prompt = normalized(driver.runner.calls[5][2])
        self.assertIn("KIND: draft_slice_note", note_prompt)
        self.assertIn("SAFEGUARD reuse-audit v2", note_prompt)
        repair_prompt = normalized(driver.runner.calls[6][2])
        self.assertIn("REPAIR", repair_prompt)
        self.assertIn("timeline", repair_prompt)
        review_prompt = normalized(driver.runner.calls[7][2])
        self.assertIn("SAFEGUARD reuse-audit-review v2", review_prompt)
        self.assertEqual(
            self.seen_pairs(driver.state),
            [
                ("reuse-audit", 1),
                ("reuse-audit-review", 1),
                ("reuse-audit", 2),
                ("reuse-audit-review", 2),
            ],
        )

    def assert_inventory_fault(self, inventory, marker):
        self.put_template(inventory=inventory)
        path = self.init_bound()
        driver = self.make_driver(path, [self.skeleton_step(audit=[])])
        driver.step()
        self.assertIsNotNone(driver.state["failure"])
        self.assertIn(
            "project standing-law fault", driver.state["failure"]["reason"]
        )
        self.assertIn(marker, driver.state["failure"]["reason"])
        self.assertEqual(len(driver.runner.calls), 1)
        self.assertNotIn("REPAIR", driver.runner.calls[0][2])

    def test_missing_inventory_fails_as_operational_fault(self):
        self.assert_inventory_fault(
            "missing_pkgs",
            "does not exist under the granted work-area roots",
        )

    def test_escaping_inventory_fails_as_config_fault(self):
        outside = os.path.join(self._tmp.name, "outside_pkgs")
        os.makedirs(outside)
        self.assert_inventory_fault(
            outside,
            "resolves outside every granted work-area root",
        )


class TestReuseAuditDriverReview(ReuseAuditRunTestCase):
    def test_review_round_binds_review_field_and_dissent_is_mechanical_ok(self):
        path = self.init_bound()
        driver = self.make_driver(
            path,
            [
                self.skeleton_step(audit=self.planning_audit()),
                step(
                    "review_round",
                    report("review_round")
                    | {"reuse_audit_review": self.review_audit(
                        decision="dissent"
                    )},
                    family="codex",
                ),
            ],
        )
        self.drive_steps(driver, 3)
        self.assertIsNone(driver.state["failure"])
        self.assertEqual(len(driver.runner.calls), 2)
        review_prompt = normalized(driver.runner.calls[-1][2])
        self.assertIn("SAFEGUARD reuse-audit-review v1", review_prompt)
        self.assertIn("REQUIRED OUTPUT FIELD 'reuse_audit_review'",
                      review_prompt)
        self.assertIn("one concur/dissent entry per audited package",
                      review_prompt)
        self.assertIn("P1 duplication finding", review_prompt)
        self.assertEqual(
            self.seen_pairs(driver.state),
            [("reuse-audit", 1), ("reuse-audit-review", 1)],
        )

    def test_review_policy_scope_excludes_implementation_calls(self):
        store = self.policy_store()
        self.assertEqual(
            [p["id"] for p in store.in_scope(
                "review_round", "slice_doc"
            ).value],
            [reuse_audit.REVIEW_POLICY_ID],
        )
        self.assertEqual(store.in_scope("delta_review", "slice_doc").value,
                         [self.policies[1]])
        self.assertEqual(store.in_scope("seal_half", "slice_doc").value,
                         [self.policies[1]])
        self.assertEqual(store.in_scope("implement", "slice_impl").value, [])
        self.assertEqual(store.in_scope("fix_findings", "slice_impl").value,
                         [])


if __name__ == "__main__":
    unittest.main()
