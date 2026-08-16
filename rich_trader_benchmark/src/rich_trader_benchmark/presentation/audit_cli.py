"""Command-line interface for the RICH/TRADER dataset audit."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich_trader_benchmark.application.audit_datasets import AuditDatasets
from rich_trader_benchmark.infrastructure.trader_dataset_audit import (
    TraderDatasetInspector,
    load_benchmark_spec,
    load_file_manifest,
    validate_manifest_coverage,
)
from rich_trader_benchmark.presentation.audit_report import write_audit_reports


PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PACKAGE_ROOT / "configs" / "datasets" / "trader_uni1_uni6.toml"
DEFAULT_MANIFEST = PACKAGE_ROOT / "metadata" / "trader_uni1_uni6_files.csv"
DEFAULT_OUTPUT = PACKAGE_ROOT / "artifacts" / "data_audit"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the provenance, identity, format, and counts of TRADER UNI1--UNI6."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Directory containing processed_graph_data_new; otherwise use the configured environment variable.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        benchmark = load_benchmark_spec(args.config)
        manifest = load_file_manifest(args.manifest)
        validate_manifest_coverage(benchmark, manifest)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    data_dir = args.data_dir
    if data_dir is None:
        configured = os.environ.get(benchmark.data_root_environment_variable)
        if configured:
            data_dir = Path(configured)
    if data_dir is None:
        print(
            "Data directory is required. Pass --data-dir or set "
            f"{benchmark.data_root_environment_variable}.",
            file=sys.stderr,
        )
        return 2

    report = AuditDatasets(TraderDatasetInspector()).execute(
        benchmark=benchmark,
        manifest=manifest,
        data_root=data_dir,
    )
    paths = write_audit_reports(report, args.output_dir)
    for dataset in report.datasets:
        print(
            f"{dataset.dataset_id}: {'PASS' if dataset.passed else 'FAIL'} "
            f"({sum(file.passed for file in dataset.file_results)}/3 files, "
            f"{len(dataset.issues)} findings)"
        )
    print(f"Overall: {'PASS' if report.passed else 'FAIL'}")
    for path in paths:
        print(f"Wrote {path}")
    return 0 if report.passed else 1
if __name__ == "__main__":
    raise SystemExit(main())
