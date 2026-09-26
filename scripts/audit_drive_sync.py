import os
import sqlite3
from pathlib import Path

drive_dir = Path("GLOBAL_SUSTAINABILITY_DATABASE/AUS/XASX")
drive_pdfs = list(drive_dir.rglob("*.pdf")) if drive_dir.exists() else []

staging_dir = Path("local/markets/Australia/staging")
staged_pdfs = list(staging_dir.rglob("*.pdf")) if staging_dir.exists() else []

work_dir = Path("local/markets/Australia/work/pdfs")
work_pdfs = list(work_dir.rglob("*.pdf")) if work_dir.exists() else []

db_path = Path("local/markets/Australia/work/manifest.sqlite3")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM downloads WHERE status='DONE'")
db_done = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM downloads WHERE status='DONE' AND path LIKE '%GLOBAL_SUSTAINABILITY_DATABASE%'")
db_drive = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM downloads WHERE status='PENDING'")
db_pending = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM filings")
total_filings = cur.fetchone()[0]

cur.execute("SELECT SUM(bytes)/(1024*1024*1024.0) FROM downloads WHERE status='DONE'")
gb_done = cur.fetchone()[0] or 0.0

print(f"CANONICAL_DRIVE_COUNT={len(drive_pdfs)}")
print(f"STAGING_COUNT={len(staged_pdfs)}")
print(f"WORK_CACHE_COUNT={len(work_pdfs)}")
print(f"SQLITE_DONE={db_done}")
print(f"SQLITE_DRIVE_PATHS={db_drive}")
print(f"SQLITE_PENDING={db_pending}")
print(f"TOTAL_FILINGS={total_filings}")
print(f"TOTAL_GB_DONE={gb_done:.2f}")
