from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx


class RetryingClient:
    def __init__(self, timeout: float = 45.0, retries: int = 4):
        self.retries = retries
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": "sgx-annual-bulk/1.0 (+public SGX annual-report downloader)",
                "Accept-Language": "en-SG,en;q=0.9",
            },
            limits=httpx.Limits(max_connections=40, max_keepalive_connections=20),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = await self.client.request(method, url, **kwargs)
                if r.status_code not in {429, 500, 502, 503, 504}:
                    r.raise_for_status()
                    return r
                if attempt >= self.retries:
                    r.raise_for_status()
                retry_after = r.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
                except ValueError:
                    delay = 0.5 * (2 ** attempt)
                await asyncio.sleep(min(delay, 30.0))
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                last = exc
                if attempt >= self.retries:
                    raise
                base = 0.5 * (2 ** attempt)
                await asyncio.sleep(base * random.uniform(0.8, 1.2))
        assert last is not None
        raise last
