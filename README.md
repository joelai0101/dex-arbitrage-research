# DEX Arbitrage Research

Research code and reproducible benchmarks for graph-based decentralized
exchange (DEX) arbitrage detection.

The repository currently focuses on two connected questions:

1. how to construct traceable DEX market data for controlled experiments; and
2. how to detect and maintain profitable negative cycles efficiently on static
   and dynamically updated token graphs.

The thesis direction is not limited to one implementation technique. Candidate
improvements may target cycle-detection algorithms, dynamic updates, DP-state
representation, memory consumption, detection latency, or throughput, while
preserving the same detection result under controlled inputs.

## Repository layout

```text
.
├── experiments/
│   └── dex_pool_rpc_probe/   # lightweight latest-state RPC smoke test
├── dex_arbitrage_feasibility/ # historical-data feasibility pipeline (PR #1)
└── rich_trader_benchmark/     # common RICH/TRADER benchmark (PR #2)
```

Only directories already merged into `main` are present in a fresh checkout.
The latter two components remain in draft pull requests until their evidence,
protocol, and limitations have been manually reviewed.

## Current component

### DEX pool RPC probe

`experiments/dex_pool_rpc_probe` is a small read-only smoke test. It queries
public JSON-RPC endpoints for selected Uniswap, PancakeSwap, and QuickSwap
pools and records their latest observable state.

It establishes basic RPC data accessibility only. It does **not** reconstruct
historical execution order, detect realized arbitrage, or estimate executable
profit.

## Data and source policy

- Raw third-party datasets, local build products, credentials, and generated
  experiment outputs are not committed unless redistribution and provenance
  are explicitly documented.
- RICH and TRADER source trees remain external baselines; this repository does
  not silently redistribute or relabel their code.
- Every reported experiment should record the dataset version or hash,
  parameters, random seeds, hardware, timeout policy, and output schema.
- Secrets such as RPC keys, wallet keys, and `.env` files must never be added
  to Git.

## Development workflow

1. Update `main` and create one `feature/<short-name>` branch per change.
2. Keep unrelated local data and experiments out of the branch.
3. Run relevant correctness and reproducibility checks.
4. Push the feature branch and open a draft pull request.
5. Merge only after checks pass and the user or designated reviewer approves.

See each component README for its inputs, outputs, execution command, and
limitations.
