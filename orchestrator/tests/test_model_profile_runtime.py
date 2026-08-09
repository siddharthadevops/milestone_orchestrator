"""Model-profile runtime: resolution, binding, and attribution (Slice 2).

The surface under test is the driver's single act-resolution seam
(`_act_staffing` / `_act_profile`) plus the binding/attribution state it
retains — no provider call is ever scripted or made. Pinned here:

- a persisted unit's FIRST act resolution binds the run's current
  selection against the CURRENT source and retains the exact resolved
  configuration + content identity (`model_profile_bound`), so later
  source edits — or even deleting the source — never restaff that unit;
- an explicit selection change is prospective: it takes effect at the
  next act resolution (`model_profile_changed`, exactly once), and an
  unknown/corrupt selection fails loudly before any dispatch without
  rewriting the prior binding;
- per-act precedence is act-wide: explicit override (the whole per-act
  policy, an explicit EMPTY entry included) > the bound rigor entry >
  the config's shipped entry > structural derivation / family default;
- a state created before the feature (no marker) resolves byte-identically
  through its persisted config and existing acts behavior and never reads
  the catalogue.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from orchestrator import contracts
from orchestrator import driver
from orchestrator import model_profiles as mp
from orchestrator import runners
from orchestrator import state as st

GOAL = "Exercise the model-profile runtime"


class ModelProfileRuntimeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="orch-mp-rt-")
        self.addCleanup(self._tmp.cleanup)
        self.home = os.path.join(self._tmp.name, "home")
        os.makedirs(self.home)
        self._n = 0

    # -- fixtures -----------------------------------------------------------

    def _driver(self, model_profile, config_acts=None, overlay=None):
        self._n += 1
        ws = os.path.join(self._tmp.name, "ws-%d" % self._n)
        os.makedirs(ws)
        cfg = json.loads(json.dumps(driver.DEFAULT_CONFIG))
        if config_acts is not None:
            cfg["acts"] = config_acts
        path = driver.default_state_path(ws)
        st.save(path, st.new_state(GOAL, ws, cfg,
                                   model_profile=model_profile))
        if overlay is not None:
            self.write_overlay(path, overlay)
        return driver.Driver(path, runner=runners.MockRunner([]))

    def feature_driver(self, selection=None, config_acts=None, overlay=None,
                       seed=True):
        """A model-profile-enabled run: marker present, catalogue seeded."""
        if seed:
            mp.ensure_default(self.home)
        return self._driver({"home": self.home, "selection": selection},
                            config_acts=config_acts, overlay=overlay)

    def pre_feature_driver(self, config_acts=None, overlay=None):
        """A state exactly as pre-feature initialization persisted it."""
        return self._driver(None, config_acts=config_acts, overlay=overlay)

    @staticmethod
    def write_overlay(state_path, acts):
        path = os.path.join(os.path.dirname(state_path), "acts.json")
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(acts, str):
                fh.write(acts)
            else:
                json.dump(acts, fh)

    @staticmethod
    def write_selection(d, payload):
        path = os.path.join(os.path.dirname(d.state_path),
                            "model_profile.json")
        with open(path, "w", encoding="utf-8") as fh:
            if isinstance(payload, str):
                fh.write(payload)
            else:
                json.dump(payload, fh)

    def save_profile(self, name, medium, low=None, high=None):
        mp.save(self.home, {
            "name": name,
            "examples": ["custom work"],
            "configurations": {
                "low": low or {},
                "medium": medium,
                "high": high or {},
            },
        })

    @staticmethod
    def events(d, etype):
        return [e for e in d.state["events"] if e.get("type") == etype]

    @staticmethod
    def seal_current_unit(d):
        unit = st.current_unit(d.state)
        unit["status"] = st.U_SEALED
        d._save()

    def edit_default_medium(self, act, value):
        doc = mp.load(self.home, "default")
        doc["configurations"]["medium"][act] = value
        mp.save(self.home, doc)
        return doc

    # -- unit-open binding retains mutable source content --------------------

    def test_unit_binding_snapshots_source_and_allows_two_unit_choices(self):
        d = self.feature_driver()
        self.assertEqual(d._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))
        bound = self.events(d, "model_profile_bound")
        self.assertEqual(len(bound), 1)
        evt = bound[0]
        seeded = mp.load(self.home, "default")["configurations"]["medium"]
        self.assertEqual(evt["unit"], "skeleton")
        self.assertEqual((evt["name"], evt["rigor"], evt["origin"]),
                         ("default", "medium", "implicit-default"))
        self.assertEqual(evt["configuration"], seeded)
        h1 = evt["content_hash"]
        self.assertEqual(h1, mp.content_identity(seeded))
        # The binding is persisted at the resolution itself — durable on
        # disk BEFORE any provider dispatch could happen.
        on_disk = st.load(d.state_path)
        self.assertEqual(
            [e["type"] for e in on_disk["events"]
             if e["type"] == "model_profile_bound"],
            ["model_profile_bound"])
        # Further resolutions never rebind.
        d._act_profile("drafter")
        d._act_profile("reclassifier", origin_family="claude")
        self.assertEqual(len(self.events(d, "model_profile_bound")), 1)

        # Editing the mutable source does not change the bound unit...
        edited = self.edit_default_medium(
            "implementer",
            {"agent": "claude", "model": "claude-sonnet-5", "effort": "low"})
        self.assertEqual(d._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))
        # ...not even across a restart with the source DELETED: the unit
        # resolves from retained content, no source read at all.
        source = os.path.join(mp.model_profiles_dir(self.home),
                              "default.json")
        os.remove(source)
        d2 = driver.Driver(d.state_path, runner=runners.MockRunner([]))
        self.assertEqual(d2._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))
        self.assertEqual(len(self.events(d2, "model_profile_bound")), 1)

        # A LATER unit binds the edited definition and retains a distinct
        # content identity under the same selection.
        mp.save(self.home, edited)
        self.seal_current_unit(d2)
        d2.state["milestone"]["slices"] = [{"id": 1, "title": "One"}]
        self.assertIsNotNone(st.ensure_due_unit(d2.state))
        d2._save()
        self.assertEqual(d2._act_profile("implementer"),
                         ("claude", "claude-sonnet-5", "low"))
        bound = self.events(d2, "model_profile_bound")
        self.assertEqual(len(bound), 2)
        self.assertNotEqual(bound[1]["unit"], "skeleton")
        self.assertEqual(bound[1]["name"], "default")
        self.assertNotEqual(bound[1]["content_hash"], h1)
        # The first unit's retained record is untouched.
        self.assertEqual(bound[0]["content_hash"], h1)

    # -- explicit change is prospective and loud -----------------------------

    def test_profile_change_applies_to_next_resolution_only(self):
        self.save_profile("webui", medium={
            "implementer": {"agent": "claude", "model": "claude-sonnet-5",
                            "effort": "medium"},
        }, high={
            "implementer": {"agent": "codex", "effort": "low"},
        })
        d = self.feature_driver()
        self.assertEqual(d._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))
        original_bound = self.events(d, "model_profile_bound")[0]

        # A pending selection request takes effect at the NEXT resolution:
        # one model_profile_changed, the unit restaffed from here on.
        self.write_selection(d, {"name": "webui", "rigor": "high"})
        self.assertEqual(d._act_profile("implementer"),
                         ("codex", "gpt-5.6-sol", "low"))
        changed = self.events(d, "model_profile_changed")
        self.assertEqual(len(changed), 1)
        webui_high = mp.load(self.home, "webui")["configurations"]["high"]
        self.assertEqual(changed[0]["configuration"], webui_high)
        self.assertEqual(changed[0]["previous"],
                         {"name": "default", "rigor": "medium"})
        self.assertEqual(d.state["model_profile"]["selection"],
                         {"name": "webui", "rigor": "high"})
        unit = st.current_unit(d.state)
        self.assertEqual(unit["model_profile_binding"]["name"], "webui")
        # Idempotent: the same request never re-fires.
        d._act_profile("implementer")
        self.assertEqual(len(self.events(d, "model_profile_changed")), 1)
        # The original binding record was never rewritten.
        self.assertEqual(self.events(d, "model_profile_bound")[0],
                         original_bound)

        # An unknown selection fails BEFORE any dispatch, falls back to
        # nothing, and rewrites neither the selection nor the binding.
        self.write_selection(d, {"name": "ghost", "rigor": "high"})
        with self.assertRaises(driver.StopStep):
            d._act_profile("implementer")
        self.assertIsNotNone(d.state["failure"])
        self.assertEqual(len(self.events(d, "model_profile_changed")), 1)
        self.assertEqual(d.state["model_profile"]["selection"],
                         {"name": "webui", "rigor": "high"})
        self.assertEqual(unit["model_profile_binding"]["name"], "webui")

        # Same loudness for an unknown rigor and for corrupt stored
        # content; the prior binding stays authoritative each time.
        d.state["failure"] = None
        self.write_selection(d, {"name": "webui", "rigor": "extreme"})
        with self.assertRaises(driver.StopStep):
            d._act_profile("implementer")
        d.state["failure"] = None
        with open(os.path.join(mp.model_profiles_dir(self.home),
                               "broken.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.write_selection(d, {"name": "broken", "rigor": "low"})
        with self.assertRaises(driver.StopStep):
            d._act_profile("implementer")
        self.assertEqual(len(self.events(d, "model_profile_changed")), 1)
        self.assertEqual(unit["model_profile_binding"]["name"], "webui")

        # A persisted selection object is not absence: if damaged, it
        # fails before even consulting the catalogue and never binds the
        # implicit default.
        for damaged in ({"rigor": "medium"}, {"name": "default"}, {},
                        "default@medium"):
            with self.subTest(persisted_selection=damaged):
                damaged_driver = self.feature_driver(selection=damaged)
                with mock.patch.object(
                        mp, "selection_content",
                        wraps=mp.selection_content) as resolve:
                    with self.assertRaises(driver.StopStep):
                        damaged_driver._act_profile("implementer")
                    resolve.assert_not_called()
                self.assertIn(
                    "persisted model-profile selection",
                    damaged_driver.state["failure"]["reason"])
                self.assertEqual(
                    self.events(damaged_driver, "model_profile_bound"), [])
                self.assertNotIn(
                    "model_profile_binding",
                    st.current_unit(damaged_driver.state))

    def test_same_selection_reapplication_refreshes_edited_content_once(self):
        self.save_profile("core", medium={
            "implementer": {
                "agent": "claude", "model": "claude-fable-5",
                "effort": "max",
            },
        })
        selection = {"name": "core", "rigor": "medium"}
        d = self.feature_driver(selection=selection)
        self.assertEqual(d._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))
        original_hash = st.current_unit(d.state)[
            "model_profile_binding"
        ]["content_hash"]

        doc = mp.load(self.home, "core")
        doc["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "gpt-5.6-terra",
            "effort": "high",
        }
        mp.save(self.home, doc)
        # A source edit alone never changes the retained unit binding.
        self.assertEqual(d._act_profile("implementer"),
                         ("claude", "claude-fable-5", "max"))

        # Reapplying the SAME selection is a new one-shot request. It
        # resolves current content, records the transition, and is consumed.
        self.write_selection(d, selection)
        self.assertEqual(d._act_profile("implementer"),
                         ("codex", "gpt-5.6-terra", "high"))
        changed = self.events(d, "model_profile_changed")
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["previous"], selection)
        self.assertNotEqual(changed[0]["content_hash"], original_hash)
        self.assertFalse(os.path.exists(d._model_profile_selection_path()))
        d._act_profile("implementer")
        self.assertEqual(len(self.events(d, "model_profile_changed")), 1)

    def test_applied_selection_request_does_not_replay_after_restart(self):
        self.save_profile("core", medium={
            "implementer": {
                "agent": "claude", "model": "claude-fable-5",
                "effort": "max",
            },
        })
        selection = {"name": "core", "rigor": "medium"}
        d = self.feature_driver()
        d._act_profile("implementer")
        self.write_selection(d, selection)

        # Simulate process death after the changed event and binding were
        # saved, but before that exact sidecar generation was unlinked.
        with mock.patch.object(
            d, "_clear_selection_request",
            side_effect=RuntimeError("simulated crash before unlink"),
        ):
            with self.assertRaisesRegex(RuntimeError, "before unlink"):
                d._act_profile("implementer")
        on_disk = st.load(d.state_path)
        changed = [
            event for event in on_disk["events"]
            if event.get("type") == "model_profile_changed"
        ]
        self.assertEqual(len(changed), 1)
        applied_hash = changed[0]["content_hash"]

        doc = mp.load(self.home, "core")
        doc["configurations"]["medium"]["implementer"] = {
            "agent": "codex", "model": "gpt-5.6-terra",
            "effort": "high",
        }
        mp.save(self.home, doc)

        restarted = driver.Driver(
            d.state_path, runner=runners.MockRunner([])
        )
        self.assertEqual(
            restarted._act_profile("implementer"),
            ("claude", "claude-fable-5", "max"),
        )
        self.assertEqual(
            len(self.events(restarted, "model_profile_changed")), 1
        )
        self.assertEqual(
            st.current_unit(restarted.state)["model_profile_binding"][
                "content_hash"
            ],
            applied_hash,
        )
        self.assertFalse(
            os.path.exists(restarted._model_profile_selection_path())
        )
        self.assertNotIn(
            "selection_request_ack", restarted.state["model_profile"]
        )

        # A newly written request with the same selection remains a distinct
        # operator action and may deliberately adopt the edited source.
        self.write_selection(restarted, selection)
        self.assertEqual(
            restarted._act_profile("implementer"),
            ("codex", "gpt-5.6-terra", "high"),
        )
        self.assertEqual(
            len(self.events(restarted, "model_profile_changed")), 2
        )

    def test_retained_binding_is_verified_without_reading_mutable_source(self):
        corruptions = ("hash-mismatch", "invalid-shape", "incomplete")
        for corruption in corruptions:
            with self.subTest(corruption=corruption):
                d = self.feature_driver()
                d._act_profile("implementer")
                unit = st.current_unit(d.state)
                binding = unit["model_profile_binding"]
                if corruption == "hash-mismatch":
                    binding["configuration"]["implementer"]["effort"] = (
                        "low"
                    )
                elif corruption == "invalid-shape":
                    binding["configuration"] = {
                        "implementer": {"agent": "claude", "dead": "x"}
                    }
                    binding["content_hash"] = mp.content_identity(
                        binding["configuration"]
                    )
                else:
                    unit["model_profile_binding"] = {"name": "default"}
                with mock.patch.object(
                    mp, "selection_content",
                    side_effect=AssertionError(
                        "damaged retained binding consulted mutable source"
                    ),
                ) as resolve:
                    with self.assertRaises(driver.StopStep):
                        d._act_profile("implementer")
                resolve.assert_not_called()
                self.assertIsNotNone(d.state["failure"])

    def test_brainstorming_resume_keeps_origin_binding_after_pending_change(self):
        d = self.feature_driver()
        self.seal_current_unit(d)
        d.state["milestone"]["slices"] = [{"id": 1, "title": "One"}]
        self.assertIsNotNone(st.ensure_due_unit(d.state))
        d._save()
        unit = st.current_unit(d.state)
        self.assertEqual(unit["kind"], st.UNIT_SLICE_DOC)
        origin_staffing = d._act_staffing("drafter")
        origin_binding = json.loads(json.dumps(
            unit["model_profile_binding"]
        ))
        origin_hash = origin_binding["content_hash"]
        unit["brainstorming_resume"] = {
            "kind": contracts.KIND_DRAFT_SLICE_NOTE,
            "output": {
                "status": "ok",
                "kind": contracts.KIND_DRAFT_SLICE_NOTE,
                "artifact": "docs/slice-01.md",
            },
            "raw_path": "raw/resumed.txt",
            "duration_s": 1.0,
            "model_profile_binding": origin_binding,
            "family": origin_staffing["family"],
            # A wait persisted by the pre-fix runtime omitted family-default
            # values even though those exact defaults were dispatched.
            "model": None,
            "effort": None,
            "pre_snapshot": {},
        }

        self.edit_default_medium(
            "drafter",
            {"agent": "codex", "model": "gpt-5.6-terra",
             "effort": "high"},
        )
        self.write_selection(
            d, {"name": "default", "rigor": "medium"}
        )
        self.assertIn("drafted", d._do_draft())

        # Reopening legitimately applies the prospective change, but the
        # already-completed continuation's immutable draft record keeps A.
        self.assertNotEqual(
            unit["model_profile_binding"]["content_hash"], origin_hash
        )
        self.assertEqual(unit["draft"]["model_profile"]["content_hash"],
                         origin_hash)
        self.assertEqual(
            (unit["draft"]["family"], unit["draft"]["model"],
             unit["draft"]["effort"]),
            ("codex", "gpt-5.6-sol", "xhigh"),
        )
        self.assertNotIn("act_override", unit["draft"])

    # -- precedence is act-wide ----------------------------------------------

    def test_precedence_whole_act_partial_relative_and_empty_override(self):
        self.save_profile("core", medium={
            "skeletoner": {"agent": "claude", "model": "claude-sonnet-5",
                           "effort": "low"},
            "implementer": {"agent": "claude", "model": "claude-fable-5",
                            "effort": "max"},
            "drafter": "claude",
            "reclassifier": "self",
            "review_claude": {"model": "claude-sonnet-5", "effort": "low"},
            "consultation": "codex",
        })
        d = self.feature_driver(
            selection={"name": "core", "rigor": "medium"},
            overlay={
                "implementer": {"agent": "codex", "effort": "xhigh"},
                "drafter": {"model": "gpt-5.6-luna"},
                "skeletoner": {},
                "fixer": "opposite",
            })
        # 1. A whole-act override beats the profile's entry outright.
        self.assertEqual(d._act_profile("implementer"),
                         ("codex", "gpt-5.6-sol", "xhigh"))
        # 2. A PARTIAL override is still the whole act policy: its missing
        # agent resolves by the entry's own form (fix-family fallback),
        # never from the profile's `drafter: claude`.
        self.assertEqual(d._act_profile("drafter"),
                         ("codex", "gpt-5.6-luna", "xhigh"))
        # 3. The explicit EMPTY policy suppresses profile AND shipped
        # config entry: the act resolves purely structurally (skeletoner
        # re-asserts its own family/effort; model = family default later).
        self.assertEqual(
            d._skeletoner_profile(), ("claude", "claude-opus-5", "max")
        )
        # 4. Relative override policies resolve from the effective
        # originating act.
        self.assertEqual(d._resolve_act("fixer", "claude"), "codex")
        self.assertEqual(d._resolve_act("fixer", "codex"), "claude")
        # 5. Profile entry beats the config's shipped act entry (shipped
        # reclassifier pins codex; the profile says `self`).
        self.assertEqual(
            d._act_profile("reclassifier", origin_family="claude",
                           default_family="codex")[0],
            "claude")
        # 6. Consultation: the profile's family policy governs where the
        # shipped entry would derive the opposite.
        self.assertEqual(d._resolve_act("consultation", "codex"), "codex")
        # 7. A profile-omitted act keeps its existing derivation: the
        # counterpart stays the structural opposite of the lead.
        lead, counterpart = d._brainstorming_profiles()
        self.assertEqual(lead["agent"], "codex")
        self.assertEqual(counterpart["agent"], "claude")
        self.assertEqual(counterpart["effort"], "xhigh")
        # 8. Review seats take profile model/effort; the family is pinned.
        self.assertEqual(d._review_profile("claude"),
                         ("claude-sonnet-5", "low"))
        # 9. Attribution provenance: the explicit empty entry is a
        # contributing override, recorded as {}.
        staffing = d._act_staffing("skeletoner")
        attribution = d._staffing_attribution(staffing)
        self.assertEqual(attribution["model_profile"]["name"], "core")
        self.assertEqual(attribution["model_profile"]["rigor"], "medium")
        self.assertEqual(attribution["act_override"],
                         {"act": "skeletoner", "entry": {}})
        # ...and an act the override layer does not touch carries none.
        untouched = d._staffing_attribution(d._act_staffing("reclassifier"))
        self.assertNotIn("act_override", untouched)
        self.assertEqual(untouched["model_profile"]["name"], "core")

    # -- old states do not opt in ---------------------------------------------

    def test_pre_feature_state_is_identical_and_never_reads_catalogue(self):
        config_acts = {
            "implementer": {"model": "claude-sonnet-5"},
            "drafter": None,
            "delta_review": "codex",
            "fixer": "codex",
            "skeletoner": {"agent": "claude", "model": "claude-fable-5",
                           "effort": "max"},
            "consultation": "opposite",
            "reclassifier": {"agent": "codex", "effort": "xhigh"},
            "brainstorming_counterpart": "opposite",
        }
        overlay = {
            "review_claude": {"model": "claude-sonnet-5"},
            "implementer": "",  # falsy overlay entries stay skipped
        }
        d = self.pre_feature_driver(config_acts=config_acts, overlay=overlay)
        spy = mock.MagicMock(
            side_effect=AssertionError("pre-feature state read the "
                                       "model-profile catalogue"))
        with mock.patch.object(mp, "load", spy), \
                mock.patch.object(mp, "selection_content", spy):
            # The historical quirks, pinned literally: a partial object
            # without `agent` falls to the fix family; a creation-cleared
            # act falls to the fix family; legacy keys stay inert.
            self.assertEqual(d._act_profile("implementer"),
                             ("codex", "claude-sonnet-5", None))
            self.assertEqual(d._act_profile("drafter"),
                             ("codex", None, None))
            self.assertEqual(d._skeletoner_profile(),
                             ("claude", "claude-fable-5", "max"))
            self.assertEqual(d._act_profile("fixer", "claude",
                                            default_family="codex"),
                             ("codex", None, None))
            self.assertEqual(d._resolve_act("consultation", "codex"),
                             "claude")
            self.assertEqual(
                d._act_profile("reclassifier", origin_family="claude",
                               default_family="claude"),
                ("codex", None, "xhigh"))
            self.assertEqual(d._review_profile("claude"),
                             ("claude-sonnet-5", "xhigh"))
            self.assertEqual(d._review_profile("codex"),
                             ("gpt-5.6-sol", "xhigh"))
            lead, counterpart = d._brainstorming_profiles()
            # The partial implementer entry keeps today's exact quirk:
            # family falls to the fix family while the pinned model rides
            # along with it.
            self.assertEqual(
                (lead["agent"], lead["model"], lead["effort"]),
                ("codex", "claude-sonnet-5", "xhigh"))
            self.assertEqual(counterpart["agent"], "claude")
            # No binding machinery ran: no events, no attribution, no
            # feature state.
            self.assertEqual(self.events(d, "model_profile_bound"), [])
            self.assertEqual(self.events(d, "model_profile_changed"), [])
            staffing = d._act_staffing("implementer")
            self.assertIsNone(staffing["binding"])
            self.assertIsNone(d._staffing_attribution(staffing))
        spy.assert_not_called()

    def test_present_malformed_feature_marker_fails_loudly(self):
        for marker in (None, "default@medium", [], 7):
            with self.subTest(marker=marker):
                d = self.feature_driver()
                d.state["model_profile"] = marker
                with mock.patch.object(
                    mp, "selection_content",
                    side_effect=AssertionError(
                        "malformed marker consulted the catalogue"
                    ),
                ) as resolve:
                    with self.assertRaises(driver.StopStep):
                        d._act_profile("implementer")
                resolve.assert_not_called()
                self.assertIn(
                    "feature state must be a JSON object",
                    d.state["failure"]["reason"],
                )

    # -- calls outside any persisted unit -------------------------------------

    def test_outside_unit_call_resolves_current_selection_at_that_call(self):
        d = self.feature_driver()
        self.seal_current_unit(d)
        self.assertIsNone(st.current_unit(d.state))
        staffing = d._act_staffing("implementer")
        self.assertEqual(
            (staffing["family"], staffing["model"], staffing["effort"]),
            ("claude", "claude-fable-5", "max"))
        self.assertTrue(staffing["binding"].get("outside_unit"))
        h1 = staffing["binding"]["content_hash"]
        # No unit: nothing binds, nothing is persisted...
        self.assertEqual(self.events(d, "model_profile_bound"), [])
        # ...and the CURRENT source governs each call: an edit shows up at
        # the very next resolution, with a distinct retained identity in
        # the call's attribution.
        self.edit_default_medium(
            "implementer",
            {"agent": "claude", "model": "claude-sonnet-5", "effort": "low"})
        staffing = d._act_staffing("implementer")
        self.assertEqual(
            (staffing["family"], staffing["model"], staffing["effort"]),
            ("claude", "claude-sonnet-5", "low"))
        attribution = d._staffing_attribution(staffing)
        self.assertEqual(attribution["model_profile"]["name"], "default")
        self.assertNotEqual(attribution["model_profile"]["content_hash"], h1)

    # -- the override layer is loud when damaged ------------------------------

    def test_unreadable_override_layer_is_loud_only_for_feature_runs(self):
        d = self.feature_driver()
        self.write_overlay(d.state_path, "{not json")
        with self.assertRaises(driver.StopStep):
            d._act_profile("implementer")
        self.assertIn("acts.json", d.state["failure"]["reason"])

        d2 = self.feature_driver()
        self.write_overlay(d2.state_path, '["not", "an", "object"]')
        with self.assertRaises(driver.StopStep):
            d2._act_profile("implementer")

        # Pre-feature runs keep the historical tolerant read.
        d3 = self.pre_feature_driver()
        self.write_overlay(d3.state_path, "{not json")
        self.assertEqual(d3._act_profile("fixer", None,
                                         default_family="codex"),
                         ("codex", None, None))
        self.assertIsNone(d3.state["failure"])

    # -- draft records carry the retained attribution -------------------------

    def test_draft_record_carries_binding_and_override_attribution(self):
        d = self.feature_driver(overlay={"implementer": {"effort": "xhigh"}})
        staffing = d._act_staffing("implementer")
        self.assertEqual(
            (staffing["family"], staffing["model"], staffing["effort"]),
            ("codex", "gpt-5.6-sol", "xhigh"),
        )
        attribution = d._staffing_attribution(staffing)
        unit = st.current_unit(d.state)
        st.record_draft(
            d.state, unit, "implement",
            {"status": "ok", "kind": "implement", "artifact": "x.md"},
            family=staffing["family"], model=staffing["model"],
            effort=staffing["effort"], attribution=attribution)
        binding = unit["model_profile_binding"]
        self.assertEqual(unit["draft"]["model_profile"], {
            "name": "default", "rigor": "medium",
            "content_hash": binding["content_hash"],
            "origin": "implicit-default",
        })
        self.assertEqual(unit["draft"]["act_override"], {
            "act": "implementer", "entry": {"effort": "xhigh"}})
        self.assertEqual(
            (unit["draft"]["family"], unit["draft"]["model"],
             unit["draft"]["effort"]),
            ("codex", "gpt-5.6-sol", "xhigh"),
        )
        recorded = self.events(d, "draft_recorded")[-1]
        self.assertEqual(recorded["model_profile"],
                         unit["draft"]["model_profile"])
        self.assertEqual(recorded["act_override"],
                         unit["draft"]["act_override"])
        self.assertEqual(
            (recorded["family"], recorded["model"], recorded["effort"]),
            ("codex", "gpt-5.6-sol", "xhigh"),
        )

        # The same effective-resolution object feeds fix round metadata.
        fixer = d._act_staffing("fixer", default_family="codex")
        self.assertEqual(
            (fixer["family"], fixer["model"], fixer["effort"]),
            ("codex", "gpt-5.6-sol", "xhigh"),
        )


if __name__ == "__main__":
    unittest.main()
