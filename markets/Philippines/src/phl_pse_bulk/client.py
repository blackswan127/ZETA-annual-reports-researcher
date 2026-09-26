from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional
import httpx

from .config import BASE_URL, Settings, require_terms_ack
from .contract import allowed_pse_url

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}


class RateLimiter:
    """Async token bucket rate limiter."""
    def __init__(self, rps: float = 2.0):
        self.rps = rps
        self.interval = 1.0 / rps if rps > 0 else 0.5
        self.lock = asyncio.Lock()
        self.last_call = 0.0

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_call
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self.last_call = time.monotonic()


class PSEClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.rate_limiter = RateLimiter(self.settings.metadata_rps)
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.timeout_seconds, connect=10.0),
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path_or_url: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3,
    ) -> httpx.Response:
        require_terms_ack()
        full_url = allowed_pse_url(path_or_url)
        client = await self.get_client()

        for attempt in range(retries):
            await self.rate_limiter.wait()
            try:
                resp = await client.request(
                    method=method,
                    url=full_url,
                    data=data,
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2.0 * (attempt + 1)))
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code >= 500:
                    await asyncio.sleep(1.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {full_url} after {retries} retries")

    async def post_form(self, path_or_url: str, data: Dict[str, Any]) -> str:
        resp = await self.request("POST", path_or_url, data=data)
        return resp.text

    async def get_html(self, path_or_url: str, params: Optional[Dict[str, Any]] = None) -> str:
        resp = await self.request("GET", path_or_url, params=params)
        return resp.text

    async def stream_download(self, path_or_url: str, dest_path: Path) -> Path:
        """Stream binary PDF to .part file and return the path."""
        require_terms_ack()
        full_url = allowed_pse_url(path_or_url)
        part_path = dest_path.with_name(dest_path.name + ".part")
        part_path.parent.mkdir(parents=True, exist_ok=True)
        client = await self.get_client()

        for attempt in range(3):
            try:
                async with client.stream("GET", full_url) as resp:
                    resp.raise_for_status()
                    with open(part_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                return part_path
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                part_path.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                await asyncio.sleep(1.0 * (attempt + 1))
        return part_path
