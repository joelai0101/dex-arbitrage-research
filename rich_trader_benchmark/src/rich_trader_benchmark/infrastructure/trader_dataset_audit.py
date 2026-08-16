"""TRADER file-format adapters used by the dataset audit."""

from __future__ import annotations

import csv
import hashlib
import math
import re
import tomllib
from pathlib import Path
from typing import Iterable, Mapping

from rich_trader_benchmark.domain.dataset_audit import (
    AuditIssue,
    BenchmarkDataSpec,
    COUNT_FIELDS,
    DatasetAuditResult,
    DatasetSpec,
    FileAuditResult,
    FileExpectation,
)


ADDRESS_PATTERN = re.compile(r"0x[0-9a-fA-F]{40}")
MAX_ISSUES_PER_CODE = 10


def load_benchmark_spec(path: Path) -> BenchmarkDataSpec:
    """Load the committed dataset specification."""

    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    datasets = tuple(
        DatasetSpec(
            dataset_id=item["id"],
            block=int(item["block"]),
            node_mapping_file=item["node_mapping_file"],
            token_graph_file=item["token_graph_file"],
            dynamic_file=item["dynamic_file"],
            mapped_nodes=int(item["mapped_nodes"]),
            initial_edge_records=int(item["initial_edge_records"]),
            finite_initial_edges=int(item["finite_initial_edges"]),
            infinite_initial_edges=int(item["infinite_initial_edges"]),
            update_records=int(item["update_records"]),
            finite_update_records=int(item["finite_update_records"]),
            unique_update_events=int(item["unique_update_events"]),
        )
        for item in payload["datasets"]
    )
    return BenchmarkDataSpec(
        schema_version=int(payload["schema_version"]),
        source_repository=payload["source_repository"],
        source_commit=payload["source_commit"],
        accessed_on=payload["accessed_on"],
        data_root_environment_variable=payload["data_root_environment_variable"],
        raw_data_redistribution=bool(payload["raw_data_redistribution"]),
        datasets=datasets,
    )


def load_file_manifest(path: Path) -> dict[tuple[str, str], FileExpectation]:
    """Load and validate the committed file-identity manifest."""

    manifest: dict[tuple[str, str], FileExpectation] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"dataset", "file", "bytes", "sha256"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Manifest must contain columns: {sorted(required)}")
        for row in reader:
            expectation = FileExpectation(
                dataset_id=row["dataset"].strip(),
                filename=row["file"].strip(),
                byte_size=int(row["bytes"]),
                sha256=row["sha256"].strip().lower(),
            )
            key = (expectation.dataset_id, expectation.filename)
            if key in manifest:
                raise ValueError(f"Duplicate manifest entry: {key}")
            if not re.fullmatch(r"[0-9a-f]{64}", expectation.sha256):
                raise ValueError(f"Invalid SHA-256 for manifest entry: {key}")
            manifest[key] = expectation
    return manifest


def validate_manifest_coverage(
    benchmark: BenchmarkDataSpec,
    manifest: Mapping[tuple[str, str], FileExpectation],
) -> None:
    """Require one manifest row for every configured raw file and no extras."""

    required = {
        (dataset.dataset_id, filename)
        for dataset in benchmark.datasets
        for filename in dataset.required_files
    }
    provided = set(manifest)
    missing = sorted(required - provided)
    extra = sorted(provided - required)
    if missing or extra:
        raise ValueError(f"Manifest coverage mismatch; missing={missing}, extra={extra}")


class TraderDatasetInspector:
    """Stream over raw text files and compare them with the frozen specification."""

    def inspect(
        self,
        data_root: Path,
        dataset: DatasetSpec,
        expectations: Mapping[str, FileExpectation],
    ) -> DatasetAuditResult:
        issues: list[AuditIssue] = []
        issue_counts: dict[str, int] = {}
        file_results = tuple(
            self._audit_file(data_root / filename, expectations.get(filename), issues)
            for filename in dataset.required_files
        )

        observed: dict[str, int | None] = {name: None for name in COUNT_FIELDS}
        mapping_path = data_root / dataset.node_mapping_file
        graph_path = data_root / dataset.token_graph_file
        dynamic_path = data_root / dataset.dynamic_file

        if mapping_path.is_file():
            observed["mapped_nodes"] = self._inspect_mapping(
                mapping_path, issues, issue_counts
            )
        if graph_path.is_file():
            graph_counts = self._inspect_graph(
                graph_path, dataset.mapped_nodes, issues, issue_counts
            )
            observed.update(graph_counts)
        if dynamic_path.is_file():
            update_counts = self._inspect_updates(
                dynamic_path, dataset.mapped_nodes, issues, issue_counts
            )
            observed.update(update_counts)

        for field_name, expected in dataset.expected_counts.items():
            actual = observed[field_name]
            if actual != expected:
                self._add_issue(
                    issues,
                    issue_counts,
                    "COUNT_MISMATCH",
                    f"{field_name}: expected {expected}, observed {actual}",
                )

        return DatasetAuditResult(
            dataset_id=dataset.dataset_id,
            block=dataset.block,
            expected_counts=dataset.expected_counts,
            observed_counts=observed,
            file_results=file_results,
            issues=tuple(issues),
        )

    def _audit_file(
        self,
        path: Path,
        expectation: FileExpectation | None,
        issues: list[AuditIssue],
    ) -> FileAuditResult:
        if expectation is None:
            issues.append(
                AuditIssue(
                    code="MANIFEST_ENTRY_MISSING",
                    filename=path.name,
                    message="No expected size/hash is recorded for this required file.",
                )
            )
        if not path.is_file():
            issues.append(
                AuditIssue(
                    code="FILE_MISSING",
                    filename=path.name,
                    message="Required raw-data file does not exist.",
                )
            )
            return FileAuditResult(
                filename=path.name,
                exists=False,
                expected_bytes=expectation.byte_size if expectation else None,
                observed_bytes=None,
                expected_sha256=expectation.sha256 if expectation else None,
                observed_sha256=None,
            )

        observed_bytes = path.stat().st_size
        observed_sha256 = self._sha256(path)
        if expectation and observed_bytes != expectation.byte_size:
            issues.append(
                AuditIssue(
                    code="FILE_SIZE_MISMATCH",
                    filename=path.name,
                    message=(
                        f"Expected {expectation.byte_size} bytes, observed "
                        f"{observed_bytes} bytes."
                    ),
                )
            )
        if expectation and observed_sha256.lower() != expectation.sha256.lower():
            issues.append(
                AuditIssue(
                    code="FILE_HASH_MISMATCH",
                    filename=path.name,
                    message="Observed SHA-256 does not match the committed manifest.",
                )
            )
        return FileAuditResult(
            filename=path.name,
            exists=True,
            expected_bytes=expectation.byte_size if expectation else None,
            observed_bytes=observed_bytes,
            expected_sha256=expectation.sha256 if expectation else None,
            observed_sha256=observed_sha256,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _inspect_mapping(
        self,
        path: Path,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> int:
        row_count = 0
        addresses: set[str] = set()
        identifiers: set[int] = set()
        for line_number, parts in self._rows(path, 2, issues, issue_counts):
            row_count += 1
            address, identifier_text = parts
            if not ADDRESS_PATTERN.fullmatch(address):
                self._add_issue(
                    issues,
                    issue_counts,
                    "INVALID_TOKEN_ADDRESS",
                    f"Invalid Ethereum address: {address}",
                    path.name,
                    line_number,
                )
            try:
                identifier = int(identifier_text)
            except ValueError:
                self._add_issue(
                    issues,
                    issue_counts,
                    "INVALID_NODE_ID",
                    f"Node ID is not an integer: {identifier_text}",
                    path.name,
                    line_number,
                )
                continue
            normalized_address = address.lower()
            if normalized_address in addresses:
                self._add_issue(
                    issues,
                    issue_counts,
                    "DUPLICATE_TOKEN_ADDRESS",
                    f"Repeated token address: {address}",
                    path.name,
                    line_number,
                )
            if identifier in identifiers:
                self._add_issue(
                    issues,
                    issue_counts,
                    "DUPLICATE_NODE_ID",
                    f"Repeated node ID: {identifier}",
                    path.name,
                    line_number,
                )
            addresses.add(normalized_address)
            identifiers.add(identifier)

        if identifiers and (
            len(identifiers) != row_count
            or min(identifiers) != 0
            or max(identifiers) != row_count - 1
        ):
            self._add_issue(
                issues,
                issue_counts,
                "NONCONTIGUOUS_NODE_IDS",
                "Node IDs are not exactly the contiguous range 0..N-1.",
                path.name,
            )
        return row_count

    def _inspect_graph(
        self,
        path: Path,
        mapped_nodes: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> dict[str, int]:
        records = 0
        finite = 0
        infinite = 0
        for line_number, parts in self._rows(path, 3, issues, issue_counts):
            records += 1
            self._parse_endpoints(
                parts[:2], mapped_nodes, path.name, line_number, issues, issue_counts
            )
            weight = self._parse_weight(
                parts[2], path.name, line_number, issues, issue_counts
            )
            if weight is not None:
                if math.isinf(weight):
                    infinite += 1
                else:
                    finite += 1
        return {
            "initial_edge_records": records,
            "finite_initial_edges": finite,
            "infinite_initial_edges": infinite,
        }

    def _inspect_updates(
        self,
        path: Path,
        mapped_nodes: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> dict[str, int]:
        records = 0
        finite = 0
        seen_events: set[str] = set()
        closed_events: set[str] = set()
        current_event: str | None = None
        previous_event_key: tuple[int, ...] | None = None

        for line_number, parts in self._rows(path, 4, issues, issue_counts):
            records += 1
            self._parse_endpoints(
                parts[:2], mapped_nodes, path.name, line_number, issues, issue_counts
            )
            weight = self._parse_weight(
                parts[2], path.name, line_number, issues, issue_counts
            )
            if weight is not None and not math.isinf(weight):
                finite += 1

            event_id = parts[3]
            event_key = self._parse_event_key(
                event_id, path.name, line_number, issues, issue_counts
            )
            if event_id != current_event:
                if current_event is not None:
                    closed_events.add(current_event)
                if event_id in closed_events:
                    self._add_issue(
                        issues,
                        issue_counts,
                        "NONCONTIGUOUS_EVENT_GROUP",
                        f"Event {event_id} reappears after its group was closed.",
                        path.name,
                        line_number,
                    )
                if (
                    event_key is not None
                    and previous_event_key is not None
                    and event_key < previous_event_key
                ):
                    self._add_issue(
                        issues,
                        issue_counts,
                        "EVENT_ORDER_DECREASED",
                        f"Event {event_id} is earlier than the preceding event group.",
                        path.name,
                        line_number,
                    )
                current_event = event_id
                if event_key is not None:
                    previous_event_key = event_key
            seen_events.add(event_id)

        return {
            "update_records": records,
            "finite_update_records": finite,
            "unique_update_events": len(seen_events),
        }

    def _rows(
        self,
        path: Path,
        expected_columns: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> Iterable[tuple[int, list[str]]]:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    self._add_issue(
                        issues,
                        issue_counts,
                        "BLANK_ROW",
                        "Blank row found in raw data.",
                        path.name,
                        line_number,
                    )
                    continue
                parts = stripped.split()
                if len(parts) != expected_columns:
                    self._add_issue(
                        issues,
                        issue_counts,
                        "INVALID_COLUMN_COUNT",
                        f"Expected {expected_columns} columns, observed {len(parts)}.",
                        path.name,
                        line_number,
                    )
                    continue
                yield line_number, parts

    def _parse_endpoints(
        self,
        endpoint_texts: list[str],
        mapped_nodes: int,
        filename: str,
        line_number: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> None:
        for endpoint_text in endpoint_texts:
            try:
                endpoint = int(endpoint_text)
            except ValueError:
                self._add_issue(
                    issues,
                    issue_counts,
                    "INVALID_EDGE_ENDPOINT",
                    f"Endpoint is not an integer: {endpoint_text}",
                    filename,
                    line_number,
                )
                continue
            if not 0 <= endpoint < mapped_nodes:
                self._add_issue(
                    issues,
                    issue_counts,
                    "EDGE_ENDPOINT_OUT_OF_RANGE",
                    f"Endpoint {endpoint} is outside 0..{mapped_nodes - 1}.",
                    filename,
                    line_number,
                )

    def _parse_weight(
        self,
        value: str,
        filename: str,
        line_number: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> float | None:
        try:
            weight = float(value)
        except ValueError:
            self._add_issue(
                issues,
                issue_counts,
                "INVALID_EDGE_WEIGHT",
                f"Weight is not numeric or inf: {value}",
                filename,
                line_number,
            )
            return None
        if math.isnan(weight) or weight == -math.inf:
            self._add_issue(
                issues,
                issue_counts,
                "INVALID_EDGE_WEIGHT",
                f"Only finite values or positive inf are allowed: {value}",
                filename,
                line_number,
            )
            return None
        return weight

    def _parse_event_key(
        self,
        event_id: str,
        filename: str,
        line_number: int,
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
    ) -> tuple[int, ...] | None:
        try:
            parts = tuple(int(part) for part in event_id.split("_"))
        except ValueError:
            parts = ()
        if len(parts) != 3:
            self._add_issue(
                issues,
                issue_counts,
                "INVALID_EVENT_ID",
                f"Expected block_transaction_log event ID, observed: {event_id}",
                filename,
                line_number,
            )
            return None
        return parts

    @staticmethod
    def _add_issue(
        issues: list[AuditIssue],
        issue_counts: dict[str, int],
        code: str,
        message: str,
        filename: str | None = None,
        line: int | None = None,
    ) -> None:
        count = issue_counts.get(code, 0)
        issue_counts[code] = count + 1
        if count < MAX_ISSUES_PER_CODE:
            issues.append(
                AuditIssue(code=code, message=message, filename=filename, line=line)
            )
