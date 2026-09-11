"""Build, collect and verify small token graphs; RPC endpoints are always explicit."""
import argparse
import getpass
import json
import os
from pathlib import Path

from delta_terminal.model import load_case, write_case
from delta_terminal.rpc import RpcClient
from .collect import DEFAULT_TOKENS, collect
from .cover import verify_cover
from .reconstruct import read_source, reconstruct
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="rebuild recorded Sync events into a new case")
    sources = build.add_mutually_exclusive_group(required=True)
    sources.add_argument("--source", type=Path)
    sources.add_argument("--source-json", type=Path)
    build.add_argument("--start-block", type=int)
    build.add_argument("--blocks", type=int)
    build.add_argument("--k", type=int, default=3)
    build.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("verify", help="compare DELTA against exhaustive small-graph oracles")
    check.add_argument("--case", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    capture = commands.add_parser("capture", help="bounded read-only RPC capture of five-token pool events")
    capture.add_argument("--tokens", type=Path, default=DEFAULT_TOKENS)
    capture.add_argument("--blocks", type=int, default=100)
    capture.add_argument("--start-block", type=int)
    capture.add_argument("--output", type=Path, required=True)
    cover = commands.add_parser("verify-cover", help="complete five-token k=4/5 color coverage and global oracle")
    cover.add_argument("--source-json", type=Path, required=True)
    cover.add_argument("--k", type=int, nargs="+", choices=(4,5), default=[4,5])
    cover.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; choose a new path")
    if args.command == "build":
        if args.source_json:
            if args.start_block is not None or args.blocks is not None:
                parser.error("A source.json has a fixed range; do not combine it with block overrides")
            source = json.loads(args.source_json.read_text(encoding="utf-8"))
        else:
            source = read_source(args.source, args.start_block, args.blocks if args.blocks is not None else 100)
        case = reconstruct(source, args.k)
        write_case(case, args.output)
        # A self-contained source slice preserves the integer observations, not just floats.
        (args.output / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"case": str(args.output), "nodes": len(case.colors),
                          "initial_edges": len(case.graph), **case.metadata["checks"]}))
    elif args.command == "verify":
        case = load_case(args.case)
        rebuilt = reconstruct(json.loads((args.case / "source.json").read_text(encoding="utf-8")), case.k, case.metadata.get("colors"))
        if case != rebuilt:
            raise ValueError("Saved case does not exactly match reconstruction from source.json")
        report = verify(case)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({key: value for key, value in report.items() if key != "results"}))
    elif args.command == "capture":
        url = os.environ.get("DELTA_RPC_URL")
        if url is None:
            url = getpass.getpass("Ethereum RPC URL (hidden; blank cancels): ")
        if not url.strip():
            print("No RPC URL; cancelled without requests or output.")
            return
        client = RpcClient(url.strip(), interval=2.0, budget=256)
        collect(client, args.output, blocks=args.blocks, start_block=args.start_block, token_path=args.tokens,
                progress=lambda text: print(text, flush=True))
        print(f"Capture completed: {args.output}")
    else:
        source = json.loads(args.source_json.read_text(encoding="utf-8"))
        result = verify_cover(source, args.output, tuple(args.k), progress=lambda text: print(text, flush=True))
        print(json.dumps(result))


if __name__ == "__main__":
    main()
