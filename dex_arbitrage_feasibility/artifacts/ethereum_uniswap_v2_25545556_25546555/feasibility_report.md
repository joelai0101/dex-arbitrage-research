# DEX Arbitrage Minimum Data Feasibility Report

## Research question

扣除 Gas 與價格衝擊後，DEX 套利還剩多少估計淨利潤？本 pilot 以 Ethereum mainnet、Uniswap v2、WETH/USDC/USDT 三角路徑為最小展示。

## Scope and exact provenance

- Chain: `Ethereum mainnet` (`chain_id=1`)
- DEX: `Uniswap v2`
- Factory: `0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f`
- Primary RPC endpoint (sanitized; block metadata): `https://ethereum-rpc.publicnode.com`
- Archive RPC endpoint (sanitized; PairCreated, Pair events, receipts, historical state): `https://ethereum-rpc.blockreq.com`
- Finality selector: `finalized`
- Exact block range: `25545556`–`25546555` inclusive (`1000` blocks)
- Routes: `WETH → USDC → USDT → WETH` and `WETH → USDT → USDC → WETH`
- Inputs: `0.01, 0.05, 0.1, 0.5, 1` WETH
- Observation unit: `(chain_id, block_number, route_id, input_amount_weth)`

Pair addresses were not copied from a web page. They were returned by the configured Factory's `getPair`, then cross-checked against Pair `token0/token1` and Factory `PairCreated` logs.

| Pair ID | Factory-derived Pair | Observed token order | Creation block |
|---|---|---|---:|
| WETH_USDC | `0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc` | USDC/WETH | 10008355 |
| USDC_USDT | `0x3041cbd36888becc7bbcbc0045e3b1f144466f5f` | USDC/USDT | 10092378 |
| USDT_WETH | `0x0d4a11d5eeaac28ec3f61d100daf4d40471f1852` | WETH/USDT | 10093341 |

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
| block_metadata.csv | 1000 rows |
| pool_events.csv (including warm-up Sync) | 941 rows |
| events inside observation window | 518 rows |
| observation-window Sync / Swap | 262 / 256 |
| transaction_receipts.csv | 50 rows |
| pool_state_snapshots.csv | 3000 rows |
| missing snapshot rows | 0 |
| arbitrage_simulation.csv | 10000 rows |
| incomplete simulation rows | 0 |
| HTTP requests / JSON-RPC calls / retries | 171 / 1200 / 0 |
| unrecovered request failures | 0 |

## Profit opportunity counts

- Positive gross profit after pool fees and price impact: `0` rows.
- Positive estimated net profit under low gas: `0` rows.
- Positive estimated net profit under median gas: `0` rows.
- Positive estimated net profit under high gas: `0` rows.

These are historical block-end counterfactual calculations, not realized trades.

## Value classification

- Direct observations: contract calls, block fields, logs, and receipts.
- Derived calculations: carried-forward snapshots, CFMM hop outputs, price-impact estimate, gross/net profit, and quality flags.
- Researcher settings: exact block count, routes, inputs, 997/1000 fee constants, receipt sample size, and P25/P50/P75 quantiles.
- Proxy values: general Swap receipt gas distributions and the sampled priority-fee median. They do not equal a replayed three-hop arbitrage transaction.

## Quality checks

| Status | Check | Critical | Detail |
|---|---|---|---|
| PASS | factory_pair_resolution | 是 | Resolved 3 pairs; all token sets must match Factory getPair inputs. |
| PASS | pair_creation_blocks | 是 | Creation block is taken from the matching Factory PairCreated event. |
| PASS | pair_creation_event_verification | 否 | When the RPC permits the historical log call, PairCreated must match the Factory getPair result. |
| PASS | token_decimals | 是 | Observed decimals {'0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': 6, '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': 18, '0xdac17f958d2ee523a2206206994597c13d831ec7': 6}; expected {'0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': 18, '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': 6, '0xdac17f958d2ee523a2206206994597c13d831ec7': 6}. |
| PASS | continuous_block_numbers_and_hashes | 是 | Fetched 1000 of 1000 consecutive finalized blocks. |
| PASS | event_sort_order | 是 | Checked 941 events by block, transaction index, and log index. |
| PASS | non_removed_logs | 是 | No retained event may be marked removed. |
| PASS | snapshot_completeness | 是 | Produced 3000 of 3000 snapshots; missing=0. |
| PASS | nonnegative_raw_reserves | 是 | Negative reserve rows=0; raw integers were retained. |
| PASS | historical_get_reserves_comparison | 否 | Compared 9 historical calls; all available samples must match. |
| PASS | receipt_proxy_sample | 是 | Collected 50 receipts; required range is 20–50. |
| PASS | cfmm_integer_floor_case | 是 | Manual case: amountIn=10, reserves=1000/2000, fee=0.3%, integer output=19. |
| PASS | gas_wei_to_weth_case | 是 | Manual case: 150,000 gas × 30 gwei = 0.0045 WETH. |
| PASS | simulation_observation_count | 是 | Produced 10000 of 10000 rows; incomplete=0. |
| PASS | pool_fee_not_double_counted | 是 | The 997/1000 fee is applied only inside each get_amount_out call; profit subtracts only input and gas. |
| PASS | unrecovered_rpc_failures | 否 | Recovered optional-stage or unrecovered transport failures recorded=0. |

Summary: PASS=`16`, WARN=`0`, FAIL=`0`.

## Conclusion

**最小資料管線可行（Minimum Data Pipeline Feasible）。**

This conclusion means the required raw data can be obtained and traced, same-block pool states can be reconstructed, two routes × five inputs can be simulated, and Gas can be converted to WETH. It does not mean that Uniswap v2 triangular arbitrage is generally profitable.

## Limitations

- 這是以 block B 區塊末狀態進行的反事實模擬，不是對當時可成交性、排序位置或實現利潤的主張。
- 三跳之間未模擬其他交易插入、mempool 競爭、MEV builder/bid、失敗交易或 reorg 風險。
- Gas units 取自一般 Swap 所在完整交易的 receipt 分布，只是 proxy；正式研究應使用固定套利合約的 local-fork replay 或 eth_estimateGas。
- 公開 RPC 的可用性與 rate limit 可能隨時間改變；checkpoint 支援中斷後續跑。
- 1,000 finalized blocks 僅能回答最小資料可行性，不能推論長期市場獲利能力。

## Reproduction

Use the exact range in this report and inject the RPC URL through an environment variable:

```powershell
$env:ETHEREUM_RPC_URL = '<your Ethereum RPC URL>'
$env:ETHEREUM_ARCHIVE_RPC_URL = '<your Ethereum archive RPC URL>'
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.run --start-block 25545556 --end-block 25546555
```

Checkpoint files under `.checkpoints/` support resumption and are intentionally excluded from Git.
