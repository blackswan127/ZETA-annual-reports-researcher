from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .config import AFRICAN_MARKETS, RuntimeConfig, resolve_african_market
from .pipeline import AfricaPipeline

BANNER = "Africa AR Bulk Harvester v1.0 (Pan-African Annual Report Engine)"


def create_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="africa-ar", description=BANNER)
    p.add_argument("--work", type=Path, default=Path("work"))
    p.add_argument("--zeta-root", type=Path, default=Path(os.environ.get("ZETA_ROOT", "GLOBAL_SUSTAINABILITY_DATABASE")))
    p.add_argument("--country", type=str, default="")
    p.add_argument("--start-year", type=int, default=2017)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--discovery-workers", type=int, default=8)
    p.add_argument("--download-workers", type=int, default=16)
    p.add_argument("--discovery-rps", type=float, default=2.0)
    p.add_argument("--download-rps", type=float, default=6.0)
    p.add_argument("--timeout", type=float, default=45.0)
    p.add_argument("--retries", type=int, default=5)
    p.add_argument("--min-pdf-bytes", type=int, default=25000)
    p.add_argument("--report-types", type=str, default="AR,SR", help="Comma-separated report types (e.g. AR,SR)")

    sub = p.add_subparsers(dest="cmd", required=True)

    # universe
    u = sub.add_parser("universe", help="Stage equity issuers across African markets")
    u.add_argument("--universe-file", type=Path)
    u.add_argument("--limit", type=int)

    # discover
    d = sub.add_parser("discover", help="Discover annual report candidates")
    d.add_argument("--limit", type=int)

    # download
    dl = sub.add_parser("download", help="Download and validate candidate PDFs")
    dl.add_argument("--limit", type=int)

    # repair-missing
    sub.add_parser("repair-missing", help="Attempt repair of missing or failed slots")

    # audit
    sub.add_parser("audit", help="Export audit CSVs and print coverage statistics")

    # run
    r = sub.add_parser("run", help="Execute complete pipeline: universe -> discover -> download -> audit")
    r.add_argument("--universe-file", type=Path)
    r.add_argument("--limit", type=int)

    # smoke-test
    st = sub.add_parser("smoke-test", help="Verify network reachability to African exchanges")

    return p


def build_config(args: argparse.Namespace) -> RuntimeConfig:
    return RuntimeConfig(
        start_year=args.start_year,
        end_year=args.end_year,
        discovery_workers=args.discovery_workers,
        download_workers=args.download_workers,
        discovery_rps=args.discovery_rps,
        download_rps=args.download_rps,
        timeout=args.timeout,
        retries=args.retries,
        min_pdf_bytes=args.min_pdf_bytes,
        work_dir=args.work,
        zeta_root=args.zeta_root,
    )


async def async_main(args: argparse.Namespace) -> int:
    if args.cmd == "smoke-test":
        print(f"=== {BANNER} ===")
        print("Testing African exchange network reachability...")
        import httpx
        endpoints = [
            ("NSE Kenya", "https://www.nse.co.ke/"),
            ("NGX Nigeria", "https://ngxgroup.com/"),
            ("DSE Tanzania", "https://dse.co.tz/"),
            ("BSE Botswana", "https://www.bse.co.bw/"),
            ("GSE Ghana", "https://gse.com.gh/"),
        ]
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            for name, url in endpoints:
                try:
                    resp = await client.get(url)
                    status_badge = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
                    print(f"  [{status_badge}] {name} -> {url}")
                except Exception as e:
                    print(f"  [FAIL] {name} -> {e}")
        print("Smoke test complete.")
        return 0

    cfg = build_config(args)
    pipe = AfricaPipeline(cfg)
    iso3 = None
    if args.country:
        res = resolve_african_market(args.country)
        iso3 = res["iso3"] if res else args.country.upper()

    rtypes = [rt.strip().upper() for rt in getattr(args, "report_types", "AR,SR").split(",") if rt.strip()]

    try:
        if args.cmd == "universe":
            u_file = getattr(args, "universe_file", None)
            lim = getattr(args, "limit", None)
            issuers = pipe.stage_universe(country_iso3=iso3, universe_csv=u_file, limit=lim, report_types=rtypes)
            print(f"Staged {len(issuers)} issuers in {cfg.work_dir / 'harvest.sqlite3'}")

        elif args.cmd == "discover":
            lim = getattr(args, "limit", None)
            target_issuers = pipe.db.get_issuers(iso3) if iso3 else None
            count = await pipe.discover(issuers=target_issuers, limit=lim)
            print(f"Discovered {count} annual/sustainability report candidates")

        elif args.cmd == "download":
            lim = getattr(args, "limit", None)
            count = await pipe.download(country_iso3=iso3, limit=lim)
            print(f"Downloaded and validated {count} reports")

        elif args.cmd == "repair-missing":
            count = await pipe.download(country_iso3=iso3, repair=True)
            print(f"Repaired {count} missing/failed reports")

        elif args.cmd == "audit":
            stats = pipe.audit()
            print("=== Africa AR Coverage Summary ===")
            for k, v in stats.items():
                print(f"  {k}: {v}")

        elif args.cmd == "run":
            u_file = getattr(args, "universe_file", None)
            lim = getattr(args, "limit", None)
            stats = await pipe.run(country_iso3=iso3, universe_csv=u_file, limit=lim, report_types=rtypes)
            print("=== Africa AR Run Completed ===")
            for k, v in stats.items():
                print(f"  {k}: {v}")

        return 0
    finally:
        pipe.close()


def main():
    p = create_parser()
    args = p.parse_args()
    rc = asyncio.run(async_main(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
