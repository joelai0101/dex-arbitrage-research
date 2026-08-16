from __future__ import annotations

import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
JSON_OUT = DATA_DIR / "dex_pool_probe.json"
CSV_OUT = DATA_DIR / "dex_pool_probe.csv"

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


SELECTORS = {
    "getPair": "0xe6a43905",
    "getPool": "0x1698ee82",
    "getReserves": "0x0902f1ac",
    "slot0": "0x3850c7bd",
    "liquidity": "0x1a686502",
    "token0": "0x0dfe1681",
    "token1": "0xd21220a7",
    "decimals": "0x313ce567",
    "symbol": "0x95d89b41",
}


CHAINS = {
    "ethereum": {
        "chain_id": 1,
        "rpc_urls": [
            "https://eth.llamarpc.com",
            "https://rpc.flashbots.net",
            "https://ethereum.publicnode.com",
            "https://rpc.ankr.com/eth",
            "https://cloudflare-eth.com",
        ],
    },
    "bnb": {
        "chain_id": 56,
        "rpc_urls": [
            "https://bsc-dataseed.binance.org",
            "https://bsc-dataseed1.defibit.io",
            "https://rpc.ankr.com/bsc",
        ],
    },
    "polygon": {
        "chain_id": 137,
        "rpc_urls": [
            "https://polygon.llamarpc.com",
            "https://1rpc.io/matic",
            "https://polygon-bor-rpc.publicnode.com",
            "https://polygon-rpc.com",
            "https://rpc.ankr.com/polygon",
        ],
    },
}


TOKENS = {
    "ethereum": {
        "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    },
    "bnb": {
        "WBNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "USDT": "0x55d398326f99059fF775485246999027B3197955",
    },
    "polygon": {
        "WMATIC": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    },
}


TARGETS = [
    {
        "chain": "ethereum",
        "dex": "Uniswap",
        "version": "v2",
        "factory": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "token_a": "WETH",
        "token_b": "USDC",
    },
    {
        "chain": "ethereum",
        "dex": "Uniswap",
        "version": "v3",
        "factory": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "token_a": "WETH",
        "token_b": "USDC",
        "fee_tiers": [500, 3000, 10000],
    },
    {
        "chain": "bnb",
        "dex": "PancakeSwap",
        "version": "v2",
        "factory": "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73",
        "token_a": "WBNB",
        "token_b": "USDT",
    },
    {
        "chain": "polygon",
        "dex": "QuickSwap",
        "version": "v2",
        "factory": "0x5757371414417b8c6caad45baef941abc7d3ab32",
        "token_a": "WMATIC",
        "token_b": "USDC.e",
    },
]


@dataclass
class RpcClient:
    chain: str
    urls: list[str]

    def request(self, method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": method,
            "params": params,
        }
        body = json.dumps(payload).encode("utf-8")
        last_error: str | None = None
        for url in self.urls:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "dex-arbitrage-research-pool-probe/0.1",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if "error" in data:
                    last_error = f"{url}: {data['error']}"
                    continue
                return data["result"]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = f"{url}: {exc}"
        raise RuntimeError(f"All RPC endpoints failed for {self.chain}: {last_error}")

    def eth_call(self, to: str, data: str) -> str:
        return self.request("eth_call", [{"to": to, "data": data}, "latest"])


def clean_hex(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def encode_address(address: str) -> str:
    return clean_hex(address).lower().rjust(64, "0")


def encode_uint(value: int) -> str:
    return hex(value)[2:].rjust(64, "0")


def decode_address(data: str) -> str:
    raw = clean_hex(data)
    if not raw or int(raw, 16) == 0:
        return ZERO_ADDRESS
    return "0x" + raw[-40:]


def decode_uints(data: str) -> list[int]:
    raw = clean_hex(data)
    return [int(raw[i : i + 64], 16) for i in range(0, len(raw), 64) if raw[i : i + 64]]


def decode_symbol(data: str) -> str:
    raw = bytes.fromhex(clean_hex(data))
    if len(raw) == 32:
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if len(raw) >= 96:
        size = int.from_bytes(raw[32:64], "big")
        return raw[64 : 64 + size].decode("utf-8", errors="replace")
    return ""


def call_symbol(client: RpcClient, token: str, fallback: str) -> str:
    try:
        return decode_symbol(client.eth_call(token, SELECTORS["symbol"])) or fallback
    except Exception:
        return fallback


def call_decimals(client: RpcClient, token: str) -> int | None:
    try:
        values = decode_uints(client.eth_call(token, SELECTORS["decimals"]))
        return values[0] if values else None
    except Exception:
        return None


def get_pair(client: RpcClient, factory: str, token_a: str, token_b: str) -> str:
    data = SELECTORS["getPair"] + encode_address(token_a) + encode_address(token_b)
    return decode_address(client.eth_call(factory, data))


def get_pool(client: RpcClient, factory: str, token_a: str, token_b: str, fee: int) -> str:
    data = SELECTORS["getPool"] + encode_address(token_a) + encode_address(token_b) + encode_uint(fee)
    return decode_address(client.eth_call(factory, data))


def get_v2_state(client: RpcClient, pool: str) -> dict[str, Any]:
    token0 = decode_address(client.eth_call(pool, SELECTORS["token0"]))
    token1 = decode_address(client.eth_call(pool, SELECTORS["token1"]))
    reserves = decode_uints(client.eth_call(pool, SELECTORS["getReserves"]))
    return {
        "pool": pool,
        "token0": token0,
        "token1": token1,
        "reserve0_raw": reserves[0] if len(reserves) > 0 else None,
        "reserve1_raw": reserves[1] if len(reserves) > 1 else None,
        "block_timestamp_last": reserves[2] if len(reserves) > 2 else None,
    }


def get_v3_state(client: RpcClient, pool: str) -> dict[str, Any]:
    token0 = decode_address(client.eth_call(pool, SELECTORS["token0"]))
    token1 = decode_address(client.eth_call(pool, SELECTORS["token1"]))
    slot0 = decode_uints(client.eth_call(pool, SELECTORS["slot0"]))
    liquidity = decode_uints(client.eth_call(pool, SELECTORS["liquidity"]))
    return {
        "pool": pool,
        "token0": token0,
        "token1": token1,
        "sqrt_price_x96": slot0[0] if len(slot0) > 0 else None,
        "tick": twos_complement(slot0[1], 256) if len(slot0) > 1 else None,
        "liquidity": liquidity[0] if liquidity else None,
    }


def twos_complement(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def enrich_tokens(client: RpcClient, row: dict[str, Any], requested_symbols: dict[str, str]) -> dict[str, Any]:
    for key in ["token0", "token1"]:
        token = row.get(key)
        if not token:
            continue
        fallback = next((name for name, addr in requested_symbols.items() if addr.lower() == token.lower()), key)
        row[f"{key}_symbol"] = call_symbol(client, token, fallback)
        row[f"{key}_decimals"] = call_decimals(client, token)
    return row


def probe_target(target: dict[str, Any]) -> list[dict[str, Any]]:
    chain = target["chain"]
    client = RpcClient(chain=chain, urls=CHAINS[chain]["rpc_urls"])
    token_a = TOKENS[chain][target["token_a"]]
    token_b = TOKENS[chain][target["token_b"]]
    rows: list[dict[str, Any]] = []

    if target["version"] == "v2":
        pool = get_pair(client, target["factory"], token_a, token_b)
        state = {"fee_tier": None, **get_v2_state(client, pool)} if pool != ZERO_ADDRESS else {"pool": pool}
        rows.append(enrich_tokens(client, base_row(target, state), TOKENS[chain]))
        return rows

    for fee in target["fee_tiers"]:
        pool = get_pool(client, target["factory"], token_a, token_b, fee)
        state = {"fee_tier": fee, **get_v3_state(client, pool)} if pool != ZERO_ADDRESS else {"fee_tier": fee, "pool": pool}
        rows.append(enrich_tokens(client, base_row(target, state), TOKENS[chain]))
    return rows


def base_row(target: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    return {
        "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chain": target["chain"],
        "chain_id": CHAINS[target["chain"]]["chain_id"],
        "dex": target["dex"],
        "version": target["version"],
        "requested_pair": f"{target['token_a']}/{target['token_b']}",
        "factory": target["factory"],
        **state,
    }


def write_outputs(rows: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    fieldnames = sorted({key for row in rows for key in row})
    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    all_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for target in TARGETS:
        label = f"{target['chain']} {target['dex']} {target['version']} {target['token_a']}/{target['token_b']}"
        print(f"Fetching {label}...")
        try:
            all_rows.extend(probe_target(target))
        except Exception as exc:
            errors.append({"target": label, "error": str(exc)})
            print(f"  FAILED: {exc}")

    if errors:
        all_rows.extend({"error": item["error"], "target": item["target"]} for item in errors)

    write_outputs(all_rows)
    print(f"Wrote {JSON_OUT}")
    print(f"Wrote {CSV_OUT}")
    if errors:
        print(f"Completed with {len(errors)} failed target(s).")
        return 1
    print("Completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
