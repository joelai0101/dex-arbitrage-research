"""Machine-readable and human-readable data-audit reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from rich_trader_benchmark.domain.dataset_audit import (
    COUNT_FIELDS,
    DatasetAuditReport,
)


def write_audit_reports(report: DatasetAuditReport, output_dir: Path) -> tuple[Path, Path, Path]:
    """Write JSON, CSV, and Markdown views of one immutable audit result."""

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "audit_summary.json"
    csv_path = output_dir / "audit_summary.csv"
    markdown_path = output_dir / "audit_report.md"

    json_path.write_text(
        json.dumps(_report_payload(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(report, csv_path)
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, csv_path, markdown_path


def _report_payload(report: DatasetAuditReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "audited_at_utc": report.audited_at_utc,
        "data_root": report.data_root,
        "source_repository": report.source_repository,
        "source_commit": report.source_commit,
        "accessed_on": report.accessed_on,
        "datasets": [
            {
                "dataset": item.dataset_id,
                "block": item.block,
                "passed": item.passed,
                "expected_counts": dict(item.expected_counts),
                "observed_counts": dict(item.observed_counts),
                "files": [
                    {
                        "filename": file.filename,
                        "passed": file.passed,
                        "exists": file.exists,
                        "expected_bytes": file.expected_bytes,
                        "observed_bytes": file.observed_bytes,
                        "expected_sha256": file.expected_sha256,
                        "observed_sha256": file.observed_sha256,
                    }
                    for file in item.file_results
                ],
                "issues": [
                    {
                        "code": issue.code,
                        "message": issue.message,
                        "filename": issue.filename,
                        "line": issue.line,
                    }
                    for issue in item.issues
                ],
            }
            for item in report.datasets
        ],
    }


def _write_csv(report: DatasetAuditReport, path: Path) -> None:
    fields = ["dataset", "block", "passed", "files_passed", *COUNT_FIELDS, "issues"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for item in report.datasets:
            writer.writerow(
                {
                    "dataset": item.dataset_id,
                    "block": item.block,
                    "passed": item.passed,
                    "files_passed": sum(file.passed for file in item.file_results),
                    **{name: item.observed_counts.get(name) for name in COUNT_FIELDS},
                    "issues": len(item.issues),
                }
            )


def _markdown(report: DatasetAuditReport) -> str:
    verdict = "PASS" if report.passed else "FAIL"
    lines = [
        "# RICH/TRADER Dataset Audit",
        "",
        f"- Verdict: **{verdict}**",
        f"- Audited at (UTC): `{report.audited_at_utc}`",
        f"- Declared source: `{report.source_repository}`",
        f"- Declared source commit: `{report.source_commit}`",
        f"- Source access date: `{report.accessed_on}`",
        f"- Local data root: `{report.data_root}`",
        "",
        "| Dataset | Block | Files | Mapped nodes | Initial rows | Finite initial | Update rows | Finite updates | Events | Result |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report.datasets:
        observed = item.observed_counts
        lines.append(
            "| {dataset} | {block} | {files}/3 | {nodes} | {initial} | {finite_initial} | "
            "{updates} | {finite_updates} | {events} | {result} |".format(
                dataset=item.dataset_id,
                block=item.block,
                files=sum(file.passed for file in item.file_results),
                nodes=_display(observed.get("mapped_nodes")),
                initial=_display(observed.get("initial_edge_records")),
                finite_initial=_display(observed.get("finite_initial_edges")),
                updates=_display(observed.get("update_records")),
                finite_updates=_display(observed.get("finite_update_records")),
                events=_display(observed.get("unique_update_events")),
                result="PASS" if item.passed else "FAIL",
            )
        )

    failures = [item for item in report.datasets if item.issues]
    lines.extend(["", "## Findings", ""])
    if not failures:
        lines.append(
            "All required files matched the committed byte-size and SHA-256 manifest; "
            "all configured counts, row formats, endpoint ranges, and event-order checks passed."
        )
    else:
        for item in failures:
            lines.append(f"### {item.dataset_id}")
            lines.append("")
            for issue in item.issues:
                location = issue.filename or "dataset"
                if issue.line is not None:
                    location += f":{issue.line}"
                lines.append(f"- `{issue.code}` ({location}): {issue.message}")
            lines.append("")

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "A passing audit establishes that the local UNI1--UNI6 files match the frozen "
            "benchmark manifest and can be parsed consistently. It does not reproduce RICH "
            "or TRADER, prove arbitrage-detection correctness, or estimate executable profit.",
            "",
        ]
    )
    return "\n".join(lines)


def _display(value: int | None) -> str:
    return "--" if value is None else f"{value:,}"

