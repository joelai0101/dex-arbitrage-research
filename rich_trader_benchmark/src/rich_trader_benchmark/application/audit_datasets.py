"""Application service for the Stage-1 RICH/TRADER data audit."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol

from rich_trader_benchmark.domain.dataset_audit import (
    BenchmarkDataSpec,
    DatasetAuditReport,
    DatasetAuditResult,
    DatasetSpec,
    FileExpectation,
)


class DatasetInspector(Protocol):
    """Port implemented by a concrete TRADER file-format adapter."""

    def inspect(
        self,
        data_root: Path,
        dataset: DatasetSpec,
        expectations: Mapping[str, FileExpectation],
    ) -> DatasetAuditResult:
        """Inspect one dataset without mutating its raw files."""


class AuditDatasets:
    """Coordinate identical checks across all configured datasets."""

    def __init__(self, inspector: DatasetInspector) -> None:
        self._inspector = inspector

    def execute(
        self,
        benchmark: BenchmarkDataSpec,
        manifest: Mapping[tuple[str, str], FileExpectation],
        data_root: Path,
    ) -> DatasetAuditReport:
        resolved_root = data_root.expanduser().resolve()
        results: list[DatasetAuditResult] = []
        for dataset in benchmark.datasets:
            expected_files = {
                filename: manifest[(dataset.dataset_id, filename)]
                for filename in dataset.required_files
                if (dataset.dataset_id, filename) in manifest
            }
            results.append(self._inspector.inspect(resolved_root, dataset, expected_files))

        return DatasetAuditReport(
            audited_at_utc=datetime.now(timezone.utc).isoformat(),
            data_root=str(resolved_root),
            source_repository=benchmark.source_repository,
            source_commit=benchmark.source_commit,
            accessed_on=benchmark.accessed_on,
            datasets=tuple(results),
        )

