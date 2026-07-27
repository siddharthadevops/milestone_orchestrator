import tempfile
import unittest

from orchestrator import contracts
from orchestrator import kvstore
from orchestrator import projects
from orchestrator import state
from orchestrator import workareas


def valid_policy(policy_id="lpc-reuse-audit", version=1, enabled=True):
    return {
        "id": policy_id,
        "version": version,
        "enabled": enabled,
        "scope": {
            "kinds": [
                contracts.KIND_DRAFT_SKELETON,
                contracts.KIND_DRAFT_SLICE_NOTE,
            ],
            "unit_kinds": [state.UNIT_SKELETON, state.UNIT_SLICE_DOC],
        },
        "prompt": "Enumerate reuse sources before inventing local mechanics.",
        "contract": {
            "field": "reuse_audit",
            "required": True,
            "entry": {
                "source": {"type": "string"},
                "package": {"type": "string"},
                "decision": {"enum": ["adopt", "gap", "reject"]},
                "evidence": {"type": "citation"},
            },
            "checks": [{"kind": "future_slice_verifier", "field": "evidence"}],
        },
    }


class ProjectStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-projects-test-")
        self.home = self._tmp.name
        self.store = projects.PolicyStore(self.home, "project-a")

    def tearDown(self):
        self._tmp.cleanup()

    def key(self, policy_id):
        return kvstore.policy_key(policy_id)


class TestPolicyValidation(ProjectStoreTestCase):
    def test_valid_policy_round_trips_with_envelope_revision(self):
        first = self.store.put(valid_policy(version=7))
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["value"]["version"], 7)

        read = self.store.read("lpc-reuse-audit")
        self.assertTrue(read.ok)
        self.assertEqual(read.value, first["value"])

        second = self.store.put(valid_policy(version=7, enabled=False))
        self.assertEqual(second["revision"], 2)
        self.assertEqual(second["value"]["version"], 7)
        self.assertFalse(second["value"]["enabled"])

    def test_rejects_top_level_key_drift_and_bad_domains_without_writing(self):
        invalids = []
        missing = valid_policy("missing")
        missing.pop("prompt")
        invalids.append(("missing", missing))
        extra = valid_policy("extra")
        extra["extra"] = True
        invalids.append(("extra", extra))
        bool_version = valid_policy("bool-version")
        bool_version["version"] = True
        invalids.append(("bool-version", bool_version))
        zero_version = valid_policy("zero-version")
        zero_version["version"] = 0
        invalids.append(("zero-version", zero_version))
        negative_version = valid_policy("negative-version")
        negative_version["version"] = -1
        invalids.append(("negative-version", negative_version))
        bad_enabled = valid_policy("bad-enabled")
        bad_enabled["enabled"] = 1
        invalids.append(("bad-enabled", bad_enabled))
        string_version = valid_policy("string-version")
        string_version["version"] = "1"
        invalids.append(("string-version", string_version))
        float_version = valid_policy("float-version")
        float_version["version"] = 1.5
        invalids.append(("float-version", float_version))
        blank_prompt = valid_policy("blank-prompt")
        blank_prompt["prompt"] = " "
        invalids.append(("blank-prompt", blank_prompt))

        for policy_id, policy in invalids:
            with self.subTest(policy_id=policy_id):
                with self.assertRaises(projects.PolicyValidationError):
                    self.store.put(policy)
                self.assertEqual(
                    self.store.read(policy_id).reason, projects.UNKNOWN
                )

        for policy_id in ("has/slash", " ", "has\x01control"):
            with self.subTest(policy_id=policy_id):
                bad_id = valid_policy(policy_id)
                with self.assertRaises(projects.PolicyValidationError):
                    self.store.put(bad_id)

    def test_scope_uses_existing_worker_and_unit_vocabularies(self):
        policy = valid_policy("scope")
        self.assertTrue(
            projects.policy_matches(
                policy, contracts.KIND_DRAFT_SKELETON, state.UNIT_SKELETON
            )
        )
        self.assertFalse(
            projects.policy_matches(
                policy, contracts.KIND_IMPLEMENT, state.UNIT_SLICE_IMPL
            )
        )
        self.assertFalse(
            projects.policy_matches(
                policy, contracts.KIND_DRAFT_SKELETON, state.UNIT_SLICE_IMPL
            )
        )
        self.assertFalse(
            projects.policy_matches(
                policy, contracts.KIND_IMPLEMENT, state.UNIT_SLICE_DOC
            )
        )
        disabled = valid_policy("disabled", enabled=False)
        self.assertFalse(
            projects.policy_matches(
                disabled, contracts.KIND_DRAFT_SKELETON, state.UNIT_SKELETON
            )
        )

        invalids = []
        missing_key = valid_policy("missing-scope")
        missing_key["scope"] = {"kinds": [contracts.KIND_IMPLEMENT]}
        invalids.append(missing_key)
        extra_key = valid_policy("extra-scope")
        extra_key["scope"]["extra"] = True
        invalids.append(extra_key)
        empty_list = valid_policy("empty-scope")
        empty_list["scope"] = {"kinds": [], "unit_kinds": [state.UNIT_SKELETON]}
        invalids.append(empty_list)
        unknown_kind = valid_policy("unknown-kind")
        unknown_kind["scope"]["kinds"] = ["planning"]
        invalids.append(unknown_kind)
        unknown_unit = valid_policy("unknown-unit")
        unknown_unit["scope"]["unit_kinds"] = ["document"]
        invalids.append(unknown_unit)
        non_list = valid_policy("non-list")
        non_list["scope"]["unit_kinds"] = state.UNIT_SKELETON
        invalids.append(non_list)
        non_list_kinds = valid_policy("non-list-kinds")
        non_list_kinds["scope"]["kinds"] = contracts.KIND_IMPLEMENT
        invalids.append(non_list_kinds)

        for policy in invalids:
            with self.subTest(policy=policy["id"]):
                with self.assertRaises(projects.PolicyValidationError):
                    self.store.put(policy)

    def test_new_policy_rejects_retired_seal_worker_scope(self):
        policy = valid_policy("retired-new")
        policy["scope"]["kinds"] = ["seal_half"]
        with self.assertRaises(projects.PolicyValidationError):
            self.store.put(policy)

    def test_contract_envelope_is_structural_only(self):
        accepted = valid_policy("unknown-check-kind")
        accepted["contract"]["checks"] = [{"kind": "not_slice_three_vocabulary"}]
        self.store.put(accepted)
        self.assertTrue(self.store.read("unknown-check-kind").ok)

        invalids = []
        for missing_key in ("field", "required", "entry", "checks"):
            missing = valid_policy("missing-contract-%s" % missing_key)
            missing["contract"].pop(missing_key)
            invalids.append(missing)
        required_false = valid_policy("required-false")
        required_false["contract"]["required"] = False
        invalids.append(required_false)
        blank_field = valid_policy("blank-field")
        blank_field["contract"]["field"] = ""
        invalids.append(blank_field)
        non_string_field = valid_policy("non-string-field")
        non_string_field["contract"]["field"] = 1
        invalids.append(non_string_field)
        empty_entry = valid_policy("empty-entry")
        empty_entry["contract"]["entry"] = {}
        invalids.append(empty_entry)
        non_object_entry = valid_policy("non-object-entry")
        non_object_entry["contract"]["entry"] = []
        invalids.append(non_object_entry)
        bad_entry_spec = valid_policy("bad-entry-spec")
        bad_entry_spec["contract"]["entry"] = {"evidence": "citation"}
        invalids.append(bad_entry_spec)
        non_list_checks = valid_policy("non-list-checks")
        non_list_checks["contract"]["checks"] = {"kind": "future_slice_verifier"}
        invalids.append(non_list_checks)
        bad_checks = valid_policy("bad-checks")
        bad_checks["contract"]["checks"] = [{"field": "evidence"}]
        invalids.append(bad_checks)
        extra_key = valid_policy("extra-contract-key")
        extra_key["contract"]["extra"] = True
        invalids.append(extra_key)

        for policy in invalids:
            with self.subTest(policy=policy["id"]):
                with self.assertRaises(projects.PolicyValidationError):
                    self.store.put(policy)


class TestPolicyStore(ProjectStoreTestCase):
    def test_stored_retired_scope_is_read_migrated_without_reactivation(self):
        mixed = valid_policy("mixed-old")
        mixed["scope"]["kinds"] = [
            contracts.KIND_REVIEW_ROUND, "seal_half"
        ]
        seal_only = valid_policy("seal-only-old")
        seal_only["scope"]["kinds"] = ["seal_half"]
        self.store.envelopes.put(self.key("mixed-old"), mixed)
        self.store.envelopes.put(self.key("seal-only-old"), seal_only)

        listed = self.store.list_policies()
        self.assertTrue(listed.ok)
        by_id = {policy["id"]: policy for policy in listed.value}
        self.assertEqual(
            by_id["mixed-old"]["scope"]["kinds"],
            [contracts.KIND_REVIEW_ROUND],
        )
        self.assertEqual(by_id["seal-only-old"]["scope"]["kinds"], [])

        matched = self.store.in_scope(
            contracts.KIND_REVIEW_ROUND, state.UNIT_SKELETON
        )
        self.assertTrue(matched.ok)
        self.assertEqual([p["id"] for p in matched.value], ["mixed-old"])

    def test_read_reports_unknown_and_malformed_without_repairing(self):
        self.assertEqual(self.store.read("missing").reason, projects.UNKNOWN)

        bad = valid_policy("bad")
        bad["id"] = "other"
        written = self.store.envelopes.put(self.key("bad"), bad)
        self.assertEqual(self.store.read("bad").reason, projects.MALFORMED)
        self.assertEqual(self.store.envelopes.read(self.key("bad")), written)

        malformed = valid_policy("malformed")
        malformed["scope"]["kinds"] = ["not-a-kind"]
        self.store.envelopes.put(self.key("malformed"), malformed)
        self.assertEqual(
            self.store.read("malformed").reason, projects.MALFORMED
        )

    def test_list_is_key_order_skips_tombstones_and_fails_closed(self):
        self.store.put(valid_policy("b"))
        self.store.put(valid_policy("a"))
        self.store.put(valid_policy("gone"))
        self.store.delete("gone")

        listed = self.store.list_policies()
        self.assertTrue(listed.ok)
        self.assertEqual([policy["id"] for policy in listed.value], ["a", "b"])

        bad = valid_policy("broken")
        bad["id"] = "other"
        self.store.envelopes.put(self.key("broken"), bad)
        self.assertEqual(self.store.list_policies().reason, projects.MALFORMED)

    def test_in_scope_returns_enabled_policies_only(self):
        self.store.put(valid_policy("enabled"))
        self.store.put(valid_policy("disabled", enabled=False))
        implement = valid_policy("implement")
        implement["scope"] = {
            "kinds": [contracts.KIND_IMPLEMENT],
            "unit_kinds": [state.UNIT_SLICE_IMPL],
        }
        self.store.put(implement)

        matched = self.store.in_scope(
            contracts.KIND_DRAFT_SLICE_NOTE, state.UNIT_SLICE_DOC
        )
        self.assertTrue(matched.ok)
        self.assertEqual([policy["id"] for policy in matched.value], ["enabled"])

        none = self.store.in_scope(contracts.KIND_REVIEW_ROUND, state.UNIT_SLICE_DOC)
        self.assertTrue(none.ok)
        self.assertEqual(none.value, [])

    def test_project_scopes_share_backing_with_workareas_but_not_each_other(self):
        project_a = projects.PolicyStore(self.home, "scope-a")
        project_b = projects.PolicyStore(self.home, "scope-b")
        project_a.put(valid_policy("same"))
        project_b.put(valid_policy("same", version=2))

        self.assertEqual(project_a.read("same").value["version"], 1)
        self.assertEqual(project_b.read("same").value["version"], 2)
        self.assertIn(kvstore.STORE_FILENAME, project_a.client.path)
        self.assertEqual(
            project_a.client.list_entries(prefix="milestone_orchestrator/policy:")[
                "items"
            ],
            [{"key": kvstore.policy_key("same"), "rev": 1}],
        )


class TestProjectRecordAssembly(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-project-record-test-")
        self.home = self._tmp.name
        self.project = projects.ProjectStore(self.home, "project-a")

    def tearDown(self):
        self._tmp.cleanup()

    def test_assembles_work_areas_policy_and_optional_defaults(self):
        self.project.work_areas.declare(
            "main",
            {"path": "/repo", "device": 1},
            [{"path": "/repo/lib", "device": "dev"}],
            "exec",
            display_name="Main",
        )
        self.project.policy.put(valid_policy("reuse"))

        without_defaults = self.project.read()
        self.assertTrue(without_defaults.ok)
        self.assertNotIn("defaults", without_defaults.value)
        self.assertEqual(
            [record["name"] for record in without_defaults.value["work_areas"]],
            ["main"],
        )
        self.assertEqual(
            [policy["id"] for policy in without_defaults.value["policy"]],
            ["reuse"],
        )

        with_defaults = self.project.read(
            defaults={"docs_dir": "implementation", "acts": {"codex": "gpt"}}
        )
        self.assertTrue(with_defaults.ok)
        self.assertEqual(
            with_defaults.value["defaults"],
            {"docs_dir": "implementation", "acts": {"codex": "gpt"}},
        )

    def test_rejects_non_object_defaults(self):
        self.assertEqual(
            self.project.read(defaults=["not", "an", "object"]).reason,
            projects.INVALID_DEFAULTS,
        )
        self.assertEqual(
            self.project.read(defaults={1: "not string keyed"}).reason,
            projects.INVALID_DEFAULTS,
        )

    def test_fails_closed_on_malformed_work_area_or_policy(self):
        self.project.work_areas.client.put(
            kvstore.raw_work_area_key("bad"), {"bad": "value"}
        )
        self.assertEqual(self.project.read().reason, workareas.MALFORMED)

        clean = projects.ProjectStore(self.home, "policy-bad")
        bad = valid_policy("bad")
        bad["id"] = "other"
        clean.policy.envelopes.put(kvstore.policy_key("bad"), bad)
        self.assertEqual(clean.read().reason, projects.MALFORMED)


if __name__ == "__main__":
    unittest.main()
