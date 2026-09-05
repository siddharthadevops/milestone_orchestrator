"""What one worker call cost, in dollars.

TWO figures, deliberately distinct — a run mixing a subscription seat with a
metered account must not report one number and imply the other:

- ``api_usd``  — orientative API-equivalent: what the call WOULD cost at
  published per-token rates, whatever the account actually pays.
- ``real_usd`` — money that actually leaves: equal to ``api_usd`` when the
  family bills per token, and 0.0 when the family runs on a subscription
  seat (the call spent a seat, not marginal money).

``None`` on either field means NOT COMPUTABLE (unknown model, missing or
malformed provider payload) and must propagate as `partial`, exactly the way
an absent token_usage already does. It never means free — free is 0.0.

ONE CONTRACT, one adapter per family:

    quote(family, model, provider_output, billing) -> Quote(api_usd, real_usd)

``provider_output`` is the provider's OWN payload — Claude's result object,
Codex's turn usage — not the normalized token shape. Normalization is lossy
by design (it exists to make two families additive in one unit) and a price
depends on bands it drops: Claude splits cache writes into 1h and 5m at
different multipliers, and Codex reports a cache-write count that the
normalized shape has no field for.

Replacing this with an Agent_99 pricing service later means registering one
more adapter under the same contract. Nothing else moves.
"""

import math

# Who pays how. A family on a subscription seat has no marginal money per
# call; one on a metered account pays exactly the API-equivalent.
BILLING_SUBSCRIPTION = "subscription"
BILLING_API = "api"
BILLING_MODES = (BILLING_SUBSCRIPTION, BILLING_API)

DEFAULT_BILLING = {
    "claude": BILLING_SUBSCRIPTION,
    "codex": BILLING_SUBSCRIPTION,
}


class Quote(object):
    """One call's cost under both readings. Either field may be None."""

    __slots__ = ("api_usd", "real_usd")

    def __init__(self, api_usd=None, real_usd=None):
        self.api_usd = api_usd
        self.real_usd = real_usd

    def as_dict(self):
        return {"api_usd": self.api_usd, "real_usd": self.real_usd}

    def __eq__(self, other):
        if not isinstance(other, Quote):
            return NotImplemented
        return (
            self.api_usd == other.api_usd
            and self.real_usd == other.real_usd
        )

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Quote(api_usd=%r, real_usd=%r)" % (self.api_usd, self.real_usd)


UNKNOWN = Quote(None, None)


def _amount(value):
    """A usable dollar amount, or None. Bools and non-finite values are not
    amounts; a negative one means the source is wrong, not cheap."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _count(value):
    """A token count. Anything unusable reads as zero: a missing band is an
    absent charge, whereas a missing PRICE is what makes a quote unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(float(value)) or value < 0:
        return 0
    return int(value)


# ---------------------------------------------------------------------------
# Claude: the provider prices itself.

def claude_api_cost(model, provider_output):
    """Claude's own figure, taken verbatim.

    The CLI's result object carries `total_cost_usd`, which covers the WHOLE
    call — including CLI-internal model calls that the result's top-level
    `usage` block does not report (a trivial call measured 0.000586 for the
    answer plus 0.012864 for an internal one; total_cost_usd was the sum).
    Deriving a price from the tokens we record would therefore undercount
    the very call it is pricing. The model argument is unused: the figure is
    already model-resolved, which is also why an unknown Claude model can
    never make a quote unknown.
    """
    if not isinstance(provider_output, dict):
        return None
    return _amount(provider_output.get("total_cost_usd"))


# ---------------------------------------------------------------------------
# Codex: no cost is reported, so it is computed.

# USD per million tokens, standard service tier (codex exec runs standard;
# the batch/flex tiers are half and do not apply here).
# Verified against the OpenAI pricing docs; input/output cross-check against
# published rate summaries. Update by hand when OpenAI moves them — git dates
# the change, so the table carries no date of its own.
CODEX_RATES = {
    "gpt-6-astra": {
        "input": 10.00, "cached_input": 1.00, "cache_write": 12.50,
        "output": 50.00,
        "long_context": {
            "input_tokens_over": 272_000,
            "input_multiplier": 2.0,
            "output_multiplier": 1.5,
        },
    },
    "gpt-5.6-sol": {
        "input": 5.00, "cached_input": 0.50, "cache_write": 6.25,
        "output": 30.00,
    },
    "gpt-5.6-terra": {
        "input": 2.00, "cached_input": 0.20, "cache_write": 2.50,
        "output": 12.00,
    },
    "gpt-5.6-luna": {
        "input": 0.20, "cached_input": 0.02, "cache_write": 0.25,
        "output": 1.20,
    },
}

_PER_MILLION = 1_000_000.0

# Codex speaks two dialects: the `exec` transport reports snake_case, the
# app-server reports camelCase (which is why normalize_token_usage carries
# both). A payload in the dialect we do not read would price every band at
# zero and report it as a KNOWN zero, so both are read here and a payload
# in neither is unknown.
_CODEX_BANDS = (
    ("input_tokens", "inputTokens"),
    ("cached_input_tokens", "cachedInputTokens"),
    ("cache_write_input_tokens", "cacheWriteInputTokens"),
    ("output_tokens", "outputTokens"),
)


def codex_api_cost(model, provider_output):
    """Price a Codex turn from its reported token bands.

    Codex reports cached input as a SUBSET of input_tokens, and cache-write
    input the same way; the fresh remainder is what is left. The subtraction
    is clamped at zero so that if a future codex ever reports those bands
    additively instead, the result is a mild undercount rather than a
    negative price.

    A model may declare a long-context tier in its rate entry. That tier is
    selected from the physical call's total reported input and applies to the
    whole call; without that total, the tier and therefore the price are
    unknown.

    reasoning_output_tokens is a breakdown of output_tokens and is therefore
    never charged again on top of it.
    """
    if not isinstance(provider_output, dict):
        return None
    rates = CODEX_RATES.get(model)
    if rates is None:
        # An unpriced model yields an unknown quote, never a free one.
        return None

    def band(snake, camel):
        if snake in provider_output:
            return _count(provider_output.get(snake))
        return _count(provider_output.get(camel))

    # A payload naming none of the bands is not a free turn — it is a shape
    # this function does not understand, and saying "$0.00" to that would be
    # the one lie this module exists to prevent.
    if not any(
        snake in provider_output or camel in provider_output
        for snake, camel in _CODEX_BANDS
    ):
        return None
    reported_input = band("input_tokens", "inputTokens")
    cached_input = band("cached_input_tokens", "cachedInputTokens")
    cache_write = band("cache_write_input_tokens", "cacheWriteInputTokens")
    output = band("output_tokens", "outputTokens")
    fresh_input = max(reported_input - cached_input - cache_write, 0)

    input_multiplier = 1.0
    output_multiplier = 1.0
    long_context = rates.get("long_context")
    if long_context is not None:
        raw_input = provider_output.get(
            "input_tokens", provider_output.get("inputTokens")
        )
        if _amount(raw_input) is None:
            # Without the total prompt-token count, the applicable Astra
            # tier cannot be known. Do not underprice a possibly long call.
            return None
        if reported_input > long_context["input_tokens_over"]:
            input_multiplier = long_context["input_multiplier"]
            output_multiplier = long_context["output_multiplier"]
    total = (
        fresh_input * rates["input"] * input_multiplier
        + cached_input * rates["cached_input"] * input_multiplier
        + cache_write * rates["cache_write"] * input_multiplier
        + output * rates["output"] * output_multiplier
    )
    return total / _PER_MILLION


# ---------------------------------------------------------------------------
# The contract.

ADAPTERS = {
    "claude": claude_api_cost,
    "codex": codex_api_cost,
}


def quote(family, model, provider_output, billing=None):
    """Cost of one worker call, under both readings.

    family/model name who ran; provider_output is that provider's own payload
    (see the module docstring). billing is the family's payment mode; absent,
    DEFAULT_BILLING decides, and an unrecognized mode is treated as a
    subscription seat rather than inventing a charge.

    An unknown api_usd makes BOTH fields None: a cost that cannot be computed
    is unknown under either reading, and callers must record it as partial.
    """
    adapter = ADAPTERS.get(family)
    if adapter is None:
        return UNKNOWN
    api_usd = adapter(model, provider_output)
    if api_usd is None:
        return UNKNOWN
    if billing is None:
        billing = DEFAULT_BILLING.get(family, BILLING_SUBSCRIPTION)
    if billing not in BILLING_MODES:
        # "API", "metered", True, a typo: any of these once read as a free
        # seat and reported a metered account as costing nothing. A mode we
        # do not recognize makes the REAL figure unknown -- the equivalent is
        # still computable and still worth showing.
        return Quote(api_usd=api_usd, real_usd=None)
    real_usd = api_usd if billing == BILLING_API else 0.0
    return Quote(api_usd=api_usd, real_usd=real_usd)


def quote_many(family, model, provider_outputs, billing=None):
    """Cost of one LOGICAL call, which may have billed more than once.

    A contract repair is a second physical call, and a controlled Codex turn
    accumulates one payload per response; both must be charged in full, so
    runners hand pricing the whole list and the summing rule lives here.

    An empty list is UNKNOWN, not free: a call whose provider said nothing
    about what it spent has not been shown to have spent nothing.
    """
    payloads = list(provider_outputs or [])
    if not payloads:
        return UNKNOWN
    return add_quotes(*[
        quote(family, model, payload, billing=billing) for payload in payloads
    ])


def add_quotes(*quotes):
    """Sum call quotes into one. A single unknown field poisons that field of
    the total — the same discipline token usage already follows, so a run
    total can never quietly omit a call it could not price.

    Returns UNKNOWN when nothing summable was supplied.
    """
    seen = False
    api_total = 0.0
    real_total = 0.0
    api_known = True
    real_known = True
    for item in quotes:
        if item is None:
            continue
        seen = True
        if item.api_usd is None:
            api_known = False
        else:
            api_total += item.api_usd
        if item.real_usd is None:
            real_known = False
        else:
            real_total += item.real_usd
    if not seen:
        return UNKNOWN
    return Quote(
        api_usd=api_total if api_known else None,
        real_usd=real_total if real_known else None,
    )
