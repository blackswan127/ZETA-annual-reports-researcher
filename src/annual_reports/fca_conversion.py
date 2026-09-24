"""FCA original-package preservation and local XHTML/ZIP-to-PDF conversion."""

from __future__ import annotations

import asyncio
import hashlib
import io
import os
import stat
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from curl_cffi.requests import AsyncSession
import httpx

from .catalog import Report
from .conversion import ensure_conversion_table, record_conversion
from .discovery import DiscoveryStore
from .engine import Result, RunLock, StateStore, native_path, validate_and_store


@dataclass(frozen=True, slots=True)
class FcaJob:
    candidate_id: int
    report: Report


def _jobs(store: DiscoveryStore, limit: int | None, company_keys: set[str] | None = None) -> list[FcaJob]:
    query = """SELECT c.*, u.country, u.exchange, u.lei, u.isin, u.ticker
               FROM candidates c JOIN companies u USING(company_key)
               WHERE c.source='FCA_NSM' AND c.report_year IS NOT NULL
                 AND c.source_format IN ('zip','html','unknown')
                 AND NOT EXISTS (
                   SELECT 1 FROM candidates p WHERE p.company_key=c.company_key
                     AND p.report_year=c.report_year AND p.source_format='pdf'
                     AND p.status IN ('DISCOVERED','VERIFIED') AND p.verified=1)
               ORDER BY c.company_key, c.report_year, c.id"""
    jobs: list[FcaJob] = []
    seen: set[tuple[str, int]] = set()
    for item in store.connection.execute(query):
        if company_keys is not None and item["company_key"] not in company_keys:
            continue
        identity = (item["company_key"], item["report_year"])
        if identity in seen:
            continue
        if urlsplit(item["source_url"]).hostname not in {"data.fca.org.uk", "api.data.fca.org.uk"}:
            continue
        seen.add(identity)
        report = Report.from_row({
            "country": item["country"], "exchange": item["exchange"],
            "lei": item["lei"], "isin": item["isin"], "ticker": item["ticker"],
            "fiscal_year": f"FY{item['report_year']}", "report_type": "AR",
            "language": "EN", "pdf_url": item["source_url"],
            "source_page": "", "verified": "true",
        })
        jobs.append(FcaJob(item["id"], report))
        if limit and len(jobs) >= limit:
            break
    return jobs


class AdaptiveFcaGate:
    def __init__(self, maximum: int = 16):
        self.limit = 4
        self.maximum = maximum
        self.active = 0
        self.last_increase = time.monotonic()
        self.condition = asyncio.Condition()

    async def acquire(self) -> None:
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1

    async def release(self, status: int) -> None:
        async with self.condition:
            self.active -= 1
            if status in {429, 503}:
                self.limit = max(1, self.limit // 2)
                self.last_increase = time.monotonic()
            elif status == 200 and time.monotonic() - self.last_increase >= 60:
                self.limit = min(self.maximum, self.limit + 1)
                self.last_increase = time.monotonic()
            self.condition.notify_all()


async def _fetch_original(session: AsyncSession | httpx.AsyncClient, url: str,
                          gate: AdaptiveFcaGate, max_bytes: int) -> bytes:
    last_error: Exception | None = None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/pdf,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
    }
    for attempt in range(3):
        await gate.acquire()
        status = 0
        try:
            if isinstance(session, AsyncSession):
                resp = await session.get(url, headers=headers, timeout=30.0, allow_redirects=True)
                status = resp.status_code
                if status in {429, 503}:
                    last_error = ValueError(f"FCA HTTP {status}")
                elif status != 200:
                    last_error = ValueError(f"FCA HTTP {status}")
                else:
                    data = resp.content
                    if len(data) > max_bytes:
                        raise ValueError("FCA original exceeds size limit")
                    return data
            else:
                async with session.stream("GET", url, follow_redirects=True) as response:
                    status = response.status_code
                    if status in {429, 503}:
                        last_error = ValueError(f"FCA HTTP {status}")
                    else:
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=256 * 1024):
                            data.extend(chunk)
                            if len(data) > max_bytes:
                                raise ValueError("FCA original exceeds size limit")
                        return bytes(data)
        except Exception as exc:
            last_error = exc
        finally:
            await gate.release(status)
        await asyncio.sleep(2 ** attempt)
    raise last_error or ValueError("FCA download failed")


def _source_format(raw: bytes) -> str:
    if raw.startswith(b"%PDF-"):
        return "pdf"
    if raw.startswith(b"PK\x03\x04"):
        return "zip"
    if b"<html" in raw[:4096].lower() or b"<!doctype html" in raw[:4096].lower():
        return "html"
    raise ValueError("FCA original is not PDF, ZIP or HTML")


def _write_original(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(".bin.part")
    try:
        with staged.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _safe_extract(archive: zipfile.ZipFile, destination: Path) -> Path:
    candidates = []
    total = 0
    if len(archive.infolist()) > 10_000:
        raise ValueError("FCA package has too many files")
    for item in archive.infolist():
        normalized = PurePosixPath(item.filename.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or ":" in item.filename:
            raise ValueError("unsafe path in FCA package")
        if stat.S_ISLNK(item.external_attr >> 16):
            raise ValueError("symlink in FCA package")
        total += item.file_size
        if total > 512 * 1024 * 1024:
            raise ValueError("FCA package expands beyond 512 MiB")
        if normalized.suffix.lower() in {".xhtml", ".html", ".htm"}:
            candidates.append((item.file_size, item.filename))
    if not candidates:
        raise ValueError("FCA package contains no HTML/XHTML report")
    archive.extractall(destination)
    candidates.sort(reverse=True)
    return destination / candidates[0][1]


async def render_fca_originals(
    state_path: Path, output_root: Path, cache_root: Path,
    *, chrome_path: Path | None = None, limit: int | None = None,
    network_workers: int = 16, render_workers: int = 4,
    max_mib: int = 128, company_keys: set[str] | None = None,
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ValueError("install the render extra: pip install -e '.[render]'") from exc
    if network_workers < 1 or render_workers < 1 or max_mib < 1:
        raise ValueError("workers and max_mib must be positive")
    with RunLock(state_path):
        discovery = DiscoveryStore(state_path)
        try:
            jobs = _jobs(discovery, limit, company_keys=company_keys)
        finally:
            discovery.close()
        if not jobs:
            if company_keys is not None:
                return {"selected": 0, "originals_downloaded": 0, "pdf_completed": 0,
                        "skipped": 0, "failed": 0, "elapsed_s": 0.0,
                        "documents_per_second": 0.0, "failures": []}
            raise ValueError("no FCA structured/unknown-format annual reports were discovered")
        ledger = StateStore(state_path)
        ensure_conversion_table(ledger.connection)
        started = time.monotonic()
        skipped = 0
        failed: list[dict] = []
        converted = 0
        originals_downloaded = 0
        queue: asyncio.Queue[FcaJob] = asyncio.Queue()
        render_queue: asyncio.Queue[tuple[FcaJob, Path, bytes] | None] = asyncio.Queue(maxsize=render_workers * 2)
        for job in jobs:
            target = output_root / job.report.relative_path
            prior = ledger.prior(job.report)
            if os.path.isfile(native_path(target)) and prior and prior[0] == "downloaded" and prior[1] == job.report.pdf_url and prior[2] == os.path.getsize(native_path(target)):
                skipped += 1
            elif os.path.isfile(native_path(target)):
                failed.append({"path": str(job.report.relative_path),
                               "error": "canonical target already exists from another source"})
            else:
                queue.put_nowait(job)
        gate = AdaptiveFcaGate()
        try:
            async with AsyncSession(impersonate="chrome") as session:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(
                        executable_path=str(chrome_path) if chrome_path else None,
                        headless=True, args=["--no-sandbox", "--allow-file-access-from-files"],
                    )
                    context = await browser.new_context(java_script_enabled=False)
                    context.set_default_timeout(120_000)

                    async def block_network(route):
                        await route.abort()

                    await context.route("http://**/*", block_network)
                    await context.route("https://**/*", block_network)

                    async def network_worker() -> None:
                        nonlocal originals_downloaded
                        while True:
                            try:
                                job = queue.get_nowait()
                            except asyncio.QueueEmpty:
                                return
                            cache_path = cache_root / "fca" / "originals" / f"{job.candidate_id}.bin"
                            try:
                                if cache_path.is_file():
                                    raw = cache_path.read_bytes()
                                    _source_format(raw)
                                else:
                                    raw = await _fetch_original(session, job.report.pdf_url, gate,
                                                                max_mib * 1024 * 1024)
                                    _source_format(raw)
                                    await asyncio.to_thread(_write_original, cache_path, raw)
                                    originals_downloaded += 1
                                await render_queue.put((job, cache_path, raw))
                            except Exception as exc:
                                failed.append({"path": str(job.report.relative_path),
                                               "error": f"FCA original: {exc}"})
                            finally:
                                queue.task_done()

                    async def renderer() -> None:
                        nonlocal converted
                        page = await context.new_page()
                        try:
                            while True:
                                item = await render_queue.get()
                                if item is None:
                                    render_queue.task_done()
                                    return
                                job, cache_path, raw = item
                                source_format = _source_format(raw)
                                try:
                                    if source_format == "pdf":
                                        pdf = raw
                                        engine = "original"
                                    elif source_format == "html":
                                        await page.set_content(raw.decode("utf-8", errors="replace"),
                                                               wait_until="domcontentloaded", timeout=30_000)
                                        pdf = await asyncio.wait_for(
                                            page.pdf(format="A4", print_background=True, prefer_css_page_size=True),
                                            timeout=90.0,
                                        )
                                        engine = "chromium"
                                    else:
                                        with tempfile.TemporaryDirectory(dir=cache_root) as folder:
                                            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                                                entry = await asyncio.to_thread(_safe_extract, archive, Path(folder))
                                            await page.goto(entry.resolve().as_uri(), wait_until="domcontentloaded",
                                                            timeout=30_000)
                                            pdf = await asyncio.wait_for(
                                                page.pdf(format="A4", print_background=True, prefer_css_page_size=True),
                                                timeout=90.0,
                                            )
                                        engine = "chromium"
                                    pages, digest = await asyncio.to_thread(validate_and_store, pdf, job.report, output_root)
                                    result = Result(job.report, "downloaded", size=len(pdf), pages=pages, sha256=digest)
                                    ledger.save(result)
                                    record_conversion(ledger.connection, job.candidate_id, cache_path,
                                                      hashlib.sha256(raw).hexdigest(), source_format,
                                                      result, engine)
                                    ledger.connection.execute(
                                        "UPDATE candidates SET status='VERIFIED', verified=1 WHERE id=?",
                                        (job.candidate_id,),
                                    )
                                    ledger.connection.commit()
                                    converted += 1
                                except Exception as exc:
                                    failed.append({"path": str(job.report.relative_path),
                                                   "error": f"FCA PDF conversion: {exc}"})
                                finally:
                                    render_queue.task_done()
                        finally:
                            await page.close()

                    render_tasks = [asyncio.create_task(renderer()) for _ in range(render_workers)]
                    await asyncio.gather(*(network_worker() for _ in range(min(network_workers, queue.qsize()))))
                    for _ in render_tasks:
                        await render_queue.put(None)
                    await render_queue.join()
                    await asyncio.gather(*render_tasks)
                    try:
                        await asyncio.wait_for(browser.close(), timeout=5.0)
                    except (asyncio.TimeoutError, Exception):
                        pass
        finally:
            ledger.close()
        elapsed = round(time.monotonic() - started, 3)
        return {"selected": len(jobs), "originals_downloaded": originals_downloaded,
                "pdf_completed": converted, "skipped": skipped, "failed": len(failed),
                "elapsed_s": elapsed, "documents_per_second": round(converted / max(elapsed, 0.001), 2),
                "failures": failed}
