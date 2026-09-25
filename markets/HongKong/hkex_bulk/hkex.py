from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

BASE = "https://www1.hkexnews.hk"
SEARCH_URL = f"{BASE}/search/titleSearchServlet.do"
ACTIVE_URL = f"{BASE}/ncms/script/eds/activestock_sehk_e.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Referer": f"{BASE}/search/titlesearch.xhtml?lang=en",
}


class AsyncRateLimiter:
    def __init__(self, rate_per_sec: float):
        self.interval = 0.0 if rate_per_sec <= 0 else 1.0 / rate_per_sec
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if self.interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next = max(now, self._next) + self.interval


class HKEXClient:
    def __init__(self, *, timeout: float = 60, max_retries: int = 5, metadata_rps: float = 2.5,
                 download_rps: float = 8.0):
        self.timeout = timeout
        self.max_retries = max_retries
        self.meta_limiter = AsyncRateLimiter(metadata_rps)
        self.download_limiter = AsyncRateLimiter(download_rps)
        self.client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
            http2=True,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()

    async def _request(self, url: str, *, params: dict[str, Any] | None = None, stream: bool = False,
                       range_start: int | None = None) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                headers = {}
                if range_start and range_start > 0:
                    headers["Range"] = f"bytes={range_start}-"
                resp = await self.client.get(url, params=params, headers=headers)
                if resp.status_code == 429 or resp.status_code >= 500:
                    retry_after = resp.headers.get("Retry-After")
                    await resp.aclose()
                    if retry_after and retry_after.isdigit():
                        delay = float(retry_after)
                    else:
                        delay = min(30.0, (2 ** (attempt - 1)) + random.random())
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last = e
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(min(30.0, (2 ** (attempt - 1)) + random.random()))
        assert last is not None
        raise last

    async def fetch_active_securities(self) -> list[dict[str, Any]]:
        await self.meta_limiter.wait()
        resp = await self._request(ACTIVE_URL)
        data = resp.json()
        await resp.aclose()
        if not isinstance(data, list):
            raise RuntimeError("HKEX active-securities endpoint returned an unexpected payload")
        return data

    @staticmethod
    def _annual_params(start: date, end: date, row_limit: int, *, stock_id: str = "-1") -> dict[str, Any]:
        # t1=40000 / t2=40100 is HKEXnews' Annual Report headline category.
        # Include both known sort parameter spellings; unknown extras are ignored by HKEX.
        return {
            "sortDir": 0,
            "sortByOptions": "DateTime",
            "sortByOrder": "DateTime",
            "category": 0,
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": -1,
            "fromDate": start.strftime("%Y%m%d"),
            "toDate": end.strftime("%Y%m%d"),
            "title": "",
            "searchType": 1 if stock_id == "-1" else 0,
            "t1code": 40000,
            "t2Gcode": -2,
            "t2code": 40100,
            "rowRange": row_limit,
            "lang": "EN",
            "t": "e",
        }

    async def annual_search(self, start: date, end: date, *, row_limit: int = 2000,
                            stock_id: str = "-1") -> tuple[list[dict[str, Any]], bool]:
        await self.meta_limiter.wait()
        resp = await self._request(SEARCH_URL, params=self._annual_params(start, end, row_limit, stock_id=stock_id))
        data = resp.json()
        await resp.aclose()
        result = data.get("result", []) if isinstance(data, dict) else []
        if isinstance(result, str):
            result = json.loads(result or "[]")
        if not isinstance(result, list):
            raise RuntimeError(f"Unexpected HKEX result type: {type(result)!r}")
        has_more = bool(data.get("hasNextRow", False)) if isinstance(data, dict) else False
        return result, has_more

    async def annual_search_complete(self, start: date, end: date, *, row_limit: int = 2000,
                                     stock_id: str = "-1", depth: int = 0) -> list[dict[str, Any]]:
        rows, has_more = await self.annual_search(start, end, row_limit=row_limit, stock_id=stock_id)
        saturated = has_more or len(rows) >= row_limit
        if not saturated:
            return rows
        if start >= end:
            # A single day should normally be well below this ceiling. Escalate once/twice
            # rather than silently truncating.
            if row_limit < 10000:
                return await self.annual_search_complete(start, end, row_limit=min(10000, row_limit * 2), stock_id=stock_id, depth=depth+1)
            raise RuntimeError(f"HKEX result set still truncated for single day {start}; manual handling required")
        if depth > 24:
            raise RuntimeError(f"Adaptive date splitting exceeded safe depth for {start}..{end}")
        days = (end - start).days
        mid = start + timedelta(days=days // 2)
        left, right = await asyncio.gather(
            self.annual_search_complete(start, mid, row_limit=row_limit, stock_id=stock_id, depth=depth+1),
            self.annual_search_complete(mid + timedelta(days=1), end, row_limit=row_limit, stock_id=stock_id, depth=depth+1),
        )
        by_id: dict[str, dict[str, Any]] = {}
        for r in left + right:
            key = str(r.get("NEWS_ID") or r.get("FILE_LINK") or json.dumps(r, sort_keys=True))
            by_id[key] = r
        return list(by_id.values())

    async def stream_pdf(self, url: str, part_path: Path) -> tuple[int, str | None, int]:
        """True streaming download with retry + best-effort HTTP Range resume."""
        part_path.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        last_status = 0
        last_type: str | None = None

        for attempt in range(1, self.max_retries + 1):
            existing = part_path.stat().st_size if part_path.exists() else 0
            headers: dict[str, str] = {}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            await self.download_limiter.wait()
            try:
                async with self.client.stream("GET", url, headers=headers) as resp:
                    last_status = resp.status_code
                    last_type = resp.headers.get("content-type")

                    # A stale/oversized .part can cause Range Not Satisfiable.
                    if resp.status_code == 416 and existing:
                        part_path.unlink(missing_ok=True)
                        await asyncio.sleep(0.5)
                        continue

                    if resp.status_code == 429 or resp.status_code >= 500:
                        retry_after = resp.headers.get("Retry-After")
                        if retry_after and retry_after.isdigit():
                            delay = float(retry_after)
                        else:
                            delay = min(30.0, (2 ** (attempt - 1)) + random.random())
                        await asyncio.sleep(delay)
                        continue

                    resp.raise_for_status()
                    if existing and resp.status_code == 206:
                        mode = "ab"
                    else:
                        # Server ignored Range: restart cleanly instead of corrupting the PDF.
                        mode = "wb"

                    with part_path.open(mode) as f:
                        async for chunk in resp.aiter_bytes(1024 * 256):
                            f.write(chunk)

                return part_path.stat().st_size, last_type, last_status

            except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
                last_error = e
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(min(30.0, (2 ** (attempt - 1)) + random.random()))

        if last_error:
            raise last_error
        raise RuntimeError(f"Download failed after retries: {url}")
