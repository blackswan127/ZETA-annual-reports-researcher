"""High-Throughput Autonomous Harvester for All Currently Listed Australian (ASX) Companies.
Extracts Annual Reports (AR) and Sustainability / ESG Reports (SR, ESG, CLIMATE) for 2017-2025.
Adheres to SOP folder and file naming conventions into GLOBAL_SUSTAINABILITY_DATABASE.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure paths
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "markets" / "Australia" / "src"))

os.environ["ASX_ACKNOWLEDGE_TERMS"] = "1"

from markets.Australia.src.asx_bulk.config import Settings
from markets.Australia.src.asx_bulk.db import Database
from markets.Australia.src.asx_bulk.downloader import PDFDownloader
from markets.Australia.src.asx_bulk.models import Filing, Issuer
from markets.Australia.src.asx_bulk.parser import parse_announcements_html
from markets.Australia.src.asx_bulk.source import ASXSource
from markets.Australia.src.asx_bulk.util import safe_name
from markets._integration.adapters import AustraliaAdapter
from markets._integration.promotion import (
    compute_sha256_and_size,
    promote_pdf_to_corpus,
    validate_pdf_bytes_or_file,
)

DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
LOCAL_WORK_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "work"
LOCAL_STAGING_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "staging"
LOCAL_MANIFEST_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "manifests"


def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = s.upper()
    s = re.sub(r"\b(LIMITED|LTD|PTY|CORP|CORPORATION|INC|INCORPORATED|PLC|GROUP|HOLDINGS)\b", "", s)
    return re.sub(r"[^A-Z0-9]", "", s)


def load_all_local_mappings() -> tuple[dict[str, str], dict[str, str]]:
    ticker_to_lei: dict[str, str] = {}
    ticker_to_isin: dict[str, str] = {}
    name_to_lei: dict[str, str] = {}
    name_to_isin: dict[str, str] = {}

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
                        lbl = item.get("itemLabel", "")
                        if isinstance(t, dict): t = t.get("value", "")
                        if isinstance(isin, dict): isin = isin.get("value", "")
                        if isinstance(lei, dict): lei = lei.get("value", "")
                        if isinstance(lbl, dict): lbl = lbl.get("value", "")

                        t = str(t).strip().upper()
                        isin = str(isin).strip().upper()
                        lei = str(lei).strip().upper()
                        norm_lbl = normalize_name(str(lbl).strip())

                        if t and lei and len(lei) == 20:
                            ticker_to_lei[t] = lei
                        if t and isin and len(isin) == 12:
                            ticker_to_isin[t] = isin
                        if norm_lbl and lei and len(lei) == 20:
                            name_to_lei[norm_lbl] = lei
                        if norm_lbl and isin and len(isin) == 12:
                            name_to_isin[norm_lbl] = isin
        except Exception:
            pass

    # Also load master ASX identifier resolution cache if available
    master_cache = ROOT_DIR / "local" / "asx_master_identifiers.json"
    if master_cache.exists() and master_cache.stat().st_size > 10:
        try:
            with open(master_cache, encoding="utf-8") as fh:
                master_data = json.load(fh)
                if isinstance(master_data, dict):
                    for t, data in master_data.items():
                        t_clean = t.strip().upper()
                        lei = str(data.get("lei", "")).strip().upper()
                        isin = str(data.get("isin", "")).strip().upper()
                        if t_clean and lei and len(lei) == 20:
                            ticker_to_lei[t_clean] = lei
                        if t_clean and isin and len(isin) == 12:
                            ticker_to_isin[t_clean] = isin
        except Exception:
            pass

    return ticker_to_lei, ticker_to_isin, name_to_lei, name_to_isin



class ASXFullHarvester:
    def __init__(
        self,
        output_corpus: Path = DEFAULT_CORPUS_ROOT,
        start_year: int = 2017,
        end_year: int = 2025,
        metadata_workers: int = 8,
        download_workers: int = 6,
        rps: float = 3.0,
    ):
        self.output_corpus = output_corpus.resolve()
        self.start_year = start_year
        self.end_year = end_year
        self.metadata_workers = metadata_workers
        self.download_workers = download_workers
        self.rps = rps

        LOCAL_WORK_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_STAGING_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

        self.db = Database(LOCAL_WORK_DIR / "manifest.sqlite3")
        self.dl = PDFDownloader(
            workers=download_workers,
            rps=rps,
            timeout=45.0,
            retries=5,
            chunk_size=1024 * 1024,
        )

        # Load metadata mappings
        print("Loading local Wikidata LEI/ISIN mappings...", flush=True)
        t_lei, t_isin, n_lei, n_isin = load_all_local_mappings()
        self.ticker_to_lei = t_lei
        self.ticker_to_isin = t_isin
        self.name_to_lei = n_lei
        self.name_to_isin = n_isin
        print(f"Loaded mappings: {len(t_lei)} ticker->LEI, {len(t_isin)} ticker->ISIN, {len(n_lei)} name->LEI", flush=True)

    def resolve_identifiers(self, ticker: str, name: str) -> tuple[str, str]:
        t = ticker.strip().upper()
        norm_n = normalize_name(name)
        lei = self.ticker_to_lei.get(t) or self.name_to_lei.get(norm_n, "")
        isin = self.ticker_to_isin.get(t) or self.name_to_isin.get(norm_n, "")
        return lei, isin

    async def refresh_issuers(self) -> list[dict]:
        source = ASXSource(timeout=35.0, retries=4, metadata_rps=self.rps)
        try:
            print("Fetching active ASX issuers directory...", flush=True)
            issuers = await source.current_issuers()
            print(f"Retrieved {len(issuers)} currently listed ASX companies.", flush=True)
        finally:
            await source.close()

        self.db.upsert_issuers(issuers)
        self.db.init_slots(self.start_year, self.end_year)

        # Return list of dicts with resolved identifiers
        out = []
        for i in issuers:
            t = i.ticker.strip().upper()
            lei, isin = self.resolve_identifiers(t, i.name)
            out.append({
                "ticker": t,
                "name": i.name,
                "industry": i.industry,
                "listing_date": i.listing_date,
                "lei": lei,
                "isin": isin,
            })
        return out

    async def process_batch(self, batch: list[dict], batch_idx: int, total_batches: int) -> dict:
        t0 = time.time()
        tickers = [item["ticker"] for item in batch]
        ticker_map = {item["ticker"]: item for item in batch}
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] --- Starting Batch {batch_idx}/{total_batches} ({len(tickers)} companies: {tickers[0]}..{tickers[-1]}) ---", flush=True)

        # 1. Discover announcements for publication years (start_year .. end_year + 1)
        publication_end = self.end_year + 1
        jobs = []
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

        if jobs:
            print(f"Scanning {len(jobs)} announcement years across {len(tickers)} companies...", flush=True)
            source = ASXSource(timeout=35.0, retries=4, metadata_rps=self.rps)
            sem = asyncio.Semaphore(self.metadata_workers)
            scanned = 0

            async def scan_one(t: str, y: int):
                nonlocal scanned
                async with sem:
                    try:
                        filings = await source.annual_candidates(t, y)
                        if filings:
                            self.db.add_filings(filings)
                        self.db.mark_scan(t, y, "DONE")
                    except Exception as exc:
                        self.db.mark_scan(t, y, "FAILED", str(exc))
                    scanned += 1

            try:
                await asyncio.gather(*(scan_one(t, y) for t, y in jobs))
            finally:
                await source.close()

        # 2. Select best candidates for AR and SR
        self.db.select_best(self.start_year, self.end_year)

        # 3. Download pending selected filings for this batch
        pending_rows = [
            r for r in self.db.selected_pending()
            if r["ticker"].strip().upper() in ticker_map
        ]
        print(f"Selected pending reports to download in batch: {len(pending_rows)}", flush=True)

        source = ASXSource(timeout=35.0, retries=4, metadata_rps=self.rps)
        downloaded = 0
        promoted = 0
        staged = 0
        failed = 0

        async def download_one(row):
            nonlocal downloaded, promoted, staged, failed
            filing_id = int(row["id"])
            ticker = row["ticker"].strip().upper()
            meta = ticker_map.get(ticker, {})
            fy = int(row["fiscal_year"])
            rep_type = (row["report_type"] if "report_type" in row.keys() else "AR") or "AR"

            try:
                pdf_url = row["pdf_url"] or await source.resolve_pdf_url(row["display_url"])
                if not row["pdf_url"]:
                    self.db.set_pdf_url(filing_id, pdf_url)

                company_dir = f"{ticker}_{safe_name(row['name'], 70)}"
                local_dir = LOCAL_WORK_DIR / "pdfs" / company_dir / str(fy)
                local_dir.mkdir(parents=True, exist_ok=True)
                local_pdf = local_dir / f"{ticker}_{fy}_{rep_type}_Report.pdf"

                # Download locally first
                if local_pdf.exists() and local_pdf.stat().st_size > 1000:
                    src_hash, src_sz = compute_sha256_and_size(local_pdf)
                else:
                    src_sz, src_hash = await self.dl.download(pdf_url, local_pdf)

                self.db.mark_download(filing_id, "DONE", str(local_pdf), src_sz, src_hash)
                downloaded += 1

                # Promote to Google Drive / SOP corpus
                status, reason, final_path = promote_pdf_to_corpus(
                    source_pdf=local_pdf,
                    output_root=self.output_corpus,
                    staging_root=LOCAL_STAGING_DIR,
                    iso3="AUS",
                    mic="XASX",
                    ticker=ticker,
                    fiscal_year=fy,
                    lei=meta.get("lei", ""),
                    isin=meta.get("isin", ""),
                    report_type=rep_type,
                )
                if status in ("PROMOTED", "IDEMPOTENT_EXISTING"):
                    promoted += 1
                elif status == "STAGED_UNRESOLVED_IDENTITY":
                    staged += 1

            except Exception as exc:
                failed += 1
                self.db.mark_download(filing_id, "FAILED", error=str(exc))

        if pending_rows:
            try:
                await asyncio.gather(*(download_one(r) for r in pending_rows))
            finally:
                await source.close()

        # Export audits
        self.db.export_audits(LOCAL_WORK_DIR / "audit")
        elapsed = time.time() - t0
        print(f"Batch {batch_idx}/{total_batches} Complete in {elapsed:.1f}s | Downloaded: {downloaded} | Promoted to Drive: {promoted} | Staged: {staged} | Failed: {failed}", flush=True)

        return {
            "batch_idx": batch_idx,
            "tickers": len(tickers),
            "pending": len(pending_rows),
            "downloaded": downloaded,
            "promoted": promoted,
            "staged": staged,
            "failed": failed,
            "elapsed_seconds": round(elapsed, 2),
        }

    async def run(self, batch_size: int = 50, max_batches: int | None = None, offset: int = 0):
        t_start = time.time()
        issuers = await self.refresh_issuers()
        total_issuers = len(issuers)
        issuers = issuers[offset:]
        if max_batches:
            issuers = issuers[: max_batches * batch_size]

        batches = [issuers[i: i + batch_size] for i in range(0, len(issuers), batch_size)]
        total_batches = len(batches)
        print(f"\n=======================================================", flush=True)
        print(f"ASX HARVEST ENGINE INITIATED: {total_issuers} total active listed issuers", flush=True)
        print(f"Processing {len(issuers)} issuers in {total_batches} batches of up to {batch_size}", flush=True)
        print(f"Fiscal Years: {self.start_year} - {self.end_year}", flush=True)
        print(f"Output Target: {self.output_corpus}", flush=True)
        print(f"=======================================================\n", flush=True)

        batch_results = []
        for idx, b in enumerate(batches, 1):
            res = await self.process_batch(b, idx, total_batches)
            batch_results.append(res)

        total_elapsed = time.time() - t_start
        tot_downloaded = sum(r["downloaded"] for r in batch_results)
        tot_promoted = sum(r["promoted"] for r in batch_results)
        tot_staged = sum(r["staged"] for r in batch_results)
        tot_failed = sum(r["failed"] for r in batch_results)

        print("\n" + "=" * 70, flush=True)
        print("ASX REPORT HARVEST RUN COMPLETED", flush=True)
        print("=" * 70, flush=True)
        print(f"Total Active Companies:       {total_issuers}")
        print(f"Processed Issuers:           {len(issuers)}")
        print(f"Batches Completed:           {len(batches)}/{total_batches}")
        print(f"Reports Downloaded:          {tot_downloaded}")
        print(f"Promoted to SOP Drive:       {tot_promoted}")
        print(f"Staged (Unresolved Identity): {tot_staged}")
        print(f"Failed Downloads:            {tot_failed}")
        print(f"Total Elapsed Time:          {total_elapsed:.1f}s")
        print(f"Audits Directory:            {LOCAL_WORK_DIR / 'audit'}")
        print("=" * 70 + "\n", flush=True)


async def main():
    parser = argparse.ArgumentParser(description="ASX Full Report Harvester")
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--start-year", type=int, default=2017)
    parser.add_argument("--end-year", type=int, default=2025)
    args = parser.parse_args()

    harvester = ASXFullHarvester(
        start_year=args.start_year,
        end_year=args.end_year,
    )
    await harvester.run(
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        offset=args.offset,
    )


if __name__ == "__main__":
    asyncio.run(main())
