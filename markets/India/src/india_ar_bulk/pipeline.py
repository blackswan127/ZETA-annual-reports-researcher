from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings, require_terms_acknowledgement
from .db import Database
from .downloader import ArtifactDownloader
from .models import Issuer
from .source import BSESource, current_india_universe
from .util import safe_name, shard_match, is_pdf, sha256_file


def row_to_issuer(r) -> Issuer:
    return Issuer(
        r['issuer_key'],
        r['isin'] or '',
        r['name'],
        r['nse_symbol'] or '',
        r['nse_series'] or '',
        bool(r['nse_sme']),
        r['bse_scrip'] or '',
        r['bse_group'] or '',
        r['source_flags'] or '',
    )


class Pipeline:
    def __init__(self, s: Settings):
        self.s = s
        self.db = Database(s.db_path)

    def close(self):
        self.db.close()

    async def refresh_universe(self):
        require_terms_acknowledgement()
        b = BSESource(timeout=self.s.timeout, retries=self.s.retries, rps=self.s.bse_rps, proxy=self.s.proxy)
        try:
            issuers, stats = await current_india_universe(b, include_sme=self.s.include_sme)
        finally:
            await b.close()

        issuers = [i for i in issuers if shard_match(i.issuer_key, self.s.shard_count, self.s.shard_index)]
        full_dedup = stats['deduped']
        stats['shard_deduped'] = len(issuers)
        stats['full_deduped_before_shard'] = full_dedup
        self.db.replace_universe(issuers, stats)
        self.db.init_slots(self.s.start_year, self.s.end_year)
        self.db.export_audits(self.s.audit_root)
        return stats

    async def discover(self, force=False):
        require_terms_acknowledgement()
        rows = self.db.active_issuers()
        if not rows:
            await self.refresh_universe()
            rows = self.db.active_issuers()

        b = BSESource(timeout=self.s.timeout, retries=self.s.retries, rps=self.s.bse_rps, proxy=self.s.proxy)
        sem = asyncio.Semaphore(max(1, self.s.metadata_workers))
        counter = 0
        lock = asyncio.Lock()

        async def primary(r):
            nonlocal counter
            i = row_to_issuer(r)
            source = "BSE_ANN"
            if not force and self.db.discovery_done(i.issuer_key, source):
                async with lock:
                    counter += 1
                return
            async with sem:
                try:
                    if i.bse_scrip:
                        cs = await b.annual_reports(i, self.s.start_year, self.s.end_year)
                    else:
                        cs = []
                    cs = [c for c in cs if self.s.start_year <= c.fiscal_year <= self.s.end_year]
                    self.db.add_candidates(cs)
                    self.db.mark_discovery(i.issuer_key, source, 'DONE')
                except Exception as exc:
                    self.db.mark_discovery(i.issuer_key, source, 'FAILED', str(exc))
            async with lock:
                counter += 1
                if counter % 50 == 0 or counter == len(rows):
                    print(f"BSE Announcements Discovery: {counter}/{len(rows)}")

        try:
            await asyncio.gather(*(primary(r) for r in rows))
            self.db.select_best(self.s.start_year, self.s.end_year)

            if self.s.use_bse_fallback:
                missing = self.db.missing_for_bse(self.s.start_year, self.s.end_year)
                if missing:
                    print(f"BSE page fallback for uncovered slots: {len(missing)}")
                    counter2 = 0
                    async def fallback(r):
                        nonlocal counter2
                        i = row_to_issuer(r)
                        if not force and self.db.discovery_done(i.issuer_key, 'BSE_PAGE'):
                            async with lock:
                                counter2 += 1
                            return
                        async with sem:
                            try:
                                cs = await b.annual_page(i)
                                cs = [c for c in cs if self.s.start_year <= c.fiscal_year <= self.s.end_year]
                                self.db.add_candidates(cs)
                                self.db.mark_discovery(i.issuer_key, 'BSE_PAGE', 'DONE')
                            except Exception as exc:
                                self.db.mark_discovery(i.issuer_key, 'BSE_PAGE', 'FAILED', str(exc))
                        async with lock:
                            counter2 += 1
                            if counter2 % 50 == 0 or counter2 == len(missing):
                                print(f"BSE page fallback: {counter2}/{len(missing)}")
                    await asyncio.gather(*(fallback(r) for r in missing))
                    self.db.select_best(self.s.start_year, self.s.end_year)
        finally:
            await b.close()

        self.db.export_audits(self.s.audit_root)

    async def download(self, limit=None, isins: list[str] | None = None, keys: list[str] | None = None):
        require_terms_acknowledgement()
        self.db.select_best(self.s.start_year, self.s.end_year)
        rows = self.db.selected_pending()
        if isins:
            allowed_isin = {i.strip().upper() for i in isins if i}
            rows = [r for r in rows if (r.get('isin') or '').strip().upper() in allowed_isin]
        if keys:
            allowed_keys = {k.strip().upper() for k in keys if k}
            rows = [
                r for r in rows
                if (r.get('issuer_key') or '').strip().upper() in allowed_keys
                or (r.get('nse_symbol') or '').strip().upper() in allowed_keys
                or (r.get('bse_scrip') or '').strip().upper() in allowed_keys
            ]
        if limit:
            rows = rows[:limit]

        dl = ArtifactDownloader(
            workers=self.s.download_workers,
            rps=self.s.download_rps,
            timeout=self.s.timeout,
            retries=self.s.retries,
            chunk_size=self.s.chunk_size,
            proxy=self.s.proxy,
        )
        count = 0
        lock = asyncio.Lock()

        async def one(r):
            nonlocal count
            cid = r['id']
            key = r['isin'] or r['nse_symbol'] or r['bse_scrip'] or r['issuer_key']
            company = f"{safe_name(key,24)}_{safe_name(r['name'],70)}"
            dest = self.s.pdf_root / company / str(r['fiscal_year']) / f"{safe_name(key,24)}_{r['fiscal_year']}_Annual_Report.pdf"
            try:
                if dest.exists() and is_pdf(dest):
                    self.db.mark_download(cid, 'DONE', str(dest), dest.stat().st_size, sha256_file(dest))
                else:
                    p, size, digest, parts = await dl.fetch(r['url'], dest, r['file_kind'] or 'PDF')
                    self.db.mark_download(cid, 'DONE', str(p), size, digest, archive_parts=parts)
            except Exception as exc:
                self.db.mark_download(cid, 'FAILED', '', 0, '', str(exc))
            async with lock:
                count += 1
                if count % 20 == 0 or count == len(rows):
                    print(f"BSE Downloads: {count}/{len(rows)}")

        try:
            await asyncio.gather(*(one(r) for r in rows))
        finally:
            await dl.close()

        self.db.export_audits(self.s.audit_root)
