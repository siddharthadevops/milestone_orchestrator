"""Pinning tests for the closed verifier vocabulary and the contract-
extension merge (Slice 4).

Covers, mapped to the slice's acceptance criteria:
- entry type-spec compile legality and the config-error matrix (AC1)
- type-exact worker-value validation and the exact entry key-set rule (AC2)
- check-kind compile legality and its config-error matrix (AC3)
- each verifier's pass/fail semantics against real tempdir roots (AC4-AC8),
  including the worker/config/operational error split and relative-path
  ambiguity across multiple granted roots
- field collisions against the reserved keys DERIVED from contracts (AC9)
- merge presence/shape, the blocked exemption, the out-of-scope no-op (AC10)
- enforcement inside call_worker's existing repair-retry path via
  MockRunner (AC11)

Every filesystem check runs against a real tempfile.TemporaryDirectory;
nothing is written into the repository.
"""

import os
import tempfile
import unittest

from orchestrator import contracts
from orchestrator import verifiers
from orchestrator.runners import MockRunner, WorkerProtocolError, call_worker


def make_policy(policy_id="lpc-reuse-audit", version=1, enabled=True,
                kinds=None, unit_kinds=None, prompt="Audit ecosystem reuse.",
                field="reuse_audit", entry=None, checks=None):
    """A Slice-3-valid policy value; tests override the piece under study."""
    if entry is None:
        entry = {
            "package": {"type": "string"},
            "decision": {"enum": ["adopt", "gap", "reject"]},
            "evidence": {"type": "citation"},
        }
    return {
        "id": policy_id,
        "version": version,
        "enabled": enabled,
        "scope": {
            "kinds": kinds or ["implement"],
            "unit_kinds": unit_kinds or ["slice_impl"],
        },
        "prompt": prompt,
        "contract": {
            "field": field,
            "required": True,
            "entry": entry,
            "checks": checks or [],
        },
    }


def implement_output(**extra):
    out = {"status": "ok", "kind": "implement", "files_changed": []}
    out.update(extra)
    return out


def make_prompt(kind):
    """Prompt with the same header layout prompts.py emits."""
    return "KIND: %s\nFAMILY: codex\nWORKSPACE: /tmp/ws\n\nDo the work." % kind


class TestErrorClasses(unittest.TestCase):
    """The config/operational classes sit OUTSIDE the repairable exception
    family (ValueError/ContractError) and are distinct from each other."""

    def test_hierarchy(self):
        self.assertTrue(
            issubclass(verifiers.PolicyConfigError, verifiers.VerifierError)
        )
        self.assertTrue(
            issubclass(verifiers.OperationalError, verifiers.VerifierError)
        )
        self.assertFalse(issubclass(verifiers.VerifierError, ValueError))
        self.assertFalse(
            issubclass(verifiers.VerifierError, contracts.ContractError)
        )

    def test_config_and_operational_are_distinct(self):
        self.assertFalse(
            issubclass(verifiers.OperationalError, verifiers.PolicyConfigError)
        )
        self.assertFalse(
            issubclass(verifiers.PolicyConfigError, verifiers.OperationalError)
        )


class TestTypeSpecCompile(unittest.TestCase):
    """AC1: the closed entry type-spec vocabulary at compile time."""

    def test_all_three_tokens_compile(self):
        ext = verifiers.compile_policy(
            make_policy(
                entry={
                    "s": {"type": "string"},
                    "c": {"type": "citation"},
                    "e": {"enum": ["adopt", "gap", "reject"]},
                }
            )
        )
        self.assertIsInstance(ext, verifiers.CompiledExtension)
        self.assertEqual(ext.policy_id, "lpc-reuse-audit")
        self.assertEqual(ext.policy_version, 1)
        self.assertEqual(ext.field, "reuse_audit")
        self.assertEqual(set(ext.entry), {"s", "c", "e"})
        self.assertEqual(ext.checks, ())

    def assert_spec_rejected(self, spec):
        with self.assertRaises(verifiers.PolicyConfigError) as cm:
            verifiers.compile_policy(make_policy(entry={"v": spec}))
        # A config error is the operator's, never a repairable worker error.
        self.assertNotIsInstance(cm.exception, ValueError)

    def test_unknown_type_is_config_error(self):
        self.assert_spec_rejected({"type": "integer"})
        self.assert_spec_rejected({"type": True})

    def test_malformed_enum_is_config_error(self):
        self.assert_spec_rejected({"enum": "adopt"})
        self.assert_spec_rejected({"enum": []})
        self.assert_spec_rejected({"enum": ["adopt", 1]})
        self.assert_spec_rejected({"enum": ["adopt", True]})

    def test_both_type_and_enum_is_config_error(self):
        self.assert_spec_rejected({"type": "string", "enum": ["a"]})

    def test_extra_or_missing_keys_is_config_error(self):
        self.assert_spec_rejected({"type": "string", "maxLength": 3})
        self.assert_spec_rejected({})

    def test_structurally_invalid_policy_is_config_error(self):
        # The compiler consumes Slice 3's validator as the single structural
        # source; its rejection surfaces as a config error, not a
        # PolicyValidationError (which is a repairable-family ValueError).
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_policy({"id": "lpc-reuse-audit"})
        bad = make_policy()
        bad["contract"]["required"] = False
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_policy(bad)


class TestCheckCompile(unittest.TestCase):
    """AC3: the closed check vocabulary and per-kind exact parameters."""

    ENTRY = {
        "package": {"type": "string"},
        "decision": {"enum": ["adopt", "gap", "reject"]},
        "evidence": {"type": "citation"},
    }

    def compile_checks(self, checks):
        return verifiers.compile_policy(
            make_policy(entry=dict(self.ENTRY), checks=checks)
        )

    def assert_checks_rejected(self, checks):
        with self.assertRaises(verifiers.PolicyConfigError) as cm:
            self.compile_checks(checks)
        self.assertNotIsInstance(cm.exception, ValueError)

    def test_all_five_kinds_compile(self):
        ext = self.compile_checks(
            [
                {"kind": "non_empty", "field": "package"},
                {"kind": "enum", "field": "decision",
                 "values": ["adopt", "gap", "reject"]},
                {"kind": "path_exists", "field": "package"},
                {"kind": "citation_exists", "field": "evidence"},
                {"kind": "dir_listing_matches", "root": "pkgs",
                 "match_field": "package"},
            ]
        )
        self.assertEqual(len(ext.checks), 5)

    def test_unknown_kind_is_config_error(self):
        self.assert_checks_rejected([{"kind": "regex", "field": "package"}])
        self.assert_checks_rejected([{"kind": "shell", "field": "package"}])

    def test_missing_or_extra_params_is_config_error(self):
        self.assert_checks_rejected([{"kind": "non_empty"}])
        self.assert_checks_rejected(
            [{"kind": "non_empty", "field": "package", "extra": 1}]
        )
        self.assert_checks_rejected([{"kind": "enum", "field": "decision"}])
        self.assert_checks_rejected(
            [{"kind": "dir_listing_matches", "root": "pkgs"}]
        )
        self.assert_checks_rejected(
            [{"kind": "citation_exists", "root": "pkgs",
              "match_field": "package"}]
        )

    def test_undeclared_field_is_config_error(self):
        self.assert_checks_rejected([{"kind": "path_exists", "field": "ghost"}])
        self.assert_checks_rejected(
            [{"kind": "dir_listing_matches", "root": "pkgs",
              "match_field": "ghost"}]
        )
        self.assert_checks_rejected([{"kind": "non_empty", "field": 5}])

    def test_bad_enum_values_is_config_error(self):
        self.assert_checks_rejected(
            [{"kind": "enum", "field": "decision", "values": "adopt"}]
        )
        self.assert_checks_rejected(
            [{"kind": "enum", "field": "decision", "values": []}]
        )
        self.assert_checks_rejected(
            [{"kind": "enum", "field": "decision", "values": ["adopt", 1]}]
        )

    def test_bad_dir_root_is_config_error(self):
        self.assert_checks_rejected(
            [{"kind": "dir_listing_matches", "root": "",
              "match_field": "package"}]
        )
        self.assert_checks_rejected(
            [{"kind": "dir_listing_matches", "root": 5,
              "match_field": "package"}]
        )


class TestFieldCollisions(unittest.TestCase):
    """AC9: reserved-key and duplicate-field collisions, derived from
    contracts as the single source."""

    def test_base_kind_reserved_key_collides(self):
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_policy(
                make_policy(field="findings", kinds=["review_round"],
                            unit_kinds=["slice_impl"])
            )
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_policy(
                make_policy(field="artifact", kinds=["draft_skeleton"],
                            unit_kinds=["skeleton"])
            )
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_policy(
                make_policy(field="suite_command", kinds=["fix_findings"])
            )

    def test_common_keys_collide_for_every_kind(self):
        for key in ("status", "kind", "blocked_reason", "notes"):
            with self.assertRaises(verifiers.PolicyConfigError):
                verifiers.compile_policy(make_policy(field=key))

    def test_collision_is_per_kind(self):
        # "artifact" is reserved for draft kinds only: the same field
        # compiles for implement scope — the set is derived per kind.
        ext = verifiers.compile_policy(
            make_policy(field="artifact", kinds=["implement"])
        )
        self.assertEqual(ext.field, "artifact")

    def test_reserved_keys_come_from_contracts_not_a_relisting(self):
        # Changing the exposed protocol keys changes what collides: the
        # compiler derives from contracts.KIND_OUTPUT_KEYS, it never
        # re-lists the names.
        policy = make_policy()  # field "reuse_audit", scope implement
        verifiers.compile_policy(policy)  # compiles today
        original = contracts.KIND_OUTPUT_KEYS[contracts.KIND_IMPLEMENT]
        contracts.KIND_OUTPUT_KEYS[contracts.KIND_IMPLEMENT] = (
            original | {"reuse_audit"}
        )
        try:
            with self.assertRaises(verifiers.PolicyConfigError):
                verifiers.compile_policy(policy)
        finally:
            contracts.KIND_OUTPUT_KEYS[contracts.KIND_IMPLEMENT] = original
        verifiers.compile_policy(policy)  # and compiles again

    def test_reserved_output_keys_content(self):
        self.assertEqual(
            contracts.reserved_output_keys("implement"),
            {"status", "kind", "blocked_reason", "notes", "gaps",
             "files_changed", "suite_command"},
        )
        self.assertIn("artifact", contracts.reserved_output_keys("draft_skeleton"))
        self.assertIn("findings", contracts.reserved_output_keys("seal_half"))
        with self.assertRaises(contracts.ContractError):
            contracts.reserved_output_keys("bogus_kind")

    def test_duplicate_field_across_policies_is_config_error(self):
        p1 = make_policy(policy_id="policy-a")
        p2 = make_policy(policy_id="policy-b")
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.compile_extensions([p1, p2])
        ext1 = verifiers.compile_policy(p1)
        ext2 = verifiers.compile_policy(p2)
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.validate_merged_output(
                implement_output(reuse_audit=[]), "implement",
                [ext1, ext2], None,
            )

    def test_compile_extensions_returns_distinct_extensions(self):
        exts = verifiers.compile_extensions(
            [
                make_policy(policy_id="policy-a", field="reuse_audit"),
                make_policy(policy_id="policy-b", field="dep_audit"),
            ]
        )
        self.assertEqual([e.field for e in exts], ["reuse_audit", "dep_audit"])


class TestEntryShapeValidation(unittest.TestCase):
    """AC2: type-exact worker-value validation and the exact key-set rule."""

    def compile_single(self, spec):
        return verifiers.compile_policy(make_policy(entry={"v": spec}))

    def validate_value(self, ext, value):
        obj = implement_output(reuse_audit=[{"v": value}])
        return verifiers.validate_merged_output(obj, "implement", [ext], None)

    def assert_value_rejected(self, ext, value):
        with self.assertRaises(contracts.ContractError):
            self.validate_value(ext, value)

    def test_string_spec_is_type_exact(self):
        ext = self.compile_single({"type": "string"})
        self.validate_value(ext, "life_product_chat")
        self.validate_value(ext, "")  # a string; blankness is non_empty's job
        for bad in (True, False, 1, 1.5, [], {}, None):
            self.assert_value_rejected(ext, bad)

    def test_citation_spec_shape(self):
        ext = self.compile_single({"type": "citation"})
        self.validate_value(ext, "apps/lib/chat.ex:120")
        # Split on the LAST colon: the path half may itself contain colons.
        self.validate_value(ext, "a:b/mod.py:3")
        for bad in (
            "no-line",          # no colon
            "path.py:",         # empty line half
            ":12",              # empty path half
            "path.py:0",        # zero line
            "path.py:-3",       # sign is not a digit
            "path.py:+3",
            "path.py:3.5",
            "path.py: 3",       # spaces are not digits
            "path.py:three",
            12,                 # non-string
            True,
            None,
        ):
            self.assert_value_rejected(ext, bad)

    def test_citation_spec_is_structural_only(self):
        # No filesystem access: a well-shaped citation to a path that does
        # not exist passes the SHAPE check (existence is citation_exists').
        ext = self.compile_single({"type": "citation"})
        self.validate_value(ext, "ghost/nowhere.py:1")

    def test_enum_spec_is_type_exact(self):
        ext = self.compile_single({"enum": ["adopt", "gap", "reject"]})
        self.validate_value(ext, "adopt")
        for bad in ("invent", "", True, 1, None, ["adopt"]):
            self.assert_value_rejected(ext, bad)

    def test_entry_key_set_must_match_exactly(self):
        ext = verifiers.compile_policy(
            make_policy(entry={"a": {"type": "string"},
                               "b": {"type": "string"}})
        )
        ok = implement_output(reuse_audit=[{"a": "x", "b": "y"}])
        verifiers.validate_merged_output(ok, "implement", [ext], None)
        for bad_entry in (
            {"a": "x"},                      # missing key
            {"a": "x", "b": "y", "c": "z"},  # extra key
            "not-an-object",
            ["a", "b"],
            5,
        ):
            with self.assertRaises(contracts.ContractError):
                verifiers.validate_merged_output(
                    implement_output(reuse_audit=[bad_entry]),
                    "implement", [ext], None,
                )


class FilesystemCase(unittest.TestCase):
    """Two granted roots with real content, for the filesystem checks."""

    def setUp(self):
        self._tmp_a = tempfile.TemporaryDirectory()
        self._tmp_b = tempfile.TemporaryDirectory()
        self._tmp_out = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_a.cleanup)
        self.addCleanup(self._tmp_b.cleanup)
        self.addCleanup(self._tmp_out.cleanup)
        self.root_a = self._tmp_a.name
        self.root_b = self._tmp_b.name
        self.outside = self._tmp_out.name
        self.roots = [self.root_a, self.root_b]
        # root_a: pkg/mod.py plus a listing target directory
        os.makedirs(os.path.join(self.root_a, "pkg"))
        self.mod_py = os.path.join(self.root_a, "pkg", "mod.py")
        with open(self.mod_py, "w", encoding="utf-8") as fh:
            fh.write("line one\nline two\n")
        # the same relative path under BOTH roots (ambiguity fixture)
        for root in (self.root_a, self.root_b):
            with open(os.path.join(root, "shared.txt"), "w",
                      encoding="utf-8") as fh:
                fh.write("shared\n")
        # a real file outside every granted root (escape fixture)
        self.outside_file = os.path.join(self.outside, "loot.txt")
        with open(self.outside_file, "w", encoding="utf-8") as fh:
            fh.write("outside\n")

    def string_ext(self, checks, field_name="package"):
        return verifiers.compile_policy(
            make_policy(entry={field_name: {"type": "string"}}, checks=checks)
        )

    def validate_entries(self, ext, entries):
        obj = implement_output(reuse_audit=entries)
        return verifiers.validate_merged_output(
            obj, "implement", [ext], self.roots
        )


class TestNonEmptyCheck(FilesystemCase):
    """AC4: non_empty forbids the empty enumeration and blank values."""

    def setUp(self):
        super().setUp()
        self.ext = self.string_ext([{"kind": "non_empty", "field": "package"}])

    def test_empty_list_fails(self):
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(self.ext, [])
        self.assertNotIsInstance(cm.exception, verifiers.VerifierError)

    def test_blank_value_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": "   "}])
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(
                self.ext, [{"package": "life"}, {"package": ""}]
            )

    def test_non_blank_entries_pass(self):
        self.validate_entries(
            self.ext, [{"package": "life"}, {"package": "chat"}]
        )


class TestEnumCheck(FilesystemCase):
    """AC5: enum(field, values) is type-exact over every entry."""

    def setUp(self):
        super().setUp()
        # Declared as a plain string so the CHECK (not the type-spec)
        # decides membership.
        self.ext = self.string_ext(
            [{"kind": "enum", "field": "package",
              "values": ["adopt", "gap", "reject"]}]
        )

    def test_members_pass(self):
        self.validate_entries(
            self.ext, [{"package": "adopt"}, {"package": "reject"}]
        )

    def test_out_of_set_value_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(
                self.ext, [{"package": "adopt"}, {"package": "maybe"}]
            )

    def test_wrong_typed_value_fails(self):
        # The bool is stopped as a ContractError either way: the string
        # type-spec rejects it at shape time, and the check itself is
        # type-exact for any caller that reaches it.
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": True}])

    def test_empty_list_passes_vacuously(self):
        # Per-entry checks quantify over entries; pairing with non_empty is
        # the safeguard author's job when emptiness must be forbidden.
        self.validate_entries(self.ext, [])


class TestPathExistsCheck(FilesystemCase):
    """AC6: existence, root containment, and relative-path ambiguity."""

    def setUp(self):
        super().setUp()
        self.ext = self.string_ext(
            [{"kind": "path_exists", "field": "package"}]
        )

    def test_absolute_path_inside_root_passes(self):
        self.validate_entries(self.ext, [{"package": self.mod_py}])

    def test_relative_path_under_exactly_one_root_passes(self):
        self.validate_entries(self.ext, [{"package": "pkg/mod.py"}])

    def test_nonexistent_path_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": "pkg/ghost.py"}])

    def test_escaping_path_is_a_worker_contract_error(self):
        # The file EXISTS but outside every granted root: worker error
        # (repairable), never a config error.
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(self.ext, [{"package": self.outside_file}])
        self.assertNotIsInstance(cm.exception, verifiers.VerifierError)

    def test_relative_escape_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": "../escape.txt"}])

    def test_ambiguous_relative_path_fails(self):
        # shared.txt exists under BOTH granted roots.
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(self.ext, [{"package": "shared.txt"}])
        self.assertIn("more than one", str(cm.exception))


class TestCitationExistsCheck(FilesystemCase):
    """AC7: path-half existence; the line number is NOT verified."""

    def setUp(self):
        super().setUp()
        self.ext = self.string_ext(
            [{"kind": "citation_exists", "field": "package"}]
        )

    def test_existing_path_half_passes(self):
        self.validate_entries(self.ext, [{"package": "pkg/mod.py:2"}])
        self.validate_entries(
            self.ext, [{"package": "%s:1" % self.mod_py}]
        )

    def test_line_number_is_not_verified(self):
        # mod.py has two lines; line 999 still passes — the goal pins only
        # "the path half of file:line exists".
        self.validate_entries(self.ext, [{"package": "pkg/mod.py:999"}])

    def test_ill_shaped_citation_fails(self):
        # Declared {"type": "string"}, so the CHECK does the parsing here.
        for bad in ("pkg/mod.py", "pkg/mod.py:", "pkg/mod.py:0", ":3"):
            with self.assertRaises(contracts.ContractError):
                self.validate_entries(self.ext, [{"package": bad}])

    def test_nonexistent_path_half_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": "pkg/ghost.py:3"}])

    def test_escaping_path_half_is_a_worker_contract_error(self):
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(
                self.ext, [{"package": "%s:1" % self.outside_file}]
            )
        self.assertNotIsInstance(cm.exception, verifiers.VerifierError)

    def test_ambiguous_relative_path_half_fails(self):
        with self.assertRaises(contracts.ContractError):
            self.validate_entries(self.ext, [{"package": "shared.txt:1"}])


class TestDirListingMatchesCheck(FilesystemCase):
    """AC8: set equality against a real directory listing, with the
    config/operational split on the operator-authored root."""

    def setUp(self):
        super().setUp()
        self.listing_dir = os.path.join(self.root_a, "pkgs")
        os.makedirs(os.path.join(self.listing_dir, "life_product_chat"))
        # nested content proves the listing does not recurse
        with open(
            os.path.join(self.listing_dir, "life_product_chat", "x.ex"),
            "w", encoding="utf-8",
        ) as fh:
            fh.write("nested\n")
        with open(os.path.join(self.listing_dir, "README.md"), "w",
                  encoding="utf-8") as fh:
            fh.write("readme\n")
        with open(os.path.join(self.listing_dir, ".hidden"), "w",
                  encoding="utf-8") as fh:
            fh.write("dot\n")
        os.symlink("README.md", os.path.join(self.listing_dir, "lnk"))
        self.children = {"life_product_chat", "README.md", ".hidden", "lnk"}
        self.ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "pkgs",
              "match_field": "package"}]
        )

    def entries_for(self, names):
        return [{"package": name} for name in sorted(names)]

    def test_exact_enumeration_passes(self):
        self.validate_entries(self.ext, self.entries_for(self.children))

    def test_under_enumeration_fails(self):
        # The M26/M27 failure: a child of the reuse source not enumerated.
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(
                self.ext,
                self.entries_for(self.children - {"life_product_chat"}),
            )
        self.assertIn("life_product_chat", str(cm.exception))

    def test_over_enumeration_fails(self):
        with self.assertRaises(contracts.ContractError) as cm:
            self.validate_entries(
                self.ext, self.entries_for(self.children | {"ghost_pkg"})
            )
        self.assertIn("ghost_pkg", str(cm.exception))

    def test_empty_directory_and_empty_enumeration_pass(self):
        os.makedirs(os.path.join(self.root_a, "empty_dir"))
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "empty_dir",
              "match_field": "package"}]
        )
        self.validate_entries(ext, [])

    def test_escaping_operator_root_is_config_error(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": self.outside,
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            self.validate_entries(ext, self.entries_for({"loot.txt"}))
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "../somewhere",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            self.validate_entries(ext, [])

    def test_ambiguous_relative_operator_root_is_config_error(self):
        for root in self.roots:
            os.makedirs(os.path.join(root, "dup"))
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "dup",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            self.validate_entries(ext, [])

    def test_absent_root_is_operational_not_worker_error(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.OperationalError) as cm:
            self.validate_entries(ext, self.entries_for({"anything"}))
        self.assertNotIsInstance(cm.exception, contracts.ContractError)
        self.assertNotIsInstance(cm.exception, ValueError)
        self.assertNotIsInstance(cm.exception, verifiers.PolicyConfigError)

    def test_non_directory_root_is_operational(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "pkgs/README.md",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.OperationalError):
            self.validate_entries(ext, [])


class TestMergedOutputValidation(FilesystemCase):
    """AC10: presence/shape enforcement, the blocked exemption, and the
    out-of-scope no-op."""

    def setUp(self):
        super().setUp()
        self.ext = verifiers.compile_policy(make_policy())

    def ok_entries(self):
        return [
            {"package": "life_product_chat", "decision": "adopt",
             "evidence": "pkg/mod.py:1"}
        ]

    def test_missing_extension_field_is_contract_error(self):
        with self.assertRaises(contracts.ContractError) as cm:
            verifiers.validate_merged_output(
                implement_output(), "implement", [self.ext], self.roots
            )
        msg = str(cm.exception)
        self.assertIn("reuse_audit", msg)
        self.assertIn("lpc-reuse-audit", msg)

    def test_operator_root_fault_preempts_missing_extension_field(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": self.outside,
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.validate_merged_output(
                implement_output(), "implement", [ext], self.roots
            )

        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.OperationalError):
            verifiers.validate_merged_output(
                implement_output(), "implement", [ext], self.roots
            )

    def test_operator_root_fault_preempts_base_contract_error(self):
        bad = {"status": "ok", "kind": "implement"}

        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": self.outside,
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.validate_merged_output(
                dict(bad), "implement", [ext], self.roots
            )

        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        with self.assertRaises(verifiers.OperationalError):
            verifiers.validate_merged_output(
                dict(bad), "implement", [ext], self.roots
            )

    def test_non_list_value_is_contract_error(self):
        for bad in ("x", {"a": 1}, True, 5, None):
            with self.assertRaises(contracts.ContractError):
                verifiers.validate_merged_output(
                    implement_output(reuse_audit=bad), "implement",
                    [self.ext], self.roots,
                )

    def test_valid_output_is_returned_unchanged(self):
        obj = implement_output(reuse_audit=self.ok_entries())
        out = verifiers.validate_merged_output(
            obj, "implement", [self.ext], self.roots
        )
        self.assertIs(out, obj)

    def test_blocked_output_is_exempt(self):
        obj = {"status": "blocked", "kind": "implement",
               "blocked_reason": "missing dependency"}
        out = verifiers.validate_merged_output(
            obj, "implement", [self.ext], self.roots
        )
        self.assertIs(out, obj)

    def test_blocked_output_is_exempt_from_operator_root_preflight(self):
        obj = {"status": "blocked", "kind": "implement",
               "blocked_reason": "missing reuse source"}
        for root in (self.outside, "nope"):
            ext = self.string_ext(
                [{"kind": "dir_listing_matches", "root": root,
                  "match_field": "package"}]
            )
            out = verifiers.validate_merged_output(
                obj, "implement", [ext], self.roots
            )
            self.assertIs(out, obj)

    def _gap_output(self):
        return {"status": "gap", "kind": "implement",
                "gaps": [{"classification": "fits_remodel",
                          "missing_or_conflict": "a field no earlier step "
                                                 "records",
                          "where": "docs/slice-01.md:12",
                          "forced_decision": "record the field upstream",
                          "plain": "the design never produces a needed field",
                          "example": "the scorer reads a field never written"}]}

    def test_gap_output_is_exempt(self):
        # A gap finishes nothing (no artifact to audit), so — like blocked —
        # it is exempt from extension enforcement. Without the exemption a
        # project-bound builder's gap fails validation and never routes.
        out = verifiers.validate_merged_output(
            self._gap_output(), "implement", [self.ext], self.roots
        )
        self.assertEqual(out["status"], "gap")

    def test_gap_output_is_exempt_from_operator_root_preflight(self):
        for root in (self.outside, "nope"):
            ext = self.string_ext(
                [{"kind": "dir_listing_matches", "root": root,
                  "match_field": "package"}]
            )
            out = verifiers.validate_merged_output(
                self._gap_output(), "implement", [ext], self.roots
            )
            self.assertEqual(out["status"], "gap")

    def test_no_extensions_is_the_base_validation(self):
        # Valid without the extension field: nothing extra is demanded.
        obj = implement_output()
        for exts in (None, []):
            self.assertIs(
                verifiers.validate_merged_output(
                    obj, "implement", exts, self.roots
                ),
                obj,
            )
        # And a base violation raises the byte-identical base error.
        bad = {"status": "ok", "kind": "implement"}
        try:
            contracts.validate_worker_output(dict(bad), "implement")
            self.fail("expected ContractError")
        except contracts.ContractError as exc:
            base_msg = str(exc)
        with self.assertRaises(contracts.ContractError) as cm:
            verifiers.validate_merged_output(dict(bad), "implement", None, None)
        self.assertEqual(str(cm.exception), base_msg)

    def test_uncompiled_extension_is_config_error(self):
        with self.assertRaises(verifiers.PolicyConfigError):
            verifiers.validate_merged_output(
                implement_output(reuse_audit=[]), "implement",
                [make_policy()], self.roots,
            )

    def test_base_validation_still_applies_with_extensions(self):
        # The merge is additive: base violations keep failing first.
        with self.assertRaises(contracts.ContractError):
            verifiers.validate_merged_output(
                {"status": "ok", "kind": "implement",
                 "reuse_audit": self.ok_entries()},
                "implement", [self.ext], self.roots,
            )


class TestCallWorkerIntegration(FilesystemCase):
    """AC11: enforcement inside the EXISTING repair-retry path — same one
    retry, same WorkerProtocolError, operational faults not retried."""

    def setUp(self):
        super().setUp()
        self.ext = self.string_ext([{"kind": "non_empty", "field": "package"}])
        self.prompt = make_prompt("implement")
        self.ok_output = implement_output(
            reuse_audit=[{"package": "life_product_chat"}]
        )

    def call(self, runner, extensions, roots=None):
        return call_worker(
            runner, "codex", self.prompt, "implement", self.root_a,
            extensions=extensions,
            roots=self.roots if roots is None else roots,
        )

    def test_failed_check_gets_exactly_one_repair_retry(self):
        failing = implement_output(reuse_audit=[])
        runner = MockRunner(
            [
                {"expect_kind": "implement", "response": failing},
                {"expect_kind": "implement", "response": self.ok_output},
            ]
        )
        obj, result = self.call(runner, [self.ext])
        self.assertEqual(obj, self.ok_output)
        self.assertEqual(len(runner.calls), 2)
        second_prompt = runner.calls[1][2]
        self.assertIn("REPAIR", second_prompt)
        self.assertIn("non_empty", second_prompt)
        self.assertTrue(second_prompt.startswith(self.prompt))

    def test_second_failure_raises_worker_protocol_error(self):
        failing = implement_output(reuse_audit=[])
        runner = MockRunner(
            [
                {"expect_kind": "implement", "response": failing},
                {"expect_kind": "implement", "response": failing},
            ]
        )
        with self.assertRaises(WorkerProtocolError) as cm:
            self.call(runner, [self.ext])
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(len(cm.exception.raw_texts), 2)
        self.assertIn("twice", str(cm.exception))

    def test_operational_error_never_enters_the_retry_loop(self):
        # A missing reuse-source directory is not the worker's fault: the
        # runner is called ONCE and no repair prompt is sent.
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        runner = MockRunner(
            [{"expect_kind": "implement", "response": self.ok_output}]
        )
        with self.assertRaises(verifiers.OperationalError):
            self.call(runner, [ext])
        self.assertEqual(len(runner.calls), 1)

    def test_config_error_never_enters_the_retry_loop(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": self.outside,
              "match_field": "package"}]
        )
        runner = MockRunner(
            [{"expect_kind": "implement", "response": self.ok_output}]
        )
        with self.assertRaises(verifiers.PolicyConfigError):
            self.call(runner, [ext])
        self.assertEqual(len(runner.calls), 1)

    def test_operator_root_fault_with_missing_field_is_not_retried(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        runner = MockRunner(
            [{"expect_kind": "implement", "response": implement_output()}]
        )
        with self.assertRaises(verifiers.OperationalError):
            self.call(runner, [ext])
        self.assertEqual(len(runner.calls), 1)

    def test_operator_root_fault_with_base_malformed_output_is_not_retried(self):
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        runner = MockRunner(
            [{"expect_kind": "implement",
              "response": {"status": "ok", "kind": "implement"}}]
        )
        with self.assertRaises(verifiers.OperationalError):
            self.call(runner, [ext])
        self.assertEqual(len(runner.calls), 1)

    def test_blocked_output_is_exempt_in_the_real_path(self):
        blocked = {"status": "blocked", "kind": "implement",
                   "blocked_reason": "cannot read the reuse source"}
        ext = self.string_ext(
            [{"kind": "dir_listing_matches", "root": "nope",
              "match_field": "package"}]
        )
        runner = MockRunner(
            [{"expect_kind": "implement", "response": blocked}]
        )
        obj, _ = self.call(runner, [ext])
        self.assertEqual(obj, blocked)
        self.assertEqual(len(runner.calls), 1)

    def test_no_extensions_is_byte_identical_to_today(self):
        # No extension field demanded, single call, no repair.
        response = implement_output()
        runner = MockRunner(
            [{"expect_kind": "implement", "response": response}]
        )
        obj, _ = call_worker(
            runner, "codex", self.prompt, "implement", self.root_a
        )
        self.assertEqual(obj, response)
        self.assertEqual(len(runner.calls), 1)
        self.assertNotIn("REPAIR", runner.calls[0][2])


if __name__ == "__main__":
    unittest.main()
