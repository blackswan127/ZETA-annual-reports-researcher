from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import Candidate, DownloadRecord, Event, ExpectedSlot, Issuer, SourceProfile


class MiddleEastDB:
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
                iso3 TEXT NOT NULL,
                mic TEXT NOT NULL,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                isin TEXT,
                lei TEXT,
                fiscal_year_end TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                universe_source TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expected_slots (
                issuer_id TEXT NOT NULL,
                fiscal_year INTEGER NOT NULL,
                required_class TEXT NOT NULL DEFAULT 'AR_FULL',
                status TEXT NOT NULL DEFAULT 'PENDING',
                selected_candidate_id TEXT,
                PRIMARY KEY (issuer_id, fiscal_year, required_class)
            );

            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                issuer_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                direct_url TEXT,
                title TEXT,
                publication_date TEXT,
                period_end TEXT,
                resolved_fy INTEGER,
                fy_confidence REAL,
                language TEXT,
                language_confidence REAL,
                document_class TEXT NOT NULL,
                class_confidence REAL,
                discovered_at TEXT NOT NULL,
                UNIQUE(issuer_id, source_url)
            );

            CREATE TABLE IF NOT EXISTS downloads (
                candidate_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                http_status INTEGER,
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
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                terms_reviewed INTEGER NOT NULL DEFAULT 0,
                last_success TEXT,
                last_failure TEXT
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
            INSERT INTO issuers (issuer_id, iso3, mic, ticker, company_name, isin, lei, fiscal_year_end, active, universe_source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(issuer_id) DO UPDATE SET
                company_name=excluded.company_name,
                isin=COALESCE(NULLIF(excluded.isin, ''), issuers.isin),
                lei=COALESCE(NULLIF(excluded.lei, ''), issuers.lei),
                fiscal_year_end=COALESCE(NULLIF(excluded.fiscal_year_end, ''), issuers.fiscal_year_end),
                active=excluded.active,
                universe_source=excluded.universe_source,
                updated_at=datetime('now');
        """, (i.issuer_id, i.iso3, i.mic, i.ticker, i.company_name, i.isin or None, i.lei or None, i.fiscal_year_end or None, i.active, i.universe_source))
        self.conn.commit()

    def make_slots(self, issuer_id: str, start_yr: int, end_yr: int, required_class: str = "AR_FULL"):
        rows = [(issuer_id, y, required_class, "PENDING") for y in range(start_yr, end_yr + 1)]
        self.conn.executemany("""
            INSERT OR IGNORE INTO expected_slots (issuer_id, fiscal_year, required_class, status)
            VALUES (?, ?, ?, ?);
        """, rows)
        self.conn.commit()

    def add_candidate(self, c: Candidate):
        self.conn.execute("""
            INSERT INTO candidates (
                candidate_id, issuer_id, source_name, source_url, direct_url,
                title, publication_date, period_end, resolved_fy, fy_confidence,
                language, language_confidence, document_class, class_confidence, discovered_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(issuer_id, source_url) DO UPDATE SET
                direct_url=excluded.direct_url,
                title=excluded.title,
                publication_date=excluded.publication_date,
                period_end=excluded.period_end,
                resolved_fy=excluded.resolved_fy,
                fy_confidence=excluded.fy_confidence,
                language=excluded.language,
                language_confidence=excluded.language_confidence,
                document_class=excluded.document_class,
                class_confidence=excluded.class_confidence;
        """, (
            c.candidate_id, c.issuer_id, c.source_name, c.source_url, c.direct_url,
            c.title, c.publication_date, c.period_end, c.resolved_fy, c.fy_confidence,
            c.language, c.language_confidence, c.document_class, c.class_confidence,
        ))
        if c.resolved_fy:
            if c.document_class == "AR_FULL":
                new_status = "AR_FULL_FOUND"
            elif c.document_class == "ANNUAL_FS_COMPONENT":
                new_status = "ANNUAL_COMPONENT_FOUND"
            else:
                new_status = "CANDIDATE_FOUND"

            self.conn.execute("""
                UPDATE expected_slots SET status=?
                WHERE issuer_id=? AND fiscal_year=? AND status IN ('PENDING', 'MISSING', 'ANNUAL_COMPONENT_FOUND');
            """, (new_status, c.issuer_id, c.resolved_fy))
        self.conn.commit()

    def mark_download(
        self,
        candidate_id: str,
        state: str,
        attempts: int = 1,
        bytes_downloaded: int = 0,
        http_status: Optional[int] = None,
        sha256: str = "",
        local_path: str = "",
        error: str = "",
    ):
        self.conn.execute("""
            INSERT INTO downloads (
                candidate_id, state, attempts, bytes_downloaded, http_status,
                sha256, local_path, error, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(candidate_id) DO UPDATE SET
                state=excluded.state,
                attempts=downloads.attempts + excluded.attempts,
                bytes_downloaded=excluded.bytes_downloaded,
                http_status=excluded.http_status,
                sha256=excluded.sha256,
                local_path=excluded.local_path,
                error=excluded.error,
                updated_at=datetime('now');
        """, (candidate_id, state, attempts, bytes_downloaded, http_status, sha256, local_path, error))
        self.conn.commit()

    def update_slot_status(self, issuer_id: str, fiscal_year: int, status: str, selected_candidate_id: Optional[str] = None, required_class: str = "AR_FULL"):
        self.conn.execute("""
            UPDATE expected_slots SET status=?, selected_candidate_id=COALESCE(?, selected_candidate_id)
            WHERE issuer_id=? AND fiscal_year=? AND required_class=?;
        """, (status, selected_candidate_id, issuer_id, fiscal_year, required_class))
        self.conn.commit()

    def record_event(self, event_type: str, issuer_id: Optional[str] = None, fiscal_year: Optional[int] = None, details: str = ""):
        self.conn.execute("""
            INSERT INTO events (ts, issuer_id, fiscal_year, event_type, details)
            VALUES (datetime('now'), ?, ?, ?, ?);
        """, (issuer_id, fiscal_year, event_type, details))
        self.conn.commit()

    def get_issuers(self, iso3: Optional[str] = None) -> List[Issuer]:
        if iso3:
            cur = self.conn.execute("SELECT * FROM issuers WHERE UPPER(iso3)=? ORDER BY ticker;", (iso3.upper(),))
        else:
            cur = self.conn.execute("SELECT * FROM issuers ORDER BY iso3, ticker;")
        return [Issuer.from_dict(dict(r)) for r in cur.fetchall()]

    def get_selected_candidates(self, repair: bool = False, required_class: str = "AR_FULL") -> List[sqlite3.Row]:
        """Return the best candidate per issuer and fiscal year.
        Strict rule: Only AR_FULL can satisfy final ZETA _AR_EN.pdf slots.
        """
        query = f"""
            SELECT 
                i.issuer_id, i.iso3, i.mic, i.ticker, i.company_name, i.isin, i.lei,
                s.fiscal_year, s.required_class, c.candidate_id, c.source_url, c.direct_url,
                c.title, c.document_class, c.language, c.fy_confidence, c.class_confidence,
                d.state as download_state, d.sha256, d.local_path
            FROM expected_slots s
            JOIN issuers i ON s.issuer_id = i.issuer_id
            JOIN candidates c ON s.issuer_id = c.issuer_id AND s.fiscal_year = c.resolved_fy
            LEFT JOIN downloads d ON c.candidate_id = d.candidate_id
            WHERE c.document_class = '{required_class}' AND c.language = 'EN'
        """
        if not repair:
            query += " AND (d.state IS NULL OR d.state NOT IN ('DONE', 'IDENTITY_MISSING'))"
        else:
            query += " AND (d.state IS NULL OR d.state = 'FAILED' OR s.status IN ('MISSING', 'MISSING_AR_FULL'))"
        query += " GROUP BY s.issuer_id, s.fiscal_year HAVING MAX(c.fy_confidence * 1000 + c.class_confidence) ORDER BY i.iso3, i.ticker, s.fiscal_year;"
        return list(self.conn.execute(query).fetchall())

    def get_coverage_stats(self) -> Dict[str, Any]:
        total_issuers = self.conn.execute("SELECT COUNT(*) FROM issuers;").fetchone()[0]
        total_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots;").fetchone()[0]
        done_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='DONE';").fetchone()[0]
        staged_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='IDENTITY_MISSING';").fetchone()[0]
        component_only = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='ANNUAL_COMPONENT_FOUND';").fetchone()[0]
        missing_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status IN ('MISSING', 'MISSING_AR_FULL');").fetchone()[0]
        failed_slots = self.conn.execute("SELECT COUNT(*) FROM expected_slots WHERE status='FAILED';").fetchone()[0]
        return {
            "total_issuers": total_issuers,
            "total_slots": total_slots,
            "done_slots": done_slots,
            "staged_slots": staged_slots,
            "component_only": component_only,
            "missing_slots": missing_slots,
            "failed_slots": failed_slots,
        }
