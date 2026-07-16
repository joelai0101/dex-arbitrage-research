from __future__ import annotations

import unittest

from dex_arbitrage_feasibility.dex_feasibility.pipeline import reconstruct_snapshots


class SnapshotReconstructionTests(unittest.TestCase):
    def test_last_sync_wins_and_state_carries(self) -> None:
        metadata = [
            {
                "pair_id": "PAIR",
                "pair_address": "0x0000000000000000000000000000000000000001",
                "token0_address": "0x0000000000000000000000000000000000000002",
                "token1_address": "0x0000000000000000000000000000000000000003",
            }
        ]
        initial = [
            {
                "pair_id": "PAIR",
                "pair_address": metadata[0]["pair_address"],
                "block_number": 9,
                "reserve0_raw": 100,
                "reserve1_raw": 200,
            }
        ]
        events = [
            {
                "block_number": 9,
                "transaction_hash": "0xwarm",
                "transaction_index": 0,
                "log_index": 0,
                "pair_address": metadata[0]["pair_address"],
                "event_type": "Sync",
                "reserve0_raw": 100,
                "reserve1_raw": 200,
                "removed": False,
            },
            {
                "block_number": 10,
                "transaction_hash": "0xfirst",
                "transaction_index": 1,
                "log_index": 2,
                "pair_address": metadata[0]["pair_address"],
                "event_type": "Sync",
                "reserve0_raw": 110,
                "reserve1_raw": 190,
                "removed": False,
            },
            {
                "block_number": 10,
                "transaction_hash": "0xlast",
                "transaction_index": 2,
                "log_index": 3,
                "pair_address": metadata[0]["pair_address"],
                "event_type": "Sync",
                "reserve0_raw": 120,
                "reserve1_raw": 180,
                "removed": False,
            },
        ]
        rows = reconstruct_snapshots(metadata, events, initial, 10, 11)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["reserve0_raw"], 120)
        self.assertEqual(rows[0]["last_sync_transaction_hash"], "0xlast")
        self.assertEqual(rows[0]["state_quality_flag"], "observed_sync")
        self.assertEqual(rows[1]["reserve0_raw"], 120)
        self.assertEqual(rows[1]["state_quality_flag"], "carried_forward")


if __name__ == "__main__":
    unittest.main()
