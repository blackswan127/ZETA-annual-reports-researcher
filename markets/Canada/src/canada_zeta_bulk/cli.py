from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .config import Settings
from .pipeline import Pipeline


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="canada-zeta-ar",description="ZETA-SOP Canada TSX/TSXV annual-report bulk harvester")
    p.add_argument("--work",type=Path,default=Path("work"))
    p.add_argument("--zeta-root",type=Path,default=Path(os.environ.get("ZETA_ROOT","GLOBAL_SUSTAINABILITY_DATABASE")))
    p.add_argument("--start-year",type=int,default=2017); p.add_argument("--end-year",type=int,default=2025)
    p.add_argument("--metadata-workers",type=int,default=8); p.add_argument("--download-workers",type=int,default=8)
    p.add_argument("--metadata-rps",type=float,default=2.0); p.add_argument("--download-rps",type=float,default=4.0)
    p.add_argument("--timeout",type=float,default=60); p.add_argument("--retries",type=int,default=5)
    p.add_argument("--include-fr",action="store_true"); p.add_argument("--no-robots",action="store_true")
    p.add_argument("--shard-count",type=int,default=1); p.add_argument("--shard-index",type=int,default=0)
    sub=p.add_subparsers(dest="cmd",required=True)
    q=sub.add_parser("universe"); q.add_argument("--universe-file",type=Path); q.add_argument("--fetch-tmx",action="store_true"); q.add_argument("--include-nex",action="store_true")
    q=sub.add_parser("identity-override"); q.add_argument("file",type=Path)
    q=sub.add_parser("identity-enrich"); q.add_argument("--openfigi",action="store_true"); q.add_argument("--openfigi-key",default=os.environ.get("OPENFIGI_API_KEY","")); q.add_argument("--limit",type=int)
    q=sub.add_parser("import-sedar"); q.add_argument("file",type=Path)
    q=sub.add_parser("discover-sites"); q.add_argument("--missing-only",action="store_true"); q.add_argument("--limit",type=int)
    sub.add_parser("resolve")
    q=sub.add_parser("download"); q.add_argument("--limit",type=int); q.add_argument("--key",action="append",default=[]); q.add_argument("--ticker",action="append",default=[])
    sub.add_parser("finalize")
    q=sub.add_parser("repair-missing"); q.add_argument("--limit",type=int)
    sub.add_parser("audit")
    q=sub.add_parser("run"); q.add_argument("--universe-file",type=Path,required=True); q.add_argument("--identity-overrides",type=Path); q.add_argument("--sedar-manifest",type=Path); q.add_argument("--skip-sites",action="store_true"); q.add_argument("--include-nex",action="store_true")
    return p


def settings(a) -> Settings:
    return Settings(work_dir=a.work,zeta_root=a.zeta_root,start_year=a.start_year,end_year=a.end_year,include_french=a.include_fr,
        metadata_workers=a.metadata_workers,download_workers=a.download_workers,metadata_rps=a.metadata_rps,download_rps=a.download_rps,
        timeout=a.timeout,retries=a.retries,obey_robots=not a.no_robots,shard_count=a.shard_count,shard_index=a.shard_index)

async def amain(a) -> None:
    pipe=Pipeline(settings(a))
    try:
        if a.cmd=="universe": print(f"Loaded {await pipe.universe(a.universe_file,a.include_nex,a.fetch_tmx)} issuers")
        elif a.cmd=="identity-override": print(f"Applied {pipe.identity_overrides(a.file)} identity overrides")
        elif a.cmd=="identity-enrich": print(await pipe.identity_enrich(True,a.openfigi,a.openfigi_key,a.limit))
        elif a.cmd=="import-sedar": print("SEDAR manifest:",pipe.import_sedar(a.file))
        elif a.cmd=="discover-sites": print(f"Scanned {await pipe.discover_issuer_sites(a.missing_only,a.limit)} issuer sites")
        elif a.cmd=="resolve": pipe.resolve()
        elif a.cmd=="download": print(f"Processed {await pipe.download(a.limit, a.key or None, a.ticker or None)} downloads")
        elif a.cmd=="finalize": print(f"Moved {pipe.finalize_staging()} staged PDFs into final ZETA paths")
        elif a.cmd=="repair-missing": await pipe.repair_missing(a.limit)
        elif a.cmd=="audit": pipe.audit()
        elif a.cmd=="run":
            await pipe.universe(a.universe_file,a.include_nex,False)
            if a.identity_overrides: pipe.identity_overrides(a.identity_overrides)
            if a.sedar_manifest: pipe.import_sedar(a.sedar_manifest)
            if not a.skip_sites: await pipe.discover_issuer_sites()
            pipe.resolve(); await pipe.download(); pipe.finalize_staging(); pipe.audit()
    finally: pipe.close()

def main() -> None:
    a=parser().parse_args()
    if a.shard_index<0 or a.shard_index>=a.shard_count: raise SystemExit("--shard-index must be 0..shard-count-1")
    asyncio.run(amain(a))
