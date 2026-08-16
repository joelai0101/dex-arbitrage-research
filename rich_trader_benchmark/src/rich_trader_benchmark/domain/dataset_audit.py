"""Domain records for auditing the TRADER UNI1--UNI6 datasets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


COUNT_FIELDS = (
    "mapped_nodes",
    "initial_edge_records",
    "finite_initial_edges",
    "infinite_initial_edges",
    "update_records",
    "finite_update_records",
    "unique_update_events",
)


@dataclass(frozen=True)
class DatasetSpec:
    """Expected files and aggregate counts for one TRADER dataset."""

    dataset_id: str
    block: int
    node_mapping_file: str
    token_graph_file: str
    dynamic_file: str
    mapped_nodes: int
    initial_edge_records: int
    finite_initial_edges: int
    infinite_initial_edges: int
    update_records: int
    finite_update_records: int
    unique_update_events: int

    @property
    def required_files(self) -> tuple[str, str, str]:
        return (
            self.node_mapping_file,
            self.token_graph_file,
            self.dynamic_file,
        )

    @property
    def expected_counts(self) -> Mapping[str, int]:
        return {field_name: getattr(self, field_name) for field_name in COUNT_FIELDS}


@dataclass(frozen=True)
class BenchmarkDataSpec:
    """Versioned provenance metadata and all dataset specifications."""

    schema_version: int
    source_repository: str
    source_commit: str
    accessed_on: str
    data_root_environment_variable: str
    raw_data_redistribution: bool
    datasets: tuple[DatasetSpec, ...]


@dataclass(frozen=True)
class FileExpectation:
    """Expected identity of one raw file."""

    dataset_id: str
    filename: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class FileAuditResult:
    """Observed identity and pass/fail state of one raw file."""

    filename: str
    exists: bool
    expected_bytes: int | None
    observed_bytes: int | None
    expected_sha256: str | None
    observed_sha256: str | None

    @property
    def passed(self) -> bool:
        return (
            self.exists
            and self.expected_bytes is not None
            and self.expected_sha256 is not None
            and self.expected_bytes == self.observed_bytes
            and self.expected_sha256.lower() == (self.observed_sha256 or "").lower()
        )


@dataclass(frozen=True)
class AuditIssue:
    """A bounded, machine-readable audit finding."""

    code: str
    message: str
    filename: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class DatasetAuditResult:
    """Observed counts and findings for one dataset."""

    dataset_id: str
    block: int
    expected_counts: Mapping[str, int]
    observed_counts: Mapping[str, int | None]
    file_results: tuple[FileAuditResult, ...]
    issues: tuple[AuditIssue, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        counts_match = all(
            self.observed_counts.get(name) == expected
            for name, expected in self.expected_counts.items()
        )
        return counts_match and all(item.passed for item in self.file_results) and not self.issues


@dataclass(frozen=True)
class DatasetAuditReport:
    """Complete Stage-1 data-audit result."""

    audited_at_utc: str
    data_root: str
    source_repository: str
    source_commit: str
    accessed_on: str
    datasets: tuple[DatasetAuditResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.datasets) and all(dataset.passed for dataset in self.datasets)
