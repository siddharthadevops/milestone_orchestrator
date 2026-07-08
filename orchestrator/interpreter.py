"""The stage interpreter: reads a run's governing strategy profile and
maps its stage composition onto the driver's review-phase decisions.

Phase 2 of the build-driven review reform implements ONLY the
`family_until_clean` loop — the canonical pre-reform rounds flow: one
family's review rounds run until that family's latest review is clean,
then the next family, then the seal. A run under the `legacy` compatibility
profile is therefore bit-equivalent to a profile-less run;
test_profile_equivalence is the gate that holds that line. Later phases add
the `parallel` loop, the fuser, and evaluator rules over this same seam.

A profile-less run has no governing profile, and the interpreter answers
`family_until_clean` for it too — so the profile-less path and the legacy
path converge on the exact same driver decisions. The loop shape is the
only thing phase 2 reads from a profile: dials (thresholds etc.) are still
read from the run config, so nothing about a run's behavior yet depends on
which profile it carries.
"""

from . import contracts

FAMILY_UNTIL_CLEAN = "family_until_clean"

# Profile fields that decompose into run-config DIALS (spec §5: "profiles
# decompose into config dials"). Only keys the driver actually consumes as
# config are listed; more join as later phases read them. Structural
# profile keys (stages, compat, fuser_*, doc_register, final_open_pass) are
# NOT dials and never merge into the config namespace.
PROFILE_DIALS = ("p3_defer_max_risk", "p3_reclassify_debt")


def governing_profile(state):
    """The semantic content of the run's governing strategy profile, or
    None. Embedded in the run config as a self-contained snapshot, so the
    driver needs no service home to interpret it; its identity hash rides
    alongside in `profile_ref`. Absent for a profile-less run — and absent
    for a run that recorded only a profile_ref label without embedded
    content, which the interpreter treats exactly like profile-less
    (family_until_clean)."""
    return (state.get("config") or {}).get("profile")


def rounds_loop(state):
    """The loop shape governing the review-rounds phase for this run.
    Profile-less runs, and any profile whose active stage is
    family_until_clean, resolve to the canonical flow. Phase 2 interprets
    only this loop; the driver rejects any other loop kind loudly rather
    than silently running the wrong flow (later phases implement them)."""
    profile = governing_profile(state)
    if not profile:
        return FAMILY_UNTIL_CLEAN
    stages = profile.get("stages") or []
    if not stages:
        return FAMILY_UNTIL_CLEAN
    # Phase 2: a single review stage. Multi-stage progression is phase 3.
    return stages[0].get("loop") or FAMILY_UNTIL_CLEAN


def effective_config(state):
    """The run config with the governing profile's recognized dials merged
    OVER it (spec §5: profiles decompose into config dials). This is how a
    profile changes a run's behavior — a `strict` run and a `light` run
    read different `p3_defer_max_risk` thresholds without any read-site in
    the driver changing.

    Profile-less runs, and profiles that declare no dials (the `legacy`
    compatibility artifact carries none), get the raw config object back
    UNCHANGED — so those runs stay byte-for-byte identical to the
    pre-reform driver. An explicit operator config value is overridden by
    the profile dial (the operator picked the profile precisely for its
    dials); an act/config hot-override that wants to win is a separate,
    later concern (it marks the run's meter data `deviated`)."""
    config = state.get("config") or {}
    profile = governing_profile(state)
    if not profile:
        return config
    overrides = {k: profile[k] for k in PROFILE_DIALS if k in profile}
    if not overrides:
        return config
    merged = dict(config)
    merged.update(overrides)
    return merged


def doc_register(state):
    """The doc-authoring register the run's profile asks for (spec §6):
    'lay+hard-table' (a lay INTENT register plus a hard PINNED-FACTS table)
    or 'dense' (uniform contract prose). Profile-less and legacy runs, and
    any profile that does not set it, get 'dense' — the pre-reform register,
    so their doc prompts are unchanged."""
    profile = governing_profile(state)
    if not profile:
        return "dense"
    return profile.get("doc_register") or "dense"


def reform_active(state):
    """Whether the reform's semantics govern this run — the single
    predicate behind gap semantics, the seal predicate, the widened doc
    gate, the question battery, and the plain/example hard-require. ON
    for every reform profile; OFF for the `legacy` compatibility artifact
    (which declares `compat`) and for profile-less runs, which reproduce
    the pre-reform driver bit-identically."""
    profile = governing_profile(state)
    return bool(profile) and not profile.get("compat")


def gap_semantics(state):
    """Whether the reform's gap semantics are ON for this run (spec §3): a
    draft/implement worker that meets a build-changing hole or contradiction
    STOPS and reports a structured gap, which the driver routes as an
    upstream repair. ON for every reform profile; OFF for the `legacy`
    compatibility artifact and for profile-less runs, which reproduce the
    pre-reform builders exactly (their prompts never advertise the gap
    exit, so they never return one — bit-identical)."""
    return reform_active(state)


def seal_predicate(state):
    """Whether this run seals by the reform PREDICATE (spec §5) rather than
    by dedicated seal-half worker calls. ON for every reform profile; OFF
    for the `legacy` compatibility artifact and profile-less runs, which
    keep the pre-reform double-seal halves (so they stay bit-identical)."""
    return reform_active(state)


def battery_questions(state, unit_kind):
    """The required question-battery ids for a unit of `unit_kind`, or
    None (no battery). The battery is NOT a dial — every reform profile
    carries it, `strict` and `light` alike (spec §4); implementation
    units have no battery (it is a DOC gate). Legacy and profile-less
    runs get None everywhere, keeping their prompts and validation
    byte-identical to the pre-reform driver."""
    if not reform_active(state):
        return None
    if unit_kind == "skeleton":
        return contracts.BATTERY_QUESTIONS_SKELETON
    if unit_kind == "slice_doc":
        return contracts.BATTERY_QUESTIONS_SLICE_NOTE
    return None


def doc_defer_scope(state):
    """The severities a DOC-phase review round may defer as tracked debt
    (subject to the drift-risk threshold). The pre-reform gate — and the
    `legacy` compat profile and every profile-less run — defer only lone
    P3s ({"P3"}). A reform profile widens this to the full §2 doc gate:
    P0/P1 ALWAYS fix (never in scope), P2/P3 are rated and the threshold
    decides fix-vs-debt ({"P2","P3"}). Returned as a tuple so callers pass
    it straight to contracts.all_in_severity.

    A reform profile is any governing profile that is not the `legacy`
    compatibility artifact (which declares `compat`)."""
    profile = governing_profile(state)
    if profile and not profile.get("compat"):
        return ("P2", "P3")
    return ("P3",)


def verify_embedded(state):
    """Fail loudly if an embedded profile snapshot is internally
    inconsistent — its content hash must match the recorded profile_ref
    hash (spec decision 15, 'verified on load'). No-op for a profile-less
    run and for a ref-only label with no embedded content (interpreted as
    family_until_clean); a content/hash mismatch means the snapshot was
    tampered with or written wrong, and running it would silently govern a
    unit by the wrong profile."""
    from . import profiles

    cfg = state.get("config") or {}
    content = cfg.get("profile")
    if content is None:
        return
    ref = cfg.get("profile_ref") or {}
    recorded = ref.get("hash")
    if not recorded:
        return
    actual = profiles.semantic_hash(content)
    if actual != recorded:
        raise ValueError(
            "embedded profile snapshot is inconsistent: content hash %s != "
            "recorded profile_ref hash %s" % (actual, recorded)
        )
