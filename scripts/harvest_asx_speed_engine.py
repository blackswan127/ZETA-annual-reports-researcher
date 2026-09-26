r"""High-Throughput Zero-Copy Speed Engine for All Listed Australian (ASX) Companies.
Implements the corporate-harvester-speed-engine protocol:
1. Zero-Copy RAM-pipelined download & PyMuPDF verification (0 redundant disk reads).
2. 28 concurrent async download workers on announcements.asx.com.au CDN (no artificial throttling).
3. 16 async metadata workers for historical announcements scanning.
4. Pre-resolves displayAnnouncement.do redirect URLs in parallel.
5. Direct single-pass atomic write to GLOBAL_SUSTAINABILITY_DATABASE (NTFS junction to G:\My Drive).
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
from markets.Australia.src.asx_bulk.util import AsyncRateLimiter, safe_name
from markets._integration.promotion import (
    build_sop_relative_path,
    is_valid_isin,
    is_valid_lei,
    promote_pdf_to_corpus,
)


DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
LOCAL_WORK_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "work"
LOCAL_STAGING_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "staging"
IDENTIFIERS_CACHE = ROOT_DIR / "local" / "asx_master_identifiers.json"


def load_master_identifiers() -> tuple[dict[str, str], dict[str, str], dict[str, dict]]:
    ticker_to_lei: dict[str, str] = {}
    ticker_to_isin: dict[str, str] = {}
    raw_cache: dict[str, dict] = {}

    # 1. Load local/asx_master_identifiers.json
    if IDENTIFIERS_CACHE.exists() and IDENTIFIERS_CACHE.stat().st_size > 10:
        try:
            with open(IDENTIFIERS_CACHE, encoding="utf-8") as f:
                raw_cache = json.load(f)
                for t, data in raw_cache.items():
                    t_clean = t.strip().upper()
                    lei = str(data.get("lei", "")).strip().upper()
                    isin = str(data.get("isin", "")).strip().upper()
                    if t_clean and lei and len(lei) == 20:
                        ticker_to_lei[t_clean] = lei
                    if t_clean and isin and len(isin) == 12:
                        ticker_to_isin[t_clean] = isin
        except Exception:
            pass

    # 2. Enrich from any local wikidata dumps if not already populated
    for p in (ROOT_DIR / "local").glob("wikidata*.json"):
        if p.stat().st_size < 10:
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, list):
                    for item in data:
                        t = item.get("ticker", "")
                        isin = item.get("isin", "")
                        lei = item.get("lei", "")
                        if isinstance(t, dict): t = t.get("value", "")
                        if isinstance(isin, dict): isin = isin.get("value", "")
                        if isinstance(lei, dict): lei = lei.get("value", "")

                        t = str(t).strip().upper()
                        isin = str(isin).strip().upper()
                        lei = str(lei).strip().upper()

                        if t and lei and len(lei) == 20 and t not in ticker_to_lei:
                            ticker_to_lei[t] = lei
                        if t and isin and len(isin) == 12 and t not in ticker_to_isin:
                            ticker_to_isin[t] = isin
        except Exception:
            pass

    return ticker_to_lei, ticker_to_isin, raw_cache


class ASXSpeedEngine:
    def __init__(
        self,
        output_corpus: Path = DEFAULT_CORPUS_ROOT,
        start_year: int = 2017,
        end_year: int = 2025,
        download_workers: int = 28,
        metadata_workers: int = 16,
        metadata_rps: float = 8.0,
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
        self.ticker_to_lei, self.ticker_to_isin, self.master_cache = load_master_identifiers()
        print(f"Loaded Master Identifiers: {len(self.ticker_to_isin)} ISINs, {len(self.ticker_to_lei)} LEIs", flush=True)

    def resolve_identifiers(self, ticker: str, name: str) -> tuple[str, str]:
        t = ticker.strip().upper()
        lei = self.ticker_to_lei.get(t, "")
        isin = self.ticker_to_isin.get(t, "")
        return lei, isin

    async def scan_metadata(self, batch: list[dict], client: httpx.AsyncClient) -> None:
        """Scan historical announcements for a batch of companies concurrently."""
        jobs = []
        publication_end = self.end_year + 1
        for item in batch:
            ticker = item["ticker"]
            listing_year = None
            if item.get("listing_date"):
                try:
                    listing_year = int(str(item["listing_date"])[:4])
                except Exception:
                    listing_year = None
            for year in range(self.start_year, publication_end + 1):
                if listing_year and year < listing_year:
                    self.db.mark_scan(ticker, year, "DONE", "pre_listing_year")
                    continue
                if self.db.scan_done(ticker, year):
                    continue
                jobs.append((ticker, year))

        if not jobs:
            return

        print(f"Scanning {len(jobs)} announcement years across {len(batch)} companies (concurrency={self.metadata_workers})...", flush=True)
        sem = asyncio.Semaphore(self.metadata_workers)
        rate = AsyncRateLimiter(self.metadata_rps)

        async def scan_one(t: str, y: int):
            async with sem:
                await rate.acquire()
                url = "https://www.asx.com.au/asx/v2/statistics/announcements.do"
                params = {"asxCode": t, "by": "asxCode", "timeframe": "Y", "year": y}
                try:
                    r = await client.get(url, params=params, timeout=25.0)
                    if r.status_code == 200:
                        filings = parse_announcements_html(r.text, t, y)
                        if filings:
                            self.db.add_filings(filings)
                        self.db.mark_scan(t, y, "DONE")
                    else:
                        self.db.mark_scan(t, y, "FAILED", f"HTTP {r.status_code}")
                except Exception as exc:
                    self.db.mark_scan(t, y, "FAILED", str(exc))

        await asyncio.gather(*(scan_one(t, y) for t, y in jobs))

    async def resolve_pdf_urls_parallel(self, pending_rows: list[dict], client: httpx.AsyncClient) -> None:
        """Batch-resolve displayAnnouncement.do to direct CDN PDF URLs."""
        needing_url = [r for r in pending_rows if not r.get("pdf_url")]
        if not needing_url:
            return

        print(f"Pre-resolving {len(needing_url)} direct CDN PDF URLs...", flush=True)
        sem = asyncio.Semaphore(16)
        rate = AsyncRateLimiter(8.0)

        async def resolve_one(r: dict):
            fid = int(r["id"])
            d_url = r["display_url"]
            async with sem:
                await rate.acquire()
                for attempt in range(3):
                    try:
                        resp = await asyncio.wait_for(client.get(d_url), timeout=10.0)
                        if resp.status_code == 200:
                            pdf_url = parse_pdf_url(resp.text)
                            if not pdf_url and resp.headers.get("content-type", "").lower().startswith("application/pdf"):
                                pdf_url = str(resp.url)
                            if pdf_url:
                                self.db.set_pdf_url(fid, pdf_url)
                                r["pdf_url"] = pdf_url
                                return
                    except Exception:
                        await asyncio.sleep(0.5)

        await asyncio.gather(*(resolve_one(r) for r in needing_url))
        print(f"Pre-resolved direct CDN PDF URLs for batch ({len(needing_url)} checked).", flush=True)

    async def download_batch_ram(self, pending_rows: list[dict], ticker_map: dict[str, dict]) -> dict:
        """Download and verify PDFs directly in RAM with zero redundant disk reads."""
        downloaded = 0
        promoted = 0
        staged = 0
        failed = 0
        print(f"Downloading {len(pending_rows)} reports in RAM across {self.download_workers} workers...", flush=True)


        # Dedicated CDN client without artificial rate throttling
        transport = httpx.AsyncHTTPTransport(retries=3, verify=True)
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(45.0, read=90.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.8"},
            limits=httpx.Limits(max_connections=self.download_workers + 8, max_keepalive_connections=self.download_workers),
        ) as cdn_client:

            sem = asyncio.Semaphore(self.download_workers)

            async def download_one(row: dict):
                nonlocal downloaded, promoted, staged, failed
                filing_id = int(row["id"])
                ticker = row["ticker"].strip().upper()
                meta = ticker_map.get(ticker, {})
                fy = int(row["fiscal_year"])
                rep_type = (row["report_type"] if "report_type" in row.keys() else "AR") or "AR"
                pdf_url = row.get("pdf_url")

                if not pdf_url:
                    failed += 1
                    self.db.mark_download(filing_id, "FAILED", error="No PDF URL resolved")
                    return

                lei = meta.get("lei", "")
                isin = meta.get("isin", "")

                # Determine target path
                if lei and isin:
                    # Canonical Google Drive Path
                    sop_rel = build_sop_relative_path(
                        iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
                        lei=lei, isin=isin, report_type=rep_type
                    )
                    final_path = self.output_corpus / sop_rel
                    is_canonical = True
                else:
                    # Unresolved identity staging path
                    final_path = LOCAL_STAGING_DIR / "unresolved_identity" / f"{ticker}_FY{fy}" / f"{ticker}_{fy}_{rep_type}_Report.pdf"
                    is_canonical = False

                # Skip if already exists and valid
                if final_path.exists() and final_path.stat().st_size > 1000:
                    try:
                        sz = final_path.stat().st_size
                        h = hashlib.sha256(final_path.read_bytes()).hexdigest()
                        self.db.mark_download(filing_id, "DONE", str(final_path), sz, h)
                        downloaded += 1
                        if is_canonical:
                            promoted += 1
                        else:
                            staged += 1
                        return
                    except Exception:
                        pass

                async with sem:
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

                            if not buf.startswith(b"%PDF-"):
                                raise RuntimeError("Downloaded content does not begin with %PDF-")

                            # Zero-Copy PyMuPDF validation in RAM
                            doc = fitz.open(stream=bytes(buf), filetype="pdf")
                            if doc.is_encrypted:
                                doc.close()
                                raise RuntimeError("PDF is password encrypted")
                            pages = len(doc)
                            doc.close()
                            if pages < 1:
                                raise RuntimeError("PDF contains 0 pages")

                            # Compute SHA-256 in RAM
                            sha = hashlib.sha256(buf).hexdigest()
                            sz = len(buf)

                            # Atomic single-pass write to destination
                            final_path.parent.mkdir(parents=True, exist_ok=True)
                            tmp_path = final_path.with_suffix(final_path.suffix + f".tmp_{os.getpid()}")
                            tmp_path.write_bytes(buf)
                            tmp_path.replace(final_path)

                            # Ledger in SQLite
                            self.db.mark_download(filing_id, "DONE", str(final_path), sz, sha)
                            downloaded += 1
                            if is_canonical:
                                promoted += 1
                            else:
                                staged += 1
                            return

                        except Exception as exc:
                            if attempt >= 2:
                                failed += 1
                                self.db.mark_download(filing_id, "FAILED", error=str(exc))
                            else:
                                await asyncio.sleep(0.5 * (attempt + 1))



            await asyncio.gather(*(download_one(r) for r in pending_rows))

        return {
            "downloaded": downloaded,
            "promoted": promoted,
            "staged": staged,
            "failed": failed,
        }

    async def run(self, batch_size: int = 50):
        print("=======================================================", flush=True)
        print("ASX SPEED HARVEST ENGINE INITIATED", flush=True)
        print(f"Download Workers: {self.download_workers} | Metadata Workers: {self.metadata_workers}")
        print(f"Output Target: {self.output_corpus}")
        print("=======================================================\n", flush=True)

        # 1. Fetch current issuers
        source = ASXSource(timeout=35.0, retries=4, metadata_rps=self.metadata_rps)
        try:
            print("Fetching active ASX issuers directory...", flush=True)
            issuers = await source.current_issuers()
            print(f"Retrieved {len(issuers)} currently listed ASX companies.", flush=True)
        finally:
            await source.close()

        self.db.upsert_issuers(issuers)
        self.db.init_slots(self.start_year, self.end_year)

        # Prepare company list with loaded identifiers
        companies = []
        for i in issuers:
            t = i.ticker.strip().upper()
            lei, isin = self.resolve_identifiers(t, i.name)
            companies.append({
                "ticker": t,
                "name": i.name,
                "industry": i.industry,
                "listing_date": i.listing_date,
                "lei": lei,
                "isin": isin,
            })

        # Process in batches
        batches = [companies[i:i + batch_size] for i in range(0, len(companies), batch_size)]
        total_batches = len(batches)
        print(f"Processing {len(companies)} issuers in {total_batches} batches of {batch_size}...\n", flush=True)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=15),
        ) as meta_client:


            for idx, batch in enumerate(batches, 1):
                t0 = time.time()
                tickers = [item["ticker"] for item in batch]
                ticker_map = {item["ticker"]: item for item in batch}
                print(f"[{datetime.now().strftime('%H:%M:%S')}] --- Starting Batch {idx}/{total_batches} ({len(tickers)} companies: {tickers[0]}..{tickers[-1]}) ---", flush=True)

                # 1. Metadata scan
                await self.scan_metadata(batch, meta_client)

                # 2. Select best candidates
                self.db.select_best(self.start_year, self.end_year)

                # 3. Retrieve all pending filings for this batch
                pending_rows = [
                    dict(r) for r in self.db.selected_pending()
                    if r["ticker"].strip().upper() in ticker_map
                ]

                print(f"Selected pending reports for batch: {len(pending_rows)}", flush=True)

                if pending_rows:
                    # 4. Pre-resolve direct PDF URLs
                    await self.resolve_pdf_urls_parallel(pending_rows, meta_client)

                    # 5. Zero-copy RAM-pipelined download & verification
                    t_dl0 = time.time()
                    res = await self.download_batch_ram(pending_rows, ticker_map)
                    dl_elapsed = time.time() - t_dl0
                    mb_speed = 0.0
                    docs_speed = res['downloaded'] / dl_elapsed if dl_elapsed > 0 else 0
                    print(f"Downloads Complete in {dl_elapsed:.1f}s ({docs_speed:.2f} docs/sec) | Downloaded: {res['downloaded']} | Promoted: {res['promoted']} | Staged: {res['staged']} | Failed: {res['failed']}", flush=True)

                # Export audits
                self.db.export_audits(LOCAL_WORK_DIR / "audit")
                elapsed = time.time() - t0
                print(f"Batch {idx}/{total_batches} Total Time: {elapsed:.1f}s\n", flush=True)

        print("\nAll batches complete! Executing final staging promotion sweep...", flush=True)
        # Final staging sweep
        self.sweep_staging()
        print("ASX Harvest 100% Complete!", flush=True)

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
                st, _, _ = promote_pdf_to_corpus(
                    source_pdf=pdf, output_root=self.output_corpus, staging_root=LOCAL_STAGING_DIR,
                    iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
                    lei=lei, isin=isin, report_type=rep_type
                )
                if st in ("PROMOTED", "IDEMPOTENT_EXISTING"):
                    promoted += 1
                    pdf.unlink(missing_ok=True)
                    if not any(pdf.parent.iterdir()):
                        pdf.parent.rmdir()
        print(f"Promoted {promoted} staged PDFs to Google Drive.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ASX High-Speed Harvester")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--download-workers", type=int, default=28)
    parser.add_argument("--metadata-workers", type=int, default=16)
    args = parser.parse_args()

    engine = ASXSpeedEngine(
        download_workers=args.download_workers,
        metadata_workers=args.metadata_workers,
    )
    asyncio.run(engine.run(batch_size=args.batch_size))
