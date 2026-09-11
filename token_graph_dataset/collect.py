"""Bounded finalized-block RPC capture; successful response envelopes are retained."""
from datetime import datetime, timezone
from itertools import combinations
import json
from pathlib import Path
import time

from delta_terminal.rpc import address, block, words
from .reconstruct import hash_value, reconstruct, require

DEFAULT_TOKENS = Path(__file__).with_name("rpc_tokens.json")
FACTORY = "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f"
SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"


def universe(path=DEFAULT_TOKENS):
    config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(config["chain_id"] == 1 and address(config["factory"]) == FACTORY, "Only Ethereum Uniswap V2 Factory is supported")
    tokens = config["tokens"]
    require(len(tokens) == 5, "This pilot requires exactly five preselected tokens")
    for token in tokens:
        token["address"] = address(token["address"])
        require(type(token["decimals"]) is int and 0 <= token["decimals"] <= 36 and token["symbol"], "Invalid token metadata")
    require(len({token["address"] for token in tokens}) == 5, "Duplicate token address")
    return sorted(tokens, key=lambda token: token["address"])


def decode_log(raw, pools, headers, start, end):
    require(isinstance(raw, dict) and raw.get("removed") is False, "Removed or malformed log")
    topics = raw.get("topics")
    require(isinstance(topics, list) and len(topics) == 1 and hash_value(topics[0]) == SYNC, "Unexpected Sync topic list")
    pool = address(raw["address"])
    n = int(raw["blockNumber"], 16)
    require(pool in pools and start < n <= end, "Log outside the requested pool/block range")
    require(hash_value(raw["blockHash"]) == headers[n]["block_hash"], "Log block hash mismatch")
    r0, r1 = words(raw["data"], 2)
    require(r0 < 2**112 and r1 < 2**112, "Sync reserves exceed uint112")
    return {"block_number": n, "block_hash": raw["blockHash"].lower(),
            "transaction_hash": hash_value(raw["transactionHash"]),
            "transaction_index": int(raw["transactionIndex"], 16), "log_index": int(raw["logIndex"], 16),
            "pair_address": pool, "event_type": "Sync", "removed": "False",
            "reserve0_raw": str(r0), "reserve1_raw": str(r1)}


def collect(client, output, *, blocks=100, start_block=None, token_path=DEFAULT_TOKENS, progress=print):
    tokens = universe(token_path)
    require(2 <= blocks <= 100, "RPC pilot supports 2-100 blocks")
    # Upper bound: chain/finality, headers, decimals, ten pair lookups, twenty
    # token-order calls, twenty reserve anchors, log chunks, and two hash rechecks.
    required = 2 + blocks + 5 + 10 + 20 + 20 + (blocks-2)//10+1 + 2
    require(required <= client.budget-client.calls, "RPC budget cannot cover the requested pilot")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    status = {"status": "running", "rpc_host": client.host, "blocks_requested": blocks,
              "tokens": tokens, "selection": "all pairs at initial block; no outcome-based pool or window filtering"}
    status_path = output / "status.json"
    old_observer = client.on_response
    with (output / "rpc_responses.jsonl").open("x", encoding="utf-8") as journal:
        def record(method, params, response):
            journal.write(json.dumps({"method": method, "params": params, "response": response}, ensure_ascii=False)+"\n")
            journal.flush()
        client.on_response = record
        try:
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
            require(client.call("eth_chainId", []) == "0x1", "RPC is not Ethereum mainnet")
            final = block(client, "finalized")
            start = final["number"]-blocks+1 if start_block is None else start_block
            end = start+blocks-1
            require(start >= 0 and end <= final["number"], "Only finalized blocks may be collected")
            status.update(start_block=start, end_block=end, finalized_at_start=final)
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
            progress(f"Fixed capture window: {start}-{end}; five tokens; <= {required} RPC calls")
            headers = {}
            for n in range(start, end+1):
                value = block(client, hex(n))
                headers[n] = {"block_number": n, "block_hash": value["hash"], "parent_hash": value["parent_hash"]}
                require(n == start or value["parent_hash"] == headers[n-1]["block_hash"], "Block parent hash mismatch")
                if (n-start+1) % 10 == 0:
                    progress(f"Block headers {n-start+1}/{blocks}; RPC calls {client.calls}")
            require(end != final["number"] or headers[end]["block_hash"] == final["hash"], "Finalized anchor changed during capture")
            for token in tokens:
                raw = client.call("eth_call", [{"to": token["address"], "data": "0x313ce567"}, hex(start)])
                require(words(raw, 1)[0] == token["decimals"], "Token decimals mismatch")
            pools, absent = [], []
            for a, b in combinations(tokens, 2):
                data = "0xe6a43905"+a["address"][2:].zfill(64)+b["address"][2:].zfill(64)
                result = words(client.call("eth_call", [{"to": FACTORY, "data": data}, hex(start)]), 1)[0]
                require(result < 2**160, "Factory returned an invalid address")
                if not result:
                    absent.append([a["address"], b["address"]])
                    continue
                pool = f"0x{result:040x}"
                row = {"pair_address": pool, "chain_id": "1", "dex_name": "Uniswap v2",
                       "factory_address": FACTORY, "factory_get_pair_verified": "True",
                       "identity_method": "factory_getPair_at_block", "identity_block": start,
                       "token_order_verified": "True", "fee_numerator": "997", "fee_denominator": "1000"}
                for i, token in enumerate((a, b)):
                    selector = "0x0dfe1681" if i == 0 else "0xd21220a7"
                    actual = words(client.call("eth_call", [{"to": pool, "data": selector}, hex(start)]), 1)[0]
                    require(actual == int(token["address"],16), "Pool token order mismatch")
                    for key in ("address", "symbol", "decimals"):
                        row[f"token{i}_{key}"] = str(token[key])
                pools.append(row)
            require({p[f"token{i}_address"] for p in pools for i in (0,1)} == {t["address"] for t in tokens},
                    "Not all five tokens have an existing pool in the selected universe")
            progress(f"Resolved {len(pools)} pools; {len(absent)} absent pairs; RPC calls {client.calls}")
            snapshots, anchors, initial = [], [], []
            for n in (start, end):
                for pool in pools:
                    raw = client.call("eth_call", [{"to": pool["pair_address"], "data": "0x0902f1ac"}, hex(n)])
                    r0, r1, timestamp = words(raw, 3)
                    require(r0 < 2**112 and r1 < 2**112 and timestamp < 2**32, "Invalid getReserves ABI values")
                    snapshots.append({"chain_id": "1", "block_number": n, "pair_address": pool["pair_address"],
                        "token0_address": pool["token0_address"], "token1_address": pool["token1_address"],
                        "reserve0_raw": str(r0), "reserve1_raw": str(r1)})
                    anchors.append({"block_number": n, "pair_address": pool["pair_address"],
                        "historical_call_reserve0_raw": str(r0), "historical_call_reserve1_raw": str(r1), "archive_call_status": "available"})
                    if n == start:
                        initial.append({"pool": pool["pair_address"], "reserves": [r0,r1], "block_number": start,
                            "block_hash": headers[start]["block_hash"], "state_source": "eth_call_getReserves", "timestamp": timestamp})
            events = []
            addresses = [pool["pair_address"] for pool in pools]
            for lo in range(start+1, end+1, 10):
                hi = min(lo+9, end)
                raw = client.call("eth_getLogs", [{"address": addresses, "topics": [SYNC], "fromBlock": hex(lo), "toBlock": hex(hi)}])
                require(isinstance(raw, list), "eth_getLogs did not return a list")
                events.extend(decode_log(log, addresses, headers, lo-1, hi) for log in raw)
                progress(f"Sync logs through {hi}; {len(events)} events; RPC calls {client.calls}")
            for n in (start, end):
                require(block(client, hex(n))["hash"] == headers[n]["block_hash"], "Block hash changed during capture")
            source = {"schema": "rpc_uniswap_v2_v1", "start_block": start, "end_block": end,
                "source": {"rpc_host": client.host, "rpc_calls": client.calls, "response_journal": "rpc_responses.jsonl",
                    "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "finalized_at_start": final,
                    "tokens": tokens, "absent_pairs": absent, "selection": status["selection"]},
                "pools": pools, "blocks": list(headers.values()), "sync_events": events,
                "snapshots": snapshots, "archive_checks": anchors, "initial_reserves": initial}
            case = reconstruct(source, 5)
            (output / "source.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
            status.update(status="completed", pools=len(pools), sync_events=len(events), transaction_batches=len(case.boundaries),
                          end_reserve_checks=len(pools))
            return source
        except BaseException as exc:
            status.update(status="failed_or_interrupted", error_type=type(exc).__name__)
            raise
        finally:
            client.on_response = old_observer
            status.update(rpc_calls=client.calls, elapsed_seconds=time.monotonic()-started)
            status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
