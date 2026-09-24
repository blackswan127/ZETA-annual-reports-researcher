"""Automated Companies House harvest pipeline runner for LSE 101-1000.
Executes ch-discover, manifest export, concurrent download, and post-harvest reconciliation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set up project environment
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from annual_reports.catalog import load_manifest
from annual_reports.cli import _filter_cohort_pdfs
from annual_reports.companies_house import (
    discover_ch_accounts,
    export_ch_manifest,
    export_ch_review,
)
from annual_reports.discovery import DiscoveryStore, read_universe
from annual_reports.engine import Settings, native_path, run, verify_store


async def main() -> None:
    started_all = time.monotonic()
    state_path = Path("local/harvest.sqlite3")
    output_root = Path("GLOBAL_SUSTAINABILITY_DATABASE")
    api_key = os.getenv("COMPANIES_HOUSE_API_KEY", "82f00221-8dfb-40e7-9bb8-9e98603193f3")
    target_years = list(range(2017, 2026))

    manifest_path = Path("local/ch_direct_remaining.csv")
    review_path = Path("local/ch_review_full.csv")

    import sqlite3
    chk_conn = sqlite3.connect(state_path)
    existing_ch_cands = chk_conn.execute("SELECT count(*) FROM candidates WHERE source='COMPANIES_HOUSE'").fetchone()[0]
    chk_conn.close()

    if existing_ch_cands > 0 and manifest_path.exists():
        print(f"Skipping Step 1: {existing_ch_cands} Companies House candidates already cached in database.")
    else:
        print(f"=== STEP 1: Discovering Companies House accounts for FY2017-FY2025 ===")
        t0 = time.monotonic()
        disc_summary = await discover_ch_accounts(
            state_path=state_path,
            years=target_years,
            output_root=output_root,
            api_key=api_key,
        )
        print(f"Discovery completed in {time.monotonic() - t0:.1f}s:")
        print(json.dumps(disc_summary, indent=2))

    print(f"\n=== STEP 2: Exporting Manifest and Review logs ===")

    pdf_count = export_ch_manifest(
        state_path=state_path,
        output_csv=manifest_path,
        output_root=output_root,
        years=target_years,
    )
    print(f"Manifest exported: {manifest_path} ({pdf_count} pending PDF candidate rows)")

    rev_summary = export_ch_review(
        state_path=state_path,
        output_csv=review_path,
    )
    print(f"Review log exported: {review_path} ({rev_summary.get('review_rows', 0)} rows)")

    if pdf_count == 0:
        print("No new pending PDFs to download! All target slots are already verified.")
        return

    print(f"\n=== STEP 3: Downloading {pdf_count} Statutory Accounts Reports to Google Drive ===")
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
            print(
                f"Progress: attempts={attempts}/{total} downloaded={downloaded} failed={failed} "
                f"({attempts/max(1,total)*100:.1f}%)",
                file=sys.stderr,
            )
            last_update = now

    summary = await run(reports, settings, progress=progress)

    dl_elapsed = time.monotonic() - t_dl
    print(f"Download phase completed in {dl_elapsed:.1f}s ({summary.get('pdfs_per_second', 0):.2f} docs/s, {summary.get('mib_per_second', 0):.2f} MiB/s):")
    print(json.dumps(summary, indent=2))

    print(f"\n=== STEP 4: Scoped Verification and Reconciliation ===")
    import sqlite3
    conn = sqlite3.connect(state_path)
    cur = conn.cursor()

    # Get total UK reports
    total_uk = 0
    by_year: dict[int, int] = {}
    for (rel,) in cur.execute("SELECT relative_path FROM reports WHERE status='downloaded' OR verified=1"):
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

    print(f"Total UK verified reports in DB: {total_uk}")
    print("UK Reports by Fiscal Year (2017-2025):")
    for yr, cnt in sorted(by_year.items()):
        print(f"  FY{yr}: {cnt}")
    print(f"Orphan .part files in GBR: {len(orphan_parts)}")
    print(f"Total pipeline elapsed: {time.monotonic() - started_all:.1f}s")


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
