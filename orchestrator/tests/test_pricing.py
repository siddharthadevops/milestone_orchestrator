import unittest

from orchestrator import pricing


class ClaudeAdapterTest(unittest.TestCase):
    def test_takes_the_providers_own_figure_verbatim(self):
        payload = {"total_cost_usd": 0.013449899999999999, "usage": {}}
        self.assertEqual(
            pricing.claude_api_cost("claude-opus-5", payload),
            0.013449899999999999,
        )

    def test_figure_is_model_resolved_so_the_model_never_matters(self):
        payload = {"total_cost_usd": 1.5}
        self.assertEqual(
            pricing.claude_api_cost("a-model-nobody-has-heard-of", payload),
            1.5,
        )

    def test_absent_figure_is_unknown_not_free(self):
        self.assertIsNone(pricing.claude_api_cost("claude-opus-5", {}))

    def test_malformed_payload_is_unknown(self):
        for payload in (None, "0.5", [], {"total_cost_usd": "0.5"},
                        {"total_cost_usd": True},
                        {"total_cost_usd": float("nan")},
                        {"total_cost_usd": float("inf")},
                        {"total_cost_usd": -1.0}):
            with self.subTest(payload=payload):
                self.assertIsNone(
                    pricing.claude_api_cost("claude-opus-5", payload)
                )

    def test_zero_is_a_real_answer(self):
        self.assertEqual(
            pricing.claude_api_cost("claude-opus-5", {"total_cost_usd": 0.0}),
            0.0,
        )


class CodexAdapterTest(unittest.TestCase):
    def test_prices_a_real_turn(self):
        # Shape observed from `codex exec --json`.
        payload = {
            "input_tokens": 19042,
            "cached_input_tokens": 11008,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 0,
        }
        # fresh 8034 @ $5 + cached 11008 @ $0.50 + output 5 @ $30
        self.assertAlmostEqual(
            pricing.codex_api_cost("gpt-5.6-sol", payload),
            (8034 * 5.00 + 11008 * 0.50 + 5 * 30.00) / 1_000_000.0,
        )

    def test_cache_write_is_charged_at_its_own_rate(self):
        payload = {
            "input_tokens": 1000,
            "cached_input_tokens": 200,
            "cache_write_input_tokens": 300,
            "output_tokens": 100,
        }
        self.assertAlmostEqual(
            pricing.codex_api_cost("gpt-5.6-sol", payload),
            (500 * 5.00 + 200 * 0.50 + 300 * 6.25 + 100 * 30.00) / 1_000_000.0,
        )

    def test_every_available_model_is_priced(self):
        million_in = {"input_tokens": 1_000_000}
        million_out = {"output_tokens": 1_000_000}
        for model, expect_in, expect_out in (
            ("gpt-5.6-sol", 5.00, 30.00),
            ("gpt-5.6-terra", 2.00, 12.00),
            ("gpt-5.6-luna", 0.20, 1.20),
        ):
            with self.subTest(model=model):
                self.assertAlmostEqual(
                    pricing.codex_api_cost(model, million_in), expect_in
                )
                self.assertAlmostEqual(
                    pricing.codex_api_cost(model, million_out), expect_out
                )

    def test_reasoning_output_is_not_charged_twice(self):
        without = {"output_tokens": 1000}
        within = {"output_tokens": 1000, "reasoning_output_tokens": 900}
        self.assertEqual(
            pricing.codex_api_cost("gpt-5.6-sol", without),
            pricing.codex_api_cost("gpt-5.6-sol", within),
        )

    def test_unpriced_model_is_unknown_never_free(self):
        payload = {"input_tokens": 1000, "output_tokens": 1000}
        self.assertIsNone(pricing.codex_api_cost("gpt-9.9-nova", payload))
        self.assertIsNone(pricing.codex_api_cost(None, payload))

    def test_additively_reported_bands_undercount_rather_than_go_negative(self):
        # If a future codex reported cached/write ALONGSIDE input instead of
        # inside it, the fresh remainder must clamp, not turn the price
        # negative.
        payload = {
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "cache_write_input_tokens": 50,
            "output_tokens": 0,
        }
        priced = pricing.codex_api_cost("gpt-5.6-sol", payload)
        self.assertAlmostEqual(
            priced, (80 * 0.50 + 50 * 6.25) / 1_000_000.0
        )
        self.assertGreaterEqual(priced, 0.0)

    def test_the_app_server_dialect_is_priced_the_same(self):
        # codex reports camelCase over the app-server transport. Reading only
        # snake_case would price every band at zero and call it KNOWN.
        camel = {
            "inputTokens": 19042, "cachedInputTokens": 11008,
            "cacheWriteInputTokens": 0, "outputTokens": 5,
        }
        snake = {
            "input_tokens": 19042, "cached_input_tokens": 11008,
            "cache_write_input_tokens": 0, "output_tokens": 5,
        }
        self.assertEqual(
            pricing.codex_api_cost("gpt-5.6-sol", camel),
            pricing.codex_api_cost("gpt-5.6-sol", snake),
        )
        self.assertGreater(pricing.codex_api_cost("gpt-5.6-sol", camel), 0)

    def test_a_payload_naming_no_band_is_unknown_not_free(self):
        # The shape is unrecognized, not empty of charges.
        self.assertIsNone(pricing.codex_api_cost("gpt-5.6-sol", {}))
        self.assertIsNone(
            pricing.codex_api_cost("gpt-5.6-sol", {"tokens": 500})
        )

    def test_a_recognized_band_at_zero_really_is_free(self):
        self.assertEqual(
            pricing.codex_api_cost("gpt-5.6-sol", {"output_tokens": 0}), 0.0
        )

    def test_malformed_payload_is_unknown(self):
        for payload in (None, "tokens", []):
            with self.subTest(payload=payload):
                self.assertIsNone(
                    pricing.codex_api_cost("gpt-5.6-sol", payload)
                )

    def test_unusable_counts_do_not_poison_the_arithmetic(self):
        payload = {
            "input_tokens": -5,
            "cached_input_tokens": True,
            "cache_write_input_tokens": float("nan"),
            "output_tokens": 1000,
        }
        self.assertAlmostEqual(
            pricing.codex_api_cost("gpt-5.6-sol", payload),
            1000 * 30.00 / 1_000_000.0,
        )


class ContractTest(unittest.TestCase):
    def test_subscription_seat_spends_no_marginal_money(self):
        quote = pricing.quote(
            "claude", "claude-opus-5", {"total_cost_usd": 2.5},
            billing=pricing.BILLING_SUBSCRIPTION,
        )
        self.assertEqual(quote.api_usd, 2.5)
        self.assertEqual(quote.real_usd, 0.0)

    def test_metered_account_pays_the_api_equivalent(self):
        quote = pricing.quote(
            "claude", "claude-opus-5", {"total_cost_usd": 2.5},
            billing=pricing.BILLING_API,
        )
        self.assertEqual(quote.api_usd, 2.5)
        self.assertEqual(quote.real_usd, 2.5)

    def test_absent_billing_mode_falls_back_to_the_declared_default(self):
        quote = pricing.quote(
            "codex", "gpt-5.6-luna", {"output_tokens": 1_000_000}
        )
        self.assertAlmostEqual(quote.api_usd, 1.20)
        self.assertEqual(
            quote.real_usd,
            1.20 if pricing.DEFAULT_BILLING["codex"] == pricing.BILLING_API
            else 0.0,
        )

    def test_unrecognized_billing_mode_leaves_real_money_unknown(self):
        # Treating it as a seat was the trap: a metered account with a typo
        # in its mode ("API", "metered") would report "$0.00 charged".
        # Unknown is the only honest answer, and the equivalent still shows.
        quote = pricing.quote(
            "claude", "claude-opus-5", {"total_cost_usd": 2.5},
            billing="prepaid-vouchers",
        )
        self.assertEqual(quote.api_usd, 2.5)
        self.assertIsNone(quote.real_usd)

    def test_uncomputable_cost_is_unknown_under_both_readings(self):
        quote = pricing.quote(
            "codex", "gpt-9.9-nova", {"input_tokens": 1000},
            billing=pricing.BILLING_API,
        )
        self.assertIsNone(quote.api_usd)
        self.assertIsNone(quote.real_usd)

    def test_unknown_family_has_no_adapter_and_prices_nothing(self):
        quote = pricing.quote("gemini", "whatever", {"total_cost_usd": 1.0})
        self.assertIsNone(quote.api_usd)
        self.assertIsNone(quote.real_usd)

    def test_every_configured_family_has_an_adapter(self):
        for family in pricing.DEFAULT_BILLING:
            self.assertIn(family, pricing.ADAPTERS)


class QuoteManyTest(unittest.TestCase):
    def test_a_repair_pays_for_both_physical_calls(self):
        total = pricing.quote_many(
            "claude", "claude-opus-5",
            [{"total_cost_usd": 0.01}, {"total_cost_usd": 0.02}],
            billing=pricing.BILLING_API,
        )
        self.assertAlmostEqual(total.api_usd, 0.03)
        self.assertAlmostEqual(total.real_usd, 0.03)

    def test_a_controlled_turn_sums_every_response(self):
        total = pricing.quote_many(
            "codex", "gpt-5.6-luna",
            [{"output_tokens": 500_000}, {"output_tokens": 500_000}],
            billing=pricing.BILLING_API,
        )
        self.assertAlmostEqual(total.api_usd, 1.20)

    def test_silence_about_spending_is_unknown_not_free(self):
        self.assertEqual(
            pricing.quote_many("claude", "claude-opus-5", []), pricing.UNKNOWN
        )
        self.assertEqual(
            pricing.quote_many("claude", "claude-opus-5", None),
            pricing.UNKNOWN,
        )

    def test_one_unpriceable_payload_poisons_the_call(self):
        total = pricing.quote_many(
            "claude", "claude-opus-5",
            [{"total_cost_usd": 0.01}, {"no_cost_here": True}],
        )
        self.assertIsNone(total.api_usd)
        self.assertIsNone(total.real_usd)


class AddQuotesTest(unittest.TestCase):
    def test_sums_both_readings(self):
        total = pricing.add_quotes(
            pricing.Quote(1.5, 0.0), pricing.Quote(2.25, 2.25)
        )
        self.assertAlmostEqual(total.api_usd, 3.75)
        self.assertAlmostEqual(total.real_usd, 2.25)

    def test_one_unknown_call_poisons_only_its_own_field(self):
        total = pricing.add_quotes(
            pricing.Quote(1.5, 0.0), pricing.Quote(None, 2.0)
        )
        self.assertIsNone(total.api_usd)
        self.assertAlmostEqual(total.real_usd, 2.0)

    def test_an_unpriced_call_cannot_be_quietly_omitted(self):
        total = pricing.add_quotes(
            pricing.Quote(1.5, 0.0), pricing.UNKNOWN
        )
        self.assertIsNone(total.api_usd)
        self.assertIsNone(total.real_usd)

    def test_absent_entries_are_skipped(self):
        total = pricing.add_quotes(None, pricing.Quote(1.0, 1.0), None)
        self.assertAlmostEqual(total.api_usd, 1.0)
        self.assertAlmostEqual(total.real_usd, 1.0)

    def test_nothing_to_sum_is_unknown_not_zero(self):
        self.assertEqual(pricing.add_quotes(), pricing.UNKNOWN)
        self.assertEqual(pricing.add_quotes(None), pricing.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
