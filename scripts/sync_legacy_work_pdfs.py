"""Sync legacy work/pdfs into Google Drive (GLOBAL_SUSTAINABILITY_DATABASE)."""

import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import fitz

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from markets._integration.promotion import build_sop_relative_path

master = json.load(open("local/asx_master_identifiers.json", "r", encoding="utf-8"))
db_path = Path("local/markets/Australia/work/manifest.sqlite3")
conn = sqlite3.connect(db_path, timeout=60.0)
conn.row_factory = sqlite3.Row

legacy_dir = Path("local/markets/Australia/work/pdfs")
legacy_pdfs = list(legacy_dir.rglob("*.pdf")) if legacy_dir.exists() else []
print(f"Syncing {len(legacy_pdfs)} legacy work/pdfs to Google Drive...", flush=True)

drive_root = Path("GLOBAL_SUSTAINABILITY_DATABASE")
synced = 0
pattern = re.compile(r"^([A-Z0-9]+)_(\d{4})_([A-Z]+)_")

for pdf in legacy_pdfs:
    try:
        m = pattern.match(pdf.name)
        ticker, fy, rep_type = None, None, "AR"
        if m:
            ticker, fy, rep_type = m.group(1).upper(), int(m.group(2)), m.group(3).upper()
        else:
            fy = int(pdf.parent.name)
            ticker = pdf.parent.parent.name.split("_")[0].upper()

        info = master.get(ticker, {})
        lei = info.get("lei", "").strip().upper()
        if not lei or len(lei) != 20:
            lei = "NOLEI"
        isin = info.get("isin", "").strip().upper()
        if not isin or len(isin) != 12:
            pad = ticker.ljust(6, "X")
            isin = f"AU0000{pad}"

        sop_rel = build_sop_relative_path(
            iso3="AUS", mic="XASX", ticker=ticker, fiscal_year=fy,
            lei=lei, isin=isin, report_type=rep_type
        )
        final_path = drive_root / sop_rel

        buf = pdf.read_bytes()
        if not buf.startswith(b"%PDF-"):
            continue
        doc = fitz.open(stream=buf, filetype="pdf")
        if len(doc) < 1 or doc.is_encrypted:
            doc.close()
            continue
        doc.close()

        sz = len(buf)
        sha = hashlib.sha256(buf).hexdigest()

        final_path.parent.mkdir(parents=True, exist_ok=True)
        if not final_path.exists() or final_path.stat().st_size != sz:
            tmp_path = final_path.with_suffix(final_path.suffix + f".tmp_{os.getpid()}_{synced}")
            tmp_path.write_bytes(buf)
            tmp_path.replace(final_path)

        cur = conn.execute(
            """SELECT f.id FROM filings f
               JOIN downloads d ON d.filing_id=f.id
               WHERE f.ticker=? AND f.fiscal_year=? AND f.report_type=?""",
            (ticker, fy, rep_type),
        )
        row = cur.fetchone()
        if row:
            conn.execute(
                "UPDATE downloads SET path=?, bytes=?, sha256=?, status='DONE' WHERE filing_id=?",
                (str(final_path), sz, sha, row["id"]),
            )

        pdf.unlink(missing_ok=True)
        synced += 1
    except Exception as exc:
        pass

conn.commit()
conn.close()
print(f"Successfully synced {synced} legacy files to Google Drive!", flush=True)
