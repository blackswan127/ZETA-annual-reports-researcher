from __future__ import annotations

import asyncio
import hashlib
import os
import random
from pathlib import Path

import httpx

from .db import Database
from .httpclient import RetryingClient
from .util import ensure_parent, safe_component

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PDFDownloader:
    def __init__(self, http: RetryingClient, db: Database, root: Path, workers: int = 6,
                 max_mb: int = 250):
        self.http = http
        self.db = db
        self.root = root
        self.sem = asyncio.Semaphore(max(1, workers))
        self.max_bytes = max_mb * 1024 * 1024

    def _target(self, row) -> Path:
        company = safe_component(f"{row['stock_code']}_{row['issuer_name']}", 100)
        filename = safe_component(row["filename"], 130)
        return self.root / company / str(row["fiscal_year"]) / filename

    async def download_row(self, row) -> tuple[bool, str]:
        async with self.sem:
            url = row["url"]
            target = self._target(row)
            part = Path(str(target) + ".part")
            ensure_parent(target)

            # A rerun is idempotent: accept an already-valid PDF and record its digest.
            if target.exists() and target.stat().st_size > 1000:
                with target.open("rb") as f:
                    if f.read(5) == b"%PDF-":
                        digest = self._sha256(target)
                        self.db.mark_download(
                            url, status="done", local_path=str(target),
                            size_bytes=target.stat().st_size, sha256=digest, error=None,
                        )
                        return True, str(target)

            self.db.mark_download(url, status="downloading", error=None, increment_attempt=True)
            resumed_any = False
            last_error: Exception | None = None

            for attempt in range(self.http.retries + 1):
                existing = part.stat().st_size if part.exists() else 0
                headers = {"Range": f"bytes={existing}-"} if existing else {}
                try:
                    async with self.http.client.stream("GET", url, headers=headers) as r:
                        # A stale/oversized .part can produce 416. Reset it once and retry cleanly.
                        if r.status_code == 416 and existing:
                            part.unlink(missing_ok=True)
                            if attempt >= self.http.retries:
                                raise RuntimeError("Server rejected resume range after retries")
                            await asyncio.sleep(0.25)
                            continue

                        if r.status_code in RETRYABLE_STATUS:
                            retry_after = r.headers.get("retry-after")
                            if attempt >= self.http.retries:
                                r.raise_for_status()
                            try:
                                delay = float(retry_after) if retry_after else 0.5 * (2 ** attempt)
                            except ValueError:
                                delay = 0.5 * (2 ** attempt)
                            await asyncio.sleep(min(delay, 30.0))
                            continue

                        if r.status_code not in (200, 206):
                            r.raise_for_status()

                        if existing and r.status_code == 206:
                            mode = "ab"
                            resumed_any = True
                        else:
                            # Server ignored Range or this is a fresh download.
                            mode = "wb"
                            existing = 0

                        content_length = r.headers.get("content-length")
                        if content_length:
                            expected = existing + int(content_length)
                            if expected > self.max_bytes:
                                raise RuntimeError(
                                    f"PDF exceeds configured {self.max_bytes // (1024 * 1024)} MB limit"
                                )

                        total = existing
                        with part.open(mode) as f:
                            async for chunk in r.aiter_bytes(1024 * 1024):
                                if not chunk:
                                    continue
                                total += len(chunk)
                                if total > self.max_bytes:
                                    raise RuntimeError("PDF exceeded maximum size during streaming")
                                f.write(chunk)

                    # Stream completed. Validate before publishing the file atomically.
                    with part.open("rb") as f:
                        if f.read(5) != b"%PDF-":
                            raise RuntimeError("SGX attachment is not a PDF")
                    os.replace(part, target)
                    digest = self._sha256(target)
                    self.db.mark_download(
                        url, status="done", local_path=str(target),
                        size_bytes=target.stat().st_size, sha256=digest, error=None,
                    )
                    return True, ("resumed " if resumed_any else "") + str(target)

                except (httpx.RequestError, httpx.HTTPStatusError, OSError, RuntimeError, ValueError) as exc:
                    last_error = exc
                    if attempt >= self.http.retries:
                        break
                    base = 0.5 * (2 ** attempt)
                    await asyncio.sleep(base * random.uniform(0.8, 1.2))

            assert last_error is not None
            self.db.mark_download(url, status="failed", error=str(last_error))
            return False, f"{url}: {last_error}"

    async def run(self, rows) -> tuple[int, int]:
        tasks = [asyncio.create_task(self.download_row(row)) for row in rows]
        ok = fail = 0
        for fut in asyncio.as_completed(tasks):
            success, msg = await fut
            if success:
                ok += 1
            else:
                fail += 1
                print("FAILED:", msg)
        return ok, fail

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
