from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import RuntimeConfig, resolve_middle_east_market, MIDDLE_EAST_MARKETS
from .downloader import Downloader
from .pipeline import MiddleEastPipeline
from .sources.exchange_direct import DirectExchangeAdapter


def parse_args():
    parser = argparse.ArgumentParser(description="Middle East Annual Reports Harvester (me-ar)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. universe
    p_uni = subparsers.add_parser("universe", help="Stage active universe and generate expected slots")
    p_uni.add_argument("--country", type=str, help="Filter by country, MIC, or alias (e.g. OMN, JOR, UAE, SAU)")
    p_uni.add_argument("--csv", type=Path, help="Path to custom universe CSV")
    p_uni.add_argument("--limit", type=int, help="Limit number of staged issuers")

    # 2. discover
    p_disc = subparsers.add_parser("discover", help="Discover annual report candidates from exchange & IR feeds")
    p_disc.add_argument("--country", type=str, help="Filter by country/market")
    p_disc.add_argument("--limit", type=int, help="Limit number of scanned issuers")

    # 3. download
    p_down = subparsers.add_parser("download", help="Download and promote verified PDF reports to ZETA tree")
    p_down.add_argument("--limit", type=int, help="Limit number of downloads")
    p_down.add_argument("--repair", action="store_true", help="Retry failed or missing slots")

    # 4. run
    p_run = subparsers.add_parser("run", help="Execute end-to-end harvest (stage -> discover -> download -> audit)")
    p_run.add_argument("--country", type=str, help="Filter by country/market")
    p_run.add_argument("--csv", type=Path, help="Path to custom universe CSV")
    p_run.add_argument("--limit", type=int, help="Limit number of issuers")
    p_run.add_argument("--years", type=str, default="2017-2025", help="Reporting year range (e.g. 2017-2025)")

    # 5. repair-missing
    subparsers.add_parser("repair-missing", help="Run secondary exchange / IR fallback repair for unfilled slots")

    # 6. audit
    subparsers.add_parser("audit", help="Export comprehensive coverage and missing audit CSVs")

    # 7. smoke-test
    p_smoke = subparsers.add_parser("smoke-test", help="Test connectivity to Middle Eastern exchange endpoints")
    p_smoke.add_argument("--country", type=str, help="Country or market to test")

    return parser.parse_args()


async def run_smoke_test(country: str | None = None):
    print("\n--- Middle East Exchange Smoke Test ---")
    direct = DirectExchangeAdapter()
    try:
        targets = [
            ("Oman (MSX)", "https://www.msx.om/"),
            ("Jordan (ASE)", "https://www.ase.com.jo/en"),
            ("UAE Dubai (DFM)", "https://www.dfm.ae/"),
            ("UAE Abu Dhabi (ADX)", "https://www.adx.ae/"),
            ("Saudi Arabia (Tadawul)", "https://www.saudiexchange.sa/"),
            ("Qatar (QSE)", "https://www.qe.com.qa/"),
            ("Bahrain (Bahrain Bourse)", "https://www.bahrainbourse.com/"),
            ("Kuwait (Boursa Kuwait)", "https://www.boursakuwait.com.kw/"),
        ]
        for name, url in targets:
            try:
                r = await direct.client.get(url, timeout=10.0)
                status = "OK" if r.status_code == 200 else f"HTTP {r.status_code}"
                print(f"[{status:^10}] {name:30} -> {url}")
            except Exception as e:
                print(f"[{'ERR':^10}] {name:30} -> {str(e)[:50]}")
    finally:
        await direct.close()
    print("---------------------------------------\n")


def main():
    args = parse_args()
    config = RuntimeConfig()

    iso3 = None
    if getattr(args, "country", None):
        meta = resolve_middle_east_market(args.country)
        if meta:
            iso3 = meta["iso3"]
        else:
            print(f"Error: Unknown or excluded Middle Eastern market '{args.country}'. Note: Palestine and Israel are excluded.")
            sys.exit(1)

    if args.command == "smoke-test":
        asyncio.run(run_smoke_test(iso3))
        return

    pipe = MiddleEastPipeline(config)
    try:
        if args.command == "universe":
            issuers = pipe.stage_universe(iso3=iso3, universe_csv=args.csv, limit=args.limit)
            print(f"Successfully staged {len(issuers)} issuers and generated expected FY{config.start_year}-FY{config.end_year} slots.")

        elif args.command == "discover":
            count = asyncio.run(pipe.discover(limit=args.limit))
            print(f"Discovery complete. Discovered {count} candidates.")

        elif args.command == "download":
            count = asyncio.run(pipe.download(limit=args.limit, repair=args.repair))
            print(f"Download complete. Downloaded/promoted {count} files.")

        elif args.command == "run":
            if getattr(args, "years", None):
                parts = args.years.split("-")
                if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                    config.start_year = int(parts[0])
                    config.end_year = int(parts[1])
            stats = asyncio.run(pipe.run(iso3=iso3, universe_csv=args.csv, limit=args.limit))
            print(f"Run completed. Stats: {stats}")

        elif args.command == "repair-missing":
            count = asyncio.run(pipe.download(repair=True))
            print(f"Repair complete. Recovered {count} missing reports.")

        elif args.command == "audit":
            stats = pipe.audit()
            print(f"Audit exported to {pipe.work_dir / 'audit'}. Summary: {stats}")
    finally:
        pipe.close()


if __name__ == "__main__":
    main()
