"""Bounded read-only Ethereum RPC -> same-block Uniswap V2 graph snapshots."""
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from .model import Case

DEFAULT_POOLS = Path(__file__).with_name("rpc_pools.json")


class RpcUnavailable(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RpcClient:
    def __init__(self, url, *, interval=2.0, budget=64, opener=None, on_response=None):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("RPC 須為 HTTPS URL，不接受帳密 user-info 或 fragment。")
        self.url = url
        self.host = parsed.hostname
        self.interval, self.budget = interval, budget
        self.calls, self.last = 0, None
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.on_response = on_response

    def call(self, method, params):
        if method not in {"eth_chainId", "eth_getBlockByNumber", "eth_call", "eth_getLogs"}:
            raise ValueError("此介面只允許唯讀 RPC 方法。")
        if self.calls >= self.budget:
            raise RpcUnavailable("本次 RPC 請求額度已用完；已停止，不自動重試。")
        if self.last is not None:
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.calls += 1
        payload = json.dumps({"jsonrpc": "2.0", "id": self.calls, "method": method, "params": params}).encode()
        request = urllib.request.Request(self.url, payload, {"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=15) as response:
                data = json.load(response)
        except urllib.error.HTTPError as exc:
            # Provider bodies and exception strings may echo the secret URL.
            raise RpcUnavailable(f"RPC HTTP {exc.code}；已暫緩，不自動重試。") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise RpcUnavailable("RPC 連線或回應格式失敗；已暫緩，不自動重試。") from None
        if not isinstance(data, dict) or data.get("id") != self.calls or "error" in data or "result" not in data:
            raise RpcUnavailable(f"RPC {method} 未回傳有效結果；已暫緩。")
        if self.on_response:
            self.on_response(method, params, data)
        return data["result"]


def words(value, count):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{" + str(64*count) + r"}", value):
        raise RpcUnavailable("合約回傳 ABI 長度／格式不符。")
    return [int(value[2+i*64:2+(i+1)*64], 16) for i in range(count)]


def address(value):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
        raise ValueError("池／代幣地址格式錯誤。")
    return value.lower()


def load_pools(path=DEFAULT_POOLS):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    pools = config["pools"]
    if config.get("chain_id") != 1 or not 1 <= len(pools) <= 8:
        raise ValueError("目前支援 Ethereum mainnet，1–8 個 Uniswap V2 池。")
    pairs, tokens, addresses = set(), {}, set()
    for pool in pools:
        pool["address"] = address(pool["address"])
        pair = []
        for key in ("token0", "token1"):
            token = pool[key]
            token["address"] = address(token["address"])
            if type(token["decimals"]) is not int or not 0 <= token["decimals"] <= 36:
                raise ValueError("代幣 decimals 須為 0–36。")
            prior = tokens.setdefault(token["address"], token)
            if prior != token:
                raise ValueError("同一代幣的 metadata 不一致。")
            pair.append(token["address"])
        if pair[0] == pair[1] or tuple(sorted(pair)) in pairs or pool["address"] in addresses:
            raise ValueError("目前不合併平行池或重複池，請提供每個代幣 pair 一個池。")
        pairs.add(tuple(sorted(pair)))
        addresses.add(pool["address"])
    return pools, tokens


def block(client, tag):
    value = client.call("eth_getBlockByNumber", [tag, False])
    if not isinstance(value, dict):
        raise RpcUnavailable("RPC 未提供指定／finalized 區塊。")
    try:
        number = int(value["number"], 16)
        if any(not re.fullmatch(r"0x[0-9a-fA-F]{64}", value[key]) for key in ("hash", "parentHash")):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise RpcUnavailable("區塊 metadata 格式不符。") from None
    if tag.startswith("0x") and number != int(tag, 16):
        raise RpcUnavailable("RPC 回傳錯誤區塊高度。")
    return {"number": number, "hash": value["hash"].lower(), "parent_hash": value["parentHash"].lower()}


def capture(client, *, blocks=2, k=3, pool_path=DEFAULT_POOLS, start_block=None, progress=None):
    if not 1 <= blocks <= 10 or not 2 <= k <= 10:
        raise ValueError("RPC 小測試限 1–10 區塊，k=2–10。")
    pools, tokens = load_pools(pool_path)
    required_calls = 2 + len(pools)*2 + len(tokens) + blocks*(len(pools)+2)
    if required_calls > client.budget - client.calls:
        raise ValueError("區塊／池數超過本次 64 請求上限，請縮小小測試。")
    if client.call("eth_chainId", []) != "0x1":
        raise RpcUnavailable("RPC 不是 Ethereum mainnet，已停止。")
    final = block(client, "finalized")
    start = final["number"] - blocks + 1 if start_block is None else start_block
    if start < 0 or start + blocks - 1 > final["number"]:
        raise ValueError("僅擷取已 finalized 的完整區塊。")
    # Validate configured pool token order and token units at the first block.
    for pool in pools:
        for key, selector in (("token0", "0x0dfe1681"), ("token1", "0xd21220a7")):
            got = words(client.call("eth_call", [{"to": pool["address"], "data": selector}, hex(start)]), 1)[0]
            if got != int(pool[key]["address"], 16):
                raise RpcUnavailable("池 token0/token1 與設定不符。")
    for token in tokens.values():
        got = words(client.call("eth_call", [{"to": token["address"], "data": "0x313ce567"}, hex(start)]), 1)[0]
        if got != token["decimals"]:
            raise RpcUnavailable("代幣 decimals 與設定不符。")
    nodes = sorted(tokens)
    ids = {token: i for i, token in enumerate(nodes)}
    snapshots, graphs = [], []
    for number in range(start, start + blocks):
        before = block(client, hex(number))
        if snapshots and before["parent_hash"] != snapshots[-1]["hash"]:
            raise RpcUnavailable("區塊 parent hash 不連續，未將部分資料當成功。")
        graph, reserves = [], []
        for pool in pools:
            raw = words(client.call("eth_call", [{"to": pool["address"], "data": "0x0902f1ac"}, hex(number)]), 3)
            r0, r1, stamp = raw
            if not (0 <= r0 < 2**112 and 0 <= r1 < 2**112 and 0 <= stamp < 2**32):
                raise RpcUnavailable("getReserves 超出 Uniswap V2 ABI 範圍。")
            reserves.append({"pool": pool["address"], "reserve0": str(r0), "reserve1": str(r1), "timestamp": stamp})
            if min(r0, r1) == 0:
                continue  # Explicitly inactive pool, never interpolate missing reserves.
            for a, b, ra, rb in ((pool["token0"], pool["token1"], r0, r1), (pool["token1"], pool["token0"], r1, r0)):
                rate = Fraction(997*rb*10**a["decimals"], 1000*ra*10**b["decimals"])
                graph.append((ids[a["address"]], ids[b["address"]], -math.log(float(rate))))
        after = block(client, hex(number))
        if before != after:
            raise RpcUnavailable("擷取期間區塊 hash 改變，已停止。")
        snapshots.append({**before, "reserves": reserves})
        graphs.append(sorted(graph))
        if progress:
            progress(f"RPC 區塊 {number} 完成 ({len(graph)} 條有向邊；{client.calls} requests)")
    updates, boundaries = [], []
    previous = {(u,v): w for u,v,w in graphs[0]}
    for graph in graphs[1:]:
        current = {(u,v): w for u,v,w in graph}
        batch = [(u,v,current[(u,v)]) for u,v in sorted(current)]
        batch += [(u,v,"D") for u,v in sorted(previous.keys()-current.keys())]
        updates.extend(batch or [(0,0,"N")])
        boundaries.append(len(updates))
        previous = current
    metadata = {"source": "rpc_finalized_block_snapshots", "rpc_host": client.host,
                "chain_id": 1, "fee_multiplier": "997/1000", "rpc_calls": client.calls,
                "nodes": [{"id": ids[t], **tokens[t]} for t in nodes], "pools": pools,
                "snapshots": snapshots, "color_rule": "sorted token IDs modulo k (single fixed coloring)"}
    case = Case(k, [i % k for i in range(len(nodes))], graphs[0], updates, boundaries, metadata)
    case.validate()
    return case
