from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def write_audits(db_path: Path, out_dir: Path, start_year: int, end_year: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def dump(name: str, query: str, params=()):
        rows = conn.execute(query, params).fetchall()
        path = out_dir / name
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader(); w.writerows(dict(r) for r in rows)
            else:
                f.write("")

    dump("issuers.csv", "SELECT * FROM issuers ORDER BY stock_code")
    dump("filings.csv", "SELECT * FROM filings ORDER BY stock_code,fiscal_year")
    dump("downloads.csv", "SELECT * FROM attachments ORDER BY status,announcement_id,filename")
    dump("failed_downloads.csv", "SELECT * FROM attachments WHERE status='failed' ORDER BY announcement_id")
    dump("unmapped_annual_reports.csv", "SELECT * FROM unmapped_reports ORDER BY fiscal_year,company_name")
    dump("multiple_annual_candidates.csv", """
         SELECT announcement_id, COUNT(*) AS selected_count,
                GROUP_CONCAT(filename, ' | ') AS filenames
         FROM attachments WHERE selected=1 GROUP BY announcement_id HAVING COUNT(*)>1
         ORDER BY announcement_id""")

    coverage_path = out_dir / "coverage.csv"
    issuers = conn.execute("SELECT ibm_code,stock_code,ticker,issuer_name FROM issuers ORDER BY stock_code").fetchall()
    with coverage_path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["ibm_code","stock_code","ticker","issuer_name","fiscal_year","filing_count","downloaded_count","status"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for issuer in issuers:
            for year in range(start_year, end_year + 1):
                filing_count = conn.execute("SELECT COUNT(*) FROM filings WHERE ibm_code=? AND fiscal_year=?", (issuer["ibm_code"], year)).fetchone()[0]
                downloaded = conn.execute("""SELECT COUNT(*) FROM attachments a JOIN filings f USING(announcement_id)
                    WHERE f.ibm_code=? AND f.fiscal_year=? AND a.selected=1 AND a.status='done'""", (issuer["ibm_code"], year)).fetchone()[0]
                status = "DOWNLOADED" if downloaded else ("FOUND_NOT_DOWNLOADED" if filing_count else "NO_FILING_FOUND")
                w.writerow({**dict(issuer), "fiscal_year":year, "filing_count":filing_count, "downloaded_count":downloaded, "status":status})
    conn.close()
