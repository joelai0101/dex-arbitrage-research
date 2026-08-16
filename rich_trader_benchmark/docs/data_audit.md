# UNI1--UNI6 Data Audit

## Purpose

This is the first gate of the common RICH/TRADER benchmark. It answers one
bounded question: **do the local TRADER UNI1--UNI6 files match the frozen data
specification and parse consistently?**

It does not execute either negative-cycle algorithm.

## Inputs

- local `processed_graph_data_new` directory;
- `configs/datasets/trader_uni1_uni6.toml`, containing provenance and expected
  aggregate counts; and
- `metadata/trader_uni1_uni6_files.csv`, containing byte sizes and SHA-256
  hashes for the 18 required files.

## Checks

1. all three files for each of UNI1--UNI6 exist;
2. file byte sizes and SHA-256 hashes match the frozen manifest;
3. node mappings, graph rows, weights, and dynamic-update rows have valid
   formats;
4. graph endpoints are within the configured token-ID range;
5. update event IDs remain in chronological, contiguous groups; and
6. observed node, edge, finite/`inf`, update, and event counts match the
   committed specification.

## Run

From the Git repository root:

```powershell
$env:TRADER_UNI_DATA_DIR = "C:\path\to\processed_graph_data_new"
python rich_trader_benchmark\scripts\audit_datasets.py
```

The data directory can instead be supplied explicitly:

```powershell
python rich_trader_benchmark\scripts\audit_datasets.py `
    --data-dir "C:\path\to\processed_graph_data_new"
```

## Outputs

Local reports are written under `rich_trader_benchmark/artifacts/data_audit/`:

- `audit_summary.json`: complete machine-readable evidence;
- `audit_summary.csv`: one compact row per dataset; and
- `audit_report.md`: a human-readable table and findings.

The artifact directory is ignored by Git because it may include local paths.
Aggregate counts intended for the thesis should be copied only after this gate
passes and the data-source wording has been reviewed.

