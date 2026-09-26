import sqlite3
import os
from pathlib import Path

db_path = Path("local/markets/Australia/work/manifest.sqlite3")
conn = sqlite3.connect(db_path, timeout=30.0)
cur = conn.cursor()

cur.execute("SELECT status, count(*) FROM downloads GROUP BY status")
statuses = dict(cur.fetchall())

cur.execute("SELECT count(*) FROM downloads WHERE status='DONE' AND path LIKE '%GLOBAL_SUSTAINABILITY_DATABASE%'")
drive_count = cur.fetchone()[0]

cur.execute("SELECT count(*) FROM filings")
total_filings = cur.fetchone()[0]

cur.execute("SELECT sum(bytes) / (1024.0 * 1024.0 * 1024.0) FROM downloads WHERE status='DONE'")
total_gb = cur.fetchone()[0] or 0.0

conn.close()

staging_dir = Path("local/markets/Australia/staging")
staged = list(staging_dir.rglob("*.pdf")) if staging_dir.exists() else []

work_dir = Path("local/markets/Australia/work/pdfs")
work_pdfs = list(work_dir.rglob("*.pdf")) if work_dir.exists() else []

print(f"DONE_TOTAL: {statuses.get('DONE', 0)}")
print(f"DONE_IN_DRIVE: {drive_count}")
print(f"PENDING: {statuses.get('PENDING', 0)}")
print(f"FAILED: {statuses.get('FAILED', 0)}")
print(f"TOTAL_FILINGS: {total_filings}")
print(f"TOTAL_GB: {total_gb:.2f} GB")
print(f"LOCAL_STAGING_PDFS: {len(staged)}")
print(f"LOCAL_WORK_PDFS: {len(work_pdfs)}")
