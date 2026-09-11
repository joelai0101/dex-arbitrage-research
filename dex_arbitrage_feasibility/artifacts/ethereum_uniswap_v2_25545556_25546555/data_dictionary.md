# Data Dictionary

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
