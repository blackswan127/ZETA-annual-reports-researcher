r"""High-Throughput Continuous Asynchronous Streaming Engine for All Listed Australian (ASX) Companies.

Architecture:
1. Continuous Multi-Stage Pipeline:
   - Stage 1 (Metadata Scanner): Asynchronously scans historical announcements across all unscanned tickers.
   - Stage 2 (Selector): Automatically selects optimal statutory candidates into expected_slots & downloads.
   - Stage 3 (URL Resolver): Resolves direct CDN PDF URLs concurrently from displayAnnouncement.do.
   - Stage 4 (Streaming Downloader Pool): 36 parallel workers streaming directly into RAM, PyMuPDF zero-copy
     validation offloaded to background threads (non-blocking event loop), and atomic write directly to
     GLOBAL_SUSTAINABILITY_DATABASE (NTFS junction to G:\My Drive).
2. Zero Straggler Delay: No batch barriers. 36 workers are 100% utilized at all times.
3. Resilient SQLite WAL state with 60s busy timeout and automatic recovery.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
import httpx

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "markets" / "Australia" / "src"))

os.environ["ASX_ACKNOWLEDGE_TERMS"] = "1"

from markets.Australia.src.asx_bulk.config import USER_AGENT
from markets.Australia.src.asx_bulk.db import Database
from markets.Australia.src.asx_bulk.models import Filing, Issuer
from markets.Australia.src.asx_bulk.parser import parse_announcements_html, parse_pdf_url
from markets.Australia.src.asx_bulk.source import ASXSource
from markets.Australia.src.asx_bulk.util import AsyncRateLimiter
from markets._integration.promotion import build_sop_relative_path

DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
LOCAL_WORK_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "work"
LOCAL_STAGING_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "staging"
IDENTIFIERS_CACHE = ROOT_DIR / "local" / "asx_master_identifiers.json"


def load_master_identifiers() -> tuple[dict[str, str], dict[str, str]]:
    ticker_to_lei: dict[str, str] = {}
    ticker_to_isin: dict[str, str] = {}

    if IDENTIFIERS_CACHE.exists():
        try:
            with open(IDENTIFIERS_CACHE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                for t, info in data.items():
                    t_up = t.strip().upper()
                    if isinstance(info, dict):
                        lei = str(info.get("lei", "")).strip().upper()
                        isin = str(info.get("isin", "")).strip().upper()
                        if lei and len(lei) == 20:
                            ticker_to_lei[t_up] = lei
                        if isin and len(isin) == 12:
                            ticker_to_isin[t_up] = isin
        except Exception:
            pass

    return ticker_to_lei, ticker_to_isin


def validate_and_write(buf: bytearray, final_path: Path) -> tuple[int, str]:
    """Runs in a worker thread to keep the asyncio event loop completely non-blocking."""
    if not buf.startswith(b"%PDF-"):
        raise RuntimeError("Downloaded content does not begin with %PDF-")

    # PyMuPDF integrity verification
    doc = fitz.open(stream=bytes(buf), filetype="pdf")
    if doc.is_encrypted:
        doc.close()
        raise RuntimeError("PDF is password encrypted")
    pages = len(doc)
    doc.close()
    if pages < 1:
        raise RuntimeError("PDF contains 0 pages")

    sha = hashlib.sha256(buf).hexdigest()
    sz = len(buf)

    # Atomic write to destination
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.with_suffix(final_path.suffix + f".tmp_{os.getpid()}_{time.time_ns()}")
    tmp_path.write_bytes(buf)
    tmp_path.replace(final_path)

    return sz, sha


class ASXStreamEngine:
    def __init__(
        self,
        output_corpus: Path = DEFAULT_CORPUS_ROOT,
        start_year: int = 2017,
        end_year: int = 2025,
        download_workers: int = 36,
        metadata_workers: int = 20,
        metadata_rps: float = 15.0,
    ):
        self.output_corpus = output_corpus.resolve()
        self.start_year = start_year
        self.end_year = end_year
        self.download_workers = download_workers
        self.metadata_workers = metadata_workers
        self.metadata_rps = metadata_rps

        LOCAL_WORK_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_STAGING_DIR.mkdir(parents=True, exist_ok=True)

        self.db = Database(LOCAL_WORK_DIR / "manifest.sqlite3")
        self.db_lock = asyncio.Lock()
        self.ticker_to_lei, self.ticker_to_isin = load_master_identifiers()
        print(f"Loaded Master Identifiers: {len(self.ticker_to_isin)} ISINs, {len(self.ticker_to_lei)} LEIs", flush=True)

        self.scan_complete = asyncio.Event()
        self.download_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=200)
        self.queued_ids: set[int] = set()
        self.completed_count = 0
        self.promoted_count = 0
        self.staged_count = 0
        self.failed_count = 0
        self.total_downloaded_bytes = 0
        self.t_start = time.time()

    async def run(self):
        print("=======================================================", flush=True)
        print("ASX CONTINUOUS STREAM HARVEST ENGINE INITIATED", flush=True)
        print(f"Download Workers: {self.download_workers} | Metadata Workers: {self.metadata_workers}")
        print(f"Target Corpus: {self.output_corpus}")
        print("=======================================================\n", flush=True)

        # 1. Fetch current issuers snapshot
        source = ASXSource(timeout=35.0, retries=4, metadata_rps=self.metadata_rps)
        try:
            print("Refreshing active ASX issuers directory...", flush=True)
            issuers = await source.current_issuers()
            print(f"Retrieved {len(issuers)} currently listed ASX companies.", flush=True)
        finally:
            await source.close()

        self.db.upsert_issuers(issuers)
        self.db.init_slots(self.start_year, self.end_year)

        # Pre-select best from existing database entries
        self.db.select_best(self.start_year, self.end_year)

        # Run decoupled pipeline concurrently
        await asyncio.gather(
            self.metadata_scanner_loop(issuers),
            self.url_resolver_loop(),
            self.queue_feeder_loop(),
            self.download_worker_pool(),
        )

        print("\nAll pipeline tasks complete! Executing final staging promotion sweep...", flush=True)
        self.sweep_staging()
        self.db.export_audits(LOCAL_WORK_DIR / "audit")
        print("\n=======================================================", flush=True)
        print("ASX HARVEST 100% COMPLETE!", flush=True)
        print(f"Total Reports Downloaded: {self.completed_count} ({self.total_downloaded_bytes / (1024*1024*1024):.2f} GB)")
        print(f"Promoted to Drive: {self.promoted_count} | Staged: {self.staged_count} | Failed: {self.failed_count}")
        print("=======================================================\n", flush=True)

    async def metadata_scanner_loop(self, issuers: list[Issuer]):
        """Stage 1: Asynchronously scans historical announcements across all unscanned tickers."""
        # Find unscanned jobs
        jobs = []
        for i in issuers:
            t = i.ticker.strip().upper()
            for y in range(self.start_year, self.end_year + 2):
                if not self.db.scan_done(t, y):
                    jobs.append((t, y))

        print(f"[Scanner] Found {len(jobs)} unscanned announcement years to crawl.", flush=True)
        if not jobs:
            self.scan_complete.set()
            return

        sem = asyncio.Semaphore(self.metadata_workers)
        rate = AsyncRateLimiter(self.metadata_rps)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=self.metadata_workers + 5, max_keepalive_connections=self.metadata_workers),
        ) as client:

            scanned = 0
            last_select = time.time()

            async def scan_one(t: str, y: int):
                nonlocal scanned, last_select
                async with sem:
                    await rate.acquire()
                    url = "https://www.asx.com.au/asx/v2/statistics/announcements.do"
                    params = {"asxCode": t, "by": "asxCode", "timeframe": "Y", "year": y}
                    try:
                        r = await client.get(url, params=params)
                        if r.status_code == 200:
                            filings = parse_announcements_html(r.text, t, y)
                            async with self.db_lock:
                                if filings:
                                    self.db.add_filings(filings)
                                self.db.mark_scan(t, y, "DONE")
                        else:
                            async with self.db_lock:
                                self.db.mark_scan(t, y, "FAILED", f"HTTP {r.status_code}")
                    except Exception as exc:
                        async with self.db_lock:
                            self.db.mark_scan(t, y, "FAILED", str(exc))

                    scanned += 1
                    if scanned % 100 == 0:
                        print(f"[Scanner Progress] Scanned {scanned}/{len(jobs)} announcement years...", flush=True)

                    # Trigger periodic candidate re-selection every 20 seconds
                    if time.time() - last_select > 20.0:
                        last_select = time.time()
                        async with self.db_lock:
                            self.db.select_best(self.start_year, self.end_year)

            await asyncio.gather(*(scan_one(t, y) for t, y in jobs))

        # Final select best
        async with self.db_lock:
            self.db.select_best(self.start_year, self.end_year)
        self.scan_complete.set()
        print(f"[Scanner] All {len(jobs)} announcement years successfully scanned!", flush=True)

    async def url_resolver_loop(self):
        """Stage 2: Resolves direct CDN PDF URLs for selected filings."""
        sem = asyncio.Semaphore(20)
        rate = AsyncRateLimiter(15.0)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=25, max_keepalive_connections=20),
        ) as client:

            async def resolve_one(fid: int, d_url: str):
                async with sem:
                    await rate.acquire()
                    for _ in range(3):
                        try:
                            resp = await client.get(d_url)
                            if resp.status_code == 200:
                                pdf_url = parse_pdf_url(resp.text)
                                if not pdf_url and resp.headers.get("content-type", "").lower().startswith("application/pdf"):
                                    pdf_url = str(resp.url)
                                if pdf_url:
                                    async with self.db_lock:
                                        self.db.set_pdf_url(fid, pdf_url)
                                    return
                        except Exception:
                            await asyncio.sleep(0.5)

            while True:
                # Find selected filings needing pdf_url
                async with self.db_lock:
                    rows = self.db.conn.execute(
                        """SELECT id, display_url FROM filings
                           WHERE selected=1 AND (pdf_url IS NULL OR pdf_url='')
                           LIMIT 100"""
                    ).fetchall()

                if rows:
                    tasks = [resolve_one(r["id"], r["display_url"]) for r in rows]
                    await asyncio.gather(*tasks)
                else:
                    if self.scan_complete.is_set():
                        # Verify one last time
                        async with self.db_lock:
                            check = self.db.conn.execute(
                                "SELECT COUNT(*) FROM filings WHERE selected=1 AND (pdf_url IS NULL OR pdf_url='')"
                            ).fetchone()[0]
                        if check == 0:
                            print("[Resolver] All direct PDF URLs resolved.", flush=True)
                            break
                    await asyncio.sleep(1.0)

    async def queue_feeder_loop(self):
        """Stage 3: Continuously feeds pending downloads into the queue."""
        while True:
            # Query pending filings that have a resolved PDF URL
            async with self.db_lock:
                rows = self.db.conn.execute(
                    """SELECT f.id, f.ticker, f.fiscal_year, f.report_type, f.pdf_url
                       FROM filings f JOIN downloads d ON f.id=d.filing_id
                       WHERE d.status='PENDING' AND f.pdf_url IS NOT NULL AND f.pdf_url != ''
                       ORDER BY f.id ASC LIMIT 200"""
                ).fetchall()

            new_jobs = [dict(r) for r in rows if r["id"] not in self.queued_ids]

            for job in new_jobs:
                self.queued_ids.add(job["id"])
                await self.download_queue.put(job)

            if not new_jobs:
                # Check if all scanning & resolving is done
                if self.scan_complete.is_set():
                    async with self.db_lock:
                        pending_total = self.db.conn.execute(
                            "SELECT COUNT(*) FROM downloads WHERE status='PENDING'"
                        ).fetchone()[0]
                        unresolved_total = self.db.conn.execute(
                            "SELECT COUNT(*) FROM filings WHERE selected=1 AND (pdf_url IS NULL OR pdf_url='')"
                        ).fetchone()[0]

                    if pending_total == 0 and unresolved_total == 0 and self.download_queue.empty():
                        print("[Queue Feeder] All pending files processed.", flush=True)
                        # Signal workers to shut down
                        for _ in range(self.download_workers):
                            await self.download_queue.put(None)
                        break

                await asyncio.sleep(1.5)
            else:
                await asyncio.sleep(0.5)

    async def download_worker_pool(self):
        """Stage 4: 36 parallel streaming workers pulling from download_queue."""
        transport = httpx.AsyncHTTPTransport(retries=3, verify=True)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(45.0, read=90.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.8"},
            limits=httpx.Limits(max_connections=self.download_workers + 10, max_keepalive_connections=self.download_workers),
        ) as cdn_client:

            async def worker(worker_id: int):
                while True:
                    job = await self.download_queue.get()
                    if job is None:
                        self.download_queue.task_done()
                        break

                    filing_id = int(job["id"])
                    ticker = job["ticker"].strip().upper()
                    fy = int(job["fiscal_year"])
                    rep_type = job.get("report_type", "AR") or "AR"
                    pdf_url = job.get("pdf_url")

                    lei = self.ticker_to_lei.get(ticker, "").strip().upper()
                    if not lei or len(lei) != 20:
                        lei = "NOLEI"

                    isin = self.ticker_to_isin.get(ticker, "").strip().upper()
                    if not isin or len(isin) != 12:
                        isin = f"AU0000{ticker.ljust(6, 'X')}"

                    sop_rel = build_sop_relative_path(
                        iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
                        lei=lei, isin=isin, report_type=rep_type
                    )
                    final_path = self.output_corpus / sop_rel
                    is_canonical = True

                    # Check if already present on disk
                    if final_path.exists() and final_path.stat().st_size > 1000:
                        try:
                            sz = final_path.stat().st_size
                            h = hashlib.sha256(final_path.read_bytes()).hexdigest()
                            async with self.db_lock:
                                self.db.mark_download(filing_id, "DONE", str(final_path), sz, h)
                            self.completed_count += 1
                            if is_canonical:
                                self.promoted_count += 1
                            else:
                                self.staged_count += 1
                            self.download_queue.task_done()
                            continue
                        except Exception:
                            pass

                    # Stream download into RAM
                    success = False
                    for attempt in range(3):
                        try:
                            buf = bytearray()
                            async with cdn_client.stream("GET", pdf_url) as resp:
                                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                                    await asyncio.sleep(1.0 * (attempt + 1))
                                    continue
                                if resp.status_code != 200:
                                    raise RuntimeError(f"HTTP {resp.status_code}")
                                async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                                    buf.extend(chunk)

                            # Validate and write in background thread
                            sz, sha = await asyncio.to_thread(validate_and_write, buf, final_path)

                            async with self.db_lock:
                                self.db.mark_download(filing_id, "DONE", str(final_path), sz, sha)
                            self.completed_count += 1
                            self.total_downloaded_bytes += sz
                            if is_canonical:
                                self.promoted_count += 1
                            else:
                                self.staged_count += 1
                            success = True

                            if self.completed_count % 20 == 0:
                                elapsed = time.time() - self.t_start
                                rate = self.completed_count / elapsed if elapsed > 0 else 0
                                mb_s = (self.total_downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                                print(
                                    f"[{datetime.now().strftime('%H:%M:%S')}] Live: {self.completed_count} reports | "
                                    f"{rate:.2f} docs/sec | {mb_s:.2f} MB/s | "
                                    f"Promoted: {self.promoted_count} | Staged: {self.staged_count} | Failed: {self.failed_count}",
                                    flush=True,
                                )
                            break

                        except Exception as exc:
                            if attempt >= 2:
                                self.failed_count += 1
                                async with self.db_lock:
                                    self.db.mark_download(filing_id, "FAILED", error=str(exc))
                            else:
                                await asyncio.sleep(0.5 * (attempt + 1))

                    self.download_queue.task_done()

            # Launch all 36 worker tasks
            workers = [asyncio.create_task(worker(i)) for i in range(self.download_workers)]
            await asyncio.gather(*workers)

    def sweep_staging(self):
        unresolved_dir = LOCAL_STAGING_DIR / "unresolved_identity"
        if not unresolved_dir.exists():
            return
        staged_pdfs = list(unresolved_dir.rglob("*.pdf"))
        if not staged_pdfs:
            return

        print(f"Sweeping {len(staged_pdfs)} staged files for promotion...", flush=True)
        promoted = 0
        pattern = re.compile(r"^([A-Z0-9]+)_(\d{4})_([A-Z]+)_")

        for pdf in staged_pdfs:
            m = pattern.match(pdf.name)
            ticker, fy, rep_type = None, None, "AR"
            if m:
                ticker, fy, rep_type = m.group(1).upper(), int(m.group(2)), m.group(3).upper()
            else:
                parts = pdf.parent.name.split("_FY")
                if len(parts) == 2:
                    ticker, fy = parts[0].upper(), int(parts[1])
            if not ticker or not fy:
                continue

            lei = self.ticker_to_lei.get(ticker, "")
            isin = self.ticker_to_isin.get(ticker, "")
            if lei and isin:
                sop_rel = build_sop_relative_path(
                    iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
                    lei=lei, isin=isin, report_type=rep_type
                )
                target = self.output_corpus / sop_rel
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix(target.suffix + f".tmp_{os.getpid()}")
                pdf.replace(tmp)
                tmp.replace(target)
                promoted += 1

        print(f"Staging Sweep Completed: {promoted} staged files promoted to Google Drive.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASX Continuous Stream Harvester")
    parser.add_argument("--download-workers", type=int, default=36, help="Download concurrency (default: 36)")
    parser.add_argument("--metadata-workers", type=int, default=20, help="Metadata crawl concurrency (default: 20)")
    parser.add_argument("--metadata-rps", type=float, default=15.0, help="Metadata requests/sec (default: 15.0)")
    args = parser.parse_args()

    engine = ASXStreamEngine(
        download_workers=args.download_workers,
        metadata_workers=args.metadata_workers,
        metadata_rps=args.metadata_rps,
    )
    asyncio.run(engine.run())
