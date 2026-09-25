from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime
from pathlib import Path

from .company_stats import fetch_official_listed_company_count
from .db import Database
from .hkex import HKEXClient
from .pipeline import discover, download_selected, refresh_active


def parse_date(value: str | None) -> date:
    return date.today() if not value else datetime.strptime(value, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hkex-annual-bulk",
        description="Bulk-discover and download HKEX annual-report PDFs for currently listed issuers.",
    )
    p.add_argument("command", nargs="?", default="all", choices=["all","discover","download","audit","status","smoke","companies"])
    p.add_argument("--output", default="output")
    p.add_argument("--start-year", type=int, default=2017)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--publication-end", default=None, help="YYYY-MM-DD; default=today. FY2025 reports published in 2026 are included.")
    p.add_argument("--metadata-rps", type=float, default=2.5)
    p.add_argument("--download-rps", type=float, default=8.0)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--row-limit", type=int, default=2000)
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--limit-reports", type=int, default=None, help="Testing only: cap PDFs downloaded this run")
    p.add_argument("--allow-code", action="append", default=[], help="Filter download queue to specific stock code(s)")
    p.add_argument("--stock-code", default="00700", help="For smoke command")
    p.add_argument("--smoke-year", type=int, default=2025)
    return p


async def run_async(args: argparse.Namespace) -> int:
    if args.command == "companies":
        result = await fetch_official_listed_company_count()
        print(f"[listed-companies] total={result['total']:,} | main_board={result['main_board']:,} | GEM={result['gem']:,} | as_of={result['as_of']}")
        print(f"Official HKEX source: {result['source_url']}")
        return 0

    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    db = Database(out / "manifest.sqlite3")
    try:
        if args.command == "status":
            print_counts(db)
            return 0
        if args.command == "audit":
            db.export_csvs(out, args.start_year, args.end_year)
            print_counts(db)
            print(f"Audit CSVs written to: {out}")
            return 0

        async with HKEXClient(timeout=args.timeout, max_retries=args.max_retries,
                              metadata_rps=args.metadata_rps, download_rps=args.download_rps) as client:
            if args.command in ("all", "discover", "smoke"):
                n = await refresh_active(db, client)
                print(f"[active-securities] loaded {n:,} security rows; this is not a company count")

            if args.command in ("all", "discover"):
                result = await fetch_official_listed_company_count()
                print(f"[listed-companies] HKEX official total={result['total']:,} (Main Board {result['main_board']:,}; GEM {result['gem']:,}), as of {result['as_of']}")
                print(f"[listed-companies-source] {result['source_url']}")

            if args.command == "smoke":
                stock_id = db.active_id_for_code(args.stock_code.zfill(5))
                if not stock_id:
                    raise RuntimeError(f"Stock code {args.stock_code} not found in current HKEX active list")
                start = date(args.smoke_year, 1, 1)
                end = min(date.today(), date(args.smoke_year + 1, 6, 30))
                rows = await client.annual_search_complete(start, end, row_limit=200, stock_id=stock_id)
                print(f"Smoke test: {args.stock_code.zfill(5)} returned {len(rows)} Annual Report category row(s) for {start}..{end}")
                for r in rows[:10]:
                    print(f"  {r.get('DATE_TIME','')} | {r.get('TITLE','')} | {r.get('FILE_LINK','')}")
                return 0 if rows else 2

            if args.command in ("all", "discover"):
                result = await discover(
                    db, client,
                    start_year=args.start_year,
                    end_year=args.end_year,
                    publication_end=parse_date(args.publication_end),
                    row_limit=args.row_limit,
                )
                print("[discover-summary] " + " | ".join(f"{k}={v:,}" for k,v in result.items()))

            if args.command in ("all", "download"):
                result = await download_selected(
                    db, client, output=out, workers=args.workers, limit_reports=args.limit_reports,
                    stock_codes=args.allow_code or None,
                )
                print("[download-summary] " + " | ".join(f"{k}={v:,}" for k,v in result.items()))

        db.export_csvs(out, args.start_year, args.end_year)
        print_counts(db)
        print(f"Output: {out}")
        return 0
    finally:
        db.close()


def print_counts(db: Database) -> None:
    counts = db.counts()
    print("\nSTATUS")
    for k,v in counts.items():
        print(f"  {k:20s} {v:,}")


def main() -> None:
    args = build_parser().parse_args()
    if args.end_year < args.start_year:
        raise SystemExit("--end-year must be >= --start-year")
    try:
        code = asyncio.run(run_async(args))
    except KeyboardInterrupt:
        print("Interrupted safely. Re-run the same command to resume.")
        code = 130
    raise SystemExit(code)


if __name__ == "__main__":
    main()
