"""End-to-end autonomous harvester for remaining LSE listed companies (2017-2025).
Chains: ch-match -> ch-discover -> manifest export -> concurrent download -> verification.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from annual_reports.catalog import load_manifest
from annual_reports.companies_house import (
    discover_ch_accounts,
    export_ch_manifest,
    export_ch_review,
    match_uk_companies,
)
from annual_reports.discovery import DiscoveryStore, read_universe
from annual_reports.engine import Settings, native_path, run, verify_store


async def main() -> None:
    started_all = time.monotonic()
    state_path = Path("local/harvest.sqlite3")
    output_root = Path("GLOBAL_SUSTAINABILITY_DATABASE")
    universe_path = Path("local/universe_lse_remaining.csv")
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY", "82f00221-8dfb-40e7-9bb8-9e98603193f3")
    target_years = list(range(2017, 2026))

    companies = read_universe(universe_path)
    print(f"Loaded {len(companies)} remaining LSE companies from {universe_path}", flush=True)

    print(f"\n=== STEP 1: Matching companies against Companies House registry ===", flush=True)
    t0 = time.monotonic()
    match_summary = await match_uk_companies(
        state_path=state_path,
        companies=companies,
        api_key=api_key,
    )
    print(f"Matching completed in {time.monotonic() - t0:.1f}s:", flush=True)
    print(json.dumps(match_summary, indent=2), flush=True)

    print(f"\n=== STEP 2: Discovering statutory accounts (FY2017-FY2025) ===", flush=True)
    t1 = time.monotonic()
    disc_summary = await discover_ch_accounts(
        state_path=state_path,
        years=target_years,
        output_root=output_root,
        companies=companies,
        api_key=api_key,
    )
    print(f"Discovery completed in {time.monotonic() - t1:.1f}s:", flush=True)
    print(json.dumps(disc_summary, indent=2), flush=True)

    print(f"\n=== STEP 3: Exporting Manifest and Review logs ===", flush=True)
    manifest_path = Path("local/ch_direct_remaining_lse2.csv")
    review_path = Path("local/ch_review_lse2.csv")

    pdf_count = export_ch_manifest(
        state_path=state_path,
        output_csv=manifest_path,
        output_root=output_root,
        companies=companies,
        years=target_years,
    )
    print(f"Manifest exported: {manifest_path} ({pdf_count} pending PDF candidate rows)", flush=True)

    rev_summary = export_ch_review(
        state_path=state_path,
        output_csv=review_path,
        companies=companies,
    )
    print(f"Review log exported: {review_path} ({rev_summary.get('rows_written', 0)} rows)", flush=True)

    if pdf_count == 0:
        print("No new pending PDFs to download for this cohort! All target slots verified.", flush=True)
        return

    print(f"\n=== STEP 4: Downloading {pdf_count} Statutory Accounts Reports to Google Drive ===", flush=True)
    reports = load_manifest(manifest_path)
    settings = Settings(
        output_root=output_root,
        state_path=state_path,
        workers=8,
        per_host=2,
        timeout_s=90.0,
        companies_house_key=api_key,
    )

    t_dl = time.monotonic()
    last_update = time.monotonic()

    def progress(attempts: int, total: int, downloaded: int, failed: int) -> None:
        nonlocal last_update
        now = time.monotonic()
        if attempts % 20 == 0 or now - last_update >= 10:
            pct = attempts / max(1, total) * 100
            print(
                f"Progress: attempts={attempts}/{total} downloaded={downloaded} failed={failed} ({pct:.1f}%)",
                file=sys.stderr,
                flush=True,
            )
            last_update = now

    summary = await run(reports, settings, progress=progress)
    dl_elapsed = time.monotonic() - t_dl
    print(f"\nDownload phase completed in {dl_elapsed:.1f}s ({summary.get('pdfs_per_second', 0):.2f} docs/s, {summary.get('mib_per_second', 0):.2f} MiB/s):", flush=True)
    print(json.dumps(summary, indent=2), flush=True)

    print(f"\n=== STEP 5: Scoped Verification and Reconciliation ===", flush=True)
    import sqlite3
    conn = sqlite3.connect(state_path)
    cur = conn.cursor()

    total_uk = 0
    by_year: dict[int, int] = {}
    for (rel,) in cur.execute("SELECT relative_path FROM reports WHERE status='downloaded'"):
        norm = rel.replace("\\", "/")
        parts = norm.split("/")
        if len(parts) >= 4 and parts[0] == "GBR":
            total_uk += 1
            fy_str = parts[3]
            if fy_str.startswith("FY") and fy_str[2:].isdigit():
                yr = int(fy_str[2:])
                if 2017 <= yr <= 2025:
                    by_year[yr] = by_year.get(yr, 0) + 1
    conn.close()

    gbr_dir = output_root / "GBR"
    orphan_parts = list(gbr_dir.glob("**/*.part")) if gbr_dir.exists() else []

    print(f"Total UK verified reports in DB: {total_uk}", flush=True)
    print("UK Reports by Fiscal Year (2017-2025):", flush=True)
    for yr, cnt in sorted(by_year.items()):
        print(f"  FY{yr}: {cnt}", flush=True)
    print(f"Orphan .part files in GBR: {len(orphan_parts)}", flush=True)
    print(f"Total pipeline elapsed: {time.monotonic() - started_all:.1f}s", flush=True)


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
