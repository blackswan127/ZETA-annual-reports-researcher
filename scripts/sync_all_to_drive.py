"""Sync and promote all staged reports directly into Google Drive (GLOBAL_SUSTAINABILITY_DATABASE).

Ensures that every harvested report across the Australian market is permanently
stored in Google Drive under canonical SOP paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "markets" / "Australia" / "src"))

from markets._integration.promotion import build_sop_relative_path

DEFAULT_CORPUS_ROOT = ROOT_DIR / "GLOBAL_SUSTAINABILITY_DATABASE"
LOCAL_WORK_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "work"
LOCAL_STAGING_DIR = ROOT_DIR / "local" / "markets" / "Australia" / "staging"
IDENTIFIERS_CACHE = ROOT_DIR / "local" / "asx_master_identifiers.json"


def sync_all():
    print("=======================================================", flush=True)
    print("SYNCING ALL HARVESTED REPORTS DIRECTLY TO GOOGLE DRIVE", flush=True)
    print(f"Target Drive Corpus: {DEFAULT_CORPUS_ROOT}")
    print("=======================================================\n", flush=True)

    master = {}
    if IDENTIFIERS_CACHE.exists():
        with open(IDENTIFIERS_CACHE, "r", encoding="utf-8") as f:
            master = json.load(f)

    db_path = LOCAL_WORK_DIR / "manifest.sqlite3"
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    unresolved_dir = LOCAL_STAGING_DIR / "unresolved_identity"
    if not unresolved_dir.exists():
        print("No staging directory found.")
        return

    staged_pdfs = list(unresolved_dir.rglob("*.pdf"))
    print(f"Found {len(staged_pdfs)} staged PDFs on local disk to sync to Drive...", flush=True)

    pattern = re.compile(r"^([A-Z0-9]+)_(\d{4})_([A-Z]+)_")
    synced = 0
    skipped_existing = 0
    errors = 0

    t0 = time.time()

    for idx, pdf in enumerate(staged_pdfs, 1):
        try:
            m = pattern.match(pdf.name)
            ticker, fy, rep_type = None, None, "AR"
            if m:
                ticker, fy, rep_type = m.group(1).upper(), int(m.group(2)), m.group(3).upper()
            else:
                parts = pdf.parent.name.split("_FY")
                if len(parts) == 2:
                    ticker, fy = parts[0].upper(), int(parts[1])
            if not ticker or not fy:
                continue

            info = master.get(ticker, {})
            lei = info.get("lei", "").strip().upper()
            if not lei or len(lei) != 20:
                lei = "NOLEI"

            isin = info.get("isin", "").strip().upper()
            if not isin or len(isin) != 12:
                isin = f"AU0000{ticker.ljust(6, 'X')}"

            sop_rel = build_sop_relative_path(
                iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
                lei=lei, isin=isin, report_type=rep_type
            )
            final_path = DEFAULT_CORPUS_ROOT / sop_rel

            # Validate before moving
            buf = pdf.read_bytes()
            if not buf.startswith(b"%PDF-"):
                errors += 1
                continue

            doc = fitz.open(stream=buf, filetype="pdf")
            if doc.is_encrypted or len(doc) < 1:
                doc.close()
                errors += 1
                continue
            doc.close()

            sz = len(buf)
            sha = hashlib.sha256(buf).hexdigest()

            # Atomic move / write to Google Drive
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if not final_path.exists() or final_path.stat().st_size != sz:
                tmp_path = final_path.with_suffix(final_path.suffix + f".tmp_{os.getpid()}_{time.time_ns()}")
                tmp_path.write_bytes(buf)
                tmp_path.replace(final_path)

            # Update database path
            cur = conn.execute(
                """SELECT f.id FROM filings f
                   JOIN downloads d ON d.filing_id=f.id
                   WHERE f.ticker=? AND f.fiscal_year=? AND f.report_type=?""",
                (ticker, fy, rep_type),
            )
            row = cur.fetchone()
            if row:
                fid = row["id"]
                conn.execute(
                    "UPDATE downloads SET path=?, bytes=?, sha256=?, status='DONE' WHERE filing_id=?",
                    (str(final_path), sz, sha, fid),
                )
            else:
                # Update by matching path substring
                conn.execute(
                    "UPDATE downloads SET path=?, bytes=?, sha256=?, status='DONE' WHERE path LIKE ?",
                    (str(final_path), sz, sha, f"%{pdf.name}%"),
                )

            # Remove local staging copy
            pdf.unlink(missing_ok=True)
            synced += 1

            if synced % 100 == 0:
                conn.commit()
                elapsed = time.time() - t0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Synced {synced}/{len(staged_pdfs)} files to Drive ({synced/elapsed:.1f} files/sec)...", flush=True)

        except Exception as exc:
            errors += 1

    conn.commit()
    conn.close()

    # Clean up empty staging folders
    for d in sorted(unresolved_dir.glob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()
            except Exception:
                pass

    elapsed = time.time() - t0
    print("\n=======================================================", flush=True)
    print(f"SYNC COMPLETE: {synced} files successfully synced to Google Drive in {elapsed:.1f}s")
    print(f"Errors: {errors} | Target: {DEFAULT_CORPUS_ROOT / 'AUS' / 'XASX'}")
    print("=======================================================\n", flush=True)


if __name__ == "__main__":
    from datetime import datetime
    sync_all()
