import csv
from pathlib import Path
import tempfile
import unittest

from verify_weight_fix import score


class QualityCheckerTests(unittest.TestCase):
    def evaluate(self, weight="-5", path="0 1 2 3 4 0", update="0 1 N", colors=None, reference="-5"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "graph.txt").write_text("0 1 -1\n1 2 -1\n2 3 -1\n3 4 -1\n4 0 -1\n")
            (root / "updates.txt").write_text(update + "\n")
            (root / "reference.tsv").write_text(f"row\tweight\n0\t-5\n1\t{reference}\n")
            with (root / "trace.tsv").open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["phase", "row", "weight", "path", "coloring"], delimiter="\t")
                writer.writeheader()
                writer.writerow(dict(phase="arrival", row=1, weight=weight, path=path, coloring=0))
            return score(root, root / "reference.tsv", root / "trace.tsv",
                         {"0": colors or {str(i): i for i in range(5)}})

    def test_valid_report(self):
        counts, failures = self.evaluate()
        self.assertEqual(counts["valid_colored_report"], 1)
        self.assertEqual(failures, [])

    def test_stale_weight(self):
        counts, failures = self.evaluate(update="0 1 1", reference="-3")
        self.assertEqual(counts["weight_mismatch"], 1)
        self.assertEqual(counts["valid_report"], 0)
        self.assertEqual(failures[0]["actual"], -3)

    def test_invalid_path(self):
        counts, _ = self.evaluate(path="0 1 1 3 4 0")
        self.assertEqual(counts["legal_path"], 0)
        self.assertEqual(counts["valid_report"], 0)

    def test_declared_color_violation(self):
        counts, _ = self.evaluate(colors={str(i): 0 for i in range(5)})
        self.assertEqual(counts["valid_report"], 1)
        self.assertEqual(counts["valid_colored_report"], 0)

    def test_suboptimal_is_not_invalid(self):
        counts, _ = self.evaluate(reference="-6")
        self.assertEqual(counts["valid_colored_report"], 1)
        self.assertEqual(counts["optimal_path"], 0)


if __name__ == "__main__":
    unittest.main()
