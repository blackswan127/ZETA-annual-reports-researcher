from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import PSEClient
from .config import Settings
from .contract import PSEIssuer, PSESlot
from .discovery import DiscoveryEngine
from .downloader import Downloader
from .universe import UniverseManager


class HarvestPipeline:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self.client = PSEClient(self.settings)
        self.universe_mgr = UniverseManager(self.settings, self.client)
        self.discovery_engine = DiscoveryEngine(self.client)
        self.downloader = Downloader(self.client, self.settings)
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        self.settings.state_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.settings.state_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS harvest_slots (
                    slot_id TEXT PRIMARY KEY,
                    issuer_id TEXT NOT NULL,
                    fiscal_year INTEGER NOT NULL,
                    report_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    destination_path TEXT,
                    sha256 TEXT,
                    page_count INTEGER,
                    file_size_bytes INTEGER,
                    reason TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def _save_slot_state(self, slot: PSESlot) -> None:
        with sqlite3.connect(self.settings.state_db) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO harvest_slots (
                    slot_id, issuer_id, fiscal_year, report_type, status,
                    destination_path, sha256, page_count, file_size_bytes, reason, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                f"PHL:{slot.issuer_id}:FY{slot.fiscal_year}:{slot.report_type}",
                slot.issuer_id,
                slot.fiscal_year,
                slot.report_type,
                slot.status,
                slot.destination_path,
                slot.sha256,
                slot.page_count,
                slot.file_size_bytes,
                slot.reason,
            ))
            conn.commit()

    async def close(self) -> None:
        await self.client.close()

    async def run(
        self,
        fiscal_years: List[int],
        report_types: List[str],
        tickers: Optional[List[str]] = None,
        max_issuers: Optional[int] = None,
    ) -> List[PSESlot]:
        t0 = time.time()
        print(f"[Philippines] Fetching PSE active universe...")
        universe = await self.universe_mgr.fetch_universe(refresh=False)
        print(f"[Philippines] Active universe loaded: {len(universe)} listed issuers.")

        if tickers:
            selected_tickers = {t.strip().upper() for t in tickers}
            issuers = [i for i in universe if i.ticker in selected_tickers]
        else:
            issuers = universe

        if max_issuers and max_issuers > 0:
            issuers = issuers[:max_issuers]

        print(f"[Philippines] Starting harvest for {len(issuers)} issuers | FY: {fiscal_years} | Types: {report_types}")
        semaphore = asyncio.Semaphore(self.settings.download_workers)
        all_slots: List[PSESlot] = []

        async def process_issuer(issuer: PSEIssuer) -> List[PSESlot]:
            async with semaphore:
                issuer_slots: List[PSESlot] = []
                try:
                    filings = await self.discovery_engine.discover_issuer_filings(
                        cmpy_id=issuer.pse_company_id,
                        ticker=issuer.ticker,
                        from_date=f"{min(fiscal_years)}-01-01",
                        to_date="2026-06-30",
                    )
                except Exception as e:
                    filings = []

                # Group candidate attachments by (fiscal_year, report_type)
                # AR requires AR_FULL; SR requires SR
                candidates_by_fy_and_type: Dict[tuple[int, str], Any] = {}
                for filing in filings:
                    fy = filing.fiscal_year
                    if not fy or fy not in fiscal_years:
                        continue
                    for att in filing.attachments:
                        if att.classification == "AR_FULL":
                            k = (fy, "AR")
                            if k not in candidates_by_fy_and_type:
                                candidates_by_fy_and_type[k] = att
                        elif att.classification == "SR":
                            k = (fy, "SR")
                            if k not in candidates_by_fy_and_type:
                                candidates_by_fy_and_type[k] = att

                for fy in fiscal_years:
                    for r_type in report_types:
                        att = candidates_by_fy_and_type.get((fy, r_type))
                        if not att:
                            slot = PSESlot(
                                issuer_id=issuer.ticker,
                                fiscal_year=fy,
                                report_type=r_type,
                                status="UNRESOLVED",
                                reason=f"No matching {r_type} filing found on PSE EDGE",
                            )
                            self._save_slot_state(slot)
                            issuer_slots.append(slot)
                            continue

                        status, reason, final_p, sha, pages, sz = await self.downloader.download_and_promote(
                            download_url=att.download_url,
                            ticker=issuer.ticker,
                            fiscal_year=fy,
                            lei=issuer.lei,
                            isin=issuer.isin,
                            report_type=r_type,
                        )

                        slot = PSESlot(
                            issuer_id=issuer.ticker,
                            fiscal_year=fy,
                            report_type=r_type,
                            status=status,
                            selected_attachment_id=att.attachment_id,
                            destination_path=str(final_p) if final_p else None,
                            sha256=sha,
                            page_count=pages,
                            file_size_bytes=sz,
                            reason=reason,
                        )
                        self._save_slot_state(slot)
                        issuer_slots.append(slot)
                return issuer_slots

        tasks = [process_issuer(iss) for iss in issuers]
        batch_results = await asyncio.gather(*tasks)
        for r_list in batch_results:
            all_slots.extend(r_list)

        elapsed = time.time() - t0
        promoted = sum(1 for s in all_slots if s.status == "PROMOTED")
        staged = sum(1 for s in all_slots if s.status == "STAGED_UNRESOLVED_IDENTITY")
        unresolved = sum(1 for s in all_slots if s.status == "UNRESOLVED")
        failed = sum(1 for s in all_slots if s.status == "FAILED")

        print("\n" + "=" * 70)
        print(f"PHILIPPINES PSE HARVEST RUN AUDIT")
        print("=" * 70)
        print(f"Total Target Slots:        {len(all_slots)}")
        print(f"Promoted to ZETA Corpus:   {promoted}")
        print(f"Staged (Missing Identity): {staged}")
        print(f"Unresolved Slots:          {unresolved}")
        print(f"Failed Slots:              {failed}")
        print(f"Elapsed Time:              {elapsed:.2f}s")
        if elapsed > 0:
            print(f"Slot Throughput:           {len(all_slots) / elapsed:.2f} slots/sec")
        print("=" * 70 + "\n")

        return all_slots
