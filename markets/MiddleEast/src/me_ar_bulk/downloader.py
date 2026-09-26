from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import httpx

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class RateLimiter:
    def __init__(self, rps: float):
        self.interval = 0.0 if rps <= 0 else 1.0 / rps
        self.lock = asyncio.Lock()
        self.last = 0.0

    async def wait(self):
        if not self.interval:
            return
        async with self.lock:
            now = time.monotonic()
            delay = self.interval - (now - self.last)
            if delay > 0:
                await asyncio.sleep(delay)
            self.last = time.monotonic()


class Downloader:
    def __init__(
        self,
        workers: int = 16,
        rps: float = 4.0,
        timeout: float = 20.0,
        retries: int = 3,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ):
        self.sem = asyncio.Semaphore(max(1, workers))
        self.limiter = RateLimiter(rps)
        self.timeout = timeout
        self.retries = retries
        headers = {
            "User-Agent": user_agent,
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=8.0, read=timeout),
            follow_redirects=True,
            headers=headers,
            limits=httpx.Limits(max_connections=workers * 2, max_keepalive_connections=workers),
        )

    async def close(self):
        await self.client.aclose()

    @staticmethod
    def validate_pdf(path: Path, min_bytes: int = 35000) -> Tuple[bool, int, str]:
        p = Path(path)
        if not p.exists():
            return False, 0, "File does not exist"
        sz = p.stat().st_size
        if sz < min_bytes:
            return False, 0, f"File size ({sz} bytes) is below minimum ({min_bytes} bytes)"

        with open(p, "rb") as f:
            header = f.read(10)
            if b"%PDF-" not in header:
                return False, 0, "Missing '%PDF-' header signature"

        if HAS_PYMUPDF:
            try:
                doc = fitz.open(str(p))
                pages = len(doc)
                if pages < 1:
                    doc.close()
                    return False, pages, "Document contains 0 pages"
                _ = doc[0].get_text("text")[:200]
                doc.close()
                return True, pages, "OK"
            except Exception as e:
                return False, 0, f"PyMuPDF validation error: {str(e)}"

        if HAS_PYPDF:
            try:
                reader = PdfReader(str(p), strict=False)
                pages = len(reader.pages)
                if pages < 1:
                    return False, pages, "Document contains 0 pages"
                return True, pages, "OK"
            except Exception as e:
                return False, 0, f"pypdf validation error: {str(e)}"

        return True, 1, "OK (parsers unavailable)"

    async def get(self, url: str, dest: Path, min_bytes: int = 35000) -> Dict[str, Any]:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = Path(str(dest) + ".part")

        async with self.sem:
            last_exc: Optional[Exception] = None
            for attempt in range(1, self.retries + 1):
                try:
                    await self.limiter.wait()
                    start = part.stat().st_size if part.exists() else 0
                    headers = {"Range": f"bytes={start}-"} if start > 0 else {}

                    async with self.client.stream("GET", url, headers=headers) as r:
                        if r.status_code == 429 or r.status_code >= 500:
                            retry_after = r.headers.get("Retry-After")
                            delay = min(float(retry_after), 30.0) if retry_after and retry_after.isdigit() else min(30.0, (1.8 ** attempt) + random.random())
                            await asyncio.sleep(delay)
                            continue

                        if r.status_code == 416 and start > 0:
                            part.unlink(missing_ok=True)
                            start = 0
                            continue

                        r.raise_for_status()

                        if start and r.status_code == 200:
                            part.unlink(missing_ok=True)
                            start = 0

                        mode = "ab" if start and r.status_code == 206 else "wb"
                        with open(part, mode) as f:
                            async for chunk in r.aiter_bytes(65536):
                                f.write(chunk)

                    valid, pages, reason = self.validate_pdf(part, min_bytes=min_bytes)
                    if not valid:
                        part.unlink(missing_ok=True)
                        raise ValueError(f"Corrupt or invalid PDF: {reason}")

                    os.replace(part, dest)
                    return {
                        "sha256": sha256_file(dest),
                        "bytes": dest.stat().st_size,
                        "pages": pages,
                        "http_status": r.status_code,
                    }
                except Exception as e:
                    last_exc = e
                    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (400, 401, 403, 404, 410):
                        part.unlink(missing_ok=True)
                        raise
                    if attempt == self.retries:
                        part.unlink(missing_ok=True)
                        raise
                    delay = min(15.0, (1.5 ** attempt) + random.random() * 0.5)
                    await asyncio.sleep(delay)

            assert last_exc is not None
            raise last_exc
