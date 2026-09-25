from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


def export_audit_csvs(conn: sqlite3.Connection, audit_dir: Path) -> None:
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)

    # 1. universe_summary.csv
    cur = conn.execute("""
        SELECT 
            iso3, mic, COUNT(*) as active_issuers,
            SUM(CASE WHEN isin IS NOT NULL AND length(isin)=12 THEN 1 ELSE 0 END) as with_isin,
            SUM(CASE WHEN lei IS NOT NULL AND length(lei)=20 THEN 1 ELSE 0 END) as with_lei
        FROM issuers WHERE active=1
        GROUP BY iso3, mic ORDER BY iso3, mic;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "universe_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["iso3", "mic", "active_issuers", "with_isin", "with_lei"])
        for r in rows:
            w.writerow(list(r))

    # 2. issuers.csv
    cur = conn.execute("""
        SELECT issuer_id, iso3, mic, ticker, company_name, isin, lei, fiscal_year_end, active, universe_source, updated_at
        FROM issuers ORDER BY iso3, ticker;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "issuers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "iso3", "mic", "ticker", "company_name", "isin", "lei", "fiscal_year_end", "active", "universe_source", "updated_at"])
        for r in rows:
            w.writerow(list(r))

    # 3. coverage.csv
    cur = conn.execute("""
        SELECT 
            s.issuer_id, i.iso3, i.mic, i.ticker, i.company_name, s.fiscal_year, s.required_class, s.status,
            d.bytes_downloaded, d.sha256, d.local_path
        FROM expected_slots s
        JOIN issuers i ON s.issuer_id = i.issuer_id
        LEFT JOIN candidates c ON s.issuer_id = c.issuer_id AND s.fiscal_year = c.resolved_fy AND c.document_class = s.required_class
        LEFT JOIN downloads d ON c.candidate_id = d.candidate_id
        ORDER BY i.iso3, i.ticker, s.fiscal_year;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "coverage.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "iso3", "mic", "ticker", "company_name", "fiscal_year", "required_class", "status", "bytes", "sha256", "local_path"])
        for r in rows:
            w.writerow(list(r))

    # 4. missing.csv
    cur = conn.execute("""
        SELECT s.issuer_id, i.iso3, i.mic, i.ticker, i.company_name, s.fiscal_year, s.status
        FROM expected_slots s
        JOIN issuers i ON s.issuer_id = i.issuer_id
        WHERE s.status IN ('PENDING', 'MISSING', 'MISSING_AR_FULL', 'FAILED')
        ORDER BY i.iso3, i.ticker, s.fiscal_year;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "missing.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "iso3", "mic", "ticker", "company_name", "fiscal_year", "status"])
        for r in rows:
            w.writerow(list(r))

    # 5. failed_downloads.csv
    cur = conn.execute("""
        SELECT d.candidate_id, c.issuer_id, c.resolved_fy, d.state, d.attempts, d.http_status, d.error, d.updated_at
        FROM downloads d
        JOIN candidates c ON d.candidate_id = c.candidate_id
        WHERE d.state = 'FAILED' OR d.error != ''
        ORDER BY d.updated_at DESC;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "failed_downloads.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "issuer_id", "fiscal_year", "state", "attempts", "http_status", "error", "updated_at"])
        for r in rows:
            w.writerow(list(r))

    # 6. identity_missing.csv
    cur = conn.execute("""
        SELECT DISTINCT i.issuer_id, i.iso3, i.mic, i.ticker, i.company_name, i.isin, i.lei
        FROM issuers i
        JOIN expected_slots s ON i.issuer_id = s.issuer_id
        WHERE s.status = 'IDENTITY_MISSING' OR (s.status = 'DONE' AND (i.isin IS NULL OR length(i.isin)!=12 OR i.lei IS NULL OR length(i.lei)!=20))
        ORDER BY i.iso3, i.ticker;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "identity_missing.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["issuer_id", "iso3", "mic", "ticker", "company_name", "isin", "lei"])
        for r in rows:
            w.writerow(list(r))

    # 7. components.csv (annual financial statements components found)
    cur = conn.execute("""
        SELECT c.candidate_id, c.issuer_id, c.resolved_fy, c.title, c.document_class, c.source_url
        FROM candidates c
        WHERE c.document_class IN ('ANNUAL_FS_COMPONENT', 'GOVERNANCE_COMPONENT', 'ESG_COMPONENT')
        ORDER BY c.issuer_id, c.resolved_fy;
    """)
    rows = cur.fetchall()
    with open(audit_dir / "components.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["candidate_id", "issuer_id", "fiscal_year", "title", "document_class", "source_url"])
        for r in rows:
            w.writerow(list(r))
