from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Sequence


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

SELECTORS = {
    "getPair": "0xe6a43905",
    "getReserves": "0x0902f1ac",
    "token0": "0x0dfe1681",
    "token1": "0xd21220a7",
    "decimals": "0x313ce567",
    "symbol": "0x95d89b41",
}

TOPICS = {
    "PairCreated": "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9",
    "Sync": "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1",
    "Swap": "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822",
}


def strip_0x(value: str) -> str:
    return value[2:] if value.startswith("0x") else value


def hex_int(value: str | None) -> int | None:
    if value in (None, "", "0x"):
        return None
    return int(value, 16)


def checksum_insensitive(value: str) -> str:
    return value.lower()


def encode_address(address: str) -> str:
    raw = strip_0x(address)
    if len(raw) != 40:
        raise ValueError(f"Invalid address length: {address!r}")
    int(raw, 16)
    return raw.lower().rjust(64, "0")


def address_topic(address: str) -> str:
    return "0x" + encode_address(address)


def decode_address_word(data: str, word_index: int = 0) -> str:
    raw = strip_0x(data)
    start = word_index * 64
    word = raw[start : start + 64]
    if len(word) != 64:
        raise ValueError("ABI address word is truncated")
    if int(word, 16) == 0:
        return ZERO_ADDRESS
    return "0x" + word[-40:]


def decode_uint_words(data: str) -> list[int]:
    raw = strip_0x(data)
    if len(raw) % 64:
        raise ValueError("ABI uint data is not word aligned")
    return [int(raw[index : index + 64], 16) for index in range(0, len(raw), 64)]


def decode_symbol(data: str) -> str:
    raw_hex = strip_0x(data)
    if not raw_hex:
        return ""
    raw = bytes.fromhex(raw_hex)
    if len(raw) == 32:
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")
    if len(raw) >= 96:
        offset = int.from_bytes(raw[:32], "big")
        if offset + 32 > len(raw):
            return ""
        size = int.from_bytes(raw[offset : offset + 32], "big")
        start = offset + 32
        return raw[start : start + size].decode("utf-8", errors="replace")
    return ""


def decode_indexed_address(topic: str) -> str:
    raw = strip_0x(topic)
    if len(raw) != 64:
        raise ValueError("Indexed address topic must be 32 bytes")
    return "0x" + raw[-40:]


def pair_key(token_a: str, token_b: str) -> tuple[str, str]:
    return tuple(sorted((token_a.lower(), token_b.lower())))


def get_amount_out(
    amount_in: int,
    reserve_in: int,
    reserve_out: int,
    fee_numerator: int = 997,
    fee_denominator: int = 1000,
) -> int:
    """Match UniswapV2Library.getAmountOut with integer floor division."""
    if amount_in <= 0:
        raise ValueError("amount_in must be positive")
    if reserve_in <= 0 or reserve_out <= 0:
        raise ValueError("reserves must be positive")
    if not (0 < fee_numerator <= fee_denominator):
        raise ValueError("invalid fee fraction")
    amount_in_with_fee = amount_in * fee_numerator
    numerator = reserve_out * amount_in_with_fee
    denominator = reserve_in * fee_denominator + amount_in_with_fee
    return numerator // denominator


def gas_cost_weth(gas_units: int, gas_price_wei: int) -> Decimal:
    if gas_units < 0 or gas_price_wei < 0:
        raise ValueError("gas inputs cannot be negative")
    return Decimal(gas_units * gas_price_wei) / Decimal(10**18)


def decimal_to_raw(amount: str | Decimal, decimals: int) -> int:
    value = Decimal(str(amount)) * (Decimal(10) ** decimals)
    integral = value.to_integral_value()
    if value != integral:
        raise ValueError(f"{amount} has more than {decimals} decimal places")
    return int(integral)


def raw_to_decimal(raw: int, decimals: int) -> Decimal:
    return Decimal(raw) / (Decimal(10) ** decimals)


def decimal_text(value: Decimal, places: int = 18) -> str:
    quantizer = Decimal(1).scaleb(-places)
    return format(value.quantize(quantizer), "f")


def quantile_int(values: Sequence[int], probability: float) -> int:
    """Linearly interpolated quantile rounded to the nearest integer."""
    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("probability must be between zero and one")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = Decimal(str(position - lower))
    interpolated = Decimal(ordered[lower]) + fraction * Decimal(ordered[upper] - ordered[lower])
    return int(interpolated.to_integral_value())


def evenly_spaced_sample(values: Sequence[str], sample_size: int) -> list[str]:
    if sample_size <= 0 or not values:
        return []
    unique = list(dict.fromkeys(values))
    if len(unique) <= sample_size:
        return unique
    positions = [round(index * (len(unique) - 1) / (sample_size - 1)) for index in range(sample_size)]
    return [unique[position] for position in positions]


def is_sorted_events(rows: Sequence[dict[str, Any]]) -> bool:
    keys = [
        (int(row["block_number"]), int(row["transaction_index"]), int(row["log_index"]))
        for row in rows
    ]
    return keys == sorted(keys)


def block_chain_is_continuous(rows: Sequence[dict[str, Any]]) -> bool:
    if not rows:
        return False
    for previous, current in zip(rows, rows[1:]):
        if int(current["block_number"]) != int(previous["block_number"]) + 1:
            return False
        if current["parent_hash"].lower() != previous["block_hash"].lower():
            return False
    return True


def decode_pair_event(log: dict[str, Any], observation_start: int, observation_end: int) -> dict[str, Any]:
    block_number = int(log["blockNumber"], 16)
    topic0 = log["topics"][0].lower()
    base: dict[str, Any] = {
        "block_number": block_number,
        "block_hash": log.get("blockHash", ""),
        "transaction_hash": log["transactionHash"],
        "transaction_index": int(log["transactionIndex"], 16),
        "log_index": int(log["logIndex"], 16),
        "pair_address": log["address"],
        "removed": bool(log.get("removed", False)),
        "in_observation_window": observation_start <= block_number <= observation_end,
        "event_type": "",
        "sender": "",
        "to": "",
        "reserve0_raw": "",
        "reserve1_raw": "",
        "amount0_in_raw": "",
        "amount1_in_raw": "",
        "amount0_out_raw": "",
        "amount1_out_raw": "",
    }
    words = decode_uint_words(log.get("data", "0x"))
    if topic0 == TOPICS["Sync"].lower():
        if len(words) != 2:
            raise ValueError("Sync event must contain two reserve words")
        base.update(event_type="Sync", reserve0_raw=words[0], reserve1_raw=words[1])
    elif topic0 == TOPICS["Swap"].lower():
        if len(words) != 4 or len(log.get("topics", [])) < 3:
            raise ValueError("Swap event payload is malformed")
        base.update(
            event_type="Swap",
            sender=decode_indexed_address(log["topics"][1]),
            to=decode_indexed_address(log["topics"][2]),
            amount0_in_raw=words[0],
            amount1_in_raw=words[1],
            amount0_out_raw=words[2],
            amount1_out_raw=words[3],
        )
    else:
        raise ValueError(f"Unsupported pair event topic: {topic0}")
    return base


def orient_reserves(
    pair_metadata: dict[str, Any], snapshot: dict[str, Any], token_in: str, token_out: str
) -> tuple[int, int]:
    token0 = pair_metadata["token0_address"].lower()
    token1 = pair_metadata["token1_address"].lower()
    incoming = token_in.lower()
    outgoing = token_out.lower()
    if incoming == token0 and outgoing == token1:
        return int(snapshot["reserve0_raw"]), int(snapshot["reserve1_raw"])
    if incoming == token1 and outgoing == token0:
        return int(snapshot["reserve1_raw"]), int(snapshot["reserve0_raw"])
    raise ValueError("Requested tokens do not match pair metadata")


def all_nonnegative(values: Iterable[int]) -> bool:
    return all(value >= 0 for value in values)
