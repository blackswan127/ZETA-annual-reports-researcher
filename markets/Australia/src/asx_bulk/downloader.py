from __future__ import annotations

import asyncio
import hashlib
import os
import random
import re
from pathlib import Path

import httpx

from .config import USER_AGENT
from .util import AsyncRateLimiter, is_pdf

class PDFDownloader:
    def __init__(self, workers: int = 6, rps: float = 3.0, timeout: float = 60.0, retries: int = 5,
                 chunk_size: int = 1024 * 1024):
        self.sem = asyncio.Semaphore(max(1, workers))
        self.rate = AsyncRateLimiter(rps)
        self.retries = retries
        self.chunk_size = chunk_size
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=max(timeout, 120)),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.8"},
            limits=httpx.Limits(max_connections=max(workers + 4, 10), max_keepalive_connections=max(workers, 6)),
        )

    async def close(self):
        await self.client.aclose()

    async def download(self, url: str, dest: Path) -> tuple[int, str]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        async with self.sem:
            last_error = None
            for attempt in range(self.retries):
                try:
                    offset = part.stat().st_size if part.exists() else 0
                    headers = {"Range": f"bytes={offset}-"} if offset else {}
                    await self.rate.acquire()
                    async with self.client.stream("GET", url, headers=headers) as r:
                        if r.status_code == 416 and offset:
                            match = re.fullmatch(r"bytes\s+\*/(\d+)", r.headers.get("Content-Range", "").strip(), re.I)
                            total = int(match.group(1)) if match else None
                            if is_pdf(part) and total == part.stat().st_size:
                                os.replace(part, dest)
                                return dest.stat().st_size, self._sha256(dest)
                            part.unlink(missing_ok=True)
                            continue
                        if r.status_code == 429 or 500 <= r.status_code < 600:
                            last_error = httpx.HTTPStatusError(
                                f"retryable HTTP status {r.status_code}", request=r.request, response=r
                            )
                            if attempt + 1 >= self.retries:
                                continue
                            retry_after = r.headers.get("Retry-After")
                            try:
                                delay = float(retry_after) if retry_after else min(30, 1.5 ** attempt)
                            except ValueError:
                                delay = min(30, 1.5 ** attempt)
                            await asyncio.sleep(delay + random.random() * .3)
                            continue
                        r.raise_for_status()
                        ctype = r.headers.get("content-type", "").lower()
                        if "text/html" in ctype:
                            raise RuntimeError("received HTML instead of PDF")
                        expected_size = None
                        if r.status_code == 206:
                            content_range = re.fullmatch(
                                r"bytes\s+(\d+)-(\d+)/(\d+)",
                                r.headers.get("Content-Range", "").strip(), re.I,
                            )
                            if not content_range:
                                raise RuntimeError("partial response is missing a valid Content-Range")
                            range_start, range_end, expected_size = map(int, content_range.groups())
                            if range_start != offset or range_end < range_start or expected_size <= range_end:
                                raise RuntimeError("partial response has an inconsistent Content-Range")
                        elif r.headers.get("Content-Length", "").isdigit():
                            expected_size = int(r.headers["Content-Length"])
                        mode = "ab" if offset and r.status_code == 206 else "wb"
                        if mode == "wb" and offset:
                            offset = 0
                        with part.open(mode) as fh:
                            async for chunk in r.aiter_bytes(self.chunk_size):
                                if chunk:
                                    fh.write(chunk)
                    if not is_pdf(part):
                        part.unlink(missing_ok=True)
                        raise RuntimeError("downloaded file does not begin with %PDF-")
                    if expected_size is not None and part.stat().st_size != expected_size:
                        raise RuntimeError(
                            f"incomplete PDF transfer: received {part.stat().st_size} of {expected_size} bytes"
                        )
                    os.replace(part, dest)
                    return dest.stat().st_size, self._sha256(dest)
                except Exception as exc:
                    last_error = exc
                    if attempt + 1 < self.retries:
                        await asyncio.sleep(min(30, 1.5 ** attempt) + random.random() * .3)
            raise RuntimeError(f"download failed after {self.retries} attempts: {last_error}")

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
