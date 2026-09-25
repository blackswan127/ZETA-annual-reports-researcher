from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .audit import export_audit_csvs
from .config import RuntimeConfig
from .db import AfricaDB
from .downloader import Downloader
from .models import Candidate, Issuer
from .sources.exchange_direct import DirectExchangeAdapter
from .sources.issuer_ir import IssuerIRCrawler
from .sources.universe import load_universe
from .zeta import build_final_path, build_staging_path

logger = logging.getLogger(__name__)


class AfricaPipeline:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.work_dir = Path(config.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.db = AfricaDB(self.work_dir / "harvest.sqlite3")
        self.output_root = Path(config.zeta_root)

    def close(self):
        self.db.close()

    def stage_universe(
        self,
        country_iso3: Optional[str] = None,
        universe_csv: Optional[Path] = None,
        limit: Optional[int] = None,
    ) -> List[Issuer]:
        issuers = load_universe(country_iso3=country_iso3, universe_csv=universe_csv, local_dir=self.work_dir.parent)
        if limit:
            issuers = issuers[:limit]
        for iss in issuers:
            self.db.upsert_issuer(iss)
            self.db.make_slots(iss.issuer_id, self.config.start_year, self.config.end_year)
        return issuers

    async def discover(
        self,
        issuers: Optional[List[Issuer]] = None,
        limit: Optional[int] = None,
    ) -> int:
        if issuers is None:
            issuers = self.db.get_issuers()
        if limit:
            issuers = issuers[:limit]

        direct_adapter = DirectExchangeAdapter(timeout=self.config.timeout, user_agent=self.config.user_agent)
        sem = asyncio.Semaphore(self.config.discovery_workers)
        total_discovered = 0

        async def scan_issuer(iss: Issuer):
            nonlocal total_discovered
            async with sem:
                try:
                    cands = await direct_adapter.discover_candidates(iss, self.config.start_year, self.config.end_year)
                    for c in cands:
                        self.db.add_candidate(c)
                        total_discovered += 1
                except Exception as e:
                    self.db.record_event("DISCOVERY_ERROR", iss.issuer_id, details=str(e))

        try:
            await asyncio.gather(*(scan_issuer(i) for i in issuers))
        finally:
            await direct_adapter.close()

        return total_discovered

    async def download(
        self,
        limit: Optional[int] = None,
        repair: bool = False,
    ) -> int:
        selected_rows = self.db.get_selected_candidates(repair=repair)
        if limit:
            selected_rows = selected_rows[:limit]

        downloader = Downloader(
            workers=self.config.download_workers,
            rps=self.config.download_rps,
            timeout=self.config.timeout,
            retries=self.config.retries,
            user_agent=self.config.user_agent,
        )
        total_downloaded = 0

        async def download_one(row):
            nonlocal total_downloaded
            cand_id = row["candidate_id"]
            iss_id = row["issuer_id"]
            iso3 = row["country_iso3"]
            mic = row["exchange_mic"]
            ticker = row["ticker"]
            fy = row["fiscal_year"]
            url = row["direct_pdf_url"] or row["source_url"]
            lei = row["lei"] or ""
            isin = row["isin"] or ""

            # Check if canonical ZETA path can be formed
            final_target = build_final_path(self.output_root, iso3, mic, lei, isin, ticker, fy)
            if final_target is not None:
                dest = final_target
                target_state = "DONE"
            else:
                dest = build_staging_path(self.work_dir / "staging", iso3, mic, ticker, fy)
                target_state = "IDENTITY_MISSING"

            if dest.exists():
                valid, pages, _ = downloader.validate_pdf(dest, min_bytes=self.config.min_pdf_bytes)
                if valid:
                    self.db.mark_download(
                        cand_id, target_state, attempts=1,
                        bytes_downloaded=dest.stat().st_size, http_status=200,
                        local_path=str(dest),
                    )
                    self.db.update_slot_status(iss_id, fy, target_state)
                    total_downloaded += 1
                    return

            try:
                res = await downloader.get(url, dest, min_bytes=self.config.min_pdf_bytes)
                self.db.mark_download(
                    cand_id, target_state, attempts=1,
                    bytes_downloaded=res["bytes"], http_status=res["http_status"],
                    sha256=res["sha256"], local_path=str(dest),
                )
                self.db.update_slot_status(iss_id, fy, target_state)
                total_downloaded += 1
            except Exception as e:
                self.db.mark_download(cand_id, "FAILED", attempts=1, error=str(e), local_path=str(dest))
                self.db.update_slot_status(iss_id, fy, "FAILED")

        try:
            await asyncio.gather(*(download_one(r) for r in selected_rows))
        finally:
            await downloader.close()

        return total_downloaded

    def audit(self) -> Dict[str, Any]:
        audit_dir = self.work_dir / "audit"
        export_audit_csvs(self.db.conn, audit_dir)
        return self.db.get_coverage_stats()

    async def run(
        self,
        country_iso3: Optional[str] = None,
        universe_csv: Optional[Path] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        issuers = self.stage_universe(country_iso3=country_iso3, universe_csv=universe_csv, limit=limit)
        await self.discover(issuers=issuers)
        await self.download()
        return self.audit()
