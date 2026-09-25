from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from .adapters import get_market_adapter
from .coordinator import Coordinator, DEFAULT_CORPUS_ROOT


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="markets-ar",
        description="Unified Multi-Market Annual Reports Harvester & SOP Promotion Coordinator",
    )
    p.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT, help="Target SOP corpus root (Drive junction)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Directive command (plain English)
    auto = sub.add_parser("auto", help="Execute plain-English directive autonomously")
    auto.add_argument("prompt", type=str, help="e.g. 'download the next 100 current listed companies in India for FY2024'")
    auto.add_argument("--offset", type=int, default=None)

    # Roster inspect command
    roster = sub.add_parser("roster", help="Query and inspect the active issuer roster for a market")
    roster.add_argument("market", type=str, help="Australia, Bangladesh, Canada, HongKong, India, NewZealand, Singapore")

    # Cohort freeze command
    cohort = sub.add_parser("cohort", help="Deterministically freeze a cohort manifest")
    cohort.add_argument("market", type=str)
    cohort.add_argument("--count", type=int, default=100)
    cohort.add_argument("--fy", type=int, action="append", default=[])
    cohort.add_argument("--offset", type=int, default=0)

    # Status command
    status = sub.add_parser("status", help="Inspect market status, manifests, and audit metrics")
    status.add_argument("market", type=str)

    return p


async def async_main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    coord = Coordinator(corpus_root=args.corpus_root)

    if args.cmd == "auto":
        print(f"Executing directive: '{args.prompt}'")
        summary = await coord.execute_directive(args.prompt, force_offset=args.offset)
        return 0 if summary.promoted_pdfs > 0 or summary.verified_pdfs > 0 else 1

    elif args.cmd == "roster":
        adapter = get_market_adapter(args.market)
        print(f"Loading current active roster for {adapter.info['name']}...")
        records = await adapter.load_roster(refresh=False)
        print(f"Found {len(records)} active issuers for {adapter.info['name']}.")
        for r in records[:15]:
            print(f"  {r.ticker:10} | ISIN: {r.isin:12} | LEI: {r.lei:20} | {r.legal_name}")
        if len(records) > 15:
            print(f"  ... and {len(records) - 15} more.")
        return 0

    elif args.cmd == "cohort":
        adapter = get_market_adapter(args.market)
        records = await adapter.load_roster(refresh=False)
        fys = args.fy or [2024]
        from .cohort import select_exact_cohort
        manifest = select_exact_cohort(
            market=args.market,
            requested_count=args.count,
            fiscal_years=fys,
            roster=records,
            corpus_root=args.corpus_root,
            manifest_dir=adapter.manifest_dir,
            offset=args.offset,
        )
        print(f"Frozen cohort manifest: {manifest.run_id} ({len(manifest.issuers)} issuers)")
        print(f"Saved to: {adapter.manifest_dir / f'{manifest.run_id}.json'}")
        return 0

    elif args.cmd == "status":
        adapter = get_market_adapter(args.market)
        print(f"Market: {adapter.info['name']} (MIC: {adapter.info['mic']}, ISO3: {adapter.info['iso3']})")
        print(f"Local State Directory: {adapter.local_dir}")
        manifests = list(adapter.manifest_dir.glob("*.json"))
        print(f"Saved Manifests: {len(manifests)}")
        for m in manifests[-5:]:
            print(f"  - {m.name}")
        return 0

    return 0


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
