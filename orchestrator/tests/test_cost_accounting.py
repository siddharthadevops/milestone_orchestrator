import unittest

from orchestrator import contracts, driver, pricing, runners
from orchestrator import state as st
from orchestrator.tests.test_state import (
    default_draft_for,
    dirty_review,
    make_state,
    seal_current_unit,
    skeleton_draft,
)


def _priced(api, real):
    return {"api_usd": api, "real_usd": real}


class CostAggregationTest(unittest.TestCase):
    def setUp(self):
        self.state = make_state("/tmp/does-not-need-to-exist")
        seal_current_unit(self.state, skeleton_draft(1))
        self.unit = st.ensure_next_unit(self.state)

    def _draft(self, cost=None, cost_partial=False, duration=1.0):
        st.record_draft(
            self.state, self.unit, contracts.KIND_DRAFT_SLICE_NOTE,
            default_draft_for(self.unit), duration=duration,
            family="claude", model="claude-opus-5",
            cost=cost, cost_partial=cost_partial,
        )

    def _round(self, cost=None, cost_partial=False, duration=1.0):
        st.transition_unit(self.state, self.unit, st.U_PRE_REVIEW_VERIFY)
        st.transition_unit(self.state, self.unit, st.U_ROUNDS)
        st.record_round(
            self.state, self.unit, "codex", contracts.KIND_REVIEW_ROUND,
            dirty_review(n=1), duration=duration,
            cost=cost, cost_partial=cost_partial,
        )

    def _unit_view(self, summary):
        return next(
            view for view in summary["units"]
            if view["unit"] == st.unit_key(self.unit)
        )

    def test_a_priced_call_reaches_both_the_unit_and_the_run(self):
        self._draft(cost=_priced(0.0134499, 0.0))
        summary = st.summary(self.state)
        view = self._unit_view(summary)
        self.assertAlmostEqual(view["work_cost"]["api_usd"], 0.0134499)
        self.assertEqual(view["work_cost"]["real_usd"], 0.0)
        self.assertFalse(view["work_cost_partial"])
        self.assertAlmostEqual(
            summary["work_cost"]["api_usd"], 0.0134499
        )
        # The run total is partial, and correctly so: the skeleton sealed in
        # setUp carries unpriced work, exactly like a run that predates cost
        # accounting. The amount is still shown; it just stops claiming to be
        # the whole bill.
        self.assertTrue(summary["work_cost_partial"])

    def test_calls_accumulate(self):
        self._draft(cost=_priced(0.0134499, 0.0))
        self._round(cost=_priced(0.045824, 0.045824))
        summary = st.summary(self.state)
        view = self._unit_view(summary)
        self.assertAlmostEqual(view["work_cost"]["api_usd"], 0.0592739)
        self.assertAlmostEqual(view["work_cost"]["real_usd"], 0.045824)

    def test_an_unpriced_call_marks_partial_rather_than_vanishing(self):
        self._draft(cost=_priced(0.01, 0.0))
        self._round(cost=None)
        summary = st.summary(self.state)
        view = self._unit_view(summary)
        # The priced call is still counted...
        self.assertAlmostEqual(view["work_cost"]["api_usd"], 0.01)
        # ...but the total no longer claims to be the whole story.
        self.assertTrue(view["work_cost_partial"])
        self.assertTrue(summary["work_cost_partial"])

    def test_an_absent_price_marks_partial_however_brief_the_call(self):
        # Same discipline token usage already follows: a record with no price
        # is unknown, not free, and duration does not excuse it.
        self._draft(cost=None, duration=0.0)
        summary = st.summary(self.state)
        self.assertTrue(self._unit_view(summary)["work_cost_partial"])
        self.assertTrue(summary["work_cost_partial"])

    def test_work_that_never_became_a_record_is_charged_too(self):
        # An interrupted implementation, a malformed answer, a classifier
        # call: none of them end up as a draft or a round, and all of them
        # were paid for.
        st.append_event(
            self.state, "worker_interrupted",
            unit=st.unit_key(self.unit), duration_s=2.0,
            cost=_priced(0.02, 0.0), cost_partial=False,
        )
        view = self._unit_view(st.summary(self.state))
        self.assertAlmostEqual(view["work_cost"]["api_usd"], 0.02)
        self.assertFalse(view["work_cost_partial"])
        # Its tokens are genuinely unknown, and that stays independent of
        # whether the price is known.
        self.assertTrue(view["work_token_usage_partial"])

    def test_unattributable_work_still_reaches_the_run_total(self):
        st.append_event(
            self.state, "error_classifier_call", duration_s=1.0,
            cost=_priced(0.005, 0.0), cost_partial=False,
        )
        summary = st.summary(self.state)
        self.assertAlmostEqual(summary["work_cost"]["api_usd"], 0.005)
        # It belongs to no unit, so no unit claims it.
        self.assertIsNone(self._unit_view(summary)["work_cost"])

    def test_a_malformed_price_is_rejected_not_trusted(self):
        for bad in (
            {"api_usd": 1.0},                       # missing the other reading
            {"api_usd": "1.0", "real_usd": 0.0},    # not a number
            {"api_usd": -1.0, "real_usd": 0.0},     # negative money
            {"api_usd": 1.0, "real_usd": 2.0},      # real above the equivalent
            {"api_usd": float("inf"), "real_usd": 0.0},
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(st._normalized_cost(bad))

    def test_billing_mode_travels_with_the_summary(self):
        # A free seat and a zero-cost call look identical in the amounts, so
        # the panel needs the mode stated rather than inferred.
        summary = st.summary(self.state)
        self.assertEqual(
            summary["billing"], self.state["config"].get("billing") or {}
        )
        self.assertIn(
            summary["billing"].get("claude"),
            (pricing.BILLING_SUBSCRIPTION, pricing.BILLING_API, None),
        )


class CodexSessionDeltaTest(unittest.TestCase):
    """Codex's session counter is cumulative; pricing it as-is would
    re-charge every earlier turn on the current call."""

    def test_a_continued_turn_is_charged_only_for_itself(self):
        delta = runners.codex_payload_delta(
            {"input_tokens": 157000, "output_tokens": 9000},
            {"input_tokens": 105000, "output_tokens": 4000},
        )
        self.assertEqual(delta["input_tokens"], 52000)
        self.assertEqual(delta["output_tokens"], 5000)

    def test_the_first_turn_of_a_session_pays_for_itself(self):
        delta = runners.codex_payload_delta(
            {"input_tokens": 105000, "output_tokens": 4000}, None
        )
        self.assertEqual(delta["input_tokens"], 105000)

    def test_a_reset_counter_is_unknown_rather_than_guessed(self):
        self.assertIsNone(runners.codex_payload_delta(
            {"input_tokens": 10}, {"input_tokens": 999}
        ))

    def test_an_unrecognized_snapshot_is_unknown(self):
        self.assertIsNone(runners.codex_payload_delta({"tokens": 5}, None))
        self.assertIsNone(runners.codex_payload_delta(None, None))


class RepairAttributionTest(unittest.TestCase):
    """A contract repair is two physical calls whose accounting is SPLIT: the
    retry on the round/draft record, the first strike on its own malformed
    event. Money must follow the same split duration and tokens already do,
    or every repaired call inflates the run by its first attempt."""

    class _Shim(driver.Driver):
        def __init__(self):  # only the pricing helpers are exercised
            self.config = {"billing": {"claude": pricing.BILLING_API}}

    class _Result(object):
        cost_payloads = [{"total_cost_usd": 0.20}]
        repair = {"cost_payloads": [{"total_cost_usd": 0.10}]}

    def test_the_two_records_sum_to_what_was_actually_spent(self):
        shim, result = self._Shim(), self._Result()
        record = shim._quote_call("claude", "claude-opus-5", result)
        strike = shim._price_call("claude", "claude-opus-5", result.repair)
        self.assertAlmostEqual(record["api_usd"], 0.20)
        self.assertAlmostEqual(strike["api_usd"], 0.10)
        self.assertAlmostEqual(
            record["api_usd"] + strike["api_usd"], 0.30
        )

    def test_the_crash_sentinel_still_sees_the_whole_logical_call(self):
        shim, result = self._Shim(), self._Result()
        sentinel = shim._price_call(
            "claude", "claude-opus-5", result, include_repair=True
        )
        self.assertAlmostEqual(sentinel["api_usd"], 0.30)
        # ...and pricing the sentinel must not have written that combined
        # figure onto the record, which is what caused the double count.
        self.assertAlmostEqual(
            shim._quote_call("claude", "claude-opus-5", result)["api_usd"],
            0.20,
        )


class BillingModeTest(unittest.TestCase):
    def test_an_unrecognized_mode_does_not_report_a_metered_account_as_free(self):
        # "API", "metered", True: each once read as a seat and claimed no
        # money was spent.
        quoted = pricing.quote(
            "claude", "claude-opus-5", {"total_cost_usd": 2.5}, billing="API"
        )
        self.assertAlmostEqual(quoted.api_usd, 2.5)
        self.assertIsNone(quoted.real_usd)

    def test_a_malformed_billing_config_cannot_break_the_accounting(self):
        shim = RepairAttributionTest._Shim()
        shim.config = {"billing": "api"}  # a string where a dict belongs
        priced = shim._price_call(
            "claude", "claude-opus-5",
            RepairAttributionTest._Result(),
        )
        self.assertAlmostEqual(priced["api_usd"], 0.20)


class MergedPayloadTest(unittest.TestCase):
    def test_a_call_that_billed_but_cannot_be_priced_poisons_the_total(self):
        # Shortening the list instead would make unpriceable spend
        # indistinguishable from no spend, and the merged record would then
        # claim to be a complete price.
        class Unpriceable(object):
            cost_payloads = []

        class Priced(object):
            cost_payloads = [{"total_cost_usd": 0.02}]

        merged = runners.merged_cost_payloads(Unpriceable(), Priced())
        self.assertIn(None, merged)
        quoted = pricing.quote_many("claude", "claude-opus-5", merged)
        self.assertIsNone(quoted.api_usd)
        self.assertIsNone(quoted.real_usd)


if __name__ == "__main__":
    unittest.main()
