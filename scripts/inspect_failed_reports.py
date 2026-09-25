"""Inspect the 182 failed reports in harvest.sqlite3."""

import sqlite3
from collections import Counter

conn = sqlite3.connect("local/harvest.sqlite3")
cur = conn.cursor()

rows = cur.execute(
    "SELECT relative_path, pdf_url, error, updated_at FROM reports WHERE status='failed'"
).fetchall()
conn.close()

print(f"Total failed rows: {len(rows)}")

errors = Counter(r[2] for r in rows)
print("\nError breakdown:")
for err, count in errors.most_common():
    print(f"  [{count}] {err}")

countries = Counter(r[0].split("\\")[0] if "\\" in r[0] else r[0].split("/")[0] for r in rows)
print("\nCountry breakdown:")
for c, count in countries.items():
    print(f"  {c}: {count}")

print("\nSample failed rows (first 10):")
for r in rows[:10]:
    print(f"Path: {r[0]}")
    print(f"  URL: {r[1]}")
    print(f"  Error: {r[2]}")
    print(f"  Updated: {r[3]}")
