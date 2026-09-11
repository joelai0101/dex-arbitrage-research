import csv
import json
import math
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from delta_terminal.app import run_case
from delta_terminal.build import PACKAGE
from delta_terminal.engine import solve
from delta_terminal.model import Case, load_case, write_case
from delta_terminal.rpc import RpcClient, RpcUnavailable, capture, load_pools, words


def oracle(graph, colors, k):
    best = None

    def visit(path, total):
        nonlocal best
        if len(path) == k:
            edge = (path[-1], path[0])
            if edge in graph:
                value = total + graph[edge]
                best = value if best is None else min(best, value)
            return
        for v in range(len(colors)):
            if v not in path and colors[v] not in {colors[u] for u in path} and (path[-1], v) in graph:
                visit(path + [v], total + graph[path[-1], v])
    for u in range(len(colors)):
        visit([u], 0.)
    return best


def assert_trace(test, case, answers):
    graph = {(u,v): w for u,v,w in case.graph}
    previous = 0
    test.assertEqual([a["row"] for a in answers], [0] + case.boundaries)
    for answer in answers:
        for u,v,w in case.updates[previous:answer["row"]]:
            if w == "D":
                graph.pop((u,v), None)
            elif w != "N":
                graph[u,v] = w
        previous = answer["row"]
        expected = oracle(graph, case.colors, case.k)
        if expected is None:
            test.assertIsNone(answer["weight"])
            test.assertEqual(answer["path"], [])
        else:
            test.assertTrue(math.isclose(expected, answer["weight"], abs_tol=1e-10, rel_tol=1e-10))
            path = answer["path"]
            test.assertEqual(len(path), case.k+1)
            test.assertEqual(path[0], path[-1])
            test.assertEqual(len(set(path[:-1])), case.k)
            test.assertEqual(len({case.colors[v] for v in path[:-1]}), case.k)
            test.assertTrue(math.isclose(sum(graph[u,v] for u,v in zip(path,path[1:])), answer["weight"], abs_tol=1e-10, rel_tol=1e-10))


class FakeRpc:
    budget, calls, host = 64, 0, "fixture.invalid"

    def __init__(self, broken=False, inactive=False):
        self.pools, self.tokens = load_pools()
        self.broken, self.inactive = broken, inactive
        self.reads = 0

    def call(self, method, params):
        self.calls += 1
        if method == "eth_chainId":
            return "0x1"
        if method == "eth_getBlockByNumber":
            n = 101 if params[0] == "finalized" else int(params[0],16)
            self.reads += 1
            h = 999 if self.broken and self.reads == 3 else n
            return {"number":hex(n), "hash":f"0x{h:064x}", "parentHash":f"0x{n-1:064x}"}
        call, block = params
        if call["data"] == "0x313ce567":
            values = [self.tokens[call["to"]]["decimals"]]
        else:
            p = next(p for p in self.pools if p["address"] == call["to"])
            if call["data"] in ("0x0dfe1681", "0xd21220a7"):
                values = [int(p["token0" if call["data"] == "0x0dfe1681" else "token1"]["address"],16)]
            else:
                values = [1000*10**p["token0"]["decimals"], (1000+int(block,16))*10**p["token1"]["decimals"], 123]
                if self.inactive and int(block,16)==101:
                    values[0] = 0
        return "0x" + "".join(f"{v:064x}" for v in values)


class TerminalTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("DELTA_REFERENCE_EXE"), "optional original binary comparison")
    def test_original_binary(self):
        case = load_case(Path(os.environ.get("DELTA_REFERENCE_CASE", PACKAGE / "examples/toy")))
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"case"
            write_case(case,folder)
            trace = Path(root)/"original.tsv"
            subprocess.run([os.environ["DELTA_REFERENCE_EXE"],str(folder),str(case.k),"group",str(trace),str(folder/"schedule.txt")],capture_output=True,check=True,timeout=30)
            with trace.open(encoding="utf-8") as stream:
                original = list(csv.DictReader(stream,delimiter="\t"))
            current = solve(case)
            assert_trace(self, case, current)
            self.assertEqual(len(original),len(current))
            for old,new in zip(original,current):
                self.assertEqual(int(old["row"]),new["row"])
                self.assertEqual(None if old["weight"]=="none" else float(old["weight"]),new["weight"])
                self.assertEqual(list(map(int,old["path"].split())),new["path"])

    def test_original_teaching_answers(self):
        case = load_case(PACKAGE / "examples/toy")
        answers = solve(case)
        self.assertEqual([a["weight"] for a in answers], [-1,1,1,2,None,-2,-2,-2,-3])
        assert_trace(self, case, answers)

    def test_random_updates_and_batching(self):
        for seed in range(12):
            rng = random.Random(seed)
            n, k = 7, 2+seed%4
            colors = [i%k for i in range(n)]
            graph = [(u,v,float(rng.randrange(-8,9))) for u in range(n) for v in range(n) if u!=v and rng.random()<.3]
            updates = []
            for _ in range(30):
                u,v = rng.sample(range(n),2)
                updates.append((u,v,rng.choice(["D","N",float(rng.randrange(-8,9))])))
            for batch in (1,7,30):
                boundaries = list(range(batch,30,batch))+[30]
                case = Case(k, colors, graph, updates, boundaries,{})
                with self.subTest(seed=seed,batch=batch):
                    assert_trace(self, case, solve(case))

    def test_rpc_export_replay_exact(self):
        case = capture(FakeRpc(), blocks=2)
        answers = solve(case)
        assert_trace(self, case, answers)
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"case"
            write_case(case, folder)
            replay = solve(load_case(folder))
            for a,b in zip(answers,replay):
                self.assertEqual((a["row"],a["weight"],a["path"]), (b["row"],b["weight"],b["path"]))
            with self.assertRaises(FileExistsError):
                write_case(case, folder)

    def test_zero_reserve_deactivates_pool(self):
        case = capture(FakeRpc(inactive=True), blocks=2)
        self.assertEqual(len(case.updates), 6)
        self.assertTrue(all(w=="D" for u,v,w in case.updates))
        answers = solve(case)
        self.assertIsNone(answers[-1]["weight"])
        assert_trace(self, case, answers)

    def test_reorg_rejected(self):
        with self.assertRaises(RpcUnavailable):
            capture(FakeRpc(broken=True), blocks=2)

    def test_input_validation(self):
        base = load_case(PACKAGE/"examples/toy")
        for graph in ([(0,1,float("nan"))],[(0,0,1.)],[(0,99,1.)],[(0,1,1.),(0,1,2.)]):
            with self.assertRaises(ValueError):
                Case(3,base.colors,graph,[],[],{}).validate()
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)/"case"
            write_case(base, folder)
            (folder/"graph.txt").write_text("0 1 2 extra\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_case(folder)

    def test_error_does_not_leak_rpc_key(self):
        secret = "https://example.invalid/v2/SECRET_TEST_TOKEN"
        opener = unittest.mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(secret,401,"SECRET_TEST_TOKEN",{},None)
        client = RpcClient(secret, interval=0, opener=opener)
        with self.assertRaises(RpcUnavailable) as caught:
            client.call("eth_chainId",[])
        self.assertNotIn("SECRET_TEST_TOKEN", str(caught.exception))
        self.assertEqual(client.calls,1)
        with self.assertRaises(ValueError):
            client.call("eth_sendRawTransaction",[])

    def test_rpc_budget_and_abi(self):
        with self.assertRaises(RpcUnavailable):
            RpcClient("https://example.invalid",budget=0).call("eth_chainId",[])
        for invalid in ("0x", "0x"+"z"*64, None):
            with self.assertRaises(RpcUnavailable):
                words(invalid,1)
        with self.assertRaises(ValueError):
            capture(FakeRpc(),blocks=11)

    def test_partial_run_is_not_success(self):
        case = load_case(PACKAGE/"examples/toy")
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)/"result"
            with patch("delta_terminal.app.solve", side_effect=RuntimeError("test failure")):
                with self.assertRaises(RuntimeError):
                    run_case(case,output,"offline")
            self.assertEqual(json.loads((output/"results.json").read_text(encoding="utf-8"))["status"],"失敗／中止")


if __name__ == "__main__":
    unittest.main()
