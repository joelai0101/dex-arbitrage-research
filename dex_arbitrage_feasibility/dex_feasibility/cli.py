from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .core import TOPICS, address_topic
from .pipeline import load_json, run_pipeline
from .rpc import RpcClient


MODULE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = MODULE_ROOT / "config" / "pilot.json"
DEFAULT_OUTPUT_ROOT = MODULE_ROOT / "artifacts"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and simulate a minimum Ethereum Uniswap v2 triangular-arbitrage dataset."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--rpc-url-env",
        default="ETHEREUM_RPC_URL",
        help="Environment variable containing the RPC URL (default: ETHEREUM_RPC_URL).",
    )
    parser.add_argument(
        "--rpc-url",
        help="Explicit runtime RPC URL. Prefer --rpc-url-env so credentials do not enter shell history.",
    )
    parser.add_argument(
        "--archive-rpc-url-env",
        default="ETHEREUM_ARCHIVE_RPC_URL",
        help="Optional environment variable for historical state/log calls.",
    )
    parser.add_argument(
        "--archive-rpc-url",
        help="Optional explicit archive RPC URL; defaults to the primary RPC URL.",
    )
    parser.add_argument("--start-block", type=int)
    parser.add_argument("--end-block", type=int)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--no-resume", action="store_true", help="Ignore existing stage checkpoints.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Verify chain, finalized block access, and Factory bytecode without writing research data.",
    )
    return parser


def resolve_rpc_url(args: argparse.Namespace) -> tuple[str, str]:
    environment_value = os.environ.get(args.rpc_url_env)
    if environment_value:
        return environment_value, f"environment:{args.rpc_url_env}"
    if args.rpc_url:
        return args.rpc_url, "explicit_runtime_argument"
    raise ValueError(
        f"No RPC URL found. Set {args.rpc_url_env} or provide --rpc-url; never commit a key."
    )


def resolve_archive_rpc_url(
    args: argparse.Namespace, primary_url: str
) -> tuple[str, str]:
    environment_value = os.environ.get(args.archive_rpc_url_env)
    if environment_value:
        return environment_value, f"environment:{args.archive_rpc_url_env}"
    if args.archive_rpc_url:
        return args.archive_rpc_url, "explicit_runtime_argument"
    return primary_url, "same_as_primary_rpc"


def run_preflight(
    config_path: Path,
    rpc_url: str,
    rpc_source: str,
    archive_rpc_url: str,
    archive_rpc_source: str,
) -> int:
    config = load_json(config_path)
    client = RpcClient(rpc_url)
    archive_client = client if archive_rpc_url == rpc_url else RpcClient(archive_rpc_url)
    chain_id = int(client.request("eth_chainId", []), 16)
    finalized = client.request("eth_getBlockByNumber", [config["finality_tag"], False])
    if finalized is None:
        raise ValueError("Finalized block was not returned")
    finalized_number = int(finalized["number"], 16)
    factory_code = client.request(
        "eth_getCode", [config["factory_address"], hex(finalized_number)]
    )
    historical_factory_code = archive_client.request(
        "eth_getCode",
        [config["factory_address"], hex(int(config["factory_deployment_block"]))],
    )
    weth = config["tokens"]["WETH"]["address"]
    usdc = config["tokens"]["USDC"]["address"]
    sorted_tokens = sorted((weth, usdc), key=lambda value: int(value, 16))
    historical_logs = archive_client.request(
        "eth_getLogs",
        [
            {
                "address": config["factory_address"],
                "fromBlock": hex(int(config["factory_deployment_block"])),
                "toBlock": hex(int(config["factory_deployment_block"]) + 20_000),
                "topics": [
                    TOPICS["PairCreated"],
                    address_topic(sorted_tokens[0]),
                    address_topic(sorted_tokens[1]),
                ],
            }
        ],
    )
    if chain_id != int(config["chain_id"]):
        raise ValueError(f"RPC chain_id={chain_id}, expected {config['chain_id']}")
    if factory_code in (None, "0x", "0x0"):
        raise ValueError("Configured Factory has no bytecode at finalized block")
    if historical_factory_code in (None, "0x", "0x0"):
        raise ValueError("RPC did not provide historical Factory bytecode at deployment block")
    print(f"RPC endpoint: {client.public_url}")
    print(f"RPC source: {rpc_source}")
    print(f"Archive RPC endpoint: {archive_client.public_url}")
    print(f"Archive RPC source: {archive_rpc_source}")
    print(f"chain_id: {chain_id}")
    print(f"finalized_block: {finalized_number}")
    print(f"factory_code_present: true")
    print(f"archive_state_access: true")
    print(f"historical_pair_created_log_count: {len(historical_logs)}")
    total_requests = client.stats.http_requests
    if archive_client is not client:
        total_requests += archive_client.stats.http_requests
    print(f"http_requests: {total_requests}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rpc_url, rpc_source = resolve_rpc_url(args)
        archive_rpc_url, archive_rpc_source = resolve_archive_rpc_url(args, rpc_url)
        if args.preflight_only:
            return run_preflight(
                args.config.resolve(),
                rpc_url,
                rpc_source,
                archive_rpc_url,
                archive_rpc_source,
            )
        output_dir, summary = run_pipeline(
            config_path=args.config.resolve(),
            rpc_url=rpc_url,
            archive_rpc_url=archive_rpc_url,
            output_root=args.output_root.resolve(),
            start_block=args.start_block,
            end_block=args.end_block,
            resume=not args.no_resume,
        )
        print(f"Output directory: {output_dir}")
        print(f"Block range: {summary['start_block']}-{summary['end_block']}")
        print(f"Simulation rows: {summary['simulation_rows']}")
        print(f"Feasibility success: {str(summary['feasibility_success']).lower()}")
        return 0 if summary["feasibility_success"] else 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
