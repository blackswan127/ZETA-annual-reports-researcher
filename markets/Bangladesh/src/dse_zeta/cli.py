import argparse,os
from pathlib import Path
from .config import RuntimeConfig
from .pipeline import Pipeline
from .sources.dse_public import parse_company_page,parse_financial_page
BANNER="DSE ZETA Annual Reports Bulk Downloader v1.0"
def cfg(a):return RuntimeConfig(a.start_year,a.end_year,a.discovery_workers,a.download_workers,a.delay,a.timeout,a.retries,a.min_pdf_bytes)
def parser():
    p=argparse.ArgumentParser(description=BANNER);p.add_argument("--work",default="work");p.add_argument("--zeta-root",default="GLOBAL_SUSTAINABILITY_DATABASE");p.add_argument("--start-year",type=int,default=2017);p.add_argument("--end-year",type=int,default=2025);p.add_argument("--discovery-workers",type=int,default=5);p.add_argument("--download-workers",type=int,default=8);p.add_argument("--shard-count",type=int,default=1);p.add_argument("--shard-index",type=int,default=0);p.add_argument("--delay",type=float,default=.35);p.add_argument("--timeout",type=int,default=45);p.add_argument("--retries",type=int,default=5);p.add_argument("--min-pdf-bytes",type=int,default=8000)
    sp=p.add_subparsers(dest="cmd",required=True);u=sp.add_parser("universe");u.add_argument("--identity-overrides");u.add_argument("--gleif",action="store_true");u.add_argument("--universe-csv");ia=sp.add_parser("ingest-authorized");ia.add_argument("manifest");sp.add_parser("discover-dse-links");sp.add_parser("discover-ir");dl=sp.add_parser("download");dl.add_argument("--ticker",action="append",default=[]);dl.add_argument("--limit",type=int);sp.add_parser("audit");sp.add_parser("repair-missing");r=sp.add_parser("run");r.add_argument("--identity-overrides");r.add_argument("--gleif",action="store_true");r.add_argument("--authorized-manifest");r.add_argument("--universe-csv");sp.add_parser("smoke-test");return p
def main(argv=None):
    a=parser().parse_args(argv);print(BANNER)
    if a.cmd=="smoke-test":
        import requests
        if os.environ.get("DSE_ACKNOWLEDGE_TERMS")!="1":print("FAIL: set DSE_ACKNOWLEDGE_TERMS=1 after reviewing DSE terms/permissions");return 2
        h=requests.get("https://dse.ternary.com.bd/company/UNITEDFIN",timeout=30,headers={"User-Agent":"Mozilla/5.0"}).text;i=parse_company_page(h,"UNITEDFIN")
        if "Equity" not in i.instrument_type or not i.financials_url:print("FAIL: DSE company profile parser");return 3
        fh=requests.get(i.financials_url,timeout=30,headers={"User-Agent":"Mozilla/5.0"}).text;c=parse_financial_page(fh,"UNITEDFIN",i.financials_url,2017,2025)
        print(f"SMOKE TEST PASS: DSE profile reachable; financial source={i.financials_url}; annual candidates={len(c)}");return 0
    P=Pipeline(Path(a.work),Path(a.zeta_root),cfg(a))
    try:
        if a.cmd=="universe":print("current DSE equity issuers:",P.universe(a.identity_overrides,a.gleif,a.universe_csv,a.shard_count,a.shard_index))
        elif a.cmd=="ingest-authorized":P.ingest_authorized(a.manifest)
        elif a.cmd=="discover-dse-links":P.discover_financial_links()
        elif a.cmd=="discover-ir":P.discover_ir_missing()
        elif a.cmd=="download":P.download(tickers=a.ticker or None, limit=a.limit)
        elif a.cmd=="audit":P.audit()
        elif a.cmd=="repair-missing":P.discover_financial_links();P.discover_ir_missing();P.download();P.audit()
        elif a.cmd=="run":
            P.universe(a.identity_overrides,a.gleif,a.universe_csv,a.shard_count,a.shard_index)
            if a.authorized_manifest:P.ingest_authorized(a.authorized_manifest)
            P.discover_financial_links();P.discover_ir_missing();P.download();P.audit()
        return 0
    finally:P.close()
if __name__=="__main__":raise SystemExit(main())
