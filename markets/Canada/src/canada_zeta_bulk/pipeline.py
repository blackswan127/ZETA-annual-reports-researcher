from __future__ import annotations

import asyncio
import csv
import os
import shutil
from pathlib import Path

from .config import Settings
from .db import Database
from .downloader import Downloader
from .identity import IdentityResolver, load_overrides
from .issuer_sites import IssuerSiteCrawler
from .models import Candidate, Issuer
from .sedar_manifest import import_candidates as import_sedar_candidates
from .universe import fetch_latest_tmx_list, parse_universe_file
from .util import in_shard
from .validator import validate_pdf
from .zeta import final_path, identifiers_complete, staging_path

class Pipeline:
    def __init__(self, settings: Settings):
        self.s=settings
        self.s.work_dir.mkdir(parents=True,exist_ok=True)
        self.s.audit_dir.mkdir(parents=True,exist_ok=True)
        self.s.staging_dir.mkdir(parents=True,exist_ok=True)
        self.db=Database(self.s.db_path)

    def close(self): self.db.close()

    def _issuer_from_row(self,r) -> Issuer:
        d = dict(r)
        return Issuer(
            issuer_key=d.get("issuer_key",""),name=d.get("name",""),ticker=d.get("ticker",""),exchange_mic=d.get("exchange_mic",""),
            security_type=d.get("security_type") or "",industry=d.get("industry") or "",listing_date=d.get("listing_date") or "",
            website=d.get("website") or "",isin=d.get("isin") or "",lei=d.get("lei") or "",sedar_profile=d.get("sedar_profile") or "",
            active=bool(d.get("active",1)),eligible=bool(d.get("eligible",1)),source=d.get("source") or "",
        )

    async def universe(self, universe_file: Path | None=None, include_nex: bool=False, fetch_tmx: bool=False) -> int:
        if universe_file:
            issuers=parse_universe_file(universe_file,include_nex)
            source_ref=str(universe_file)
        elif fetch_tmx:
            issuers,source_ref=await fetch_latest_tmx_list(self.s.timeout,include_nex)
        else:
            raise RuntimeError("Provide --universe-file with the official TSX/TSXV issuer list, or use --fetch-tmx if authorized.")
        n=self.db.upsert_issuers(issuers)
        slots=self.db.init_slots(self.s.start_year,self.s.end_year,self.s.language)
        self.db.log("INFO","universe",f"loaded={n}; slots={slots}; source={source_ref}")
        self.db.export_audits(self.s.audit_dir)
        return n

    def identity_overrides(self,path: Path) -> int:
        n=self.db.apply_identity_overrides(load_overrides(path))
        self.db.log("INFO","identity",f"overrides_applied={n}; file={path}")
        self.db.export_audits(self.s.audit_dir); return n

    async def identity_enrich(self,use_gleif: bool=True,use_openfigi: bool=False,openfigi_key: str="",limit: int|None=None) -> dict[str,int]:
        rows=list(self.db.unresolved_identity())
        rows=[r for r in rows if in_shard(r["issuer_key"],self.s.shard_count,self.s.shard_index)]
        if limit: rows=rows[:limit]
        resolver=IdentityResolver(self.s.timeout,0.7,openfigi_key)
        stats={"lei":0,"isin":0,"unresolved":0}
        try:
            for idx,r in enumerate(rows,1):
                updates=[]; vals=[]
                if use_gleif and not (r["lei"] or ""):
                    try:
                        lei,conf,note=await resolver.gleif_lei(r["name"])
                        if lei:
                            updates.append("lei=?"); vals.append(lei); stats["lei"]+=1
                        else:
                            self.db.conn.execute("INSERT OR IGNORE INTO identifier_candidates(issuer_key,kind,value,source,confidence,status,note) VALUES(?,?,?,?,?,'CANDIDATE',?)",(r["issuer_key"],"LEI","","GLEIF",conf,note))
                    except Exception as exc: self.db.log("WARN","identity_gleif",str(exc),r["issuer_key"])
                if use_openfigi and not (r["isin"] or ""):
                    try:
                        isin,conf,note=await resolver.openfigi_isin(r["ticker"],r["exchange_mic"])
                        if isin:
                            updates.append("isin=?"); vals.append(isin); stats["isin"]+=1
                        else: self.db.log("WARN","identity_openfigi",note,r["issuer_key"])
                    except Exception as exc: self.db.log("WARN","identity_openfigi",str(exc),r["issuer_key"])
                if updates:
                    vals.append(r["issuer_key"]); self.db.conn.execute(f"UPDATE issuers SET {','.join(updates)} WHERE issuer_key=?",vals); self.db.conn.commit()
                if idx%100==0 or idx==len(rows): print(f"Identity: {idx}/{len(rows)}")
        finally: await resolver.close()
        stats["unresolved"]=len(self.db.unresolved_identity())
        self.db.export_audits(self.s.audit_dir); return stats

    def import_sedar(self,path: Path) -> tuple[int,int]:
        issuer_rows=[dict(r) for r in self.db.conn.execute("SELECT * FROM issuers WHERE active=1 AND eligible=1")]
        candidates,unmatched=import_sedar_candidates(path,issuer_rows,self.s.start_year,self.s.end_year)
        n=self.db.add_candidates(candidates)
        out=self.s.audit_dir/"sedar_unmatched.csv"
        with out.open("w",newline="",encoding="utf-8-sig") as fh:
            if unmatched:
                w=csv.DictWriter(fh,fieldnames=unmatched[0].keys()); w.writeheader(); w.writerows(unmatched)
            else: csv.writer(fh).writerow([])
        self.db.log("INFO","sedar_import",f"candidates={n}; unmatched={len(unmatched)}; file={path}")
        self.resolve(); return n,len(unmatched)

    async def discover_issuer_sites(self,missing_only: bool=False,limit: int|None=None) -> int:
        if missing_only:
            keys=sorted({r["issuer_key"] for r in self.db.missing_slots()})
            qmarks=",".join("?" for _ in keys) if keys else "''"
            rows=self.db.conn.execute(f"SELECT * FROM issuers WHERE issuer_key IN ({qmarks})",keys).fetchall() if keys else []
        else:
            rows=self.db.conn.execute("SELECT * FROM issuers WHERE active=1 AND eligible=1 AND COALESCE(website,'')<>'' ORDER BY exchange_mic,ticker").fetchall()
        rows=[r for r in rows if in_shard(r["issuer_key"],self.s.shard_count,self.s.shard_index)]
        if limit: rows=rows[:limit]
        crawler=IssuerSiteCrawler(self.s.timeout,self.s.metadata_rps,self.s.max_site_pages,self.s.max_site_depth,self.s.obey_robots)
        sem=asyncio.Semaphore(max(1,self.s.metadata_workers)); total=0; lock=asyncio.Lock()
        async def one(r):
            nonlocal total
            issuer=self._issuer_from_row(r)
            async with sem:
                try:
                    cands=await crawler.discover(issuer,self.s.start_year,self.s.end_year)
                    self.db.add_candidates(cands); self.db.source_state(issuer.issuer_key,"ISSUER_SITE","DONE")
                    self.db.set_source_profile(issuer.issuer_key,"ISSUER_SITE",issuer.website,"OK" if cands else "EMPTY",notes=f"candidates={len(cands)}")
                except Exception as exc:
                    self.db.source_state(issuer.issuer_key,"ISSUER_SITE","FAILED",str(exc)); self.db.set_source_profile(issuer.issuer_key,"ISSUER_SITE",issuer.website,"FAILED",str(exc))
                async with lock:
                    total+=1
                    if total%50==0 or total==len(rows): print(f"Issuer-site discovery: {total}/{len(rows)}")
        try: await asyncio.gather(*(one(r) for r in rows))
        finally: await crawler.close()
        self.resolve(); return len(rows)

    def resolve(self) -> None:
        self.db.select_best(self.s.start_year,self.s.end_year,self.s.language,self.s.include_french)
        self.db.export_audits(self.s.audit_dir)

    async def download(self,limit: int|None=None, keys: list[str] | None = None, tickers: list[str] | None = None) -> int:
        rows=[r for r in self.db.pending_downloads() if in_shard(r["issuer_key"],self.s.shard_count,self.s.shard_index)]
        if keys:
            allowed_keys = {k.strip().upper() for k in keys if k}
            rows = [r for r in rows if r["issuer_key"].strip().upper() in allowed_keys or (dict(r).get("ticker") or "").strip().upper() in allowed_keys]
        if tickers:
            allowed_tickers = {t.strip().upper() for t in tickers if t}
            rows = [r for r in rows if (dict(r).get("ticker") or "").strip().upper() in allowed_tickers]
        if limit: rows=rows[:limit]
        dl=Downloader(self.s.download_workers,self.s.download_rps,self.s.timeout,self.s.retries,self.s.chunk_size)
        done=0; lock=asyncio.Lock()
        async def one(r):
            nonlocal done
            issuer=self._issuer_from_row(r)
            fy=int(r["fiscal_year"]); lang=r["language"] or self.s.language
            final=final_path(self.s.zeta_root,issuer,fy,"AR",lang) if identifiers_complete(issuer) else None
            dest=final if final else staging_path(self.s.staging_dir,issuer,fy,lang)
            try:
                if dest.exists():
                    val=validate_pdf(dest,fy,self.s.min_pdf_bytes,self.s.min_pages)
                    if val.status!="PASS": dest.unlink(missing_ok=True); await dl.download(r["url"],dest); val=validate_pdf(dest,fy,self.s.min_pdf_bytes,self.s.min_pages)
                else:
                    await dl.download(r["url"],dest); val=validate_pdf(dest,fy,self.s.min_pdf_bytes,self.s.min_pages)
                if val.status!="PASS": raise RuntimeError(f"validation_failed:{val.note}")
                self.db.mark_download(int(r["id"]),"DONE",staging_path="" if final else str(dest),final_path=str(final) if final else "",bytes_=val.bytes,pages=val.pages,sha256=val.sha256,validation_status=val.status,semantic_status=val.semantic_status)
            except Exception as exc:
                self.db.mark_download(int(r["id"]),"FAILED",staging_path=str(dest) if not final else "",final_path=str(final) if final else "",error=str(exc))
            async with lock:
                done+=1
                if done%25==0 or done==len(rows): print(f"Downloads: {done}/{len(rows)}")
        try: await asyncio.gather(*(one(r) for r in rows))
        finally: await dl.close()
        self.db.export_audits(self.s.audit_dir); return len(rows)

    def finalize_staging(self) -> int:
        rows=self.db.conn.execute("""SELECT d.candidate_id,d.staging_path,c.fiscal_year,c.language,i.* FROM downloads d
            JOIN candidates c ON c.id=d.candidate_id JOIN issuers i USING(issuer_key)
            WHERE d.status='DONE' AND COALESCE(d.staging_path,'')<>''""").fetchall()
        moved=0
        for r in rows:
            issuer=self._issuer_from_row(r)
            if not identifiers_complete(issuer): continue
            src=Path(r["staging_path"]); dest=final_path(self.s.zeta_root,issuer,int(r["fiscal_year"]),"AR",r["language"] or self.s.language)
            if not src.exists(): continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.exists():
                # Hash equality is checked by validation database; avoid duplicate writes.
                src.unlink(missing_ok=True)
            else: shutil.move(str(src),str(dest))
            self.db.conn.execute("UPDATE downloads SET final_path=?,staging_path='' WHERE candidate_id=?",(str(dest),r["candidate_id"])); self.db.conn.commit(); moved+=1
        self.db.export_audits(self.s.audit_dir); return moved

    async def repair_missing(self,site_limit: int|None=None) -> None:
        # Deliberately repairs only unresolved slots: no re-harvesting completed work.
        await self.discover_issuer_sites(missing_only=True,limit=site_limit)
        await self.download()
        self.audit()

    def audit(self) -> dict[str,int]:
        self.resolve(); stats=self.db.summary()
        print("ZETA coverage:")
        for k,v in sorted(stats.items()): print(f"  {k}: {v}")
        return stats
