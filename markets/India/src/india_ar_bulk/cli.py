from __future__ import annotations
import argparse,asyncio
from pathlib import Path
from .config import Settings
from .pipeline import Pipeline

def parser():
    p=argparse.ArgumentParser(prog='india-ar',description='Mass annual report downloader for current NSE/BSE listed Indian companies')
    p.add_argument('--output',default='output'); p.add_argument('--start-year',type=int,default=2017); p.add_argument('--end-year',type=int,default=2025)
    p.add_argument('--metadata-workers',type=int,default=6); p.add_argument('--nse-rps',type=float,default=1.5); p.add_argument('--bse-rps',type=float,default=2.5)
    p.add_argument('--download-workers',type=int,default=8); p.add_argument('--download-rps',type=float,default=4.0); p.add_argument('--retries',type=int,default=5)
    p.add_argument('--exclude-sme',action='store_true'); p.add_argument('--no-bse-fallback',action='store_true'); p.add_argument('--deep-bse-fallback',action='store_true')
    p.add_argument('--shard-count',type=int,default=1); p.add_argument('--shard-index',type=int,default=0)
    sub=p.add_subparsers(dest='cmd',required=True); sub.add_parser('universe'); d=sub.add_parser('discover'); d.add_argument('--force',action='store_true')
    dl=sub.add_parser('download'); dl.add_argument('--limit',type=int); dl.add_argument('--isin',action='append',default=[]); dl.add_argument('--key',action='append',default=[]); sub.add_parser('audit'); sm=sub.add_parser('smoke'); sm.add_argument('--nse-symbol',default='RELIANCE'); sm.add_argument('--year',type=int,default=2025); sub.add_parser('run')
    return p

def main():
    a=parser().parse_args()
    if a.end_year<a.start_year: raise SystemExit('--end-year must be >= --start-year')
    if a.shard_count<1 or not 0<=a.shard_index<a.shard_count: raise SystemExit('invalid shard settings')
    s=Settings(Path(a.output),a.start_year,a.end_year,a.metadata_workers,a.nse_rps,a.bse_rps,a.download_workers,a.download_rps,45.0,a.retries,1024*1024,not a.exclude_sme,not a.no_bse_fallback,a.deep_bse_fallback,a.shard_count,a.shard_index)
    pipe=Pipeline(s)
    try:
        if a.cmd=='universe': print(asyncio.run(pipe.refresh_universe()))
        elif a.cmd=='discover': asyncio.run(pipe.discover(a.force))
        elif a.cmd=='download': asyncio.run(pipe.download(a.limit, a.isin or None, a.key or None))
        elif a.cmd=='audit': pipe.audit()
        elif a.cmd=='smoke': asyncio.run(pipe.smoke(a.nse_symbol,a.year))
        elif a.cmd=='run': asyncio.run(pipe.run_all())
    finally: pipe.close()
if __name__=='__main__': main()
