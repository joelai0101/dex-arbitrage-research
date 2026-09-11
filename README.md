# DEX Arbitrage Research

[English](README.md) | [繁體中文](README.zh-TW.md)

Research software for reproducible token-graph experiments and incremental cycle maintenance in decentralized exchanges. This checkout provides a DELTA terminal application and the RICH/TRADER dataset-audit foundation.

## Available components

| Component | Available functionality | Guide |
|---|---|---|
| DELTA terminal | Interactive menu, offline graph replay, bounded read-only Ethereum RPC capture, answer-equivalence tests | [Terminal guide (繁體中文)](delta_terminal/README.md) |
| RICH/TRADER benchmark | UNI1–UNI6 source/data audit, experiment protocol, result schema | [Benchmark guide](rich_trader_benchmark/README.md) |
| Supporting experiments | Scoped, reproducible research experiments | [Experiment policy](experiments/README.md) |

Benchmark execution, CCSS evaluation, dependency profiling, and historical feasibility work on other unmerged branches are not automatically included in this checkout. Raw author datasets, external baseline source trees, compiled binaries, and generated results are not bundled.

## Quick start: DELTA

Requirements: Python 3.12+ and an existing C++17 compiler. DELTA uses the Python standard library; no terminal-UI or Web3 package installation is required. Use a project-local virtual environment. Run the following commands from the Git repository root:

~~~powershell
# Activate your project environment, or replace python with its full path.
python -m delta_terminal build
python -m delta_terminal
~~~

The menu offers offline input, RPC capture/testing, core compilation, and exit. In the existing Windows research workspace, [start.ps1](delta_terminal/start.ps1) locates an ancestor project's `.venv/Scripts/python.exe` and opens the menu.

If the compiler is not discovered automatically:

~~~powershell
python -m delta_terminal build --compiler "C:\path\to\clang++.exe"
~~~

### Offline mode

~~~powershell
python -m delta_terminal offline
python -m delta_terminal offline --case "C:\data\token_case" --k 5 --batch 100 --output "C:\results\new_run"
~~~

A case contains `colors.txt`, `graph.txt`, `updates.txt`, and optionally `schedule.txt` and `metadata.json`. Updates set a weight, delete an edge (`D`), or record a no-op (`N`). Without `--batch`, an existing schedule is preserved; without a schedule, every update is answered. See the [input contract](delta_terminal/README.md#離線資料契約).

The terminal displays a sample; `results.json` retains every answer, witness path, and engine counters. Choose a new output directory for every run; existing outputs are not overwritten.

### RPC mode

~~~powershell
python -m delta_terminal rpc --blocks 2 --output "C:\results\new_rpc_run"
~~~

Enter an HTTPS RPC URL at the hidden prompt, or provide it through the process environment variable `DELTA_RPC_URL`. An empty prompt uses the configured Pocket public endpoint. Do not commit provider keys or put them in command-line URL arguments.

This mode captures a bounded sequence of finalized Ethereum block-end snapshots, then incrementally replays the resulting graph; it is not a continuous mempool subscription. Defaults are three Uniswap V2 pools (USDC/USDT/WETH), two blocks, one fixed coloring, and `k=3`. Each run permits at most 64 read-only requests, at least two seconds apart, without automatic retries. An unavailable RPC pauses that mode; offline replay remains available.

The capture also creates `<output>_case`, including block hashes and raw reserve values. Replay the same input offline:

~~~powershell
python -m delta_terminal offline --case "C:\results\new_rpc_run_case" --output "C:\results\rpc_replay"
~~~

Use `--pools` for a compatible pool configuration and `--start-block` for a finalized historical starting block, if the provider serves that state. The adapter assumes Uniswap V2's 997/1000 fee multiplier and one pool per token pair; parallel pools are rejected rather than silently merged.

## Correctness and architecture

DELTA maintains the minimum-weight simple directed cycle with exactly `k` edges within the chosen fixed coloring. A nonnegative best cycle is still returned; no candidate is represented by `null`. This does not guarantee the optimum over all uncolored cycles.

RPC weights are negative natural logarithms of fee-adjusted marginal exchange rates. A negative cycle is a price signal, not executable net profit: finite trade size, slippage, gas, competition, and transaction execution are not modeled. The application does not sign or submit transactions.

The terminal preserves the validated DELTA recurrence. The native engine, process adapter, data sources, application state, and terminal view have separate responsibilities. Lightweight MVVM and boundary adapters are used without a framework-wide rewrite.

## Tests

~~~powershell
python -m unittest delta_terminal.tests.test_terminal -v
~~~

Tests cover the teaching fixture, independently enumerated small graphs, batching, RPC-to-offline replay, inactive pools, block-hash changes, invalid input, credential redaction, request limits, and failed-run status. The optional original-binary comparison requires:

~~~powershell
$env:DELTA_REFERENCE_EXE = "C:\path\to\original_delta.exe"
python -m unittest delta_terminal.tests.test_terminal -v
~~~

`DELTA_REFERENCE_CASE` can select a different small case. This comparison also performs exhaustive enumeration: do not use it on a large graph. Dated local acceptance results are in the terminal guide; these functional tests are not performance benchmarks.

## RICH/TRADER data audit

Obtain the author-provided TRADER data separately and keep it outside Git:

~~~powershell
python rich_trader_benchmark/scripts/audit_datasets.py --data-dir "C:\data\processed_graph_data_new" --output-dir "C:\results\data_audit"
~~~

Alternatively set `TRADER_UNI_DATA_DIR`. The audit checks provenance, manifest identity, format, counts, and event order, then writes JSON/CSV/Markdown reports. Passing a data audit does not establish an arbitrage result. Read [data provenance](rich_trader_benchmark/docs/data_provenance.md), [audit details](rich_trader_benchmark/docs/data_audit.md), and the [experiment protocol](rich_trader_benchmark/docs/experiment_protocol.md) before interpreting measurements.

## Repository layout

~~~text
.
├── README.md                  # English entry point
├── README.zh-TW.md             # Traditional Chinese entry point
├── delta_terminal/             # DELTA core, terminal, RPC adapter, tests
├── rich_trader_benchmark/      # Dataset audit and benchmark specification
└── experiments/               # Supporting experiment policy
~~~

The surrounding research workspace may contain `6D/doc`, `6D/pdf`, or other research materials; those directories are outside this Git repository.

## Development and data policy

- Start implementation on a feature branch based on updated `main`; preserve unrelated changes and use a separate worktree when needed.
- Preserve original data and external baselines. Never commit `.env`, RPC credentials, wallet secrets, local runtimes, or large generated data.
- Check answer quality before interpreting speed. State initialization costs, measurement boundaries, and resource costs explicitly.
- Run relevant checks, commit the scoped change, and open a PR. Merge only after checks pass and the user or designated reviewer approves.
- Before removing a branch, verify PR/commit coverage and worktree contents. An absent remote branch alone is not evidence that local work can be discarded.
