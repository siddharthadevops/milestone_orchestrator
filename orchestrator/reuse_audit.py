"""Built-in reuse-audit safeguard template (the milestone's payoff slice).

Instantiating the template for (source, inventory, registry, version?)
yields EXACTLY two sealed-valid policy objects — the frozen goal's policy
example with the id and the parameterized root substituted:

- ``reuse-audit`` (planning): the ``reuse_audit`` contract field on the
  planning kinds over the document units — one adopt/gap/reject decision
  per package of the audited inventory, with ``file:line`` evidence,
  mechanically checked against a REAL directory listing.
- ``reuse-audit-review`` (review): the ``reuse_audit_review`` field on the
  report kinds over the same units — one concur/dissent entry per audited
  package with the reviewer's OWN citation, same two checks over the SAME
  inventory.

The pair rides the sealed pipeline whole (storage slice 3, compile and
enforcement slice 4, rendering/ledger slice 6, service gates slices 7/8):
this module is pure functions over the sealed vocabularies — no storage,
no I/O, nothing added to the closed verifier or type-spec sets.

Deliberately minimal (amendment A3): no schema variants, no generalization
hooks, no default parameter values — the one worked example lives in the
README. The ids are FIXED, not source-derived: source-derived ids would
let a re-parameterization mint a SECOND pair whose duplicate field turns
standing law into a sealed config error (verifiers._require_distinct_fields)
failing every in-scope call; fixed ids make re-enable an overwrite of the
same two documents, structurally. One audited source per project in V1:
further sources are hand-authored ordinary policies (distinct ids AND
distinct fields) through the sealed editor, or successor-process scope.
"""

from __future__ import annotations

from orchestrator import contracts
from orchestrator import state


PLANNING_POLICY_ID = "reuse-audit"
REVIEW_POLICY_ID = "reuse-audit-review"

PLANNING_FIELD = "reuse_audit"
REVIEW_FIELD = "reuse_audit_review"

INVALID_TEMPLATE_PARAMS = "invalid_template_params"

# The audit is planning-altitude law (the goal's gate machinery §2):
# skeleton/slice-note drafting over the document units. The review policy
# binds the FULL report vocabulary (a fixer may edit the note's audit
# table — the delta review judges exactly that edit); `slice_impl` units
# and the implement/fix kinds carry no reuse-audit obligation.
_PLANNING_KINDS = (
    contracts.KIND_DRAFT_SKELETON,
    contracts.KIND_DRAFT_SLICE_NOTE,
)
_DOC_UNIT_KINDS = (state.UNIT_SKELETON, state.UNIT_SLICE_DOC)

_PARAM_KEYS = frozenset({"source", "inventory", "registry", "version"})
_REQUIRED_PARAMS = ("source", "inventory", "registry")


class TemplateParamError(ValueError):
    """Instantiation refused: a missing, blank, or wrong-typed parameter,
    or an unknown body key. `reason` is the route's verbatim refusal
    token; the message carries the operator-facing detail."""

    def __init__(self, detail):
        super().__init__("%s: %s" % (INVALID_TEMPLATE_PARAMS, detail))
        self.reason = INVALID_TEMPLATE_PARAMS


def validate_params(body):
    """Normalize {source, inventory, registry, version?} or raise.

    Nothing is defaulted except the documented ``version`` = 1, and every
    string must be non-blank: a template that instantiated with defaults
    or blanks would ship a slot that is statistically free to fill — the
    bare-boolean anti-pattern wearing a contract field's clothes. Strings
    ride verbatim (validated non-blank, never trimmed or reshaped)."""
    if not isinstance(body, dict):
        raise TemplateParamError("parameters must be a JSON object")
    unknown = sorted(set(body) - _PARAM_KEYS, key=str)
    if unknown:
        raise TemplateParamError("unknown parameter keys %s" % unknown)
    params = {}
    for key in _REQUIRED_PARAMS:
        value = body.get(key)
        if type(value) is not str or not value.strip():
            raise TemplateParamError(
                "%r must be a non-blank string, got %r" % (key, value)
            )
        params[key] = value
    version = body.get("version", 1)
    if type(version) is not int or version <= 0:
        raise TemplateParamError(
            "'version' must be a positive integer, got %r" % (version,)
        )
    params["version"] = version
    return params


def planning_prompt(source, inventory, registry):
    """The planning procedure (contract C): the operator-authority half;
    the machine-enforced obligation renders separately from the compiled
    extension."""
    return (
        "REUSE AUDIT — standing safeguard over reuse source %(source)s.\n"
        "Audited inventory: %(inventory)s — its immediate children are\n"
        "the audited packages. Registry: %(registry)s.\n"
        "Procedure: enumerate the inventory, read the registry rows at\n"
        "%(registry)s first, then record one adopt/gap/reject decision\n"
        "per package with file:line evidence read from the source\n"
        "itself.\n"
        "The drafted artifact must carry the audit as a TABLE with the\n"
        "same rows as the required output field (the field is the\n"
        "mechanical slot; the table is what reviewers read). A missing\n"
        "or uncited audit is a P1 content gap.\n"
        "Recorded gaps go to the source's consumer-needs channel, never\n"
        "to local reimplementation."
        % {"source": source, "inventory": inventory, "registry": registry}
    )


def review_prompt(source, inventory, registry):
    """The review duties (contract C), same three parameters."""
    return (
        "REUSE AUDIT REVIEW — standing safeguard over reuse source\n"
        "%(source)s. Audited inventory: %(inventory)s — its immediate\n"
        "children are the audited packages. Registry: %(registry)s.\n"
        "Verify the artifact's audit claims by reading the source\n"
        "READ-ONLY — never edit it. Enumerate the inventory and read\n"
        "the registry rows at %(registry)s yourself, then record one\n"
        "concur/dissent entry per audited package with your own\n"
        "file:line citation — never the author's citation echoed.\n"
        "Every dissent must back a finding. Implementing locally what a\n"
        "reuse source already provides, without a recorded reject\n"
        "decision, is a P1 duplication finding."
        % {"source": source, "inventory": inventory, "registry": registry}
    )


def _entry(decisions):
    """The frozen example's entry shape; only the decision vocabulary
    differs between the pair."""
    return {
        "source": {"type": "string"},
        "package": {"type": "string"},
        "decision": {"enum": list(decisions)},
        "evidence": {"type": "citation"},
    }


def _checks(inventory):
    """Exactly the frozen example's two checks, on BOTH policies — the
    inventory parameter becomes dir_listing_matches.root verbatim."""
    return [
        {"kind": "citation_exists", "field": "evidence"},
        {
            "kind": "dir_listing_matches",
            "root": inventory,
            "match_field": "package",
        },
    ]


def build_policies(params):
    """The template pair for already-validated params, planning first.

    Both objects change together as one safeguard: `version` stamps both
    verbatim (no auto-bump ever — re-parameterizing without a bump changes
    standing law without a `project_safeguard_seen` re-record; the sealed
    editor's documented rule applies here unchanged)."""
    source = params["source"]
    inventory = params["inventory"]
    registry = params["registry"]
    version = params["version"]
    planning = {
        "id": PLANNING_POLICY_ID,
        "version": version,
        "enabled": True,
        "scope": {
            "kinds": list(_PLANNING_KINDS),
            "unit_kinds": list(_DOC_UNIT_KINDS),
        },
        "prompt": planning_prompt(source, inventory, registry),
        "contract": {
            "field": PLANNING_FIELD,
            "required": True,
            "entry": _entry(("adopt", "gap", "reject")),
            "checks": _checks(inventory),
        },
    }
    review = {
        "id": REVIEW_POLICY_ID,
        "version": version,
        "enabled": True,
        "scope": {
            "kinds": list(contracts.REPORT_KINDS),
            "unit_kinds": list(_DOC_UNIT_KINDS),
        },
        "prompt": review_prompt(source, inventory, registry),
        "contract": {
            "field": REVIEW_FIELD,
            "required": True,
            "entry": _entry(("concur", "dissent")),
            "checks": _checks(inventory),
        },
    }
    return [planning, review]


def instantiate(body):
    """validate_params + build_policies in one step (the route's seam)."""
    return build_policies(validate_params(body))
