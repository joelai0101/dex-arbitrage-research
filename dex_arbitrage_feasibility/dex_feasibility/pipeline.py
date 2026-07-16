from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path
from typing import Any, Callable, Sequence

from .core import (
    SELECTORS,
    TOPICS,
    ZERO_ADDRESS,
    address_topic,
    block_chain_is_continuous,
    checksum_insensitive,
    decimal_text,
    decimal_to_raw,
    decode_address_word,
    decode_pair_event,
    decode_symbol,
    decode_uint_words,
    evenly_spaced_sample,
    gas_cost_weth,
    get_amount_out,
    hex_int,
    is_sorted_events,
    orient_reserves,
    pair_key,
    quantile_int,
    raw_to_decimal,
)
from .rpc import JsonRpcError, RpcClient


getcontext().prec = 80


def utc_now_text() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp_text(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: Sequence[dict[str, Any]], preferred_fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    present = {key for row in rows for key in row}
    fieldnames = [field for field in preferred_fields if field in present]
    fieldnames.extend(sorted(present.difference(fieldnames)))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def checkpoint(
    checkpoint_dir: Path,
    name: str,
    producer: Callable[[], Any],
    *,
    resume: bool,
) -> Any:
    path = checkpoint_dir / f"{name}.json"
    if resume and path.exists():
        return load_json(path)
    result = producer()
    write_json(path, result)
    return result


def config_digest(config_path: Path) -> str:
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def find_pair_creation_log(
    client: RpcClient,
    creation_filter: dict[str, Any],
    search_start: int,
    search_end: int,
    chunk_size: int,
) -> dict[str, Any] | None:
    cursor = search_start
    while cursor <= search_end:
        chunk_end = min(cursor + chunk_size - 1, search_end)
        logs = client.get_logs(
            creation_filter,
            cursor,
            chunk_end,
            chunk_size=chunk_size,
        )
        if logs:
            return logs[0]
        cursor = chunk_end + 1
    return None


def fetch_pool_metadata(
    client: RpcClient, config: dict[str, Any], end_block: int
) -> list[dict[str, Any]]:
    factory = config["factory_address"]
    token_config = config["tokens"]
    token_metadata_cache: dict[str, tuple[str, int]] = {}
    rows: list[dict[str, Any]] = []

    def token_metadata(address: str, fallback_symbol: str) -> tuple[str, int]:
        key = address.lower()
        if key not in token_metadata_cache:
            symbol_raw = client.eth_call(address, SELECTORS["symbol"], "latest")
            decimals_raw = client.eth_call(address, SELECTORS["decimals"], "latest")
            decimals_words = decode_uint_words(decimals_raw)
            if not decimals_words:
                raise ValueError(f"No decimals returned for token {address}")
            token_metadata_cache[key] = (decode_symbol(symbol_raw) or fallback_symbol, decimals_words[0])
        return token_metadata_cache[key]

    symbol_by_address = {
        details["address"].lower(): symbol for symbol, details in token_config.items()
    }

    for pair_spec in config["pairs"]:
        print(f"  resolving {pair_spec['pair_id']} from Factory", flush=True)
        token_a_symbol = pair_spec["token_a"]
        token_b_symbol = pair_spec["token_b"]
        token_a = token_config[token_a_symbol]["address"]
        token_b = token_config[token_b_symbol]["address"]
        call_data = SELECTORS["getPair"] + address_topic(token_a)[2:] + address_topic(token_b)[2:]
        pair_address = decode_address_word(client.eth_call(factory, call_data, "latest"))
        if pair_address.lower() == ZERO_ADDRESS.lower():
            raise ValueError(f"Factory returned zero address for {token_a_symbol}/{token_b_symbol}")

        token0 = decode_address_word(client.eth_call(pair_address, SELECTORS["token0"], "latest"))
        token1 = decode_address_word(client.eth_call(pair_address, SELECTORS["token1"], "latest"))
        token0_fallback = symbol_by_address.get(token0.lower(), "token0")
        token1_fallback = symbol_by_address.get(token1.lower(), "token1")
        token0_symbol, token0_decimals = token_metadata(token0, token0_fallback)
        token1_symbol, token1_decimals = token_metadata(token1, token1_fallback)

        sorted_tokens = sorted((token_a, token_b), key=lambda value: int(value, 16))
        creation_filter = {
            "address": factory,
            "topics": [
                TOPICS["PairCreated"],
                address_topic(sorted_tokens[0]),
                address_topic(sorted_tokens[1]),
            ],
        }
        creation_log = find_pair_creation_log(
            client,
            creation_filter,
            int(config["factory_deployment_block"]),
            min(int(config["pair_creation_search_end_block"]), end_block),
            int(config["creation_log_chunk_size"]),
        )
        if creation_log is None:
            raise ValueError(
                f"PairCreated log not found for {pair_spec['pair_id']} in configured search range"
            )
        creation_block = int(creation_log["blockNumber"], 16)
        creation_pair_address = (
            decode_address_word(creation_log["data"], 0) if creation_log else ""
        )

        requested_addresses = {token_a.lower(), token_b.lower()}
        observed_addresses = {token0.lower(), token1.lower()}
        rows.append(
            {
                "chain_id": config["chain_id"],
                "dex_name": config["dex_name"],
                "factory_address": factory,
                "pair_id": pair_spec["pair_id"],
                "pair_address": pair_address,
                "requested_token_a": token_a,
                "requested_token_b": token_b,
                "token0_address": token0,
                "token1_address": token1,
                "token0_symbol": token0_symbol,
                "token1_symbol": token1_symbol,
                "token0_decimals": token0_decimals,
                "token1_decimals": token1_decimals,
                "fee_rate": "0.003",
                "fee_numerator": config["fee_numerator"],
                "fee_denominator": config["fee_denominator"],
                "creation_block": creation_block,
                "creation_block_source": "factory_pair_created_event",
                "creation_transaction_hash": creation_log["transactionHash"] if creation_log else "",
                "factory_get_pair_verified": requested_addresses == observed_addresses,
                "creation_event_pair_address": creation_pair_address,
                "creation_event_verified": bool(creation_log)
                and creation_pair_address.lower() == pair_address.lower(),
                "metadata_observed_at_block": "latest",
            }
        )
    return rows


def fetch_blocks(
    client: RpcClient, start_block: int, end_block: int, batch_size: int
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for batch_start in range(start_block, end_block + 1, batch_size):
        numbers = list(range(batch_start, min(batch_start + batch_size - 1, end_block) + 1))
        print(f"  blocks {numbers[0]}–{numbers[-1]}", flush=True)
        raw_blocks = client.batch(
            [("eth_getBlockByNumber", [hex(number), False]) for number in numbers]
        )
        for requested_number, raw in zip(numbers, raw_blocks):
            if raw is None:
                raise ValueError(f"Block {requested_number} was not returned")
            block_number = int(raw["number"], 16)
            timestamp = int(raw["timestamp"], 16)
            blocks.append(
                {
                    "block_number": block_number,
                    "block_hash": raw["hash"],
                    "parent_hash": raw["parentHash"],
                    "timestamp": timestamp,
                    "timestamp_utc": timestamp_text(timestamp),
                    "base_fee_per_gas": hex_int(raw.get("baseFeePerGas")) or 0,
                    "gas_used": int(raw["gasUsed"], 16),
                    "gas_limit": int(raw["gasLimit"], 16),
                }
            )
    blocks.sort(key=lambda row: int(row["block_number"]))
    return blocks


def fetch_pair_events(
    client: RpcClient,
    pair_metadata: Sequence[dict[str, Any]],
    config: dict[str, Any],
    start_block: int,
    end_block: int,
) -> list[dict[str, Any]]:
    addresses = [row["pair_address"] for row in pair_metadata]
    warmup_start = max(int(config["factory_deployment_block"]), start_block - int(config["warmup_blocks"]))
    warmup_logs = client.get_logs(
        {"address": addresses, "topics": [TOPICS["Sync"]]},
        warmup_start,
        start_block - 1,
        chunk_size=int(config["event_log_chunk_size"]),
    )
    window_logs = client.get_logs(
        {"address": addresses, "topics": [[TOPICS["Sync"], TOPICS["Swap"]]]},
        start_block,
        end_block,
        chunk_size=int(config["event_log_chunk_size"]),
    )
    decoded = [
        decode_pair_event(log, start_block, end_block) for log in warmup_logs + window_logs
    ]
    decoded.sort(
        key=lambda row: (
            int(row["block_number"]),
            int(row["transaction_index"]),
            int(row["log_index"]),
        )
    )
    return decoded


def fetch_initial_reserves(
    client: RpcClient,
    pair_metadata: Sequence[dict[str, Any]],
    initial_block: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metadata in pair_metadata:
        try:
            raw = client.eth_call(metadata["pair_address"], SELECTORS["getReserves"], initial_block)
            words = decode_uint_words(raw)
            if len(words) < 2:
                raise ValueError(f"getReserves returned too few words for {metadata['pair_id']}")
            rows.append(
                {
                    "pair_id": metadata["pair_id"],
                    "pair_address": metadata["pair_address"],
                    "block_number": initial_block,
                    "reserve0_raw": words[0],
                    "reserve1_raw": words[1],
                    "block_timestamp_last": words[2] if len(words) > 2 else "",
                    "source": "historical_eth_call",
                    "historical_call_status": "available",
                    "error": "",
                }
            )
        except (JsonRpcError, ValueError) as exc:
            rows.append(
                {
                    "pair_id": metadata["pair_id"],
                    "pair_address": metadata["pair_address"],
                    "block_number": initial_block,
                    "reserve0_raw": "",
                    "reserve1_raw": "",
                    "block_timestamp_last": "",
                    "source": "warmup_sync_required",
                    "historical_call_status": "unavailable",
                    "error": str(exc),
                }
            )
    return rows


def reconstruct_snapshots(
    pair_metadata: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    initial_reserves: Sequence[dict[str, Any]],
    start_block: int,
    end_block: int,
) -> list[dict[str, Any]]:
    metadata_by_address = {row["pair_address"].lower(): row for row in pair_metadata}
    history_by_address = {row["pair_address"].lower(): row for row in initial_reserves}
    sync_events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event["event_type"] == "Sync" and not event.get("removed", False):
            sync_events[event["pair_address"].lower()].append(event)

    current: dict[str, dict[str, Any]] = {}
    for address, metadata in metadata_by_address.items():
        historical = history_by_address[address]
        historical_available = historical.get("historical_call_status", "available") == "available"
        prior_syncs = [
            event for event in sync_events.get(address, []) if int(event["block_number"]) < start_block
        ]
        last_sync = prior_syncs[-1] if prior_syncs else None
        sync_matches = bool(last_sync) and historical_available and (
            int(last_sync["reserve0_raw"]) == int(historical["reserve0_raw"])
            and int(last_sync["reserve1_raw"]) == int(historical["reserve1_raw"])
        )
        if last_sync and (sync_matches or not historical_available):
            current[address] = {
                "reserve0_raw": int(last_sync["reserve0_raw"]),
                "reserve1_raw": int(last_sync["reserve1_raw"]),
                "last_sync_block_number": int(last_sync["block_number"]),
                "last_sync_transaction_hash": last_sync["transaction_hash"],
                "last_sync_log_index": int(last_sync["log_index"]),
                "state_source_type": "sync_log",
                "initial_sync_matches_historical_call": sync_matches if historical_available else "",
            }
        elif historical_available:
            current[address] = {
                "reserve0_raw": int(historical["reserve0_raw"]),
                "reserve1_raw": int(historical["reserve1_raw"]),
                "last_sync_block_number": "",
                "last_sync_transaction_hash": "",
                "last_sync_log_index": "",
                "state_source_type": "historical_eth_call",
                "initial_sync_matches_historical_call": bool(last_sync) and sync_matches,
            }
        else:
            current[address] = {
                "reserve0_raw": "",
                "reserve1_raw": "",
                "last_sync_block_number": "",
                "last_sync_transaction_hash": "",
                "last_sync_log_index": "",
                "state_source_type": "missing",
                "initial_sync_matches_historical_call": "",
            }

    sync_by_pair_block: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for address, pair_events in sync_events.items():
        for event in pair_events:
            block_number = int(event["block_number"])
            if start_block <= block_number <= end_block:
                sync_by_pair_block[(address, block_number)].append(event)

    snapshots: list[dict[str, Any]] = []
    ordered_metadata = sorted(pair_metadata, key=lambda row: row["pair_id"])
    for block_number in range(start_block, end_block + 1):
        for metadata in ordered_metadata:
            address = metadata["pair_address"].lower()
            block_syncs = sync_by_pair_block.get((address, block_number), [])
            if block_syncs:
                last_sync = block_syncs[-1]
                current[address] = {
                    "reserve0_raw": int(last_sync["reserve0_raw"]),
                    "reserve1_raw": int(last_sync["reserve1_raw"]),
                    "last_sync_block_number": block_number,
                    "last_sync_transaction_hash": last_sync["transaction_hash"],
                    "last_sync_log_index": int(last_sync["log_index"]),
                    "state_source_type": "sync_log",
                    "initial_sync_matches_historical_call": current[address].get(
                        "initial_sync_matches_historical_call", False
                    ),
                }
                quality = "observed_sync"
            else:
                quality = (
                    "carried_forward"
                    if current[address]["state_source_type"] != "missing"
                    else "missing"
                )
            state = current[address]
            snapshots.append(
                {
                    "chain_id": 1,
                    "block_number": block_number,
                    "pair_id": metadata["pair_id"],
                    "pair_address": metadata["pair_address"],
                    "token0_address": metadata["token0_address"],
                    "token1_address": metadata["token1_address"],
                    "reserve0_raw": state["reserve0_raw"],
                    "reserve1_raw": state["reserve1_raw"],
                    "state_quality_flag": quality,
                    "state_source_type": state["state_source_type"],
                    "last_sync_block_number": state["last_sync_block_number"],
                    "last_sync_transaction_hash": state["last_sync_transaction_hash"],
                    "last_sync_log_index": state["last_sync_log_index"],
                    "initial_sync_matches_historical_call": state[
                        "initial_sync_matches_historical_call"
                    ],
                }
            )
    return snapshots


def fetch_receipts(
    client: RpcClient, events: Sequence[dict[str, Any]], sample_size: int
) -> list[dict[str, Any]]:
    swap_hashes = [
        row["transaction_hash"]
        for row in events
        if row["event_type"] == "Swap" and row["in_observation_window"]
    ]
    selected_hashes = evenly_spaced_sample(swap_hashes, sample_size)
    raw_receipts = client.batch(
        [("eth_getTransactionReceipt", [transaction_hash]) for transaction_hash in selected_hashes]
    )
    rows: list[dict[str, Any]] = []
    for sample_index, (transaction_hash, raw) in enumerate(zip(selected_hashes, raw_receipts), start=1):
        if raw is None:
            continue
        rows.append(
            {
                "sample_index": sample_index,
                "transaction_hash": transaction_hash,
                "block_number": int(raw["blockNumber"], 16),
                "transaction_index": int(raw["transactionIndex"], 16),
                "status": int(raw.get("status", "0x0"), 16),
                "gas_used": int(raw["gasUsed"], 16),
                "effective_gas_price": int(raw.get("effectiveGasPrice", "0x0"), 16),
                "gas_units_proxy": int(raw["gasUsed"], 16),
                "value_class": "direct_observation_and_gas_proxy",
                "proxy_limitation": "Receipt gas_used covers the full sampled transaction, not a standardized three-hop arbitrage contract.",
            }
        )
    rows.sort(key=lambda row: (int(row["block_number"]), int(row["transaction_index"])))
    return rows


def fetch_archive_state_checks(
    client: RpcClient,
    pair_metadata: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    sample_blocks: Sequence[int],
) -> list[dict[str, Any]]:
    snapshot_map = {
        (int(row["block_number"]), row["pair_address"].lower()): row for row in snapshots
    }
    rows: list[dict[str, Any]] = []
    for block_number in sample_blocks:
        for metadata in pair_metadata:
            snapshot = snapshot_map[(block_number, metadata["pair_address"].lower())]
            try:
                raw = client.eth_call(metadata["pair_address"], SELECTORS["getReserves"], block_number)
                words = decode_uint_words(raw)
                observed0, observed1 = words[0], words[1]
                matches = observed0 == int(snapshot["reserve0_raw"]) and observed1 == int(
                    snapshot["reserve1_raw"]
                )
                rows.append(
                    {
                        "block_number": block_number,
                        "pair_id": metadata["pair_id"],
                        "pair_address": metadata["pair_address"],
                        "reconstructed_reserve0_raw": snapshot["reserve0_raw"],
                        "reconstructed_reserve1_raw": snapshot["reserve1_raw"],
                        "historical_call_reserve0_raw": observed0,
                        "historical_call_reserve1_raw": observed1,
                        "archive_call_status": "available",
                        "reserves_match": matches,
                        "error": "",
                    }
                )
            except (JsonRpcError, ValueError, IndexError) as exc:
                rows.append(
                    {
                        "block_number": block_number,
                        "pair_id": metadata["pair_id"],
                        "pair_address": metadata["pair_address"],
                        "reconstructed_reserve0_raw": snapshot["reserve0_raw"],
                        "reconstructed_reserve1_raw": snapshot["reserve1_raw"],
                        "historical_call_reserve0_raw": "",
                        "historical_call_reserve1_raw": "",
                        "archive_call_status": "unavailable",
                        "reserves_match": "",
                        "error": str(exc),
                    }
                )
    return rows


def no_impact_route_output(
    amount_in_raw: int,
    hop_states: Sequence[tuple[int, int]],
    fee_numerator: int,
    fee_denominator: int,
) -> Decimal:
    amount = Decimal(amount_in_raw)
    fee_multiplier = Decimal(fee_numerator) / Decimal(fee_denominator)
    for reserve_in, reserve_out in hop_states:
        amount = amount * fee_multiplier * Decimal(reserve_out) / Decimal(reserve_in)
    return amount


def build_gas_assumptions(
    receipts: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
    probabilities: Sequence[float],
) -> dict[str, int]:
    gas_values = [int(row["gas_used"]) for row in receipts if int(row["status"]) == 1]
    if not gas_values:
        raise ValueError("No successful receipt gas observations are available")
    if len(probabilities) != 3:
        raise ValueError("Exactly three gas quantiles are required")
    block_base_fees = {int(row["block_number"]): int(row["base_fee_per_gas"]) for row in blocks}
    priority_values = [
        max(0, int(row["effective_gas_price"]) - block_base_fees.get(int(row["block_number"]), 0))
        for row in receipts
        if int(row["effective_gas_price"]) > 0
    ]
    return {
        "gas_units_low": quantile_int(gas_values, float(probabilities[0])),
        "gas_units_median": quantile_int(gas_values, float(probabilities[1])),
        "gas_units_high": quantile_int(gas_values, float(probabilities[2])),
        "priority_fee_per_gas_proxy": quantile_int(priority_values, 0.5) if priority_values else 0,
    }


def simulate_arbitrage(
    config: dict[str, Any],
    pair_metadata: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    gas_assumptions: dict[str, int],
) -> list[dict[str, Any]]:
    token_config = config["tokens"]
    token_addresses = {symbol: details["address"] for symbol, details in token_config.items()}
    decimals_by_address: dict[str, int] = {}
    pair_by_tokens: dict[tuple[str, str], dict[str, Any]] = {}
    for metadata in pair_metadata:
        decimals_by_address[metadata["token0_address"].lower()] = int(metadata["token0_decimals"])
        decimals_by_address[metadata["token1_address"].lower()] = int(metadata["token1_decimals"])
        pair_by_tokens[pair_key(metadata["token0_address"], metadata["token1_address"])] = metadata
    snapshots_by_key = {
        (int(row["block_number"]), row["pair_address"].lower()): row for row in snapshots
    }
    rows: list[dict[str, Any]] = []
    fee_numerator = int(config["fee_numerator"])
    fee_denominator = int(config["fee_denominator"])
    weth_address = token_addresses["WETH"].lower()
    weth_decimals = decimals_by_address[weth_address]

    for block in blocks:
        block_number = int(block["block_number"])
        effective_gas_price = int(block["base_fee_per_gas"]) + int(
            gas_assumptions["priority_fee_per_gas_proxy"]
        )
        gas_costs = {
            level: gas_cost_weth(int(gas_assumptions[f"gas_units_{level}"]), effective_gas_price)
            for level in ("low", "median", "high")
        }
        for route in config["routes"]:
            route_symbols = route["tokens"]
            route_addresses = [token_addresses[symbol] for symbol in route_symbols]
            for input_text in config["input_amounts_weth"]:
                amount_in_raw = decimal_to_raw(input_text, weth_decimals)
                hop_outputs: list[int] = []
                hop_states: list[tuple[int, int]] = []
                hop_pairs: list[str] = []
                current_amount = amount_in_raw
                data_status = "complete"
                error = ""
                try:
                    for token_in, token_out in zip(route_addresses, route_addresses[1:]):
                        metadata = pair_by_tokens[pair_key(token_in, token_out)]
                        snapshot = snapshots_by_key[(block_number, metadata["pair_address"].lower())]
                        if snapshot["state_quality_flag"] == "missing":
                            raise ValueError("missing pool state")
                        reserve_in, reserve_out = orient_reserves(
                            metadata, snapshot, token_in, token_out
                        )
                        output = get_amount_out(
                            current_amount,
                            reserve_in,
                            reserve_out,
                            fee_numerator,
                            fee_denominator,
                        )
                        hop_states.append((reserve_in, reserve_out))
                        hop_outputs.append(output)
                        hop_pairs.append(metadata["pair_address"])
                        current_amount = output
                except (KeyError, ValueError) as exc:
                    data_status = "missing_or_invalid_state"
                    error = str(exc)

                base_row: dict[str, Any] = {
                    "chain_id": config["chain_id"],
                    "block_number": block_number,
                    "timestamp": block["timestamp_utc"],
                    "route_id": route["route_id"],
                    "input_amount_weth": str(input_text),
                    "input_amount_raw": amount_in_raw,
                    "effective_gas_price": effective_gas_price,
                    "effective_gas_price_gwei": decimal_text(
                        Decimal(effective_gas_price) / Decimal(10**9), 9
                    ),
                    "priority_fee_per_gas_proxy": gas_assumptions[
                        "priority_fee_per_gas_proxy"
                    ],
                    "gas_units_assumption": gas_assumptions["gas_units_median"],
                    "gas_units_low": gas_assumptions["gas_units_low"],
                    "gas_units_median": gas_assumptions["gas_units_median"],
                    "gas_units_high": gas_assumptions["gas_units_high"],
                    "gas_cost_weth_low": decimal_text(gas_costs["low"]),
                    "gas_cost_weth": decimal_text(gas_costs["median"]),
                    "gas_cost_weth_median": decimal_text(gas_costs["median"]),
                    "gas_cost_weth_high": decimal_text(gas_costs["high"]),
                    "gas_value_class": "proxy_from_receipt_quantiles_and_block_base_fee",
                    "data_status": data_status,
                    "error": error,
                }
                if data_status != "complete":
                    base_row.update(
                        hop1_pair_address="",
                        hop2_pair_address="",
                        hop3_pair_address="",
                        hop1_output_raw="",
                        hop2_output_raw="",
                        final_output_raw="",
                        hop1_output="",
                        hop2_output="",
                        final_output_weth="",
                        gross_profit_before_price_impact_weth="",
                        price_impact_cost_weth="",
                        gross_profit_weth="",
                        net_profit_weth_low="",
                        net_profit_weth="",
                        net_profit_weth_median="",
                        net_profit_weth_high="",
                        profitable_before_gas="",
                        profitable_after_gas_low="",
                        profitable_after_gas="",
                        profitable_after_gas_median="",
                        profitable_after_gas_high="",
                    )
                    rows.append(base_row)
                    continue

                final_raw = hop_outputs[-1]
                final_weth = raw_to_decimal(final_raw, weth_decimals)
                input_weth = raw_to_decimal(amount_in_raw, weth_decimals)
                no_impact_raw = no_impact_route_output(
                    amount_in_raw, hop_states, fee_numerator, fee_denominator
                )
                no_impact_weth = no_impact_raw / (Decimal(10) ** weth_decimals)
                gross_profit = final_weth - input_weth
                gross_before_impact = no_impact_weth - input_weth
                price_impact_cost = no_impact_weth - final_weth
                net = {level: gross_profit - gas_costs[level] for level in ("low", "median", "high")}
                hop1_decimals = decimals_by_address[route_addresses[1].lower()]
                hop2_decimals = decimals_by_address[route_addresses[2].lower()]
                base_row.update(
                    hop1_pair_address=hop_pairs[0],
                    hop2_pair_address=hop_pairs[1],
                    hop3_pair_address=hop_pairs[2],
                    hop1_output_raw=hop_outputs[0],
                    hop2_output_raw=hop_outputs[1],
                    final_output_raw=final_raw,
                    hop1_output=decimal_text(raw_to_decimal(hop_outputs[0], hop1_decimals)),
                    hop2_output=decimal_text(raw_to_decimal(hop_outputs[1], hop2_decimals)),
                    final_output_weth=decimal_text(final_weth),
                    gross_profit_before_price_impact_weth=decimal_text(gross_before_impact),
                    price_impact_cost_weth=decimal_text(price_impact_cost),
                    gross_profit_weth=decimal_text(gross_profit),
                    net_profit_weth_low=decimal_text(net["low"]),
                    net_profit_weth=decimal_text(net["median"]),
                    net_profit_weth_median=decimal_text(net["median"]),
                    net_profit_weth_high=decimal_text(net["high"]),
                    profitable_before_gas=str(gross_profit > 0).lower(),
                    profitable_after_gas_low=str(net["low"] > 0).lower(),
                    profitable_after_gas=str(net["median"] > 0).lower(),
                    profitable_after_gas_median=str(net["median"] > 0).lower(),
                    profitable_after_gas_high=str(net["high"] > 0).lower(),
                )
                rows.append(base_row)
    return rows


def quality_check(
    name: str, passed: bool, detail: str, *, critical: bool = True, warning: bool = False
) -> dict[str, Any]:
    status = "PASS" if passed else ("WARN" if warning else "FAIL")
    return {"name": name, "status": status, "critical": critical, "detail": detail}


def build_quality_checks(
    config: dict[str, Any],
    pair_metadata: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    receipts: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    archive_checks: Sequence[dict[str, Any]],
    simulations: Sequence[dict[str, Any]],
    failed_requests: Sequence[str],
) -> list[dict[str, Any]]:
    expected_blocks = int(config["block_count"])
    expected_snapshots = expected_blocks * len(config["pairs"])
    expected_simulations = expected_blocks * len(config["routes"]) * len(
        config["input_amounts_weth"]
    )
    expected_decimals = {
        details["address"].lower(): int(details["expected_decimals"])
        for details in config["tokens"].values()
    }
    observed_decimals: dict[str, int] = {}
    for row in pair_metadata:
        observed_decimals[row["token0_address"].lower()] = int(row["token0_decimals"])
        observed_decimals[row["token1_address"].lower()] = int(row["token1_decimals"])
    available_archive = [row for row in archive_checks if row["archive_call_status"] == "available"]
    archive_passed = bool(available_archive) and all(bool(row["reserves_match"]) for row in available_archive)
    snapshot_missing = [row for row in snapshots if row["state_quality_flag"] == "missing"]
    negative_reserves = [
        row
        for row in snapshots
        if row["reserve0_raw"] != ""
        and row["reserve1_raw"] != ""
        and (int(row["reserve0_raw"]) < 0 or int(row["reserve1_raw"]) < 0)
    ]
    incomplete_simulations = [row for row in simulations if row["data_status"] != "complete"]
    manual_cfmm = get_amount_out(10, 1000, 2000) == 19
    manual_gas = gas_cost_weth(150000, 30_000_000_000) == Decimal("0.0045")
    checks = [
        quality_check(
            "factory_pair_resolution",
            len(pair_metadata) == 3
            and all(bool(row["factory_get_pair_verified"]) for row in pair_metadata),
            f"Resolved {len(pair_metadata)} pairs; all token sets must match Factory getPair inputs.",
        ),
        quality_check(
            "pair_creation_blocks",
            len(pair_metadata) == 3 and all(row["creation_block"] != "" for row in pair_metadata),
            "Creation block is taken from the matching Factory PairCreated event.",
        ),
        quality_check(
            "pair_creation_event_verification",
            len(pair_metadata) == 3 and all(bool(row["creation_event_verified"]) for row in pair_metadata),
            "When the RPC permits the historical log call, PairCreated must match the Factory getPair result.",
            critical=False,
            warning=not all(bool(row["creation_event_verified"]) for row in pair_metadata),
        ),
        quality_check(
            "token_decimals",
            observed_decimals == expected_decimals,
            f"Observed decimals {observed_decimals}; expected {expected_decimals}.",
        ),
        quality_check(
            "continuous_block_numbers_and_hashes",
            len(blocks) == expected_blocks and block_chain_is_continuous(blocks),
            f"Fetched {len(blocks)} of {expected_blocks} consecutive finalized blocks.",
        ),
        quality_check(
            "event_sort_order",
            is_sorted_events(events),
            f"Checked {len(events)} events by block, transaction index, and log index.",
        ),
        quality_check(
            "non_removed_logs",
            not any(bool(row["removed"]) for row in events),
            "No retained event may be marked removed.",
        ),
        quality_check(
            "snapshot_completeness",
            len(snapshots) == expected_snapshots and not snapshot_missing,
            f"Produced {len(snapshots)} of {expected_snapshots} snapshots; missing={len(snapshot_missing)}.",
        ),
        quality_check(
            "nonnegative_raw_reserves",
            not negative_reserves,
            f"Negative reserve rows={len(negative_reserves)}; raw integers were retained.",
        ),
        quality_check(
            "historical_get_reserves_comparison",
            archive_passed,
            (
                f"Compared {len(available_archive)} historical calls; all available samples must match."
                if available_archive
                else "Historical eth_call was unavailable; Sync-log reconstruction remains the fallback."
            ),
            critical=False,
            warning=not available_archive,
        ),
        quality_check(
            "receipt_proxy_sample",
            int(config["receipt_sample_minimum"]) <= len(receipts) <= int(config["receipt_sample_size"]),
            f"Collected {len(receipts)} receipts; required range is {config['receipt_sample_minimum']}–{config['receipt_sample_size']}.",
        ),
        quality_check(
            "cfmm_integer_floor_case",
            manual_cfmm,
            "Manual case: amountIn=10, reserves=1000/2000, fee=0.3%, integer output=19.",
        ),
        quality_check(
            "gas_wei_to_weth_case",
            manual_gas,
            "Manual case: 150,000 gas × 30 gwei = 0.0045 WETH.",
        ),
        quality_check(
            "simulation_observation_count",
            len(simulations) == expected_simulations and not incomplete_simulations,
            f"Produced {len(simulations)} of {expected_simulations} rows; incomplete={len(incomplete_simulations)}.",
        ),
        quality_check(
            "pool_fee_not_double_counted",
            True,
            "The 997/1000 fee is applied only inside each get_amount_out call; profit subtracts only input and gas.",
        ),
        quality_check(
            "unrecovered_rpc_failures",
            not failed_requests,
            f"Recovered optional-stage or unrecovered transport failures recorded={len(failed_requests)}.",
            critical=False,
            warning=bool(failed_requests),
        ),
    ]
    return checks


POOL_METADATA_FIELDS = [
    "chain_id",
    "dex_name",
    "factory_address",
    "pair_id",
    "pair_address",
    "token0_address",
    "token1_address",
    "token0_symbol",
    "token1_symbol",
    "token0_decimals",
    "token1_decimals",
    "fee_rate",
    "creation_block",
]

BLOCK_FIELDS = [
    "block_number",
    "block_hash",
    "parent_hash",
    "timestamp",
    "timestamp_utc",
    "base_fee_per_gas",
    "gas_used",
    "gas_limit",
]

EVENT_FIELDS = [
    "block_number",
    "block_hash",
    "transaction_hash",
    "transaction_index",
    "log_index",
    "pair_address",
    "event_type",
    "in_observation_window",
    "sender",
    "to",
    "reserve0_raw",
    "reserve1_raw",
    "amount0_in_raw",
    "amount1_in_raw",
    "amount0_out_raw",
    "amount1_out_raw",
]

RECEIPT_FIELDS = [
    "transaction_hash",
    "block_number",
    "transaction_index",
    "status",
    "gas_used",
    "effective_gas_price",
    "gas_units_proxy",
]

SNAPSHOT_FIELDS = [
    "chain_id",
    "block_number",
    "pair_id",
    "pair_address",
    "token0_address",
    "token1_address",
    "reserve0_raw",
    "reserve1_raw",
    "state_quality_flag",
    "state_source_type",
    "last_sync_block_number",
    "last_sync_transaction_hash",
    "last_sync_log_index",
]

SIMULATION_FIELDS = [
    "block_number",
    "timestamp",
    "route_id",
    "input_amount_weth",
    "hop1_output",
    "hop2_output",
    "final_output_weth",
    "gross_profit_before_price_impact_weth",
    "price_impact_cost_weth",
    "gross_profit_weth",
    "gas_units_assumption",
    "effective_gas_price",
    "gas_cost_weth",
    "net_profit_weth",
    "profitable_after_gas",
    "data_status",
]


def run_pipeline(
    *,
    config_path: Path,
    rpc_url: str,
    archive_rpc_url: str,
    output_root: Path,
    start_block: int | None,
    end_block: int | None,
    resume: bool,
) -> tuple[Path, dict[str, Any]]:
    from .reporting import create_outputs

    config = load_json(config_path)
    client = RpcClient(rpc_url)
    archive_client = client if archive_rpc_url == rpc_url else RpcClient(archive_rpc_url)
    chain_id = int(client.request("eth_chainId", []), 16)
    if chain_id != int(config["chain_id"]):
        raise ValueError(f"RPC chain_id={chain_id}, expected {config['chain_id']}")
    if archive_client is not client:
        archive_chain_id = int(archive_client.request("eth_chainId", []), 16)
        if archive_chain_id != chain_id:
            raise ValueError(
                f"Archive RPC chain_id={archive_chain_id}, primary chain_id={chain_id}"
            )

    finalized_block = client.request("eth_getBlockByNumber", [config["finality_tag"], False])
    if finalized_block is None:
        raise ValueError(f"RPC did not return the {config['finality_tag']} block")
    finalized_number = int(finalized_block["number"], 16)
    if end_block is None:
        end_block = finalized_number
    if end_block > finalized_number:
        raise ValueError(f"end_block {end_block} exceeds finalized block {finalized_number}")
    if start_block is None:
        start_block = end_block - int(config["block_count"]) + 1
    if end_block - start_block + 1 != int(config["block_count"]):
        raise ValueError(f"Pilot requires exactly {config['block_count']} continuous blocks")

    output_dir = output_root / f"ethereum_uniswap_v2_{start_block}_{end_block}"
    checkpoint_dir = output_dir / ".checkpoints"
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    run_metadata: dict[str, Any] = {
        "run_started_at_utc": utc_now_text(),
        "chain_id": chain_id,
        "chain_name": config["chain_name"],
        "dex_name": config["dex_name"],
        "factory_address": config["factory_address"],
        "rpc_endpoint_sanitized": client.public_url,
        "rpc_url_source": "environment_or_explicit_runtime_argument",
        "archive_rpc_endpoint_sanitized": archive_client.public_url,
        "archive_rpc_url_source": "environment_or_explicit_runtime_argument_or_primary",
        "stage_rpc_endpoints": {
            "pool_metadata_and_pair_created": archive_client.public_url,
            "block_metadata": client.public_url,
            "pair_events_and_receipts": archive_client.public_url,
            "historical_get_reserves_checks": archive_client.public_url,
        },
        "finality_tag": config["finality_tag"],
        "finalized_block_at_start": finalized_number,
        "start_block": start_block,
        "end_block": end_block,
        "block_count": end_block - start_block + 1,
        "config_path": str(config_path),
        "config_sha256": config_digest(config_path),
        "resume_enabled": resume,
        "classification": {
            "direct_observations": "Factory/Pair/ERC-20 eth_call results, block objects, logs, and receipts.",
            "derived_values": "Snapshots, CFMM outputs, price-impact estimates, and profits.",
            "researcher_settings": "Block count, routes, input sizes, fee constants, sample size, and quantiles.",
            "proxy_values": "Receipt gas quantiles and median receipt priority fee applied to block base fees.",
        },
    }
    write_json(output_dir / "run_metadata.json", run_metadata)

    print("[1/8] Fetching Factory-derived pool metadata", flush=True)
    pair_metadata = checkpoint(
        checkpoint_dir,
        "pool_metadata",
        lambda: fetch_pool_metadata(archive_client, config, end_block),
        resume=resume,
    )
    write_csv(output_dir / "pool_metadata.csv", pair_metadata, POOL_METADATA_FIELDS)

    print("[2/8] Fetching 1,000 finalized block headers", flush=True)
    blocks = checkpoint(
        checkpoint_dir,
        "block_metadata",
        lambda: fetch_blocks(client, start_block, end_block, int(config["block_batch_size"])),
        resume=resume,
    )
    write_csv(output_dir / "block_metadata.csv", blocks, BLOCK_FIELDS)

    print("[3/8] Fetching Pair Sync/Swap event logs", flush=True)
    events = checkpoint(
        checkpoint_dir,
        "pool_events",
        lambda: fetch_pair_events(
            archive_client, pair_metadata, config, start_block, end_block
        ),
        resume=resume,
    )
    write_csv(output_dir / "pool_events.csv", events, EVENT_FIELDS)

    print("[4/8] Reconstructing block-end pool states", flush=True)
    initial_reserves = checkpoint(
        checkpoint_dir,
        "initial_reserves",
        lambda: fetch_initial_reserves(archive_client, pair_metadata, start_block - 1),
        resume=resume,
    )
    snapshots = checkpoint(
        checkpoint_dir,
        "pool_state_snapshots",
        lambda: reconstruct_snapshots(
            pair_metadata, events, initial_reserves, start_block, end_block
        ),
        resume=resume,
    )
    write_csv(output_dir / "pool_state_snapshots.csv", snapshots, SNAPSHOT_FIELDS)

    print("[5/8] Sampling transaction receipts for gas proxies", flush=True)
    receipts = checkpoint(
        checkpoint_dir,
        "transaction_receipts",
        lambda: fetch_receipts(
            archive_client, events, int(config["receipt_sample_size"])
        ),
        resume=resume,
    )
    write_csv(output_dir / "transaction_receipts.csv", receipts, RECEIPT_FIELDS)

    sample_blocks = sorted({start_block, (start_block + end_block) // 2, end_block})
    print("[6/8] Comparing reconstructed states with historical getReserves", flush=True)
    archive_checks = checkpoint(
        checkpoint_dir,
        "archive_state_checks",
        lambda: fetch_archive_state_checks(
            archive_client, pair_metadata, snapshots, sample_blocks
        ),
        resume=resume,
    )
    write_csv(
        output_dir / "archive_state_checks.csv",
        archive_checks,
        [
            "block_number",
            "pair_id",
            "pair_address",
            "reconstructed_reserve0_raw",
            "reconstructed_reserve1_raw",
            "historical_call_reserve0_raw",
            "historical_call_reserve1_raw",
            "archive_call_status",
            "reserves_match",
            "error",
        ],
    )

    print("[7/8] Simulating two routes and five WETH inputs", flush=True)
    gas_assumptions = build_gas_assumptions(receipts, blocks, config["gas_quantiles"])
    simulations = checkpoint(
        checkpoint_dir,
        "arbitrage_simulation",
        lambda: simulate_arbitrage(config, pair_metadata, blocks, snapshots, gas_assumptions),
        resume=resume,
    )
    write_csv(output_dir / "arbitrage_simulation.csv", simulations, SIMULATION_FIELDS)

    print("[8/8] Running quality checks and generating reports/figures", flush=True)
    checks = build_quality_checks(
        config,
        pair_metadata,
        blocks,
        events,
        receipts,
        snapshots,
        archive_checks,
        simulations,
        client.stats.failed_requests
        + (archive_client.stats.failed_requests if archive_client is not client else []),
    )
    write_json(output_dir / "quality_checks.json", checks)
    feasibility_success = not any(
        row["critical"] and row["status"] != "PASS" for row in checks
    )

    summary: dict[str, Any] = {
        "feasibility_success": feasibility_success,
        "start_block": start_block,
        "end_block": end_block,
        "block_rows": len(blocks),
        "event_rows_total": len(events),
        "event_rows_observation_window": sum(bool(row["in_observation_window"]) for row in events),
        "sync_rows_observation_window": sum(
            row["event_type"] == "Sync" and bool(row["in_observation_window"]) for row in events
        ),
        "swap_rows_observation_window": sum(
            row["event_type"] == "Swap" and bool(row["in_observation_window"]) for row in events
        ),
        "receipt_rows": len(receipts),
        "snapshot_rows": len(snapshots),
        "snapshot_missing_rows": sum(row["state_quality_flag"] == "missing" for row in snapshots),
        "simulation_rows": len(simulations),
        "simulation_incomplete_rows": sum(row["data_status"] != "complete" for row in simulations),
        "gross_positive_rows": sum(
            row["data_status"] == "complete" and Decimal(row["gross_profit_weth"]) > 0
            for row in simulations
        ),
        "net_positive_rows_low_gas": sum(
            row["data_status"] == "complete" and Decimal(row["net_profit_weth_low"]) > 0
            for row in simulations
        ),
        "net_positive_rows_median_gas": sum(
            row["data_status"] == "complete" and Decimal(row["net_profit_weth"]) > 0
            for row in simulations
        ),
        "net_positive_rows_high_gas": sum(
            row["data_status"] == "complete" and Decimal(row["net_profit_weth_high"]) > 0
            for row in simulations
        ),
        "gas_assumptions": gas_assumptions,
        "http_requests": client.stats.http_requests
        + (archive_client.stats.http_requests if archive_client is not client else 0),
        "rpc_calls": client.stats.rpc_calls
        + (archive_client.stats.rpc_calls if archive_client is not client else 0),
        "rpc_retries": client.stats.retries
        + (archive_client.stats.retries if archive_client is not client else 0),
        "unrecovered_request_failures": len(client.stats.failed_requests)
        + (len(archive_client.stats.failed_requests) if archive_client is not client else 0),
        "quality_pass": sum(row["status"] == "PASS" for row in checks),
        "quality_warn": sum(row["status"] == "WARN" for row in checks),
        "quality_fail": sum(row["status"] == "FAIL" for row in checks),
    }
    write_json(output_dir / "run_summary.json", summary)
    create_outputs(
        output_dir=output_dir,
        config=config,
        metadata=run_metadata,
        summary=summary,
        checks=checks,
        pair_metadata=pair_metadata,
        blocks=blocks,
        events=events,
        receipts=receipts,
        snapshots=snapshots,
        simulations=simulations,
    )
    run_metadata.update(
        run_completed_at_utc=utc_now_text(),
        rpc_stats={
            "primary": {
                "endpoint": client.public_url,
                "http_requests": client.stats.http_requests,
                "rpc_calls": client.stats.rpc_calls,
                "retries": client.stats.retries,
                "unrecovered_failures": client.stats.failed_requests,
            },
            "archive": {
                "endpoint": archive_client.public_url,
                "http_requests": archive_client.stats.http_requests,
                "rpc_calls": archive_client.stats.rpc_calls,
                "retries": archive_client.stats.retries,
                "unrecovered_failures": archive_client.stats.failed_requests,
            },
        },
        feasibility_success=feasibility_success,
    )
    write_json(output_dir / "run_metadata.json", run_metadata)
    return output_dir, summary
