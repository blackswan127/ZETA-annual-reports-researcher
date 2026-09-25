from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .models import Filing, Issuer

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS issuers (
  ticker TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  industry TEXT,
  listing_date TEXT,
  source TEXT,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS scan_state (
  ticker TEXT NOT NULL,
  publication_year INTEGER NOT NULL,
  status TEXT NOT NULL,
  last_error TEXT,
  PRIMARY KEY (ticker, publication_year)
);
CREATE TABLE IF NOT EXISTS filings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  published_date TEXT NOT NULL,
  title TEXT NOT NULL,
  display_url TEXT NOT NULL,
  announcement_id TEXT NOT NULL,
  pages INTEGER,
  size_text TEXT,
  source_year INTEGER,
  fiscal_year INTEGER,
  year_method TEXT,
  score INTEGER NOT NULL,
  pdf_url TEXT,
  selected INTEGER NOT NULL DEFAULT 0,
  UNIQUE (ticker, announcement_id)
);
CREATE TABLE IF NOT EXISTS expected_slots (
  ticker TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'MISSING',
  selected_filing_id INTEGER,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  PRIMARY KEY (ticker, fiscal_year)
);
CREATE TABLE IF NOT EXISTS downloads (
  filing_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'PENDING',
  path TEXT,
  bytes INTEGER,
  sha256 TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  FOREIGN KEY (filing_id) REFERENCES filings(id)
);
CREATE INDEX IF NOT EXISTS idx_filings_slot ON filings(ticker, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_filings_selected ON filings(selected);
"""

class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    def upsert_issuers(self, issuers: list[Issuer]) -> None:
        # A refresh is a snapshot of today's listed universe. Keep old rows and
        # their reports for audit/history, but exclude delisted tickers from
        # future discovery and current-universe coverage.
        with self.conn:
            self.conn.execute("UPDATE issuers SET active=0")
            self.conn.executemany(
                """INSERT INTO issuers(ticker,name,industry,listing_date,source,active)
                   VALUES(?,?,?,?,?,1)
                   ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, industry=excluded.industry,
                     listing_date=excluded.listing_date, source=excluded.source, active=1""",
                [(i.ticker, i.name, i.industry, i.listing_date, i.source) for i in issuers],
            )

    def init_slots(self, start_year: int, end_year: int) -> None:
        rows = self.conn.execute("SELECT ticker FROM issuers WHERE active=1").fetchall()
        self.conn.executemany(
            "INSERT OR IGNORE INTO expected_slots(ticker,fiscal_year) VALUES(?,?)",
            [(r[0], y) for r in rows for y in range(start_year, end_year + 1)],
        )
        self.conn.commit()

    def scan_done(self, ticker: str, year: int) -> bool:
        row = self.conn.execute(
            "SELECT status FROM scan_state WHERE ticker=? AND publication_year=?", (ticker, year)
        ).fetchone()
        return bool(row and row[0] == "DONE")

    def mark_scan(self, ticker: str, year: int, status: str, error: str = "") -> None:
        self.conn.execute(
            """INSERT INTO scan_state(ticker,publication_year,status,last_error) VALUES(?,?,?,?)
               ON CONFLICT(ticker,publication_year) DO UPDATE SET status=excluded.status,last_error=excluded.last_error""",
            (ticker, year, status, error[:1000]),
        )
        self.conn.commit()

    def add_filings(self, filings: list[Filing]) -> None:
        self.conn.executemany(
            """INSERT INTO filings(ticker,published_date,title,display_url,announcement_id,pages,size_text,
               source_year,fiscal_year,year_method,score,pdf_url)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ticker,announcement_id) DO UPDATE SET
                 title=excluded.title,pages=excluded.pages,size_text=excluded.size_text,
                 fiscal_year=excluded.fiscal_year,year_method=excluded.year_method,score=excluded.score""",
            [
                (f.ticker, f.published_date.isoformat(), f.title, f.display_url, f.announcement_id,
                 f.pages, f.size_text, f.source_year, f.fiscal_year, f.year_method, f.score, f.pdf_url)
                for f in filings
            ],
        )
        self.conn.commit()

    def select_best(self, start_year: int, end_year: int) -> None:
        self.conn.execute("UPDATE filings SET selected=0")
        slots = self.conn.execute(
            """SELECT e.ticker,e.fiscal_year FROM expected_slots e
               JOIN issuers i ON i.ticker=e.ticker AND i.active=1
               WHERE e.fiscal_year BETWEEN ? AND ?""",
            (start_year, end_year),
        ).fetchall()
        for slot in slots:
            ticker, fy = slot[0], slot[1]
            candidates = self.conn.execute(
                """SELECT id,score,pages,published_date,year_method,title FROM filings
                   WHERE ticker=? AND fiscal_year=?
                   ORDER BY score DESC, COALESCE(pages,0) DESC, published_date DESC""",
                (ticker, fy),
            ).fetchall()
            if not candidates:
                self.conn.execute(
                    "UPDATE expected_slots SET status='MISSING',selected_filing_id=NULL,candidate_count=0,note='' WHERE ticker=? AND fiscal_year=?",
                    (ticker, fy),
                )
                continue
            best = candidates[0]
            self.conn.execute("UPDATE filings SET selected=1 WHERE id=?", (best[0],))
            note = ""
            if len(candidates) > 1:
                note = "multiple_candidates"
            if str(best[4]).startswith("publication_heuristic"):
                note = (note + ";" if note else "") + "heuristic_year"
            self.conn.execute(
                """UPDATE expected_slots SET status='FOUND',selected_filing_id=?,candidate_count=?,note=?
                   WHERE ticker=? AND fiscal_year=?""",
                (best[0], len(candidates), note, ticker, fy),
            )
            self.conn.execute("INSERT OR IGNORE INTO downloads(filing_id,status) VALUES(?,'PENDING')", (best[0],))
        self.conn.commit()

    def selected_pending(self):
        return self.conn.execute(
            """SELECT f.*, i.name, d.status download_status, d.path download_path
               FROM filings f JOIN issuers i ON i.ticker=f.ticker
               LEFT JOIN downloads d ON d.filing_id=f.id
               WHERE f.selected=1 AND COALESCE(d.status,'PENDING')!='DONE'
               ORDER BY f.ticker,f.fiscal_year"""
        ).fetchall()

    def set_pdf_url(self, filing_id: int, pdf_url: str) -> None:
        self.conn.execute("UPDATE filings SET pdf_url=? WHERE id=?", (pdf_url, filing_id))
        self.conn.commit()

    def mark_download(self, filing_id: int, status: str, path: str = "", size: int | None = None,
                      sha256: str = "", error: str = "") -> None:
        self.conn.execute(
            """INSERT INTO downloads(filing_id,status,path,bytes,sha256,attempts,last_error)
               VALUES(?,?,?,?,?,1,?)
               ON CONFLICT(filing_id) DO UPDATE SET status=excluded.status,path=excluded.path,
               bytes=excluded.bytes,sha256=excluded.sha256,attempts=downloads.attempts+1,last_error=excluded.last_error""",
            (filing_id, status, path, size, sha256, error[:1000]),
        )
        if status == "DONE":
            self.conn.execute(
                "UPDATE expected_slots SET status='DONE' WHERE selected_filing_id=?", (filing_id,)
            )
        elif status == "FAILED":
            self.conn.execute(
                "UPDATE expected_slots SET status='FAILED' WHERE selected_filing_id=?", (filing_id,)
            )
        self.conn.commit()

    def export_audits(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        queries = {
            "issuers.csv": "SELECT * FROM issuers ORDER BY ticker",
            "filings.csv": "SELECT * FROM filings ORDER BY ticker,fiscal_year,published_date",
            "coverage.csv": """SELECT e.ticker,i.name,e.fiscal_year,e.status,e.candidate_count,e.note,
                f.title,f.published_date,f.display_url,f.pdf_url,d.path,d.bytes,d.sha256,d.last_error
                FROM expected_slots e JOIN issuers i USING(ticker)
                LEFT JOIN filings f ON f.id=e.selected_filing_id
                LEFT JOIN downloads d ON d.filing_id=f.id
                WHERE i.active=1
                ORDER BY e.ticker,e.fiscal_year""",
            "missing.csv": """SELECT e.ticker,i.name,e.fiscal_year,e.status,e.note FROM expected_slots e
                JOIN issuers i USING(ticker) WHERE i.active=1 AND e.status IN ('MISSING','FAILED') ORDER BY e.ticker,e.fiscal_year""",
            "multiple_candidates.csv": """SELECT e.ticker,i.name,e.fiscal_year,e.candidate_count,e.note
                FROM expected_slots e JOIN issuers i USING(ticker) WHERE i.active=1 AND e.candidate_count>1 ORDER BY e.ticker,e.fiscal_year""",
            "heuristic_years.csv": """SELECT e.ticker,i.name,e.fiscal_year,f.title,f.published_date,f.year_method
                FROM expected_slots e JOIN issuers i USING(ticker) JOIN filings f ON f.id=e.selected_filing_id
                WHERE i.active=1 AND f.year_method LIKE 'publication_heuristic%' ORDER BY e.ticker,e.fiscal_year""",
            "failed_downloads.csv": """SELECT f.ticker,f.fiscal_year,f.title,d.status,d.attempts,d.last_error
                FROM downloads d JOIN filings f ON f.id=d.filing_id WHERE d.status='FAILED' ORDER BY f.ticker,f.fiscal_year""",
        }
        for filename, query in queries.items():
            rows = self.conn.execute(query).fetchall()
            path = root / filename
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                if rows:
                    writer.writerow(rows[0].keys())
                    writer.writerows([tuple(r) for r in rows])
                else:
                    writer.writerow([])
