from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from .db import DB
from .http import Http
from .sources.nzx_public import NZXPublic
from .sources.authorized_manifest import load_authorized_manifest
from .sources.issuer_ir import discover_ir
from .identity import load_overrides,apply_override,gleif_exact,load_universe_csv
from .downloader import fetch_candidate
from .audit import export

class Pipeline:
    def __init__(self,work:Path,zeta_root:Path,cfg):
        self.work=Path(work); self.root=Path(zeta_root); self.work.mkdir(parents=True,exist_ok=True)
        self.db=DB(self.work/"harvest.sqlite3"); self.http=Http(cfg.request_delay,cfg.timeout,cfg.max_retries); self.cfg=cfg
    def close(self): self.db.close()
    def universe(self,overrides=None,gleif=False,universe_csv=None,shard_count=1,shard_index=0):
        if universe_csv:
            from .sources.nzx_public import shard_accept
            rows=[x for x in load_universe_csv(Path(universe_csv)) if shard_accept(x.ticker,shard_count,shard_index)]
        else:
            rows=NZXPublic(self.http).current_universe(shard_count,shard_index)
        ovs=load_overrides(overrides) if overrides else {}
        for i in rows:
            i=apply_override(i,ovs.get(i.ticker,{}))
            if gleif and not i.lei:
                try:i.lei=gleif_exact(self.http,i)
                except Exception:pass
            self.db.upsert_issuer(i)
        self.db.ensure_slots(self.cfg.start_year,self.cfg.end_year); return len(rows)
    def ingest_authorized(self,path):
        for c in load_authorized_manifest(Path(path),self.cfg.start_year,self.cfg.end_year): self.db.add_candidate(c)
        self.db.select_best()
    def discover_documents(self):
        src=NZXPublic(self.http); rows=self.db.conn.execute("SELECT ticker FROM issuers WHERE current=1 ORDER BY ticker").fetchall()
        def one(t): return src.documents(t,self.cfg.start_year,self.cfg.end_year)
        with ThreadPoolExecutor(max_workers=self.cfg.discovery_workers) as ex:
            fut={ex.submit(one,r['ticker']):r['ticker'] for r in rows}
            for f in as_completed(fut):
                t=fut[f]
                try:
                    for c in f.result(): self.db.add_candidate(c)
                except Exception as e:self.db.event("WARN","documents_failed",{"ticker":t,"error":str(e)})
        self.db.select_best()
    def discover_ir_missing(self):
        rows=self.db.conn.execute("SELECT DISTINCT i.ticker,i.website FROM expected_slots s JOIN issuers i USING(ticker) WHERE s.status='MISSING' AND i.website<>''").fetchall()
        def one(r): return discover_ir(self.http,r['ticker'],r['website'],self.cfg.start_year,self.cfg.end_year)
        with ThreadPoolExecutor(max_workers=max(1,self.cfg.discovery_workers//2)) as ex:
            fut={ex.submit(one,r):r['ticker'] for r in rows}
            for f in as_completed(fut):
                t=fut[f]
                try:
                    for c in f.result(): self.db.add_candidate(c)
                except Exception as e:self.db.event("WARN","ir_failed",{"ticker":t,"error":str(e)})
        self.db.select_best()
    def download(self, tickers: list[str] | None = None, limit: int | None = None):
        rows=self.db.selected()
        if tickers:
            allowed = {t.strip().upper() for t in tickers if t}
            rows = [r for r in rows if r['ticker'].strip().upper() in allowed]
        if limit:
            rows = rows[:limit]
        def one(r): return fetch_candidate(self.http,r,self.root,self.work/"staging",self.cfg.min_pdf_bytes)
        with ThreadPoolExecutor(max_workers=self.cfg.download_workers) as ex:
            fut={ex.submit(one,r):r for r in rows}
            for f in as_completed(fut):
                r=fut[f]
                try:
                    p,h,n,complete=f.result(); self.db.mark_done(r['ticker'],r['fiscal_year'],r['id'],p,h,n)
                    if not complete:self.db.event("WARN","staged_identity_missing",{"ticker":r['ticker'],"fy":r['fiscal_year'],"path":str(p)})
                except Exception as e:self.db.mark_failed(r['ticker'],r['fiscal_year'],r['id'],str(e))
    def audit(self): export(self.db,self.work/"audit")
