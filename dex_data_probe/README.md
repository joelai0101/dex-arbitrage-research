# DEX Data Probe

This small project checks whether basic DEX pool data can be fetched without paid data platforms.

## Scope

Initial targets:

- Ethereum Uniswap v2: `WETH/USDC`
- Ethereum Uniswap v3: `WETH/USDC` pools at fee tiers `500`, `3000`, `10000`
- BNB Chain PancakeSwap v2: `WBNB/USDT`
- Polygon QuickSwap v2: `WMATIC/USDC.e`

The script uses public JSON-RPC endpoints and read-only `eth_call`.
No private key, wallet, API key, or transaction signing is required.

## Files

- `probe_dex_pools.py`: fetches pool addresses and pool state.
- `data/`: output folder for `dex_pool_probe.json` and `dex_pool_probe.csv`.

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe 6D\code\dex_data_probe\probe_dex_pools.py
```

## What This Proves

If the script succeeds, the thesis workflow can use direct RPC calls to reconstruct a minimal pool state dataset.
This is enough for early feasibility checks for:

- gas-aware negative cycle detection;
- CFMM routing benchmark;
- cross-chain DEX price discrepancy scouting.

For full empirical work, this should later be replaced or complemented with indexed data from BigQuery, Dune, The Graph, or self-built event log extraction.
