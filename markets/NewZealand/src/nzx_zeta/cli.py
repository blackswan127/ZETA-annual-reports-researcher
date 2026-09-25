import argparse, os, sys
from pathlib import Path
from .config import RuntimeConfig
from .pipeline import Pipeline
from .sources.nzx_public import parse_documents_page, parse_company_page

BANNER="NZX ZETA Annual Reports Bulk Downloader v1.0"

def cfg(a): return RuntimeConfig(a.start_year,a.end_year,a.discovery_workers,a.download_workers,a.delay,a.timeout,a.retries,a.min_pdf_bytes)

def parser():
    p=argparse.ArgumentParser(description=BANNER); p.add_argument("--work",default="work"); p.add_argument("--zeta-root",default="GLOBAL_SUSTAINABILITY_DATABASE")
    p.add_argument("--start-year",type=int,default=2017); p.add_argument("--end-year",type=int,default=2025); p.add_argument("--discovery-workers",type=int,default=4); p.add_argument("--download-workers",type=int,default=6)
    p.add_argument("--shard-count",type=int,default=1); p.add_argument("--shard-index",type=int,default=0); p.add_argument("--delay",type=float,default=.35); p.add_argument("--timeout",type=int,default=45); p.add_argument("--retries",type=int,default=5); p.add_argument("--min-pdf-bytes",type=int,default=8000)
    sp=p.add_subparsers(dest="cmd",required=True)
    u=sp.add_parser("universe"); u.add_argument("--identity-overrides"); u.add_argument("--gleif",action="store_true"); u.add_argument("--universe-csv")
    ia=sp.add_parser("ingest-authorized"); ia.add_argument("manifest")
    sp.add_parser("discover-documents"); sp.add_parser("discover-ir")
    dl=sp.add_parser("download"); dl.add_argument("--ticker",action="append",default=[]); dl.add_argument("--limit",type=int); sp.add_parser("audit"); sp.add_parser("repair-missing")
    r=sp.add_parser("run"); r.add_argument("--identity-overrides"); r.add_argument("--gleif",action="store_true"); r.add_argument("--authorized-manifest"); r.add_argument("--universe-csv")
    sp.add_parser("smoke-test")
    return p

def main(argv=None):
    a=parser().parse_args(argv); print(BANNER)
    if a.cmd=="smoke-test":
        import requests
        if os.environ.get("NZX_ACKNOWLEDGE_TERMS")!="1": print("FAIL: set NZX_ACKNOWLEDGE_TERMS=1 after reviewing NZX terms"); return 2
        u="https://www.nzx.com/companies/NZX/documents"; h=requests.get(u,timeout=30,headers={"User-Agent":"Mozilla/5.0"}).text
        c=parse_documents_page(h,"NZX",2017,2025)
        if not any(x.fiscal_year==2025 for x in c): print("FAIL: could not find NZX FY2025 annual report"); return 3
        p=requests.get("https://www.nzx.com/companies/NZX",timeout=30,headers={"User-Agent":"Mozilla/5.0"}).text; i=parse_company_page(p,"NZX")
        if i.isin!="NZNZXE0001S7": print("FAIL: company profile/ISIN parse"); return 4
        print("SMOKE TEST PASS: NZX profile + historical annual report discovery reachable"); return 0
    P=Pipeline(Path(a.work),Path(a.zeta_root),cfg(a))
    try:
        if a.cmd=="universe": print("current equity issuers:",P.universe(a.identity_overrides,a.gleif,a.universe_csv,a.shard_count,a.shard_index))
        elif a.cmd=="ingest-authorized": P.ingest_authorized(a.manifest)
        elif a.cmd=="discover-documents": P.discover_documents()
        elif a.cmd=="discover-ir": P.discover_ir_missing()
        elif a.cmd=="download": P.download(tickers=a.ticker or None, limit=a.limit)
        elif a.cmd=="audit": P.audit()
        elif a.cmd=="repair-missing": P.discover_documents(); P.discover_ir_missing(); P.download(); P.audit()
        elif a.cmd=="run":
            P.universe(a.identity_overrides,a.gleif,a.universe_csv,a.shard_count,a.shard_index)
            if a.authorized_manifest:P.ingest_authorized(a.authorized_manifest)
            P.discover_documents(); P.discover_ir_missing(); P.download(); P.audit()
        return 0
    finally:P.close()

if __name__=="__main__": raise SystemExit(main())
