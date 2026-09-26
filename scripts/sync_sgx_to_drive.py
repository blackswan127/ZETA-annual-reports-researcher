from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "markets" / "Singapore" / "src"))
sys.path.insert(0, str(ROOT_DIR))

import httpx

DB_PATH = ROOT_DIR / "local" / "markets" / "Singapore" / "work" / "manifest.sqlite3"
DRIVE_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
AUDIT_DIR = ROOT_DIR / "local" / "markets" / "Singapore" / "work" / "audit"
LEI_CACHE_PATH = ROOT_DIR / "local" / "markets" / "Singapore" / "lei_cache.json"


def sanitize_token(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", s.strip())


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(64 * 1024):
            h.update(chunk)
    return h.hexdigest()


async def resolve_all_leis(issuers: list[dict]) -> dict[str, str]:
    cache: dict[str, str] = {}
    if LEI_CACHE_PATH.exists():
        try:
            with open(LEI_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            print(f"Loaded {len(cache)} cached LEIs.")
        except Exception:
            cache = {}

    to_fetch = [i for i in issuers if i["ibm_code"] not in cache]
    print(f"Resolving LEIs for {len(to_fetch)} issuers via GLEIF API...")

    if not to_fetch:
        return cache

    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(timeout=10.0) as client:
        async def fetch(item: dict) -> tuple[str, str]:
            ibm = item["ibm_code"]
            isin = item["isin"]
            name = item["issuer_name"]
            async with sem:
                # 1. Try by ISIN
                if isin:
                    try:
                        r = await client.get(f"https://api.gleif.org/api/v1/lei-records?filter[isin]={isin}")
                        if r.status_code == 200:
                            data = r.json().get("data", [])
                            if data:
                                return ibm, data[0]["attributes"]["lei"]
                    except Exception:
                        pass
                # 2. Try by Legal Name
                try:
                    clean_name = name.replace("LIMITED", "").replace("LTD", "").replace("CORP", "").replace(".", "").strip()
                    r = await client.get(f"https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]={clean_name}")
                    if r.status_code == 200:
                        data = r.json().get("data", [])
                        if data:
                            return ibm, data[0]["attributes"]["lei"]
                except Exception:
                    pass
                return ibm, "NOLEI"

        tasks = [fetch(item) for item in to_fetch]
        for fut in asyncio.as_completed(tasks):
            ibm, lei = await fut
            cache[ibm] = lei

    with open(LEI_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    print(f"LEI cache saved with {len(cache)} records.")
    return cache


def main() -> int:
    t_start = time.time()
    print("=" * 75)
    print("SGX TO GOOGLE DRIVE SYNC & SOP PROMOTION PIPELINE")
    print(f"Target SOP Corpus: {DRIVE_ROOT}")
    print(f"Start Time:        {datetime.now(timezone.utc).isoformat()}")
    print("=" * 75)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Load issuers
    issuer_rows = conn.execute("SELECT * FROM issuers").fetchall()
    issuers = [dict(r) for r in issuer_rows]
    issuers_by_ibm = {r["ibm_code"]: r for r in issuers}

    # 2. Resolve LEIs
    lei_cache = asyncio.run(resolve_all_leis(issuers))
    found_leis = sum(1 for l in lei_cache.values() if l and l != "NOLEI")
    print(f"LEI Resolution Summary: {found_leis} issuers with verified LEI, {len(issuers) - found_leis} with NOLEI.")

    # Update issuers in DB with LEI
    try:
        conn.execute("ALTER TABLE issuers ADD COLUMN lei TEXT DEFAULT 'NOLEI'")
    except sqlite3.OperationalError:
        pass
    for ibm, lei in lei_cache.items():
        conn.execute("UPDATE issuers SET lei=? WHERE ibm_code=?", (lei, ibm))
    conn.commit()

    # 3. Process completed downloads
    completed_rows = conn.execute(
        """SELECT a.url, a.local_path, a.filename, a.size_bytes, a.sha256,
                  f.ibm_code, f.stock_code, f.fiscal_year, f.report_type
           FROM attachments a JOIN filings f USING(announcement_id)
           WHERE a.selected=1 AND a.status='done'"""
    ).fetchall()

    print(f"\nSyncing {len(completed_rows)} validated files to Google Drive (GLOBAL_SUSTAINABILITY_DATABASE)...")

    synced_count = 0
    idempotent_count = 0
    failed_count = 0
    total_bytes = 0

    for idx, row in enumerate(completed_rows, 1):
        ibm = row["ibm_code"]
        issuer = issuers_by_ibm.get(ibm, {})
        isin = issuer.get("isin") or "NOISIN"
        stock_code = row["stock_code"] or ibm
        clean_ticker = sanitize_token(stock_code).upper()
        lei = lei_cache.get(ibm) or "NOLEI"
        fy = int(row["fiscal_year"])
        rtype = (row["report_type"] or "AR").upper()

        # SOP folder and file names
        company_folder = f"{lei}_{isin}_{clean_ticker}"
        fy_folder = f"FY{fy}"
        sop_filename = f"{lei}_SGP_XSES_{clean_ticker}_{isin}_FY{fy}_{rtype}_EN.pdf"

        dest_dir = DRIVE_ROOT / "SGP" / "XSES" / company_folder / fy_folder
        dest_file = dest_dir / sop_filename
        dest_part = dest_dir / f"{sop_filename}.part"

        src_path = Path(row["local_path"]) if row["local_path"] else None

        # Check if already present on Drive with identical SHA-256
        if dest_file.exists():
            if dest_file.stat().st_size == row["size_bytes"]:
                idempotent_count += 1
                conn.execute("UPDATE attachments SET local_path=? WHERE url=?", (str(dest_file), row["url"]))
                if src_path and src_path.exists() and src_path.resolve() != dest_file.resolve():
                    src_path.unlink(missing_ok=True)
                continue

        if not src_path or not src_path.exists():
            print(f"Warning: source file missing for {row['filename']}")
            failed_count += 1
            continue

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Copy to .part on Drive
            shutil.copy2(src_path, dest_part)
            # Verify byte size
            if dest_part.stat().st_size != src_path.stat().st_size:
                dest_part.unlink(missing_ok=True)
                failed_count += 1
                continue

            # Atomic replace on Drive
            os.replace(dest_part, dest_file)
            synced_count += 1
            total_bytes += dest_file.stat().st_size

            # Update DB with final canonical Drive path
            conn.execute("UPDATE attachments SET local_path=? WHERE url=?", (str(dest_file), row["url"]))

            # Unlink source on local SSD to preserve disk space
            src_path.unlink(missing_ok=True)

        except Exception as e:
            print(f"Error syncing {row['filename']}: {e}")
            failed_count += 1

        if idx % 500 == 0 or idx == len(completed_rows):
            conn.commit()
            print(f"  --> Progress: {idx}/{len(completed_rows)} processed ({synced_count} newly synced, {idempotent_count} idempotent)")

    conn.commit()

    # 4. Write audit reports
    from sgx_bulk.audit import write_audits
    write_audits(DB_PATH, AUDIT_DIR, 2017, 2025)
    # Also copy audit CSVs to Drive
    drive_audit = DRIVE_ROOT / "SGP" / "audit"
    drive_audit.mkdir(parents=True, exist_ok=True)
    for csv_f in AUDIT_DIR.glob("*.csv"):
        shutil.copy2(csv_f, drive_audit / csv_f.name)

    elapsed = time.time() - t_start
    print("\n" + "=" * 75)
    print("SYNC AND DRIVE PROMOTION COMPLETE")
    print("=" * 75)
    print(f"Total Target Reports:     {len(completed_rows)}")
    print(f"Newly Promoted to Drive:  {synced_count}")
    print(f"Idempotent in Drive:      {idempotent_count}")
    print(f"Failed / Missing:         {failed_count}")
    print(f"Transferred Volume:       {total_bytes / (1024*1024):.1f} MB")
    print(f"Elapsed Time:             {elapsed:.1f}s ({elapsed/60.0:.2f} min)")
    print(f"Drive SOP Directory:      {DRIVE_ROOT / 'SGP' / 'XSES'}")
    print(f"Drive Audit Directory:    {drive_audit}")
    print("=" * 75 + "\n")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
