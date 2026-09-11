"""Read recorded chain observations, then replay complete transactions into a graph."""
import csv
from fractions import Fraction
import hashlib
from itertools import groupby
import json
import math
from pathlib import Path
import re

from delta_terminal.model import Case
from delta_terminal.rpc import address


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hash_value(value):
    require(isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{64}", value), "Invalid chain hash")
    return value.lower()


def reserves(row):
    values = [int(row[f"reserve{i}_raw"]) for i in (0, 1)]
    require(all(0 <= value < 2**112 for value in values), "Reserves must be uint112 integers")
    return values


def read_source(folder, start, blocks):
    """Import the documented recorded-pilot CSV schema, without importing old code."""
    folder = Path(folder)
    require(1 <= blocks <= 1000, "Small datasets support 1-1000 blocks")
    fingerprints = {}

    def read(name):
        path = folder / name
        raw = path.read_bytes()
        fingerprints[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        return list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))

    blocks_raw = read("block_metadata.csv")
    start = min(int(row["block_number"]) for row in blocks_raw) if start is None else start
    end = start + blocks - 1
    headers = [row for row in blocks_raw if start <= int(row["block_number"]) <= end]
    require(len(headers) == blocks, "Missing or duplicate block headers in requested range")
    pools = read("pool_metadata.csv")
    events = read("pool_events.csv")
    # Keep warm-up Sync records: their latest observations initialize the first block end.
    events = [row for row in events if row["event_type"] == "Sync" and int(row["block_number"]) <= end]
    snapshots = [row for row in read("pool_state_snapshots.csv") if start <= int(row["block_number"]) <= end]
    anchors = [row for row in read("archive_state_checks.csv") if start <= int(row["block_number"]) <= end]
    metadata = json.loads((folder / "run_metadata.json").read_text(encoding="utf-8-sig"))
    require(metadata["chain_id"] == 1 and metadata["dex_name"] == "Uniswap v2", "Only Ethereum Uniswap V2 is supported")
    require(metadata["finality_tag"] == "finalized" and end <= int(metadata["finalized_block_at_start"]), "Source range was not finalized")
    require(int(metadata["start_block"]) <= start <= end <= int(metadata["end_block"]), "Requested range exceeds recorded observation window")
    return {"schema": "recorded_uniswap_v2_v1", "start_block": start, "end_block": end,
            "source": {"folder": str(folder.resolve()), "files": fingerprints,
                       "recorded_at_utc": metadata["run_completed_at_utc"],
                       "finalized_block_at_capture": metadata["finalized_block_at_start"]},
            "pools": pools, "blocks": headers, "sync_events": events,
            "snapshots": snapshots, "archive_checks": anchors}


def reconstruct(source, k=3):
    start, end = source["start_block"], source["end_block"]
    require(2 <= k <= 5, "Small-graph validation supports k=2-5")
    headers = sorted(source["blocks"], key=lambda row: int(row["block_number"]))
    require([int(row["block_number"]) for row in headers] == list(range(start, end+1)), "Block sequence is incomplete or duplicated")
    block_hashes = {}
    for row in headers:
        number = int(row["block_number"])
        block_hashes[number] = hash_value(row["block_hash"])
        parent = hash_value(row["parent_hash"])
        require(number == start or parent == block_hashes[number-1], "Block parent hash mismatch")

    pools, tokens, pairs = {}, {}, set()
    require(1 <= len(source["pools"]) <= 8, "Small datasets support 1-8 pools")
    for row in source["pools"]:
        pool = address(row["pair_address"])
        pair = tuple(address(row[f"token{i}_address"]) for i in (0, 1))
        require(pair[0] < pair[1] and pair not in pairs and pool not in pools, "Invalid, duplicate or parallel pool")
        require(int(row["chain_id"]) == 1 and row["dex_name"] == "Uniswap v2", "Invalid pool protocol")
        require((int(row["fee_numerator"]), int(row["fee_denominator"])) == (997, 1000), "Unsupported pool fee")
        require(row["factory_get_pair_verified"] == "True" and row["creation_event_verified"] == "True", "Pool identity was not verified in source")
        require(address(row["creation_event_pair_address"]) == pool and int(row["creation_block"]) <= start, "Pool creation does not match selected universe")
        hash_value(row["creation_transaction_hash"])
        for i, token in enumerate(pair):
            item = {"address": token, "symbol": row[f"token{i}_symbol"], "decimals": int(row[f"token{i}_decimals"])}
            require(0 <= item["decimals"] <= 36, "Invalid token decimals")
            require(tokens.setdefault(token, item) == item, "Conflicting token metadata")
        pools[pool] = pair
        pairs.add(pair)
    nodes = sorted(tokens)
    require(k <= len(nodes) <= 10, "Need k to 10 tokens for bounded exhaustive validation")
    ids = {token: i for i, token in enumerate(nodes)}

    seen, tx_ids, tx_positions = set(), {}, {}
    events = []
    for row in source["sync_events"]:
        n, tx, log = (int(row[key]) for key in ("block_number", "transaction_index", "log_index"))
        require(n >= 0 and tx >= 0 and log >= 0 and n <= end, "Invalid event position")
        require(row["event_type"] == "Sync" and row["removed"] == "False", "Expected non-removed Sync event")
        pool = address(row["pair_address"])
        require(pool in pools, "Sync event references an unknown pool")
        h, th = hash_value(row["block_hash"]), hash_value(row["transaction_hash"])
        require(n < start or h == block_hashes[n], "Event block hash mismatch")
        require((n, log) not in seen, "Duplicate log position")
        require(tx_ids.setdefault((n, tx), th) == th, "Conflicting transaction hashes")
        require(tx_positions.setdefault(th, (n, tx)) == (n, tx), "Transaction hash appears at multiple positions")
        seen.add((n, log))
        events.append({"block_number": n, "block_hash": h, "transaction_hash": th,
                       "transaction_index": tx, "log_index": log, "pool": pool,
                       "reserves": reserves(row)})
    events.sort(key=lambda row: (row["block_number"], row["transaction_index"], row["log_index"]))
    for _, group in groupby(events, key=lambda row: row["block_number"]):
        indexes = [row["log_index"] for row in group]
        require(indexes == sorted(indexes), "Log order conflicts with transaction order")
    require(len([event for event in events if event["block_number"] > start]) <= 10000, "Small dataset event limit exceeded")

    checkpoints = {}
    for row in source["snapshots"]:
        key = (int(row["block_number"]), address(row["pair_address"]))
        require(key not in checkpoints and key[1] in pools and start <= key[0] <= end, "Invalid snapshot key")
        require(int(row["chain_id"]) == 1, "Snapshot chain mismatch")
        require(tuple(address(row[f"token{i}_address"]) for i in (0, 1)) == pools[key[1]], "Snapshot token order mismatch")
        checkpoints[key] = reserves(row)
    require(len(checkpoints) == len(pools)*(end-start+1), "Incomplete block-end checkpoint coverage")

    archive = {}
    for row in source["archive_checks"]:
        key = (int(row["block_number"]), address(row["pair_address"]))
        require(key not in archive and key in checkpoints, "Invalid archive checkpoint key")
        require(row["archive_call_status"] == "available", "Historical getReserves checkpoint unavailable")
        values = [int(row[f"historical_call_reserve{i}_raw"]) for i in (0, 1)]
        require(values == checkpoints[key], "Historical getReserves checkpoint mismatch")
        archive[key] = values
    require(all((start, pool) in archive for pool in pools), "Initial state needs historical getReserves anchors for every pool; choose an anchored start block")

    state, initial_events = {}, {}
    for event in events:
        if event["block_number"] <= start:
            state[event["pool"]] = event["reserves"]
            initial_events[event["pool"]] = event
    require(set(state) == set(pools), "Missing initial Sync observation; do not fill missing reserves")

    def check_block(number):
        for pool, value in state.items():
            require(value == checkpoints[number, pool], f"Reconstructed block-end reserves mismatch at {number}, {pool}")

    def edges(pool):
        a, b = pools[pool]
        r0, r1 = state[pool]
        if not r0 or not r1:
            return [(ids[a], ids[b], "D"), (ids[b], ids[a], "D")]
        rate = Fraction(997*r1*10**tokens[a]["decimals"], 1000*r0*10**tokens[b]["decimals"])
        reverse = Fraction(997*r0*10**tokens[b]["decimals"], 1000*r1*10**tokens[a]["decimals"])
        return [(ids[a], ids[b], -math.log(float(rate))), (ids[b], ids[a], -math.log(float(reverse)))]

    check_block(start)
    graph = sorted(edge for pool in pools for edge in edges(pool) if edge[2] != "D")
    updates, boundaries, transactions = [], [], []
    window = [event for event in events if event["block_number"] > start]
    by_block = {n: list(group) for n, group in groupby(window, key=lambda event: event["block_number"])}
    for number in range(start+1, end+1):
        for tx, group in groupby(by_block.get(number, []), key=lambda event: event["transaction_index"]):
            changed, batch_events = set(), list(group)
            for event in batch_events:
                state[event["pool"]] = event["reserves"]
                changed.add(event["pool"])
            # All pools, both directions, and repeated Syncs in one transaction are atomic.
            updates.extend(edge for pool in sorted(changed) for edge in edges(pool))
            boundaries.append(len(updates))
            transactions.append({"row": len(updates), "block_number": number,
                                 "block_hash": block_hashes[number], "transaction_index": tx,
                                 "transaction_hash": batch_events[0]["transaction_hash"],
                                 "events": batch_events})
        check_block(number)
    metadata = {"source": "recorded_uniswap_v2_sync_transactions", "chain_id": 1, "k": k,
                "start_block": start, "end_block": end, "fee_multiplier": "997/1000",
                "initial_state": "end of start_block; no updates from start_block replayed twice",
                "answer_boundary": "after all selected-pool Sync events in one complete transaction",
                "nodes": [{"id": ids[token], **tokens[token]} for token in nodes],
                "pools": source["pools"], "initial_events": list(initial_events.values()),
                "transactions": transactions, "provenance": source["source"],
                "color_rule": "sorted token ID modulo k; fixed coloring, not a global guarantee",
                "checks": {"block_end_reserve_matches": len(checkpoints), "historical_call_matches": len(archive),
                           "update_sync_events": len(window), "transaction_batches": len(boundaries)}}
    case = Case(k, [i % k for i in range(len(nodes))], graph, updates, boundaries, metadata)
    case.validate()
    return case
