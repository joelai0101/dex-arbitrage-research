# Ethereum Uniswap v2 Triangular-Arbitrage Data Feasibility

This isolated module demonstrates whether a reproducible 1,000-finalized-block dataset can support gas- and price-impact-aware triangular-arbitrage simulation.

## Scope

- Ethereum mainnet and Uniswap v2.
- Factory-derived WETH/USDC, USDC/USDT, and USDT/WETH Pair contracts.
- Routes: WETH → USDC → USDT → WETH and the reverse route.
- Inputs: 0.01, 0.05, 0.1, 0.5, and 1 WETH.
- Same-block end-state counterfactual simulation, not realized profit.

The module does not import or reuse `dex_data_probe/data`, prior experiment outputs, or conclusions.

## Security

Supply the RPC URL at runtime. Never commit a key or `.env` file.

```powershell
$env:ETHEREUM_RPC_URL = '<your Ethereum mainnet RPC URL>'
$env:ETHEREUM_ARCHIVE_RPC_URL = '<optional archive-capable Ethereum RPC URL>'
```

Only sanitized scheme/host values and the stage-to-endpoint mapping are recorded in `run_metadata.json`.

## Preflight

From the DEX repository root (`6D/code`):

```powershell
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.run --preflight-only
```

Preflight verifies chain ID, access to the `finalized` tag, and bytecode at the configured Factory address. It does not write research data.

## Run

Automatic 1,000-block range ending at the current finalized block:

```powershell
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.run
```

Exact reproducible range:

```powershell
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.run --start-block <START> --end-block <END>
```

Stages are checkpointed under the isolated artifact directory. Re-running resumes completed stages; use `--no-resume` only when intentionally rebuilding the same range.

## Tests

```powershell
..\..\.venv\Scripts\python.exe -m unittest discover -s dex_arbitrage_feasibility/tests -v
```

Independent validation of generated CSV files and all 30,000 CFMM hop calculations:

```powershell
..\..\.venv\Scripts\python.exe -m dex_arbitrage_feasibility.validate_artifacts <artifact-directory>
```

## Outputs

Each `artifacts/ethereum_uniswap_v2_<start>_<end>/` directory contains:

- `pool_metadata.csv`
- `block_metadata.csv`
- `pool_events.csv`
- `transaction_receipts.csv`
- `pool_state_snapshots.csv`
- `arbitrage_simulation.csv`
- `data_dictionary.md`
- `feasibility_report.md`
- three PNG figures
- `traceability_case.md`, `quality_checks.json`, `archive_state_checks.csv`, and run metadata

Checkpoint files are excluded from Git.
