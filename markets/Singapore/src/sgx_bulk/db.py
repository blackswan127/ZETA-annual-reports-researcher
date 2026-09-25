from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Attachment, Filing, Issuer

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS issuers (
  ibm_code TEXT PRIMARY KEY,
  stock_code TEXT NOT NULL,
  ticker TEXT NOT NULL,
  issuer_name TEXT NOT NULL,
  short_name TEXT NOT NULL,
  market TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS filings (
  announcement_id TEXT PRIMARY KEY,
  ibm_code TEXT NOT NULL,
  stock_code TEXT NOT NULL,
  issuer_name TEXT NOT NULL,
  short_name TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  period_end TEXT NOT NULL,
  broadcast_at TEXT NOT NULL,
  detail_url TEXT NOT NULL,
  title TEXT NOT NULL,
  source_mode TEXT NOT NULL DEFAULT 'global',
  mapping_reason TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_filings_issuer_year ON filings(ibm_code, fiscal_year);
CREATE TABLE IF NOT EXISTS attachments (
  url TEXT PRIMARY KEY,
  announcement_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  score INTEGER NOT NULL,
  selected INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'discovered',
  local_path TEXT,
  size_bytes INTEGER,
  sha256 TEXT,
  error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_attachments_status ON attachments(status, selected);
CREATE TABLE IF NOT EXISTS unmapped_reports (
  announcement_id TEXT PRIMARY KEY,
  company_name TEXT,
  security_name TEXT,
  fiscal_year INTEGER,
  detail_url TEXT,
  reason TEXT
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_issuers(self, issuers: Iterable[Issuer]) -> None:
        self.conn.executemany(
            """INSERT INTO issuers(ibm_code, stock_code, ticker, issuer_name, short_name, market)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(ibm_code) DO UPDATE SET
                 stock_code=excluded.stock_code, ticker=excluded.ticker,
                 issuer_name=excluded.issuer_name, short_name=excluded.short_name,
                 market=excluded.market, updated_at=CURRENT_TIMESTAMP""",
            [(i.ibm_code, i.stock_code, i.ticker, i.issuer_name, i.short_name, i.market) for i in issuers],
        )
        self.conn.commit()

    def upsert_filing(self, filing: Filing, source_mode: str, mapping_reason: str) -> None:
        self.conn.execute(
            """INSERT INTO filings(announcement_id, ibm_code, stock_code, issuer_name, short_name,
               fiscal_year, period_end, broadcast_at, detail_url, title, source_mode, mapping_reason)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(announcement_id) DO UPDATE SET
                 ibm_code=excluded.ibm_code, stock_code=excluded.stock_code,
                 issuer_name=excluded.issuer_name, short_name=excluded.short_name,
                 fiscal_year=excluded.fiscal_year, period_end=excluded.period_end,
                 broadcast_at=excluded.broadcast_at, detail_url=excluded.detail_url,
                 title=excluded.title, source_mode=excluded.source_mode,
                 mapping_reason=excluded.mapping_reason, updated_at=CURRENT_TIMESTAMP""",
            (
                filing.announcement_id, filing.ibm_code, filing.stock_code, filing.issuer_name,
                filing.short_name, filing.fiscal_year, filing.period_end.isoformat(),
                filing.broadcast_at.isoformat(), filing.detail_url, filing.title,
                source_mode, mapping_reason,
            ),
        )
        self.conn.commit()

    def add_unmapped(self, row: dict, fiscal_year: int | None, reason: str) -> None:
        ann = str(row.get("id") or "").strip().upper()
        if not ann:
            return
        self.conn.execute(
            """INSERT OR REPLACE INTO unmapped_reports
               (announcement_id, company_name, security_name, fiscal_year, detail_url, reason)
               VALUES(?,?,?,?,?,?)""",
            (ann, row.get("companyName"), row.get("securityName"), fiscal_year, row.get("url"), reason),
        )
        self.conn.commit()

    def replace_attachments(self, announcement_id: str, attachments: list[Attachment], selected_urls: set[str]) -> None:
        for a in attachments:
            self.conn.execute(
                """INSERT INTO attachments(url, announcement_id, filename, score, selected)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(url) DO UPDATE SET filename=excluded.filename,
                   score=excluded.score, selected=excluded.selected, updated_at=CURRENT_TIMESTAMP""",
                (a.url, announcement_id, a.filename, a.score, 1 if a.url in selected_urls else 0),
            )
        self.conn.commit()

    def filings_needing_resolution(self) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        return self.conn.execute(
            """SELECT f.* FROM filings f
               WHERE NOT EXISTS (SELECT 1 FROM attachments a WHERE a.announcement_id=f.announcement_id)
               ORDER BY f.fiscal_year, f.stock_code"""
        ).fetchall()

    def selected_downloads(self, retry_failed: bool = True) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        statuses = ("discovered", "failed") if retry_failed else ("discovered",)
        qmarks = ",".join("?" for _ in statuses)
        return self.conn.execute(
            f"""SELECT a.*, f.ibm_code, f.stock_code, f.issuer_name, f.fiscal_year
                FROM attachments a JOIN filings f USING(announcement_id)
                WHERE a.selected=1 AND a.status IN ({qmarks})
                ORDER BY f.fiscal_year, f.stock_code, a.filename""",
            statuses,
        ).fetchall()

    def mark_download(self, url: str, *, status: str, local_path: str | None = None,
                      size_bytes: int | None = None, sha256: str | None = None,
                      error: str | None = None, increment_attempt: bool = False) -> None:
        self.conn.execute(
            """UPDATE attachments SET status=?, local_path=COALESCE(?,local_path),
               size_bytes=COALESCE(?,size_bytes), sha256=COALESCE(?,sha256), error=?,
               attempts=attempts+?, updated_at=CURRENT_TIMESTAMP WHERE url=?""",
            (status, local_path, size_bytes, sha256, error, 1 if increment_attempt else 0, url),
        )
        self.conn.commit()

    def reset_stale_downloading(self) -> None:
        self.conn.execute("UPDATE attachments SET status='failed', error='Interrupted previous run' WHERE status='downloading'")
        self.conn.commit()
