from __future__ import annotations

import unittest
from decimal import Decimal

from dex_arbitrage_feasibility.dex_feasibility.core import (
    address_topic,
    block_chain_is_continuous,
    decimal_to_raw,
    evenly_spaced_sample,
    gas_cost_weth,
    get_amount_out,
    quantile_int,
    raw_to_decimal,
)


class CoreCalculationTests(unittest.TestCase):
    def test_uniswap_v2_integer_floor_manual_case(self) -> None:
        self.assertEqual(get_amount_out(10, 1000, 2000), 19)

    def test_fee_is_not_optional_or_reapplied(self) -> None:
        once = get_amount_out(10**18, 100 * 10**18, 200_000 * 10**6)
        twice = get_amount_out(once, 200_000 * 10**6, 100 * 10**18)
        self.assertGreater(once, 0)
        self.assertLess(twice, 10**18)

    def test_gas_conversion(self) -> None:
        self.assertEqual(gas_cost_weth(150_000, 30_000_000_000), Decimal("0.0045"))

    def test_decimal_raw_roundtrip(self) -> None:
        raw = decimal_to_raw("0.01", 18)
        self.assertEqual(raw, 10**16)
        self.assertEqual(raw_to_decimal(raw, 18), Decimal("0.01"))

    def test_quantile_interpolation(self) -> None:
        self.assertEqual(quantile_int([100, 200, 300, 400], 0.5), 250)
        self.assertEqual(quantile_int([100, 200, 300, 400], 0.25), 175)

    def test_even_sample_is_deterministic(self) -> None:
        values = [f"tx-{index}" for index in range(100)]
        sample = evenly_spaced_sample(values, 5)
        self.assertEqual(sample, ["tx-0", "tx-25", "tx-50", "tx-74", "tx-99"])

    def test_address_topic(self) -> None:
        address = "0x00000000000000000000000000000000000000ab"
        self.assertEqual(address_topic(address), "0x" + "0" * 62 + "ab")

    def test_block_hash_continuity(self) -> None:
        rows = [
            {"block_number": 1, "block_hash": "0xaa", "parent_hash": "0x00"},
            {"block_number": 2, "block_hash": "0xbb", "parent_hash": "0xaa"},
        ]
        self.assertTrue(block_chain_is_continuous(rows))
        rows[1]["parent_hash"] = "0xcc"
        self.assertFalse(block_chain_is_continuous(rows))


if __name__ == "__main__":
    unittest.main()
