from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from .dex_feasibility.core import (
    block_chain_is_continuous,
    decimal_text,
    gas_cost_weth,
    get_amount_out,
    is_sorted_events,
    orient_reserves,
    pair_key,
    raw_to_decimal,
)


MODULE_ROOT = Path(__file__).resolve().parent


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate(artifact_dir: Path) -> dict[str, Any]:
    required_files = [
        "pool_metadata.csv",
        "block_metadata.csv",
        "pool_events.csv",
        "transaction_receipts.csv",
        "pool_state_snapshots.csv",
        "arbitrage_simulation.csv",
        "data_dictionary.md",
        "feasibility_report.md",
        "traceability_case.md",
        "quality_checks.json",
        "run_metadata.json",
        "run_summary.json",
        "profit_by_input.png",
        "opportunity_counts.png",
        "gas_scenario_distribution.png",
    ]
    missing_files = [name for name in required_files if not (artifact_dir / name).is_file()]
    require(not missing_files, f"Missing required files: {missing_files}")
    empty_files = [name for name in required_files if (artifact_dir / name).stat().st_size == 0]
    require(not empty_files, f"Empty required files: {empty_files}")

    config = json.loads((MODULE_ROOT / "config" / "pilot.json").read_text(encoding="utf-8"))
    metadata = read_csv(artifact_dir / "pool_metadata.csv")
    blocks = read_csv(artifact_dir / "block_metadata.csv")
    events = read_csv(artifact_dir / "pool_events.csv")
    receipts = read_csv(artifact_dir / "transaction_receipts.csv")
    snapshots = read_csv(artifact_dir / "pool_state_snapshots.csv")
    simulations = read_csv(artifact_dir / "arbitrage_simulation.csv")

    require(len(metadata) == 3, f"Expected 3 pool metadata rows, got {len(metadata)}")
    require(len(blocks) == 1000, f"Expected 1000 blocks, got {len(blocks)}")
    require(block_chain_is_continuous(blocks), "Block numbers or hash links are not continuous")
    require(is_sorted_events(events), "Events are not in canonical order")
    require(20 <= len(receipts) <= 50, f"Receipt count outside 20–50: {len(receipts)}")
    require(len(snapshots) == 3000, f"Expected 3000 snapshots, got {len(snapshots)}")
    require(
        all(row["state_quality_flag"] in {"observed_sync", "carried_forward"} for row in snapshots),
        "A snapshot is missing or has an unknown quality flag",
    )
    require(
        all(int(row["reserve0_raw"]) >= 0 and int(row["reserve1_raw"]) >= 0 for row in snapshots),
        "Negative or blank reserve found",
    )
    snapshot_keys = {
        (int(row["block_number"]), row["pair_address"].lower()) for row in snapshots
    }
    require(len(snapshot_keys) == len(snapshots), "Snapshot keys are not unique")

    expected_simulations = 1000 * len(config["routes"]) * len(config["input_amounts_weth"])
    require(
        len(simulations) == expected_simulations,
        f"Expected {expected_simulations} simulations, got {len(simulations)}",
    )
    observation_keys = {
        (
            row["chain_id"],
            int(row["block_number"]),
            row["route_id"],
            row["input_amount_weth"],
        )
        for row in simulations
    }
    require(len(observation_keys) == len(simulations), "Simulation observation keys are not unique")
    require(
        all(row["data_status"] == "complete" for row in simulations),
        "At least one simulation row is incomplete",
    )

    metadata_by_pair = {row["pair_address"].lower(): row for row in metadata}
    metadata_by_tokens = {
        pair_key(row["token0_address"], row["token1_address"]): row for row in metadata
    }
    snapshot_map = {
        (int(row["block_number"]), row["pair_address"].lower()): row for row in snapshots
    }
    token_addresses = {symbol: values["address"] for symbol, values in config["tokens"].items()}
    routes = {row["route_id"]: row["tokens"] for row in config["routes"]}
    fee_numerator = int(config["fee_numerator"])
    fee_denominator = int(config["fee_denominator"])

    recomputed_hops = 0
    for row in simulations:
        block_number = int(row["block_number"])
        route_addresses = [token_addresses[symbol] for symbol in routes[row["route_id"]]]
        amount = int(row["input_amount_raw"])
        outputs: list[int] = []
        for token_in, token_out in zip(route_addresses, route_addresses[1:]):
            pair = metadata_by_tokens[pair_key(token_in, token_out)]
            snapshot = snapshot_map[(block_number, pair["pair_address"].lower())]
            reserve_in, reserve_out = orient_reserves(pair, snapshot, token_in, token_out)
            amount = get_amount_out(
                amount, reserve_in, reserve_out, fee_numerator, fee_denominator
            )
            outputs.append(amount)
            recomputed_hops += 1
        require(int(row["hop1_output_raw"]) == outputs[0], "Hop 1 output mismatch")
        require(int(row["hop2_output_raw"]) == outputs[1], "Hop 2 output mismatch")
        require(int(row["final_output_raw"]) == outputs[2], "Final output mismatch")

        input_raw = int(row["input_amount_raw"])
        gross = raw_to_decimal(outputs[2] - input_raw, 18)
        require(row["gross_profit_weth"] == decimal_text(gross), "Gross profit mismatch")
        expected_gas = gas_cost_weth(
            int(row["gas_units_assumption"]), int(row["effective_gas_price"])
        )
        require(row["gas_cost_weth"] == decimal_text(expected_gas), "Gas cost mismatch")
        expected_net = gross - expected_gas
        require(row["net_profit_weth"] == decimal_text(expected_net), "Net profit mismatch")
        require(
            row["profitable_after_gas"] == str(expected_net > 0).lower(),
            "Profitability flag mismatch",
        )
        require(
            Decimal(row["price_impact_cost_weth"]) >= 0,
            "Negative price-impact cost found",
        )

    quality_checks = json.loads((artifact_dir / "quality_checks.json").read_text(encoding="utf-8"))
    critical_failures = [
        row for row in quality_checks if row["critical"] and row["status"] != "PASS"
    ]
    require(not critical_failures, f"Critical quality failures: {critical_failures}")
    summary = json.loads((artifact_dir / "run_summary.json").read_text(encoding="utf-8"))
    require(bool(summary["feasibility_success"]), "run_summary does not mark feasibility success")

    return {
        "artifact_dir": str(artifact_dir),
        "required_files": len(required_files),
        "pool_metadata_rows": len(metadata),
        "block_rows": len(blocks),
        "event_rows": len(events),
        "receipt_rows": len(receipts),
        "snapshot_rows": len(snapshots),
        "simulation_rows": len(simulations),
        "unique_observation_keys": len(observation_keys),
        "recomputed_cfmm_hops": recomputed_hops,
        "critical_quality_failures": 0,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Independently validate generated feasibility artifacts.")
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    try:
        result = validate(args.artifact_dir.resolve())
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
