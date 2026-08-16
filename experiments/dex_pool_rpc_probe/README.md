# DEX Pool RPC Probe

This lightweight experiment checks whether selected DEX pool states can be
read directly from public JSON-RPC endpoints without a paid data platform.

## Question

Can a local research workflow retrieve the latest pool address and state for a
small cross-chain sample using read-only contract calls?

## Scope

- Ethereum Uniswap v2: `WETH/USDC`
- Ethereum Uniswap v3: `WETH/USDC` at fee tiers `500`, `3000`, and `10000`
- BNB Chain PancakeSwap v2: `WBNB/USDT`
- Polygon QuickSwap v2: `WMATIC/USDC.e`

The script uses public JSON-RPC endpoints and read-only `eth_call`. It does not
require a private key, wallet, transaction signature, or API key.

## Run

From this Git repository root:

```powershell
python experiments/dex_pool_rpc_probe/probe_dex_pools.py
```

Inside the thesis workspace, the project virtual environment can be invoked
explicitly:

```powershell
& "..\..\.venv\Scripts\python.exe" `
    "experiments\dex_pool_rpc_probe\probe_dex_pools.py"
```

## Outputs

The script writes local files under `experiments/dex_pool_rpc_probe/data/`:

- `dex_pool_probe.json`
- `dex_pool_probe.csv`

Generated data is ignored by Git.

## Interpretation and limitations

A successful run shows that the selected latest-state values are accessible
through at least one configured public endpoint. It does not establish:

- historical data availability;
- transaction-order or mempool observability;
- complete token-graph coverage;
- arbitrage detection accuracy; or
- realizable profit after fees, slippage, latency, and execution risk.

Historical experiments require indexed logs or a validated event-reconstruction
pipeline rather than this latest-state smoke test alone.
