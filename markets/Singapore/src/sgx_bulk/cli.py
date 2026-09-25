from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .pipeline import Pipeline
from .httpclient import RetryingClient
from .sgx import SGXSource


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sgx-annual-bulk", description="Bulk-download current SGX annual reports")
    p.add_argument("command", choices=["run", "discover", "download", "audit", "smoke"])
    p.add_argument("--start-year", type=int, default=2017)
    p.add_argument("--end-year", type=int, default=2025)
    p.add_argument("--output", type=Path, default=Path("output"))
    p.add_argument("--discovery-workers", type=int, default=6)
    p.add_argument("--detail-workers", type=int, default=8)
    p.add_argument("--download-workers", type=int, default=6)
    p.add_argument("--stock-code", action="append", default=[], help="Filter cohort to stock code(s)")
    p.add_argument("--ibm-code", action="append", default=[], help="Filter cohort to SGX IBM code(s)")
    p.add_argument("--no-targeted-recovery", action="store_true")
    return p


async def smoke() -> int:
    http = RetryingClient(timeout=30, retries=2)
    source = SGXSource(http)
    try:
        try:
            issuers = await source.current_issuers()
            sgx = next((x for x in issuers if x.stock_code == "S68"), None)
            if not sgx:
                print("FAIL: S68 not found in current SGX issuer registry")
                return 2
            rows = await source.company_report_rows(sgx)
            annual = [r for r in rows if source.is_annual(r)]
            if not annual:
                print("FAIL: no annual report records found for S68")
                return 3
            filing = source.filing_from_row(annual[0], sgx)
            if not filing:
                print("FAIL: could not normalize latest S68 annual report")
                return 4
            attachments, selected = await source.resolve_attachments(filing)
            if not selected:
                print("FAIL: annual-report PDF attachment not resolved")
                return 5
            print("PASS")
            print("Current issuers:", len(issuers))
            print("S68 latest annual period:", filing.period_end)
            print("Announcement:", filing.announcement_id)
            print("Selected PDF(s):")
            for a in attachments:
                if a.url in selected:
                    print(" -", a.url)
            return 0
        except Exception as exc:
            print(f"FAIL: live SGX smoke check could not complete: {exc}")
            return 10
    finally:
        await http.close()


async def async_main(args) -> int:
    if args.command == "smoke":
        return await smoke()
    if args.start_year > args.end_year:
        raise SystemExit("--start-year must be <= --end-year")
    pipe = Pipeline(
        args.output, args.start_year, args.end_year,
        discovery_workers=args.discovery_workers,
        detail_workers=args.detail_workers,
        download_workers=args.download_workers,
        targeted_recovery=not args.no_targeted_recovery,
    )
    try:
        if args.command in {"run", "discover"}:
            issuers, filings = await pipe.discover()
            resolved_ok, resolved_fail = await pipe.resolve()
            print(f"Discovery summary: issuers={issuers}, filings={filings}, resolved={resolved_ok}, unresolved={resolved_fail}")
        if args.command in {"run", "download"}:
            ok, fail = await pipe.download(ibm_codes=args.ibm_code or None, stock_codes=args.stock_code or None)
            print(f"Download summary: done={ok}, failed={fail}")
        pipe.audit()
        print("Audit CSVs:", args.output / "audit")
        return 0
    finally:
        await pipe.close()


def main() -> None:
    args = parser().parse_args()
    raise SystemExit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
