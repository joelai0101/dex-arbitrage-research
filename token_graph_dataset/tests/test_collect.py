import io
from fractions import Fraction
from itertools import combinations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from delta_terminal.model import load_case
from delta_terminal.rpc import RpcClient
from token_graph_dataset.__main__ import main
from token_graph_dataset.collect import FACTORY, SYNC, collect, universe
from token_graph_dataset.cover import color_cover, verify_cover
from token_graph_dataset.reconstruct import reconstruct
from token_graph_dataset.verify import minimum_cycle


class FakeOpener:
    """Synthetic RPC observations for five tokens, never market acceptance data."""
    def __init__(self, fault=None):
        self.tokens = universe()
        self.pairs = {f"0x{index+1:040x}": pair for index, pair in enumerate(combinations(self.tokens, 2))}
        self.lookups = {tuple(token["address"] for token in pair): pool for pool, pair in self.pairs.items()}
        self.fault = fault
        self.requests = []

    def log(self, n, log, pool, r1):
        return {"address": pool, "topics": [SYNC], "data": "0x"+f"{1000:064x}{r1:064x}",
                "blockNumber": hex(n), "blockHash": f"0x{n:064x}", "transactionHash": f"0x{n+1000:064x}",
                "transactionIndex": "0x0", "logIndex": hex(log), "removed": False}

    def open(self, request, timeout):
        packet = json.loads(request.data)
        self.requests.append(packet)
        method, params = packet["method"], packet["params"]
        if method == "eth_chainId":
            result = "0x1"
        elif method == "eth_getBlockByNumber":
            n = 102 if params[0] == "finalized" else int(params[0],16)
            result = {"number": hex(n), "hash": f"0x{n:064x}", "parentHash": f"0x{n-1:064x}"}
            if self.fault == "finality" and params[0] == "finalized":
                result["hash"] = "0x"+"f"*64
        elif method == "eth_getLogs":
            pools = list(self.pairs)
            result = [self.log(101,0,pools[0],2000), self.log(101,1,pools[1],1500), self.log(102,0,pools[0],2100)]
            lo, hi = int(params[0]["fromBlock"],16), int(params[0]["toBlock"],16)
            result = [log for log in result if lo <= int(log["blockNumber"],16) <= hi]
            if self.fault == "removed":
                result[0]["removed"] = True
            elif self.fault == "hash":
                result[0]["blockHash"] = "0x"+"f"*64
            elif self.fault == "duplicate":
                result.append(dict(result[0]))
            elif self.fault == "missing":
                result.pop()
            elif self.fault == "no_updates":
                result = []
        else:
            call, height = params
            if call["to"] == FACTORY:
                values = [int(self.lookups[("0x"+call["data"][34:74], "0x"+call["data"][98:138])],16)]
            elif call["data"] == "0x313ce567":
                values = [next(t["decimals"] for t in self.tokens if t["address"] == call["to"])]
            elif call["data"] in ("0x0dfe1681", "0xd21220a7"):
                values = [int(self.pairs[call["to"]][call["data"] == "0xd21220a7"]["address"],16)]
            else:
                r1 = 1000
                if int(height,16) == 102 and self.fault != "no_updates":
                    if call["to"] == list(self.pairs)[0]:
                        r1 = 2100
                    elif call["to"] == list(self.pairs)[1]:
                        r1 = 1500
                values = [1000,r1,123]
            result = "0x"+"".join(f"{v:064x}" for v in values)
        return io.BytesIO(json.dumps({"jsonrpc":"2.0", "id":packet["id"], "result":result}).encode())


class CollectionTests(unittest.TestCase):
    def test_exact_oracle_orders_near_zero_float_ties(self):
        graph = {(0,1): 0., (1,2): 0., (2,0): 0., (0,3): 0., (3,2): 0.}
        rates = {edge: Fraction(1) for edge in graph}
        rates[0,3] = Fraction(10**30+1,10**30)
        self.assertEqual(minimum_cycle(graph,4,3,rates=rates)["path"], [0,3,2,0])

    def client(self, fault=None, budget=256):
        return RpcClient("https://example.invalid/v2/TEST_SECRET", interval=0, budget=budget, opener=FakeOpener(fault))

    def test_capture_raw_observations_and_no_fake_initial_sync(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/"capture"
            client = self.client()
            source = collect(client, output, blocks=3, progress=lambda _: None)
            self.assertEqual(len(source["pools"]), 10)
            self.assertEqual(len(source["initial_reserves"]), 10)
            self.assertTrue(all(row["block_number"] > 100 for row in source["sync_events"]))
            case = reconstruct(source,5)
            self.assertEqual(case.boundaries, [4,6])
            self.assertEqual(case.metadata["initial_events"], [])
            self.assertEqual(case.metadata["checks"]["historical_call_matches"], 20)
            journal = (output/"rpc_responses.jsonl").read_text()
            self.assertEqual(len(journal.splitlines()), client.calls)
            self.assertNotIn("TEST_SECRET", journal + (output/"source.json").read_text())
            self.assertEqual(json.loads((output/"status.json").read_text())["status"], "completed")

    def test_bad_logs_fail_without_successful_source(self):
        for fault in ("removed", "hash", "duplicate", "missing", "finality"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as root:
                output = Path(root)/"capture"
                with self.assertRaises(ValueError):
                    collect(self.client(fault), output, blocks=3, progress=lambda _: None)
                self.assertFalse((output/"source.json").exists())
                self.assertEqual(json.loads((output/"status.json").read_text())["status"], "failed_or_interrupted")
                self.assertTrue((output/"rpc_responses.jsonl").exists())

    def test_limits_and_blank_rpc_do_not_write(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/"capture"
            client = self.client(budget=1)
            with self.assertRaises(ValueError):
                collect(client, output, blocks=3)
            self.assertEqual(client.calls,0)
            self.assertFalse(output.exists())
            for blank in ("", "  ", "\t\n"):
                with patch.dict("os.environ", {"DELTA_RPC_URL": blank}), patch("sys.argv", ["dataset", "capture", "--output", str(output)]), patch("token_graph_dataset.__main__.RpcClient") as rpc:
                    main()
                    rpc.assert_not_called()
                    self.assertFalse(output.exists())

    def test_full_cover_is_outcome_independent_and_complete(self):
        self.assertEqual(len(color_cover(5,4)),4)
        self.assertEqual(len(color_cover(5,5)),1)
        for k in (4,5):
            for subset in combinations(range(5), k):
                self.assertTrue(any(len({colors[v] for v in subset}) == k for colors in color_cover(5,k)))

    def test_rpc_window_without_sync_keeps_only_initial_answer(self):
        with tempfile.TemporaryDirectory() as root:
            source = collect(self.client("no_updates"), Path(root)/"capture", blocks=3, progress=lambda _: None)
            report = verify_cover(source, Path(root)/"cover", progress=lambda _: None)
            self.assertTrue(all(row["states"] == 1 and row["global_negative_states"] == 0 for row in report["results"]))

    def test_hundred_block_capture_obeys_ten_block_log_ranges(self):
        with tempfile.TemporaryDirectory() as root:
            client = self.client()
            source = collect(client, Path(root)/"capture", blocks=100, progress=lambda _: None)
            requests = [r["params"][0] for r in client.opener.requests if r["method"] == "eth_getLogs"]
            ranges = [(int(r["fromBlock"],16),int(r["toBlock"],16)) for r in requests]
            self.assertEqual(len(ranges),10)
            self.assertTrue(all(hi-lo+1 <= 10 for lo,hi in ranges))
            self.assertEqual([n for lo,hi in ranges for n in range(lo,hi+1)], list(range(source["start_block"]+1,source["end_block"]+1)))
            self.assertEqual(client.calls,169)

    def test_positive_four_and_five_hop_fixtures(self):
        with tempfile.TemporaryDirectory() as root:
            source = collect(self.client(), Path(root)/"capture", blocks=3, progress=lambda _: None)
            report = verify_cover(source, Path(root)/"cover", progress=lambda _: None)
            self.assertEqual(report["status"], "passed")
            for row in report["results"]:
                self.assertEqual(row["global_weight_matches"], row["states"])
                self.assertEqual(row["global_product_matches"], row["states"])
                self.assertGreater(row["global_negative_states"],0)
                self.assertEqual(row["delta_negative_states"],row["global_negative_states"])
            folder = Path(root)/"cover/k4/color_00"
            case = load_case(folder)
            self.assertEqual(case, reconstruct(source,4,case.colors))
            with patch("sys.argv", ["dataset", "verify", "--case", str(folder), "--output", str(Path(root)/"replay.json")]):
                main()


if __name__ == "__main__":
    unittest.main()
