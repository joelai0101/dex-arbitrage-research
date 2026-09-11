"""CLI for an explicit recorded source; no network calls or implicit endpoints."""
import argparse
import json
from pathlib import Path

from delta_terminal.model import load_case, write_case
from .reconstruct import read_source, reconstruct
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="rebuild recorded Sync events into a new case")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--start-block", type=int)
    build.add_argument("--blocks", type=int, default=100)
    build.add_argument("--k", type=int, default=3)
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="compare DELTA against exhaustive small-graph oracles")
    check.add_argument("--case", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    if args.command == "build":
        source = read_source(args.source, args.start_block, args.blocks)
        case = reconstruct(source, args.k)
        write_case(case, args.output)
        # A self-contained source slice preserves the integer observations, not just floats.
        (args.output / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": str(args.output), "nodes": len(case.colors),
                          "initial_edges": len(case.graph), **case.metadata["checks"]}))
    else:
        case = load_case(args.case)
        rebuilt = reconstruct(json.loads((args.case / "source.json").read_text(encoding="utf-8")), case.k)
        if case != rebuilt:
            raise ValueError("Saved case does not exactly match reconstruction from source.json")
        report = verify(case)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({key: value for key, value in report.items() if key != "results"}))


if __name__ == "__main__":
    main()
