from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def export_audit_csvs(conn: sqlite3.Connection, audit_dir: Path) -> None:
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    # 1. universe_summary.csv
    with open(audit_dir / "universe_summary.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["country_iso3", "exchange_mic", "total_issuers", "active_issuers", "with_isin", "with_lei"])
        cur = conn.execute("""
            SELECT country_iso3, exchange_mic, COUNT(*), SUM(active), 
                   SUM(CASE WHEN isin IS NOT NULL AND length(isin)=12 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN lei IS NOT NULL AND length(lei)=20 THEN 1 ELSE 0 END)
            FROM issuers GROUP BY country_iso3, exchange_mic ORDER BY country_iso3, exchange_mic;
        """)
        w.writerows(cur.fetchall())

    # 2. issuers.csv
    with open(audit_dir / "issuers.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "country_iso3", "exchange_mic", "ticker", "company_name", "isin", "lei", "fiscal_year_end", "active", "source_url"])
        cur = conn.execute("SELECT issuer_id, country_iso3, exchange_mic, ticker, company_name, isin, lei, fiscal_year_end, active, source_url FROM issuers ORDER BY country_iso3, ticker;")
        w.writerows(cur.fetchall())

    # 3. coverage.csv
    with open(audit_dir / "coverage.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "country_iso3", "ticker", "company_name", "fiscal_year", "status", "candidate_id", "sha256", "bytes", "local_path"])
        cur = conn.execute("""
            SELECT s.issuer_id, i.country_iso3, i.ticker, i.company_name, s.fiscal_year, s.status,
                   c.candidate_id, d.sha256, d.bytes_downloaded, d.local_path
            FROM expected_slots s
            JOIN issuers i ON s.issuer_id = i.issuer_id
            LEFT JOIN candidates c ON s.issuer_id = c.issuer_id AND s.fiscal_year = c.resolved_fy
            LEFT JOIN downloads d ON c.candidate_id = d.candidate_id
            ORDER BY i.country_iso3, i.ticker, s.fiscal_year;
        """)
        w.writerows(cur.fetchall())

    # 4. missing.csv
    with open(audit_dir / "missing.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "country_iso3", "ticker", "company_name", "fiscal_year", "status"])
        cur = conn.execute("""
            SELECT s.issuer_id, i.country_iso3, i.ticker, i.company_name, s.fiscal_year, s.status
            FROM expected_slots s
            JOIN issuers i ON s.issuer_id = i.issuer_id
            WHERE s.status IN ('PENDING', 'MISSING')
            ORDER BY i.country_iso3, i.ticker, s.fiscal_year;
        """)
        w.writerows(cur.fetchall())

    # 5. failed_downloads.csv
    with open(audit_dir / "failed_downloads.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "issuer_id", "source_url", "http_status", "attempts", "error", "updated_at"])
        cur = conn.execute("""
            SELECT d.candidate_id, c.issuer_id, c.source_url, d.http_status, d.attempts, d.error, d.updated_at
            FROM downloads d
            JOIN candidates c ON d.candidate_id = c.candidate_id
            WHERE d.state = 'FAILED'
            ORDER BY d.updated_at DESC;
        """)
        w.writerows(cur.fetchall())

    # 6. identity_missing.csv
    with open(audit_dir / "identity_missing.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "country_iso3", "ticker", "company_name", "missing_reason", "staged_path"])
        cur = conn.execute("""
            SELECT i.issuer_id, i.country_iso3, i.ticker, i.company_name,
                   CASE 
                     WHEN (i.isin IS NULL OR length(i.isin)!=12) AND (i.lei IS NULL OR length(i.lei)!=20) THEN 'Missing both LEI and ISIN'
                     WHEN i.isin IS NULL OR length(i.isin)!=12 THEN 'Missing valid ISIN'
                     ELSE 'Missing valid LEI'
                   END,
                   d.local_path
            FROM issuers i
            JOIN expected_slots s ON i.issuer_id = s.issuer_id
            JOIN candidates c ON s.issuer_id = c.issuer_id AND s.fiscal_year = c.resolved_fy
            JOIN downloads d ON c.candidate_id = d.candidate_id
            WHERE d.state = 'IDENTITY_MISSING'
            GROUP BY i.issuer_id;
        """)
        w.writerows(cur.fetchall())
