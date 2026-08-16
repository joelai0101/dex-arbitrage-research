# RICH / TRADER Common Benchmark

This package defines a reproducible benchmark for static and dynamic
negative-cycle detection on the six TRADER Uniswap V2 datasets (UNI1--UNI6).

It deliberately does **not** contain the author-provided datasets or copied
RICH/TRADER source code. Baselines are kept outside the repository and are
referenced through local environment variables.

## Research objective

Given the same initial token graph, chronological edge-update stream, hop
limit, color assignments, and random seeds, evaluate whether a proposed method
can preserve the same detected cycle weight while improving at least one system
metric:

- detection/update time;
- maximum memory consumption;
- update throughput.

Cycle weight and relative error are mandatory correctness/quality checks. All
five metrics are reported even when the proposed contribution targets only one
of them.

## Directory layout

```text
rich_trader_benchmark/
├── configs/
│   ├── datasets/trader_uni1_uni6.toml
│   └── experiments/common_benchmark.toml
├── data/                      # local-only; raw data is ignored by Git
├── docs/
│   ├── data_provenance.md
│   ├── experiment_protocol.md
│   └── result_schema.md
├── metadata/
│   └── trader_uni1_uni6_files.csv
├── scripts/                   # thin, user-facing entry points
├── src/rich_trader_benchmark/
│   ├── domain/                # graph/update/cycle models and invariants
│   ├── application/           # benchmark use cases (ViewModel layer)
│   ├── infrastructure/        # parsers, CSR export, runners, measurements
│   └── presentation/          # CLI and report adapters (View layer)
└── tests/
    ├── unit/
    └── integration/
```

The package follows MVVM/SOLID separation:

- **Model/domain** owns graph semantics and correctness rules.
- **ViewModel/application** coordinates a benchmark without depending on file
  formats or a particular baseline executable.
- **View/presentation** exposes CLI commands and reports.
- **Infrastructure** adapts TRADER text files, RICH CSR files, external
  processes, timers, and memory monitors to domain interfaces.

## Data setup

1. Obtain `processed_graph_data_new` from the original TRADER repository.
2. Keep it outside Git.
3. Set `TRADER_UNI_DATA_DIR` to that directory.
4. Verify every file against `metadata/trader_uni1_uni6_files.csv` before use.

See `docs/data_provenance.md` for the exact interpretation of `inf`, update
event IDs, and the difference between the RICH and TRADER datasets named UNI1
through UNI6.

Run the Stage-1 audit from the Git repository root:

```powershell
python rich_trader_benchmark\scripts\audit_datasets.py `
    --data-dir "C:\path\to\processed_graph_data_new"
```

It writes local JSON, CSV, and Markdown reports under
`rich_trader_benchmark/artifacts/data_audit/`. See `docs/data_audit.md` for the
inputs, checks, outputs, and interpretation boundary.

## Planned execution order

1. Validate file hashes, row counts, and event ordering.
2. Reproduce one RICH and one TRADER smoke case without changing their code.
3. Generate common static checkpoints from the TRADER update stream.
4. Run the controlled common benchmark with fixed parameters and seeds.
5. Profile bottlenecks, lock one primary improvement target, implement the new
   method independently, and run the final evaluation.

No experiment result is considered final until the protocol in
`docs/experiment_protocol.md` is frozen.
