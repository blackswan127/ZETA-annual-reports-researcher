from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Settings, require_terms_acknowledgement
from .db import Database
from .downloader import ArtifactDownloader
from .models import Issuer
from .source import BSESource, NSESource, current_india_universe
from .util import safe_name, shard_match, is_pdf, sha256_file


def row_to_issuer(r)->Issuer:
    return Issuer(r['issuer_key'],r['isin'] or '',r['name'],r['nse_symbol'] or '',r['nse_series'] or '',bool(r['nse_sme']),r['bse_scrip'] or '',r['bse_group'] or '',r['source_flags'] or '')

class Pipeline:
    def __init__(self,s:Settings): self.s=s; self.db=Database(s.db_path)
    def close(self): self.db.close()
    async def refresh_universe(self):
        require_terms_acknowledgement(); n=NSESource(self.s.timeout,self.s.retries,self.s.nse_rps); b=BSESource(self.s.timeout,self.s.retries,self.s.bse_rps)
        try: issuers,stats=await current_india_universe(n,b,self.s.include_sme)
        finally: await n.close(); await b.close()
        issuers=[i for i in issuers if shard_match(i.issuer_key,self.s.shard_count,self.s.shard_index)]
        full_dedup=stats['deduped']; stats['shard_deduped']=len(issuers); stats['full_deduped_before_shard']=full_dedup
        self.db.replace_universe(issuers,stats); self.db.init_slots(self.s.start_year,self.s.end_year); self.db.export_audits(self.s.audit_root)
        return stats
    async def discover(self,force=False):
        require_terms_acknowledgement(); rows=self.db.active_issuers()
        if not rows: await self.refresh_universe(); rows=self.db.active_issuers()
        n=NSESource(self.s.timeout,self.s.retries,self.s.nse_rps); b=BSESource(self.s.timeout,self.s.retries,self.s.bse_rps)
        sem=asyncio.Semaphore(max(1,self.s.metadata_workers)); counter=0; lock=asyncio.Lock()
        async def primary(r):
            nonlocal counter
            i=row_to_issuer(r); source='NSE' if i.nse_symbol else 'BSE_PAGE'
            if not force and self.db.discovery_done(i.issuer_key,source):
                async with lock: counter+=1
                return
            async with sem:
                try:
                    if i.nse_symbol: cs=await n.annual_reports(i)
                    elif i.bse_scrip: cs=await b.annual_page(i)
                    else: cs=[]
                    cs=[c for c in cs if self.s.start_year<=c.fiscal_year<=self.s.end_year]
                    self.db.add_candidates(cs); self.db.mark_discovery(i.issuer_key,source,'DONE')
                except Exception as exc: self.db.mark_discovery(i.issuer_key,source,'FAILED',str(exc))
            async with lock:
                counter+=1
                if counter%100==0 or counter==len(rows): print(f'Primary discovery: {counter}/{len(rows)}')
        try:
            await asyncio.gather(*(primary(r) for r in rows)); self.db.select_best(self.s.start_year,self.s.end_year)
            if self.s.use_bse_fallback:
                missing=self.db.missing_for_bse(self.s.start_year,self.s.end_year); print(f'BSE fallback issuers with missing slots: {len(missing)}')
                counter2=0
                async def fallback(r):
                    nonlocal counter2
                    i=row_to_issuer(r)
                    if not force and self.db.discovery_done(i.issuer_key,'BSE_PAGE'):
                        async with lock: counter2+=1
                        return
                    async with sem:
                        try:
                            cs=await b.annual_page(i); cs=[c for c in cs if self.s.start_year<=c.fiscal_year<=self.s.end_year]
                            self.db.add_candidates(cs); self.db.mark_discovery(i.issuer_key,'BSE_PAGE','DONE')
                        except Exception as exc: self.db.mark_discovery(i.issuer_key,'BSE_PAGE','FAILED',str(exc))
                    async with lock:
                        counter2+=1
                        if counter2%100==0 or counter2==len(missing): print(f'BSE page fallback: {counter2}/{len(missing)}')
                await asyncio.gather(*(fallback(r) for r in missing)); self.db.select_best(self.s.start_year,self.s.end_year)
                if self.s.deep_bse_fallback:
                    remaining=self.db.missing_for_bse(self.s.start_year,self.s.end_year); print(f'Deep BSE announcement fallback issuers: {len(remaining)}')
                    for idx,r in enumerate(remaining,1):
                        i=row_to_issuer(r)
                        try:
                            cs=await b.announcement_fallback(i,self.s.start_year,self.s.end_year); cs=[c for c in cs if self.s.start_year<=c.fiscal_year<=self.s.end_year]
                            self.db.add_candidates(cs); self.db.mark_discovery(i.issuer_key,'BSE_ANN','DONE')
                        except Exception as exc: self.db.mark_discovery(i.issuer_key,'BSE_ANN','FAILED',str(exc))
                        if idx%50==0 or idx==len(remaining): print(f'Deep BSE fallback: {idx}/{len(remaining)}')
                    self.db.select_best(self.s.start_year,self.s.end_year)
        finally: await n.close(); await b.close()
        self.db.export_audits(self.s.audit_root)
    async def download(self,limit=None,isins: list[str] | None = None,keys: list[str] | None = None):
        require_terms_acknowledgement(); self.db.select_best(self.s.start_year,self.s.end_year); rows=self.db.selected_pending();
        if isins:
            allowed_isin = {i.strip().upper() for i in isins if i}
            rows = [r for r in rows if (r.get('isin') or '').strip().upper() in allowed_isin]
        if keys:
            allowed_keys = {k.strip().upper() for k in keys if k}
            rows = [r for r in rows if (r.get('issuer_key') or '').strip().upper() in allowed_keys or (r.get('nse_symbol') or '').strip().upper() in allowed_keys or (r.get('bse_scrip') or '').strip().upper() in allowed_keys]
        if limit: rows=rows[:limit]
        dl=ArtifactDownloader(self.s.download_workers,self.s.download_rps,self.s.timeout,self.s.retries,self.s.chunk_size)
        count=0; lock=asyncio.Lock()
        async def one(r):
            nonlocal count
            cid=r['id']; key=r['isin'] or r['nse_symbol'] or r['bse_scrip'] or r['issuer_key']
            company=f"{safe_name(key,24)}_{safe_name(r['name'],70)}"; dest=self.s.pdf_root/company/str(r['fiscal_year'])/f"{safe_name(key,24)}_{r['fiscal_year']}_Annual_Report.pdf"
            try:
                if dest.exists() and is_pdf(dest): self.db.mark_download(cid,'DONE',str(dest),dest.stat().st_size,sha256_file(dest))
                else:
                    p,size,digest,parts=await dl.fetch(r['url'],dest,r['file_kind'] or 'PDF'); self.db.mark_download(cid,'DONE',str(p),size,digest,archive_parts=parts)
            except Exception as exc: self.db.mark_download(cid,'FAILED',error=str(exc))
            async with lock:
                count+=1
                if count%50==0 or count==len(rows): print(f'Downloads: {count}/{len(rows)}')
        try: await asyncio.gather(*(one(r) for r in rows))
        finally: await dl.close()
        self.db.export_audits(self.s.audit_root)
    def audit(self):
        self.db.select_best(self.s.start_year,self.s.end_year); self.db.export_audits(self.s.audit_root)
        print('Universe:')
        for r in self.db.conn.execute('SELECT k,v FROM universe_stats ORDER BY k'): print(f"  {r['k']}: {r['v']}")
        print('Coverage:')
        for r in self.db.conn.execute("SELECT status,count(*) n FROM expected_slots GROUP BY status ORDER BY status"): print(f"  {r['status']}: {r['n']}")
    async def smoke(self,nse_symbol='RELIANCE',year=2025):
        require_terms_acknowledgement(); n=NSESource(self.s.timeout,self.s.retries,1.0)
        try:
            universe=await n.universe(False); match=next((x for x in universe if x.nse_symbol==nse_symbol.upper()),None)
            if not match: raise RuntimeError(f'{nse_symbol} not found in current NSE universe')
            cs=await n.annual_reports(match); cs=[c for c in cs if c.fiscal_year==year]
            print(f'{nse_symbol} FY{year} candidates: {len(cs)}')
            if not cs: raise RuntimeError('no candidate for smoke year')
            c=max(cs,key=lambda x:x.score); print(f'{c.source}: {c.title} -> {c.url}')
            # Request only first bytes where Range is honored; if ignored, stream and stop quickly.
            await n.http.rate.acquire()
            async with n.http.client.stream('GET',c.url,headers={'Range':'bytes=0-15'}) as r:
                r.raise_for_status(); first=b''
                async for chunk in r.aiter_bytes():
                    first+=chunk
                    if len(first)>=5: break
            if c.file_kind=='PDF' and not first.startswith(b'%PDF-'): raise RuntimeError('smoke target is not PDF')
            if c.file_kind=='ZIP' and not first.startswith(b'PK'): raise RuntimeError('smoke target is not ZIP')
            print('SMOKE TEST PASS')
        finally: await n.close()
    async def run_all(self):
        stats=await self.refresh_universe(); print('Current live universe:',stats); await self.discover(); await self.download(); self.audit()
