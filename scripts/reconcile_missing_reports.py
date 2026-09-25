"""Examine all missing reports from harvest.sqlite3 and output a full report."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def main():
    state_path = Path("local/harvest.sqlite3")
    output_root = os.path.abspath("GLOBAL_SUSTAINABILITY_DATABASE")

    conn = sqlite3.connect(state_path)
    cur = conn.cursor()

    cur.execute(
        "SELECT relative_path, pdf_url, source_page, status, verified, bytes, pages, sha256, updated_at "
        "FROM reports WHERE status='downloaded' OR verified=1"
    )
    rows = cur.fetchall()

    missing = []
    for rel, url, sp, st, v, b, pg, sha, upd in rows:
        full_path = os.path.join(output_root, rel)
        if not os.path.exists(full_path):
            missing.append({
                "relative_path": rel,
                "pdf_url": url,
                "source_page": sp,
                "status": st,
                "verified": v,
                "bytes": b,
                "pages": pg,
                "sha256": sha,
                "updated_at": upd,
            })

    print(f"Total checked: {len(rows):,}")
    print(f"Missing count: {len(missing)}")

    by_status = {}
    by_country = {}
    by_year = {}

    for m in missing:
        st = m["status"]
        by_status[st] = by_status.get(st, 0) + 1

        rel = m["relative_path"]
        parts = rel.replace("\\", "/").split("/")
        c = parts[0] if parts else "UNKNOWN"
        by_country[c] = by_country.get(c, 0) + 1

        for p in parts:
            if p.startswith("FY") and p[2:].isdigit():
                by_year[p] = by_year.get(p, 0) + 1
                break

    print("Missing by status:", by_status)
    print("Missing by country:", by_country)
    print("Missing by year:", sorted(by_year.items()))

    print("\nSample missing records (first 10):")
    for m in missing[:10]:
        print(f"  Path: {m['relative_path']}")
        print(f"    Status: {m['status']}, Verified: {m['verified']}, Bytes: {m['bytes']}, Pages: {m['pages']}")
        print(f"    URL: {m['pdf_url']}")
        print(f"    Updated: {m['updated_at']}")

    # Check the 23 GBR missing records specifically
    gbr_missing = [m for m in missing if m["relative_path"].startswith("GBR")]
    print(f"\nAll GBR missing records ({len(gbr_missing)}):")
    for m in gbr_missing:
        print(f"  {m['relative_path']} | status={m['status']} | bytes={m['bytes']} | updated={m['updated_at']} | url={m['pdf_url']}")

    conn.close()


if __name__ == "__main__":
    main()
