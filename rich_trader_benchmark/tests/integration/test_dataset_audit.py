from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rich_trader_benchmark.domain.dataset_audit import DatasetSpec, FileExpectation
from rich_trader_benchmark.infrastructure.trader_dataset_audit import TraderDatasetInspector


class TraderDatasetInspectorTest(unittest.TestCase):
    def test_valid_fixture_passes_all_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            spec = self._spec()
            expectations = self._expectations(root, spec)

            result = TraderDatasetInspector().inspect(root, spec, expectations)

            self.assertTrue(result.passed)
            self.assertEqual(result.observed_counts["mapped_nodes"], 3)
            self.assertEqual(result.observed_counts["unique_update_events"], 2)

    def test_changed_file_fails_hash_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_fixture(root)
            spec = self._spec()
            expectations = self._expectations(root, spec)
            graph_path = root / spec.token_graph_file
            graph_path.write_text(
                graph_path.read_text(encoding="utf-8") + "2 0 0.4\n",
                encoding="utf-8",
            )

            result = TraderDatasetInspector().inspect(root, spec, expectations)

            self.assertFalse(result.passed)
            codes = {issue.code for issue in result.issues}
            self.assertIn("FILE_HASH_MISMATCH", codes)
            self.assertIn("COUNT_MISMATCH", codes)

    @staticmethod
    def _write_fixture(root: Path) -> None:
        (root / "1_node_mapping.txt").write_text(
            "0x0000000000000000000000000000000000000001 0\n"
            "0x0000000000000000000000000000000000000002 1\n"
            "0x0000000000000000000000000000000000000003 2\n",
            encoding="utf-8",
        )
        (root / "1_token_graph.txt").write_text(
            "0 1 -1.0\n1 2 inf\n",
            encoding="utf-8",
        )
        (root / "1_dynamic.txt").write_text(
            "0 1 -1.1 2_0_0\n"
            "1 0 1.0 2_0_0\n"
            "1 2 inf 3_0_0\n",
            encoding="utf-8",
        )

    @staticmethod
    def _spec() -> DatasetSpec:
        return DatasetSpec(
            dataset_id="TEST",
            block=1,
            node_mapping_file="1_node_mapping.txt",
            token_graph_file="1_token_graph.txt",
            dynamic_file="1_dynamic.txt",
            mapped_nodes=3,
            initial_edge_records=2,
            finite_initial_edges=1,
            infinite_initial_edges=1,
            update_records=3,
            finite_update_records=2,
            unique_update_events=2,
        )

    @staticmethod
    def _expectations(root: Path, spec: DatasetSpec) -> dict[str, FileExpectation]:
        output: dict[str, FileExpectation] = {}
        for filename in spec.required_files:
            path = root / filename
            output[filename] = FileExpectation(
                dataset_id=spec.dataset_id,
                filename=filename,
                byte_size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        return output


if __name__ == "__main__":
    unittest.main()

