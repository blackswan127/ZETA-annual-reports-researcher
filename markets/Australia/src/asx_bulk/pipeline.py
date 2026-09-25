from __future__ import annotations

import asyncio
import zlib
from datetime import datetime
from pathlib import Path

from .config import Settings, require_terms_acknowledgement
from .db import Database
from .downloader import PDFDownloader
from .source import ASXSource
from .util import safe_name

class Pipeline:
    def __init__(self, settings: Settings):
        self.s = settings
        self.s.output_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.s.db_path)

    def close(self):
        self.db.close()

    def _in_shard(self, ticker: str) -> bool:
        if self.s.shard_count <= 1:
            return True
        return (zlib.crc32(ticker.encode("utf-8")) & 0xffffffff) % self.s.shard_count == self.s.shard_index

    async def refresh_universe(self) -> int:
        require_terms_acknowledgement()
        source = ASXSource(self.s.timeout, self.s.retries, self.s.metadata_rps)
        try:
            issuers = await source.current_issuers()
        finally:
            await source.close()
        self.db.upsert_issuers(issuers)
        self.db.init_slots(self.s.start_year, self.s.end_year)
        return len(issuers)

    async def discover(self, tickers: list[str] | None = None, force: bool = False) -> None:
        require_terms_acknowledgement()
        rows = self.db.conn.execute("SELECT ticker,listing_date FROM issuers WHERE active=1 ORDER BY ticker").fetchall()
        rows = [r for r in rows if self._in_shard(r[0])]
        if tickers:
            wanted = {x.upper() for x in tickers}
            rows = [r for r in rows if r[0] in wanted]
        publication_end = self.s.end_year + (1 if self.s.capture_following_year else 0)
        jobs = []
        for r in rows:
            ticker = r[0]
            listing_year = None
            if r[1]:
                try:
                    listing_year = int(str(r[1])[:4])
                except Exception:
                    listing_year = None
            for year in range(self.s.start_year, publication_end + 1):
                if listing_year and year < listing_year:
                    self.db.mark_scan(ticker, year, "DONE", "pre_listing_year")
                    continue
                if not force and self.db.scan_done(ticker, year):
                    continue
                jobs.append((ticker, year))

        source = ASXSource(self.s.timeout, self.s.retries, self.s.metadata_rps)
        sem = asyncio.Semaphore(max(1, self.s.metadata_workers))
        counter = 0
        lock = asyncio.Lock()

        async def one(ticker: str, year: int):
            nonlocal counter
            async with sem:
                try:
                    filings = await source.annual_candidates(ticker, year)
                    self.db.add_filings(filings)
                    self.db.mark_scan(ticker, year, "DONE")
                except Exception as exc:
                    self.db.mark_scan(ticker, year, "FAILED", str(exc))
                async with lock:
                    counter += 1
                    if counter % 100 == 0 or counter == len(jobs):
                        print(f"Discovery: {counter}/{len(jobs)} pages")

        try:
            await asyncio.gather(*(one(t, y) for t, y in jobs))
        finally:
            await source.close()
        self.db.select_best(self.s.start_year, self.s.end_year)
        self.db.export_audits(self.s.audit_root)

    async def download(self, limit: int | None = None, tickers: list[str] | None = None) -> None:
        require_terms_acknowledgement()
        rows = [r for r in self.db.selected_pending() if self._in_shard(r["ticker"])]
        if tickers:
            allowed = {t.strip().upper() for t in tickers if t}
            rows = [r for r in rows if r["ticker"].strip().upper() in allowed]
        if limit:
            rows = rows[:limit]
        source = ASXSource(self.s.timeout, self.s.retries, self.s.metadata_rps)
        dl = PDFDownloader(self.s.download_workers, self.s.download_rps, self.s.timeout, self.s.retries, self.s.chunk_size)
        counter = 0
        lock = asyncio.Lock()

        async def one(row):
            nonlocal counter
            filing_id = int(row["id"])
            try:
                pdf_url = row["pdf_url"] or await source.resolve_pdf_url(row["display_url"])
                if not row["pdf_url"]:
                    self.db.set_pdf_url(filing_id, pdf_url)
                company_dir = f"{row['ticker']}_{safe_name(row['name'], 70)}"
                rep_type = (row["report_type"] if "report_type" in row.keys() else "AR") or "AR"
                if rep_type == "AR":
                    filename = f"{row['ticker']}_{row['fiscal_year']}_Annual_Report.pdf"
                else:
                    filename = f"{row['ticker']}_{row['fiscal_year']}_{rep_type}_Report.pdf"
                dest = self.s.pdf_root / company_dir / str(row["fiscal_year"]) / filename
                if dest.exists():
                    from .util import is_pdf, sha256_file
                    if is_pdf(dest):
                        self.db.mark_download(filing_id, "DONE", str(dest), dest.stat().st_size, sha256_file(dest))
                    else:
                        size, digest = await dl.download(pdf_url, dest)
                        self.db.mark_download(filing_id, "DONE", str(dest), size, digest)
                else:
                    size, digest = await dl.download(pdf_url, dest)
                    self.db.mark_download(filing_id, "DONE", str(dest), size, digest)
            except Exception as exc:
                self.db.mark_download(filing_id, "FAILED", error=str(exc))
            async with lock:
                counter += 1
                if counter % 25 == 0 or counter == len(rows):
                    print(f"Downloads: {counter}/{len(rows)}")

        try:
            await asyncio.gather(*(one(r) for r in rows))
        finally:
            await source.close()
            await dl.close()
        self.db.export_audits(self.s.audit_root)

    def audit(self) -> None:
        self.db.select_best(self.s.start_year, self.s.end_year)
        self.db.export_audits(self.s.audit_root)
        stats = self.db.conn.execute(
            """SELECT e.status,count(*) n FROM expected_slots e
               JOIN issuers i ON i.ticker=e.ticker AND i.active=1
               GROUP BY e.status ORDER BY e.status"""
        ).fetchall()
        print("Coverage:")
        for r in stats:
            print(f"  {r['status']}: {r['n']}")

    async def smoke(self, ticker: str = "BHP", year: int = 2025) -> None:
        require_terms_acknowledgement()
        source = ASXSource(self.s.timeout, self.s.retries, 1.5)
        try:
            issuers = await source.current_issuers()
            print(f"Current issuer universe: {len(issuers)}")
            if ticker.upper() not in {i.ticker for i in issuers}:
                raise RuntimeError(f"{ticker} was not found in current ASX company universe")
            filings = await source.annual_candidates(ticker.upper(), year)
            print(f"Annual-report candidates for {ticker.upper()} publication year {year}: {len(filings)}")
            if not filings:
                raise RuntimeError("No annual-report candidate found in smoke test")
            best = sorted(filings, key=lambda x: (x.score, x.pages or 0), reverse=True)[0]
            print(f"Best: {best.title} | FY={best.fiscal_year} | pages={best.pages} | id={best.announcement_id}")
            pdf_url = await source.resolve_pdf_url(best.display_url)
            print(f"Resolved PDF URL: {pdf_url}")
            # Download only first bytes using Range to avoid a full report during smoke test.
            await source.rate.acquire()
            r = await source.client.get(pdf_url, headers={"Range": "bytes=0-15"})
            r.raise_for_status()
            if not r.content.startswith(b"%PDF-"):
                raise RuntimeError("Smoke target did not return PDF bytes")
            print("SMOKE TEST PASS")
        finally:
            await source.close()

    async def run_all(self) -> None:
        n = await self.refresh_universe()
        print(f"Loaded {n} current ASX companies")
        await self.discover()
        await self.download()
        self.audit()
