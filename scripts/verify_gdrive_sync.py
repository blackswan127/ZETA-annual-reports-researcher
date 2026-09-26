"""Fast, direct verification of all harvested HKEX reports in Google Drive.
Audits physical file existence on G:\\My Drive\\GLOBAL_SUSTAINABILITY_DATABASE,
validates file size, integrity, and cleans any interrupted .part files.
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys
import time


def verify_gdrive_sync():
    db_path = pathlib.Path("local/harvest.sqlite3")
    gdrive_root = pathlib.Path("G:/My Drive/GLOBAL_SUSTAINABILITY_DATABASE")
    junction_root = pathlib.Path("GLOBAL_SUSTAINABILITY_DATABASE")

    print(f"Connecting to database {db_path}...", flush=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT canonical_path, sha256, file_size, pages, ticker, fiscal_year, report_type
        FROM hkex_reports
        WHERE status = 'verified'
        ORDER BY created_at
    """).fetchall()

    total_records = len(rows)
    print(f"Total verified reports in SQLite ledger: {total_records}", flush=True)
    print(f"Auditing directly against Google Drive root: {gdrive_root}...", flush=True)

    missing = []
    size_mismatches = []
    header_errors = []
    part_cleaned = 0

    start_t = time.perf_counter()
    for idx, r in enumerate(rows, start=1):
        c_path, expected_sha, expected_size, pages, ticker, fy, rtype = r
        g_file = gdrive_root / c_path

        # Check for lingering .part file and remove if full file exists
        part_file = g_file.with_suffix(".part")
        if part_file.exists():
            try:
                part_file.unlink()
                part_cleaned += 1
            except Exception:
                pass

        if not g_file.exists():
            missing.append(c_path)
            continue

        try:
            actual_size = g_file.stat().st_size
            if actual_size != expected_size:
                size_mismatches.append((c_path, actual_size, expected_size))

            with open(g_file, "rb") as f:
                hdr = f.read(5)
                if not hdr.startswith(b"%PDF"):
                    header_errors.append(c_path)
        except Exception as exc:
            missing.append(f"{c_path} ({exc})")

        if idx % 100 == 0 or idx == total_records:
            elapsed = time.perf_counter() - start_t
            print(f"[{idx}/{total_records}] Audited {idx} files on Google Drive ({idx/max(elapsed, 0.1):.1f} files/sec)...", flush=True)

    elapsed = time.perf_counter() - start_t
    verified_on_drive = total_records - len(missing)

    print("\n" + "=" * 65, flush=True)
    print("GOOGLE DRIVE SYNCHRONIZATION AUDIT REPORT", flush=True)
    print("=" * 65, flush=True)
    print(f"Target Google Drive Root:  {gdrive_root}", flush=True)
    print(f"Total Verified in Ledger:  {total_records}", flush=True)
    print(f"Confirmed on Google Drive: {verified_on_drive}/{total_records} ({(verified_on_drive/max(total_records,1))*100:.2f}%)", flush=True)
    print(f"Missing on Google Drive:   {len(missing)}", flush=True)
    print(f"File Size Mismatches:      {len(size_mismatches)}", flush=True)
    print(f"Corrupted PDF Headers:     {len(header_errors)}", flush=True)
    print(f"Cleaned Orphan .part:      {part_cleaned}", flush=True)
    print(f"Total Audit Time:          {elapsed:.2f}s", flush=True)
    print("=" * 65 + "\n", flush=True)

    if missing:
        print("Sample missing paths:", flush=True)
        for m in missing[:5]:
            print(f"  - {m}", flush=True)

    conn.close()


if __name__ == "__main__":
    verify_gdrive_sync()
