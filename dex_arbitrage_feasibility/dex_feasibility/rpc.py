from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence


class JsonRpcError(RuntimeError):
    pass


class JsonRpcTransportError(JsonRpcError):
    pass


def sanitized_rpc_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


@dataclass
class RpcStats:
    http_requests: int = 0
    rpc_calls: int = 0
    retries: int = 0
    failed_requests: list[str] = field(default_factory=list)


class RpcClient:
    def __init__(
        self,
        url: str,
        *,
        timeout_seconds: int = 30,
        max_retries: int = 3,
        retry_base_seconds: float = 0.5,
    ) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("RPC URL must use HTTP or HTTPS")
        self.url = url
        self.public_url = sanitized_rpc_url(url)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.stats = RpcStats()
        self._next_id = 1
        self._batch_supported: bool | None = None

    def _post(self, payload: dict[str, Any] | list[dict[str, Any]]) -> Any:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            self.stats.http_requests += 1
            request = urllib.request.Request(
                self.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "dex-arbitrage-data-feasibility/0.1",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    decoded = json.loads(response.read().decode("utf-8"))
                return decoded
            except urllib.error.HTTPError as exc:
                response_body = exc.read().decode("utf-8", errors="replace")[:1000]
                try:
                    decoded_error = json.loads(response_body)
                except json.JSONDecodeError:
                    decoded_error = None
                if decoded_error is not None:
                    return decoded_error
                last_error = f"HTTPError {exc.code}: {response_body or exc.reason}"
                if exc.code in {400, 401, 403, 404}:
                    break
                if attempt >= self.max_retries:
                    break
                self.stats.retries += 1
                delay = self.retry_base_seconds * (2**attempt) + random.random() * 0.2
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt >= self.max_retries:
                    break
                self.stats.retries += 1
                delay = self.retry_base_seconds * (2**attempt) + random.random() * 0.2
                time.sleep(delay)
        safe_error = f"RPC request failed via {self.public_url}: {last_error}"
        self.stats.failed_requests.append(safe_error)
        raise JsonRpcTransportError(safe_error)

    def request(self, method: str, params: list[Any]) -> Any:
        request_id = self._next_id
        self._next_id += 1
        self.stats.rpc_calls += 1
        response = self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        if not isinstance(response, dict):
            raise JsonRpcError(f"Unexpected response type for {method}")
        if "error" in response:
            error = response["error"]
            raise JsonRpcError(f"{method} error {error.get('code')}: {error.get('message')}")
        if "result" not in response:
            raise JsonRpcError(f"{method} response has no result")
        return response["result"]

    def batch(self, calls: Sequence[tuple[str, list[Any]]]) -> list[Any]:
        if not calls:
            return []
        if self._batch_supported is False:
            return [self.request(method, params) for method, params in calls]
        payload: list[dict[str, Any]] = []
        order: list[int] = []
        methods: dict[int, str] = {}
        for method, params in calls:
            request_id = self._next_id
            self._next_id += 1
            order.append(request_id)
            methods[request_id] = method
            payload.append(
                {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            )
        self.stats.rpc_calls += len(payload)
        response = self._post(payload)
        if not isinstance(response, list):
            self._batch_supported = False
            return [self.request(method, params) for method, params in calls]
        self._batch_supported = True
        indexed = {item.get("id"): item for item in response if isinstance(item, dict)}
        results: list[Any] = []
        for request_id in order:
            item = indexed.get(request_id)
            method = methods[request_id]
            if not item:
                raise JsonRpcError(f"Missing batch response for {method}")
            if "error" in item:
                error = item["error"]
                raise JsonRpcError(f"{method} error {error.get('code')}: {error.get('message')}")
            results.append(item.get("result"))
        return results

    def eth_call(self, to: str, data: str, block: int | str) -> str:
        block_tag = hex(block) if isinstance(block, int) else block
        return self.request("eth_call", [{"to": to, "data": data}, block_tag])

    def get_logs(
        self,
        base_filter: dict[str, Any],
        start_block: int,
        end_block: int,
        *,
        chunk_size: int,
    ) -> list[dict[str, Any]]:
        if end_block < start_block:
            return []
        rows: list[dict[str, Any]] = []
        cursor = start_block
        while cursor <= end_block:
            chunk_end = min(cursor + chunk_size - 1, end_block)
            rows.extend(self._get_logs_adaptive(base_filter, cursor, chunk_end))
            cursor = chunk_end + 1
        return rows

    def _get_logs_adaptive(
        self, base_filter: dict[str, Any], start_block: int, end_block: int
    ) -> list[dict[str, Any]]:
        params = {
            **base_filter,
            "fromBlock": hex(start_block),
            "toBlock": hex(end_block),
        }
        try:
            result = self.request("eth_getLogs", [params])
            if not isinstance(result, list):
                raise JsonRpcError("eth_getLogs returned a non-list result")
            return result
        except JsonRpcError as exc:
            message = str(exc).lower()
            splittable_markers = (
                "block range",
                "range is too",
                "too many results",
                "more than",
                "response size",
                "result limit",
                "query timeout",
                "httperror 403",
            )
            if start_block >= end_block or not any(marker in message for marker in splittable_markers):
                raise
            midpoint = (start_block + end_block) // 2
            return self._get_logs_adaptive(base_filter, start_block, midpoint) + self._get_logs_adaptive(
                base_filter, midpoint + 1, end_block
            )
