from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Candidate, DownloadRecord, Event, ExpectedSlot, Issuer, SourceProfile


class AfricaDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self):
        self.conn.close()

    def _init_schema(self):
        cur = self.conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS issuers (
                issuer_id TEXT PRIMARY KEY,
                country_iso3 TEXT NOT NULL,
                exchange_mic TEXT NOT NULL,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                isin TEXT,
                lei TEXT,
                fiscal_year_end TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                source_url TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expected_slots (
                issuer_id TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL,
                report_type TEXT NOT NULL DEFAULT 'AR',
                status TEXT NOT NULL DEFAULT 'PENDING',
                PRIMARY KEY (issuer_id, fiscal_year, report_type)
            );

            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                issuer_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT,
                publication_date TEXT,
                resolved_fy INTEGER,
                fy_confidence REAL,
                classification TEXT,
                classification_score REAL,
                direct_pdf_url TEXT,
                discovered_at TEXT NOT NULL,
                UNIQUE (issuer_id, source_url)
            );

            CREATE TABLE IF NOT EXISTS downloads (
                candidate_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                http_status INTEGER,
                content_type TEXT,
                sha256 TEXT,
                local_path TEXT,
                error TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS source_profiles (
                source_key TEXT PRIMARY KEY,
                host TEXT NOT NULL,
                adapter TEXT NOT NULL,
                requests_per_second REAL NOT NULL DEFAULT 1.0,
                max_concurrency INTEGER NOT NULL DEFAULT 2,
                health TEXT NOT NULL DEFAULT 'UNKNOWN',
                last_success TEXT,
                last_failure TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                terms_reviewed INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                issuer_id TEXT,
                fiscal_year INTEGER,
                event_type TEXT NOT NULL,
                details TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_issuer_fy ON candidates(issuer_id, resolved_fy);
            CREATE INDEX IF NOT EXISTS idx_expected_slots_status ON expected_slots(status);
        """)
        self.conn.commit()

    def upsert_issuer(self, i: Issuer):
        self.conn.execute("""
            INSERT INTO issuers (issuer_id, country_iso3, exchange_mic, ticker, company_name, isin, lei, fiscal_year_end, active, source_url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(issuer_id) DO UPDATE SET
                company_name=excluded.company_name,
                isin=COALESCE(NULLIF(excluded.isin, ''), issuers.isin),
                lei=COALESCE(NULLIF(excluded.lei, ''), issuers.lei),
                fiscal_year_end=COALESCE(NULLIF(excluded.fiscal_year_end, ''), issuers.fiscal_year_end),
                active=excluded.active,
                updated_at=datetime('now');
        """, (i.issuer_id, i.country_iso3, i.exchange_mic, i.ticker, i.company_name, i.isin or None, i.lei or None, i.fiscal_year_end or None, i.active, i.source_url))
        self.conn.commit()

    def make_slots(self, issuer_id: str, start_yr: int, end_yr: int, report_types: Any = "AR"):
        if isinstance(report_types, str):
            rtypes = [report_types]
        else:
            rtypes = list(report_types)
        rows = [(issuer_id, y, rt, "PENDING") for y in range(start_yr, end_yr + 1) for rt in rtypes]
        self.conn.executemany("""
            INSERT OR IGNORE INTO expected_slots (issuer_id, fiscal_year, report_type, status)
            VALUES (?, ?, ?, ?);
        """, rows)
        self.conn.commit()

    def add_candidate(self, c: Candidate):
        self.conn.execute("""
            INSERT INTO candidates (
                candidate_id, issuer_id, source_name, source_url, title,
                publication_date, resolved_fy, fy_confidence, classification,
                classification_score, direct_pdf_url, discovered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(issuer_id, source_url) DO UPDATE SET
                title=excluded.title,
                resolved_fy=excluded.resolved_fy,
                fy_confidence=excluded.fy_confidence,
                classification=excluded.classification,
                classification_score=excluded.classification_score,
                direct_pdf_url=excluded.direct_pdf_url;
        """, (
            c.candidate_id, c.issuer_id, c.source_name, c.source_url, c.title,
            c.publication_date, c.resolved_fy, c.fy_confidence, c.classification,
            c.classification_score, c.direct_pdf_url,
        ))
        if c.resolved_fy:
            rtype = c.classification if c.classification in ("AR", "SR") else "AR"
            self.conn.execute("""
                UPDATE expected_slots SET status='CANDIDATE_FOUND'
                WHERE issuer_id=? AND fiscal_year=? AND report_type=? AND status IN ('PENDING', 'MISSING');
            """, (c.issuer_id, c.resolved_fy, rtype))
        self.conn.commit()

    def mark_download(
        self,
        candidate_id: str,
        state: str,
        attempts: int = 1,
        bytes_downloaded: int = 0,
        http_status: Optional[int] = None,
        content_type: str = "",
        sha256: str = "",
        local_path: str = "",
        error: str = "",
    ):
        self.conn.execute("""
            INSERT INTO downloads (
                candidate_id, state, attempts, bytes_downloaded, http_status,
                content_type, sha256, local_path, error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(candidate_id) DO UPDATE SET
                state=excluded.state,
                attempts=downloads.attempts + excluded.attempts,
                bytes_downloaded=excluded.bytes_downloaded,
                http_status=excluded.http_status,
                content_type=excluded.content_type,
                sha256=excluded.sha256,
                local_path=excluded.local_path,
                error=excluded.error,
                updated_at=datetime('now');
        """, (candidate_id, state, attempts, bytes_downloaded, http_status, content_type, sha256, local_path, error))
        self.conn.commit()

    def update_slot_status(self, issuer_id: str, fiscal_year: int, status: str, report_type: str = "AR"):
        self.conn.execute("""
            UPDATE expected_slots SET status=?
            WHERE issuer_id=? AND fiscal_year=? AND report_type=?;
        """, (status, issuer_id, fiscal_year, report_type))
        self.conn.commit()

    def record_event(self, event_type: str, issuer_id: Optional[str] = None, fiscal_year: Optional[int] = None, details: str = ""):
        self.conn.execute("""
            INSERT INTO events (ts, issuer_id, fiscal_year, event_type, details)
            VALUES (datetime('now'), ?, ?, ?, ?);
        """, (issuer_id, fiscal_year, event_type, details))
        self.conn.commit()

    def get_issuers(self, country_iso3: Optional[str] = None) -> List[Issuer]:
        if country_iso3:
            cur = self.conn.execute("SELECT * FROM issuers WHERE UPPER(country_iso3)=? ORDER BY ticker;", (country_iso3.upper(),))
        else:
            cur = self.conn.execute("SELECT * FROM issuers ORDER BY country_iso3, ticker;")
        return [Issuer.from_dict(dict(r)) for r in cur.fetchall()]

    def get_selected_candidates(self, country_iso3: Optional[str] = None, report_type: Optional[str] = None, repair: bool = False) -> List[sqlite3.Row]:
        """Return the best candidate per issuer, fiscal year, and report type."""
        query = """
            SELECT 
                i.issuer_id, i.country_iso3, i.exchange_mic, i.ticker, i.company_name, i.isin, i.lei,
                s.fiscal_year, s.report_type, c.candidate_id, c.source_url, c.direct_pdf_url, c.title, c.fy_confidence,
                d.state as download_state, d.sha256, d.local_path
            FROM expected_slots s
            JOIN issuers i ON s.issuer_id = i.issuer_id
            JOIN candidates c ON s.issuer_id = c.issuer_id AND s.fiscal_year = c.resolved_fy AND s.report_type = c.classification
            LEFT JOIN downloads d ON c.candidate_id = d.candidate_id
            WHERE 1=1
        """
        if country_iso3:
            clean_c = country_iso3.strip().upper()
            query += f" AND UPPER(i.country_iso3) = '{clean_c}'"
        if report_type:
            clean_rt = report_type.strip().upper()
            query += f" AND s.report_type = '{clean_rt}'"
        if not repair:
            query += " AND (d.state IS NULL OR d.state NOT IN ('DONE', 'IDENTITY_MISSING'))"
        else:
            query += " AND (d.state IS NULL OR d.state = 'FAILED' OR s.status = 'MISSING')"
        query += " GROUP BY s.issuer_id, s.fiscal_year, s.report_type HAVING MAX(c.fy_confidence * 1000 + c.classification_score) ORDER BY i.country_iso3, i.ticker, s.fiscal_year, s.report_type;"
        return list(self.conn.execute(query).fetchall())

    def get_coverage_stats(self) -> Dict[str, Any]:
        total_issuers = self.conn.execute("SELECT COUNT(*) FROM issuers;").fetchone()[0]
        total_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots;").fetchone()[0]
        done_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='DONE';").fetchone()[0]
        staged_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='IDENTITY_MISSING';").fetchone()[0]
        missing_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='MISSING';").fetchone()[0]
        failed_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='FAILED';").fetchone()[0]
        return {
            "total_issuers": total_issuers,
            "total_slots": total_slots,
            "done_slots": done_slots,
            "staged_slots": staged_slots,
            "missing_slots": missing_slots,
            "failed_slots": failed_slots,
        }
