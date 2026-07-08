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

FAMILY_UNTIL_CLEAN = "family_until_clean"


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
