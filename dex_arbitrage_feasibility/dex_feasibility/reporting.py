from __future__ import annotations

import os
import statistics
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence


os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(__file__).resolve().parents[2] / ".matplotlib")
)

import matplotlib


matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .core import orient_reserves, pair_key, quantile_int


def markdown_bool(value: Any) -> str:
    return "是" if bool(value) else "否"


def write_text(path: Path, value: str) -> None:
    path.write_text(value.rstrip() + "\n", encoding="utf-8")


def create_profit_plot(
    output_dir: Path, config: dict[str, Any], simulations: Sequence[dict[str, Any]]
) -> None:
    routes = [route["route_id"] for route in config["routes"]]
    inputs = [str(value) for value in config["input_amounts_weth"]]
    figure, axes = plt.subplots(1, len(routes), figsize=(14, 5), sharey=True)
    if len(routes) == 1:
        axes = [axes]
    for axis, route_id in zip(axes, routes):
        gross_medians: list[float] = []
        net_medians: list[float] = []
        gross_low: list[float] = []
        gross_high: list[float] = []
        net_low: list[float] = []
        net_high: list[float] = []
        for input_amount in inputs:
            subset = [
                row
                for row in simulations
                if row["route_id"] == route_id
                and str(row["input_amount_weth"]) == input_amount
                and row["data_status"] == "complete"
            ]
            gross = sorted(float(row["gross_profit_weth"]) for row in subset)
            net = sorted(float(row["net_profit_weth"]) for row in subset)
            gross_medians.append(statistics.median(gross))
            net_medians.append(statistics.median(net))
            gross_low.append(gross[max(0, round(0.05 * (len(gross) - 1)))])
            gross_high.append(gross[round(0.95 * (len(gross) - 1))])
            net_low.append(net[max(0, round(0.05 * (len(net) - 1)))])
            net_high.append(net[round(0.95 * (len(net) - 1))])
        x = [float(value) for value in inputs]
        axis.plot(x, gross_medians, marker="o", label="Gross profit after price impact")
        axis.fill_between(x, gross_low, gross_high, alpha=0.16)
        axis.plot(x, net_medians, marker="s", label="Net profit after median gas")
        axis.fill_between(x, net_low, net_high, alpha=0.16)
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_xscale("log")
        axis.set_title(route_id.replace("_", " → "))
        axis.set_xlabel("Input amount (WETH, log scale)")
        axis.grid(alpha=0.25)
    axes[0].set_ylabel("Profit (WETH), median and 5–95% range")
    axes[-1].legend(loc="best", fontsize=8)
    figure.suptitle("Input size vs. gross and gas-adjusted triangular-arbitrage profit")
    figure.tight_layout()
    figure.savefig(output_dir / "profit_by_input.png", dpi=170)
    plt.close(figure)


def create_opportunity_plot(
    output_dir: Path, config: dict[str, Any], simulations: Sequence[dict[str, Any]]
) -> None:
    labels: list[str] = []
    gross_counts: list[int] = []
    net_counts: list[int] = []
    for route in config["routes"]:
        route_id = route["route_id"]
        route_label = "forward" if "USDC_USDT" in route_id else "reverse"
        for input_amount in config["input_amounts_weth"]:
            subset = [
                row
                for row in simulations
                if row["route_id"] == route_id
                and str(row["input_amount_weth"]) == str(input_amount)
                and row["data_status"] == "complete"
            ]
            labels.append(f"{route_label}\n{input_amount} WETH")
            gross_counts.append(sum(Decimal(row["gross_profit_weth"]) > 0 for row in subset))
            net_counts.append(sum(Decimal(row["net_profit_weth"]) > 0 for row in subset))
    x = list(range(len(labels)))
    width = 0.38
    figure, axis = plt.subplots(figsize=(14, 6))
    gross_bars = axis.bar(
        [value - width / 2 for value in x], gross_counts, width, label="Gross > 0"
    )
    net_bars = axis.bar(
        [value + width / 2 for value in x], net_counts, width, label="Net > 0 (median gas)"
    )
    axis.bar_label(gross_bars, labels=[str(value) for value in gross_counts], padding=3)
    axis.bar_label(net_bars, labels=[str(value) for value in net_counts], padding=3)
    axis.set_xticks(x, labels, rotation=25, ha="right")
    axis.set_ylabel("Number of blocks")
    axis.set_title("Theoretical positive opportunities before and after median gas")
    axis.grid(axis="y", alpha=0.25)
    axis.legend()
    if max(gross_counts + net_counts, default=0) == 0:
        axis.set_ylim(0, 1)
        axis.text(
            0.5,
            0.65,
            "No positive observations in this 1,000-block pilot",
            transform=axis.transAxes,
            ha="center",
            va="center",
            fontsize=12,
        )
    figure.tight_layout()
    figure.savefig(output_dir / "opportunity_counts.png", dpi=170)
    plt.close(figure)


def create_gas_plot(output_dir: Path, simulations: Sequence[dict[str, Any]]) -> None:
    unique_by_block: dict[int, dict[str, Any]] = {}
    for row in simulations:
        if row["data_status"] == "complete":
            unique_by_block.setdefault(int(row["block_number"]), row)
    levels = ["low", "median", "high"]
    columns = {
        "low": "gas_cost_weth_low",
        "median": "gas_cost_weth_median",
        "high": "gas_cost_weth_high",
    }
    values = [
        [float(row[columns[level]]) for row in unique_by_block.values()] for level in levels
    ]
    figure, axis = plt.subplots(figsize=(9, 6))
    axis.boxplot(values, tick_labels=levels, showfliers=False)
    axis.set_ylabel("Gas cost (WETH)")
    axis.set_title("Low / median / high gas-proxy cost distributions across blocks")
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_dir / "gas_scenario_distribution.png", dpi=170)
    plt.close(figure)


def write_data_dictionary(output_dir: Path) -> None:
    content = """# Data Dictionary

## Value classes

- `direct_observation`: value returned by Ethereum JSON-RPC from a contract call, block object, event log, or receipt.
- `derived_calculation`: deterministically reconstructed or calculated from direct observations.
- `researcher_setting`: scope or model choice fixed before simulation.
- `proxy_value`: empirical substitute that is not the exact gas use of a standardized three-hop arbitrage transaction.

## pool_metadata.csv

| Field | Meaning | Class |
|---|---|---|
| chain_id, dex_name | Chain and DEX identifiers | researcher_setting, chain_id verified directly |
| factory_address | Uniswap v2 Factory used for `getPair` | researcher_setting |
| pair_address | Factory `getPair(tokenA, tokenB)` result | direct_observation |
| token0_address, token1_address | Pair contract token order | direct_observation |
| token0_symbol, token1_symbol | ERC-20 `symbol()` response | direct_observation |
| token0_decimals, token1_decimals | ERC-20 `decimals()` response | direct_observation |
| fee_rate / numerator / denominator | 0.3% fee encoded as 997/1000 | researcher_setting matching Uniswap v2 |
| creation_block | Matching Factory `PairCreated` log block | direct_observation |

## block_metadata.csv

All fields (`block_number`, hashes, timestamp, base fee, gas used, and gas limit) are direct observations from `eth_getBlockByNumber`. Hash linkage is a derived quality check.

## pool_events.csv

| Field | Meaning | Class |
|---|---|---|
| block / transaction / log coordinates | Canonical event position | direct_observation |
| pair_address, event_type | Emitting Pair and decoded topic | direct_observation / deterministic decoding |
| reserve0_raw, reserve1_raw | `Sync` uint112 values, unchanged integers | direct_observation |
| Swap amount fields, sender, to | Decoded `Swap` payload | direct_observation |
| in_observation_window | Separates warm-up Sync logs from the 1,000-block pilot | derived_calculation |

## transaction_receipts.csv

Receipt status, gas used, and effective gas price are direct observations. `gas_units_proxy` copies receipt `gas_used`, but its interpretation is a proxy because the sampled transaction is not a standardized three-hop arbitrage contract.

## pool_state_snapshots.csv

Reserves are direct observations when `state_quality_flag=observed_sync`; `carried_forward` rows deterministically reuse the latest observed state. `last_sync_*` preserves the raw event provenance. The snapshot semantics are end-of-block state, not a claim of actual execution.

## arbitrage_simulation.csv

| Field | Meaning | Class |
|---|---|---|
| block_number, timestamp | Snapshot observation coordinate | direct observation link |
| route_id, input_amount_weth | Route and fixed input | researcher_setting |
| hop outputs / final output | Three sequential 997/1000 CFMM integer calculations | derived_calculation |
| gross_profit_before_price_impact_weth | Marginal reserve-ratio output, with pool fees but without curve movement, minus input | derived_calculation |
| price_impact_cost_weth | No-impact output minus actual integer CFMM output | derived_calculation |
| gross_profit_weth | Actual final CFMM output minus input; pool fees already included | derived_calculation |
| gas_units_low/median/high | P25/P50/P75 of sampled receipt gas use | proxy_value |
| effective_gas_price | Block base fee plus median sampled priority fee | proxy_value built from direct observations |
| gas_cost_weth | Median gas units × gas price ÷ 1e18 | derived from proxy values |
| net_profit_weth | Gross profit minus median gas cost | derived_calculation |
| profitable_after_gas | `net_profit_weth > 0` | derived_calculation |
| data_status | Whether all three same-block pool states were available | derived quality flag |

The primary `gas_units_assumption`, `gas_cost_weth`, `net_profit_weth`, and `profitable_after_gas` columns use the median scenario. Low and high scenario columns are retained in the same observation row, so the observation unit remains `(chain_id, block_number, route_id, input_amount_weth)` and the maximum is 10,000 rows.
"""
    write_text(output_dir / "data_dictionary.md", content)


def select_trace_row(simulations: Sequence[dict[str, Any]]) -> dict[str, Any]:
    complete = [row for row in simulations if row["data_status"] == "complete"]
    if not complete:
        raise ValueError("No complete simulation row is available for tracing")
    return max(complete, key=lambda row: Decimal(row["net_profit_weth"]))


def write_traceability_case(
    output_dir: Path,
    config: dict[str, Any],
    summary: dict[str, Any],
    pair_metadata: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    receipts: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    simulations: Sequence[dict[str, Any]],
) -> None:
    row = select_trace_row(simulations)
    block_number = int(row["block_number"])
    block = next(item for item in blocks if int(item["block_number"]) == block_number)
    route = next(item for item in config["routes"] if item["route_id"] == row["route_id"])
    token_addresses = {symbol: item["address"] for symbol, item in config["tokens"].items()}
    metadata_by_address = {item["pair_address"].lower(): item for item in pair_metadata}
    snapshots_by_key = {
        (int(item["block_number"]), item["pair_address"].lower()): item for item in snapshots
    }
    event_by_source = {
        (item["transaction_hash"].lower(), int(item["log_index"])): item
        for item in events
        if item["event_type"] == "Sync"
    }
    hop_lines: list[str] = []
    for index, (token_in_symbol, token_out_symbol, pair_address) in enumerate(
        zip(route["tokens"], route["tokens"][1:], [row["hop1_pair_address"], row["hop2_pair_address"], row["hop3_pair_address"]]),
        start=1,
    ):
        metadata = metadata_by_address[pair_address.lower()]
        snapshot = snapshots_by_key[(block_number, pair_address.lower())]
        reserve_in, reserve_out = orient_reserves(
            metadata,
            snapshot,
            token_addresses[token_in_symbol],
            token_addresses[token_out_symbol],
        )
        source_hash = str(snapshot["last_sync_transaction_hash"])
        source_index = snapshot["last_sync_log_index"]
        source = (
            event_by_source.get((source_hash.lower(), int(source_index)))
            if source_hash and source_index != ""
            else None
        )
        output_raw = row[f"hop{index}_output_raw"] if index < 3 else row["final_output_raw"]
        source_text = (
            f"block `{source['block_number']}`, tx `{source['transaction_hash']}`, log `{source['log_index']}`"
            if source
            else f"{snapshot['state_source_type']} (no warm-up Sync source available)"
        )
        hop_lines.extend(
            [
                f"### Hop {index}: {token_in_symbol} → {token_out_symbol}",
                "",
                f"- Pair: `{pair_address}`",
                f"- State quality at block {block_number}: `{snapshot['state_quality_flag']}`",
                f"- Last state-changing Sync source: {source_text}",
                f"- Pair raw reserves: reserve0=`{snapshot['reserve0_raw']}`, reserve1=`{snapshot['reserve1_raw']}`",
                f"- Oriented reserves: reserve_in=`{reserve_in}`, reserve_out=`{reserve_out}`",
                f"- Integer CFMM output raw: `{output_raw}`",
                "",
            ]
        )

    gas_units = [int(item["gas_used"]) for item in receipts if int(item["status"]) == 1]
    median_units = int(summary["gas_assumptions"]["gas_units_median"])
    representative = min(receipts, key=lambda item: abs(int(item["gas_used"]) - median_units))
    hop_section = "\n".join(hop_lines)
    content = f"""# Complete Traceability Case

This case is selected deterministically as the complete row with the highest median-gas estimated net profit. Selection does not imply that the transaction was executable or realized at the time.

## Observation coordinate

- Chain: Ethereum mainnet (`chain_id=1`)
- Block: `{block_number}`
- Block hash: `{block['block_hash']}`
- Parent hash: `{block['parent_hash']}`
- Timestamp: `{block['timestamp_utc']}`
- Route: `{row['route_id']}`
- Input: `{row['input_amount_weth']} WETH` (`{row['input_amount_raw']}` raw units)

## State provenance and three-hop calculation

Each state is the selected block's end-of-block reserve state. A carried state points to the latest preceding `Sync` event.

{hop_section}
The contract-equivalent calculation at every hop is:

```text
amount_in_with_fee = amount_in × 997
amount_out = reserve_out × amount_in_with_fee
             ÷ (reserve_in × 1000 + amount_in_with_fee)
```

Integer floor division is used. The 0.3% fee is therefore already present in each hop output and is not subtracted again.

## Price impact and gross profit

- Final output: `{row['final_output_weth']} WETH` (`{row['final_output_raw']}` raw units)
- Marginal no-curve-movement gross profit: `{row['gross_profit_before_price_impact_weth']} WETH`
- Estimated price-impact cost: `{row['price_impact_cost_weth']} WETH`
- Gross profit after CFMM fees and price impact: `{row['gross_profit_weth']} WETH`

## Receipt sample and gas proxy

- Successful sampled receipts: `{len(gas_units)}`
- P25 / P50 / P75 gas-unit proxy: `{summary['gas_assumptions']['gas_units_low']}` / `{summary['gas_assumptions']['gas_units_median']}` / `{summary['gas_assumptions']['gas_units_high']}`
- Representative sampled receipt nearest P50: `{representative['transaction_hash']}`
- Representative receipt gas used: `{representative['gas_used']}`
- Block-specific effective gas-price proxy: `{row['effective_gas_price']}` wei (`{row['effective_gas_price_gwei']} gwei`)
- Median-scenario gas cost: `{row['gas_cost_weth']} WETH`

Receipt `gas_used` is a proxy for scenario construction. It is not claimed to equal the gas of a standardized three-hop arbitrage contract.

## Estimated net result

```text
estimated_net_profit = gross_profit_weth - gas_cost_weth
                     = {row['gross_profit_weth']} - {row['gas_cost_weth']}
                     = {row['net_profit_weth']} WETH
```

- Profitable after median gas: `{row['profitable_after_gas']}`
- Data status: `{row['data_status']}`
"""
    write_text(output_dir / "traceability_case.md", content)


def write_feasibility_report(
    output_dir: Path,
    config: dict[str, Any],
    metadata: dict[str, Any],
    summary: dict[str, Any],
    checks: Sequence[dict[str, Any]],
    pair_metadata: Sequence[dict[str, Any]],
) -> None:
    conclusion = (
        "最小資料管線可行（Minimum Data Pipeline Feasible）。"
        if summary["feasibility_success"]
        else "尚不能宣稱最小資料管線可行；至少一項關鍵品質檢查失敗。"
    )
    pair_lines = "\n".join(
        f"| {row['pair_id']} | `{row['pair_address']}` | {row['token0_symbol']}/{row['token1_symbol']} | {row['creation_block']} |"
        for row in pair_metadata
    )
    check_lines = "\n".join(
        f"| {row['status']} | {row['name']} | {markdown_bool(row['critical'])} | {row['detail']} |"
        for row in checks
    )
    limitations = [
        "這是以 block B 區塊末狀態進行的反事實模擬，不是對當時可成交性、排序位置或實現利潤的主張。",
        "三跳之間未模擬其他交易插入、mempool 競爭、MEV builder/bid、失敗交易或 reorg 風險。",
        "Gas units 取自一般 Swap 所在完整交易的 receipt 分布，只是 proxy；正式研究應使用固定套利合約的 local-fork replay 或 eth_estimateGas。",
        "公開 RPC 的可用性與 rate limit 可能隨時間改變；checkpoint 支援中斷後續跑。",
        "1,000 finalized blocks 僅能回答最小資料可行性，不能推論長期市場獲利能力。",
    ]
    content = rf"""# DEX Arbitrage Minimum Data Feasibility Report

## Research question

扣除 Gas 與價格衝擊後，DEX 套利還剩多少估計淨利潤？本 pilot 以 Ethereum mainnet、Uniswap v2、WETH/USDC/USDT 三角路徑為最小展示。

## Scope and exact provenance

- Chain: `{config['chain_name']}` (`chain_id={config['chain_id']}`)
- DEX: `{config['dex_name']}`
- Factory: `{config['factory_address']}`
- Primary RPC endpoint (sanitized; block metadata): `{metadata['rpc_endpoint_sanitized']}`
- Archive RPC endpoint (sanitized; PairCreated, Pair events, receipts, historical state): `{metadata['archive_rpc_endpoint_sanitized']}`
- Finality selector: `{metadata['finality_tag']}`
- Exact block range: `{summary['start_block']}`–`{summary['end_block']}` inclusive (`{summary['block_rows']}` blocks)
- Routes: `WETH → USDC → USDT → WETH` and `WETH → USDT → USDC → WETH`
- Inputs: `{', '.join(config['input_amounts_weth'])}` WETH
- Observation unit: `(chain_id, block_number, route_id, input_amount_weth)`

Pair addresses were not copied from a web page. They were returned by the configured Factory's `getPair`, then cross-checked against Pair `token0/token1` and Factory `PairCreated` logs.

| Pair ID | Factory-derived Pair | Observed token order | Creation block |
|---|---|---|---:|
{pair_lines}

## Data sources and processing

1. `eth_call`: Factory `getPair`, Pair `token0/token1/getReserves`, and ERC-20 `symbol/decimals`.
2. `eth_getBlockByNumber`: 1,000 finalized block objects with hash linkage and EIP-1559 base fee.
3. `eth_getLogs`: Pair `Sync` and `Swap`; warm-up `Sync` rows are flagged separately and supply provenance for carried-forward states.
4. `eth_getTransactionReceipt`: deterministic evenly spaced sample of Swap transaction receipts.
5. Deterministic processing: last `Sync` in transaction/log order defines a block-end state; no-Sync blocks carry the latest state and receive `state_quality_flag=carried_forward`.
6. Uniswap v2 integer CFMM: every hop applies 997/1000 exactly once, with integer floor division.
7. Gas proxy: receipt P25/P50/P75 gas units; each block's gas price is its observed base fee plus the median sampled priority fee.

## Row counts, missingness, and requests

| Dataset / metric | Result |
|---|---:|
| block_metadata.csv | {summary['block_rows']} rows |
| pool_events.csv (including warm-up Sync) | {summary['event_rows_total']} rows |
| events inside observation window | {summary['event_rows_observation_window']} rows |
| observation-window Sync / Swap | {summary['sync_rows_observation_window']} / {summary['swap_rows_observation_window']} |
| transaction_receipts.csv | {summary['receipt_rows']} rows |
| pool_state_snapshots.csv | {summary['snapshot_rows']} rows |
| missing snapshot rows | {summary['snapshot_missing_rows']} |
| arbitrage_simulation.csv | {summary['simulation_rows']} rows |
| incomplete simulation rows | {summary['simulation_incomplete_rows']} |
| HTTP requests / JSON-RPC calls / retries | {summary['http_requests']} / {summary['rpc_calls']} / {summary['rpc_retries']} |
| unrecovered request failures | {summary['unrecovered_request_failures']} |

## Profit opportunity counts

- Positive gross profit after pool fees and price impact: `{summary['gross_positive_rows']}` rows.
- Positive estimated net profit under low gas: `{summary['net_positive_rows_low_gas']}` rows.
- Positive estimated net profit under median gas: `{summary['net_positive_rows_median_gas']}` rows.
- Positive estimated net profit under high gas: `{summary['net_positive_rows_high_gas']}` rows.

These are historical block-end counterfactual calculations, not realized trades.

## Value classification

- Direct observations: contract calls, block fields, logs, and receipts.
- Derived calculations: carried-forward snapshots, CFMM hop outputs, price-impact estimate, gross/net profit, and quality flags.
- Researcher settings: exact block count, routes, inputs, 997/1000 fee constants, receipt sample size, and P25/P50/P75 quantiles.
- Proxy values: general Swap receipt gas distributions and the sampled priority-fee median. They do not equal a replayed three-hop arbitrage transaction.

## Quality checks

| Status | Check | Critical | Detail |
|---|---|---|---|
{check_lines}

Summary: PASS=`{summary['quality_pass']}`, WARN=`{summary['quality_warn']}`, FAIL=`{summary['quality_fail']}`.

## Conclusion

**{conclusion}**

This conclusion means the required raw data can be obtained and traced, same-block pool states can be reconstructed, two routes × five inputs can be simulated, and Gas can be converted to WETH. It does not mean that Uniswap v2 triangular arbitrage is generally profitable.

## Limitations

{chr(10).join(f'- {item}' for item in limitations)}

## Reproduction

Use the exact range in this report and inject the RPC URL through an environment variable:

```powershell
$env:ETHEREUM_RPC_URL = '<your Ethereum RPC URL>'
$env:ETHEREUM_ARCHIVE_RPC_URL = '<your Ethereum archive RPC URL>'
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.run --start-block {summary['start_block']} --end-block {summary['end_block']}
```

Checkpoint files under `.checkpoints/` support resumption and are intentionally excluded from Git.
"""
    write_text(output_dir / "feasibility_report.md", content)


def create_outputs(
    *,
    output_dir: Path,
    config: dict[str, Any],
    metadata: dict[str, Any],
    summary: dict[str, Any],
    checks: Sequence[dict[str, Any]],
    pair_metadata: Sequence[dict[str, Any]],
    blocks: Sequence[dict[str, Any]],
    events: Sequence[dict[str, Any]],
    receipts: Sequence[dict[str, Any]],
    snapshots: Sequence[dict[str, Any]],
    simulations: Sequence[dict[str, Any]],
) -> None:
    write_data_dictionary(output_dir)
    write_traceability_case(
        output_dir,
        config,
        summary,
        pair_metadata,
        blocks,
        events,
        receipts,
        snapshots,
        simulations,
    )
    write_feasibility_report(output_dir, config, metadata, summary, checks, pair_metadata)
    create_profit_plot(output_dir, config, simulations)
    create_opportunity_plot(output_dir, config, simulations)
    create_gas_plot(output_dir, simulations)
