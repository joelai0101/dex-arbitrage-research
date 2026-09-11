import copy
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from delta_terminal.model import load_case, write_case
from delta_terminal.rpc import load_pools
from token_graph_dataset.reconstruct import read_source, reconstruct
from token_graph_dataset.verify import minimum_cycle, verify


def fixture():
    """Synthetic unit-test data; never presented as captured market observations."""
    pools = []
    for p in load_pools()[0]:
        row = {"pair_address": p["address"], "chain_id": "1", "dex_name": "Uniswap v2",
               "fee_numerator": "997", "fee_denominator": "1000",
               "factory_get_pair_verified": "True", "creation_event_verified": "True",
               "creation_event_pair_address": p["address"], "creation_block": "10",
               "creation_transaction_hash": "0x"+"a"*64}
        for i in (0, 1):
            for key in ("address", "symbol", "decimals"):
                row[f"token{i}_{key}"] = str(p[f"token{i}"][key])
        pools.append(row)
    def event(n, tx, log, pool, values):
        return {"block_number": str(n), "block_hash": f"0x{n:064x}",
                "transaction_hash": f"0x{1000+n*10+tx:064x}",
                "transaction_index": str(tx), "log_index": str(log),
                "pair_address": pools[pool]["pair_address"], "event_type": "Sync", "removed": "False",
                "reserve0_raw": str(values[0]), "reserve1_raw": str(values[1])}
    events = [event(100, 0, i, i, (1000, 1000)) for i in range(3)]
    events += [event(101, 0, 0, 0, (1000, 1500)), event(101, 0, 1, 1, (1000, 1200)),
               event(101, 0, 2, 0, (1000, 2000)),
               event(102, 0, 0, 2, (0, 1000)), event(102, 1, 1, 2, (1000, 900))]
    states = [[(1000,1000)]*3, [(1000,2000),(1000,1200),(1000,1000)],
              [(1000,2000),(1000,1200),(1000,900)]]
    snapshots, anchors = [], []
    for number, values in enumerate(states, 100):
        for p, reserves in zip(pools, values):
            snapshots.append({"block_number": str(number), "pair_address": p["pair_address"],
                              "chain_id": "1", "token0_address": p["token0_address"], "token1_address": p["token1_address"],
                              "reserve0_raw": str(reserves[0]), "reserve1_raw": str(reserves[1])})
            if number == 100:
                anchors.append({"block_number": "100", "pair_address": p["pair_address"],
                                "historical_call_reserve0_raw": "1000", "historical_call_reserve1_raw": "1000",
                                "archive_call_status": "available"})
    return {"schema": "recorded_uniswap_v2_v1", "start_block": 100, "end_block": 102,
            "source": {"fixture": True}, "pools": pools, "sync_events": events,
            "blocks": [{"block_number": str(n), "block_hash": f"0x{n:064x}", "parent_hash": f"0x{n-1:064x}"} for n in range(100,103)],
            "snapshots": snapshots, "archive_checks": anchors}


class DatasetTests(unittest.TestCase):
    def test_fee_direction_and_decimal_units(self):
        case = reconstruct(fixture())
        ids = {node["symbol"]: node["id"] for node in case.metadata["nodes"]}
        graph = {(u,v): weight for u,v,weight in case.graph}
        self.assertAlmostEqual(graph[ids["USDC"],ids["WETH"]], -math.log(0.997e-12))
        self.assertAlmostEqual(graph[ids["WETH"],ids["USDC"]], -math.log(0.997e12))
        self.assertAlmostEqual(graph[ids["USDC"],ids["USDT"]], -math.log(0.997))

    def test_transaction_atomicity_and_reactivation(self):
        case = reconstruct(fixture())
        self.assertEqual(case.boundaries, [4, 6, 8])
        self.assertEqual(case.metadata["checks"]["update_sync_events"], 5)
        self.assertTrue(all(w == "D" for u,v,w in case.updates[4:6]))
        self.assertTrue(all(isinstance(w, float) for u,v,w in case.updates[6:]))
        report = verify(case)
        self.assertEqual(report["answers_checked"], 4)
        self.assertEqual(report["restricted_matches"], report["global_matches"])
        self.assertIsNone(report["results"][2]["global_oracle"]["weight"])
        self.assertGreater(report["global_negative_states"], 0)

    def test_unordered_input_is_deterministic(self):
        source = fixture()
        expected = reconstruct(source)
        source["sync_events"].reverse()
        source["blocks"].reverse()
        self.assertEqual(reconstruct(source), expected)

    def test_no_update_case(self):
        source = fixture()
        source["end_block"] = 100
        for key, field in (("blocks", "block_number"), ("sync_events", "block_number"), ("snapshots", "block_number")):
            source[key] = [row for row in source[key] if int(row[field]) == 100]
        case = reconstruct(source)
        self.assertEqual(case.boundaries, [])
        self.assertEqual(verify(case)["answers_checked"], 1)

    def test_invalid_events_are_rejected(self):
        changes = [("removed", "True"), ("block_hash", "0x"+"f"*64),
                   ("transaction_hash", "0x"+"f"*64), ("reserve0_raw", "-1"),
                   ("reserve1_raw", str(2**112)), ("pair_address", "0x"+"f"*40),
                   ("log_index", "0")]
        for key, value in changes:
            source = fixture()
            source["sync_events"][4][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                reconstruct(source)
        source = fixture()
        source["sync_events"].append(copy.deepcopy(source["sync_events"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate log"):
            reconstruct(source)

    def test_missing_or_inconsistent_states_rejected(self):
        for key in ("blocks", "snapshots", "archive_checks"):
            source = fixture()
            source[key].pop(0)
            with self.subTest(key=key), self.assertRaises(ValueError):
                reconstruct(source)
        for key, field in (("blocks", "parent_hash"), ("snapshots", "reserve0_raw"),
                           ("archive_checks", "historical_call_reserve0_raw")):
            source = fixture()
            source[key][1][field] = "0x"+"f"*64 if key == "blocks" else "999"
            with self.subTest(key=key), self.assertRaises(ValueError):
                reconstruct(source)
        source = fixture()
        source["sync_events"].pop(0)
        with self.assertRaisesRegex(ValueError, "Missing initial"):
            reconstruct(source)

    def test_parallel_pools_and_fee_rejected(self):
        source = fixture()
        source["pools"].append(copy.deepcopy(source["pools"][0]))
        with self.assertRaises(ValueError):
            reconstruct(source)
        source = fixture()
        source["pools"][0]["fee_numerator"] = "1000"
        with self.assertRaisesRegex(ValueError, "fee"):
            reconstruct(source)

    def test_oracle_distinguishes_color_coverage(self):
        graph = {(0,1): -2., (1,2): -2., (2,0): -2., (0,3): 1., (3,2): 1.}
        self.assertEqual(minimum_cycle(graph,4,3)["weight"], -6.)
        self.assertEqual(minimum_cycle(graph,4,3,[0,0,2,1])["weight"], 0.)

    def test_saved_case_and_cli_replay(self):
        source = fixture()
        case = reconstruct(source)
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"case"
            write_case(case, folder)
            (folder/"source.json").write_text(json.dumps(source), encoding="utf-8")
            self.assertEqual(load_case(folder), case)
            output = Path(root)/"result.json"
            command = [sys.executable, "-m", "token_graph_dataset", "verify", "--case", str(folder), "--output", str(output)]
            subprocess.run(command, check=True, capture_output=True, timeout=30)
            report = json.loads(output.read_text())
            self.assertEqual(report["status"], "passed")
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=30).returncode, 0)
            (folder/"graph.txt").write_text("0 1 1\n", encoding="utf-8")
            command[-1] = str(Path(root)/"tampered.json")
            self.assertNotEqual(subprocess.run(command, capture_output=True, timeout=30).returncode, 0)
            self.assertFalse(Path(command[-1]).exists())

    def test_recorded_csv_import_and_range(self):
        source = fixture()
        names = {"block_metadata.csv": "blocks", "pool_metadata.csv": "pools", "pool_events.csv": "sync_events",
                 "pool_state_snapshots.csv": "snapshots", "archive_state_checks.csv": "archive_checks"}
        with tempfile.TemporaryDirectory() as root:
            for name, key in names.items():
                with (Path(root)/name).open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(source[key][0]))
                    writer.writeheader()
                    writer.writerows(source[key])
            (Path(root)/"run_metadata.json").write_text(json.dumps({"chain_id": 1, "dex_name": "Uniswap v2",
                 "finality_tag": "finalized", "finalized_block_at_start": 200, "start_block": 100,
                 "end_block": 102, "run_completed_at_utc": "fixture"}), encoding="utf-8")
            captured = read_source(root, None, 3)
            case = reconstruct(captured)
            self.assertEqual(case.graph, reconstruct(source).graph)
            self.assertEqual(len(captured["source"]["files"]), 5)
            with self.assertRaises(ValueError):
                read_source(root, 100, 4)


if __name__ == "__main__":
    unittest.main()
