from __future__ import annotations

import asyncio
from pathlib import Path

from .audit import write_audits
from .db import Database
from .downloader import PDFDownloader
from .httpclient import RetryingClient
from .models import Filing, Issuer
from .sgx import SGXSource


class Pipeline:
    def __init__(self, output: Path, start_year: int, end_year: int,
                 discovery_workers: int = 6, detail_workers: int = 8,
                 download_workers: int = 6, targeted_recovery: bool = True):
        self.output = output
        self.start_year = start_year
        self.end_year = end_year
        self.discovery_workers = discovery_workers
        self.detail_workers = detail_workers
        self.download_workers = download_workers
        self.targeted_recovery = targeted_recovery
        self.db_path = output / "manifest.sqlite3"
        self.db = Database(self.db_path)
        self.http = RetryingClient()
        self.source = SGXSource(self.http)

    async def close(self) -> None:
        self.db.close()
        await self.http.close()

    async def discover(self) -> tuple[int, int]:
        print("[1/4] Loading current SGX Mainboard/Catalist issuer universe...")
        issuers = await self.source.current_issuers()
        self.db.upsert_issuers(issuers)
        print(f"      current issuers: {len(issuers)}")

        print("[2/4] Scanning SGX financial-reports feed...")
        rows = await self.source.global_report_rows(workers=self.discovery_workers)
        annual_rows = [r for r in rows if self.source.is_annual(r)]
        alias_index = self.source.issuer_alias_index(issuers)
        mapped = 0
        for row in annual_rows:
            year = self.source.row_year(row)
            if year is None or not (self.start_year <= year <= self.end_year):
                continue
            issuer, reason = self.source.map_row(row, alias_index)
            if issuer is None:
                self.db.add_unmapped(row, year, reason)
                continue
            filing = self.source.filing_from_row(row, issuer)
            if filing:
                self.db.upsert_filing(filing, "global", reason)
                mapped += 1
        print(f"      mapped annual filings in target years: {mapped}")

        if self.targeted_recovery:
            missing = self._issuers_with_missing_any_year(issuers)
            print(f"[3/4] Targeted recovery for {len(missing)} issuers with at least one uncovered year...")
            sem = asyncio.Semaphore(max(1, self.discovery_workers))

            async def recover(issuer: Issuer) -> int:
                async with sem:
                    try:
                        rws = await self.source.company_report_rows(issuer)
                    except Exception as exc:
                        print(f"      recovery failed {issuer.stock_code}: {exc}")
                        return 0
                    count = 0
                    for row in rws:
                        year = self.source.row_year(row)
                        if year is None or not (self.start_year <= year <= self.end_year):
                            continue
                        filing = self.source.filing_from_row(row, issuer)
                        if filing:
                            self.db.upsert_filing(filing, "targeted", "companyname-query")
                            count += 1
                    return count

            recovered = 0
            tasks = [asyncio.create_task(recover(i)) for i in missing]
            for fut in asyncio.as_completed(tasks):
                recovered += await fut
            print(f"      targeted filing rows accepted: {recovered}")
        else:
            print("[3/4] Targeted recovery disabled.")

        total = self.db.conn.execute("SELECT COUNT(*) FROM filings").fetchone()[0]
        return len(issuers), total

    def _issuers_with_missing_any_year(self, issuers: list[Issuer]) -> list[Issuer]:
        out = []
        for issuer in issuers:
            found = {r[0] for r in self.db.conn.execute("SELECT DISTINCT fiscal_year FROM filings WHERE ibm_code=?", (issuer.ibm_code,))}
            if any(y not in found for y in range(self.start_year, self.end_year + 1)):
                out.append(issuer)
        return out

    async def resolve(self) -> tuple[int, int]:
        print("[4/4] Resolving annual-report PDF attachments...")
        rows = self.db.filings_needing_resolution()
        sem = asyncio.Semaphore(max(1, self.detail_workers))
        ok = fail = 0

        async def resolve_one(row):
            async with sem:
                filing = Filing(
                    announcement_id=row["announcement_id"], ibm_code=row["ibm_code"],
                    stock_code=row["stock_code"], issuer_name=row["issuer_name"],
                    short_name=row["short_name"], fiscal_year=row["fiscal_year"],
                    period_end=__import__("datetime").date.fromisoformat(row["period_end"]),
                    broadcast_at=__import__("datetime").datetime.fromisoformat(row["broadcast_at"]),
                    detail_url=row["detail_url"], title=row["title"],
                )
                attachments, selected = await self.source.resolve_attachments(filing)
                if not attachments or not selected:
                    return False, filing.announcement_id
                self.db.replace_attachments(filing.announcement_id, attachments, selected)
                return True, filing.announcement_id

        tasks = [asyncio.create_task(resolve_one(r)) for r in rows]
        for fut in asyncio.as_completed(tasks):
            try:
                good, ann = await fut
                if good: ok += 1
                else:
                    fail += 1; print("      no annual PDF candidate:", ann)
            except Exception as exc:
                fail += 1; print("      attachment resolution failed:", exc)
        return ok, fail

    async def download(self, ibm_codes: list[str] | None = None, stock_codes: list[str] | None = None) -> tuple[int, int]:
        self.db.reset_stale_downloading()
        rows = self.db.selected_downloads(retry_failed=True)
        if ibm_codes:
            allowed_ibm = {x.strip().upper() for x in ibm_codes if x}
            rows = [r for r in rows if r["ibm_code"].strip().upper() in allowed_ibm]
        if stock_codes:
            allowed_stock = {x.strip().upper() for x in stock_codes if x}
            rows = [r for r in rows if r["stock_code"] and r["stock_code"].strip().upper() in allowed_stock]
        print(f"Downloading {len(rows)} selected PDF attachment(s) with {self.download_workers} workers...")
        downloader = PDFDownloader(self.http, self.db, self.output / "pdfs", workers=self.download_workers)
        return await downloader.run(rows)

    def audit(self) -> None:
        write_audits(self.db_path, self.output / "audit", self.start_year, self.end_year)
