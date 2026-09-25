from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS active_securities (
    code TEXT PRIMARY KEY,
    hkex_id TEXT NOT NULL,
    name_en TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filings (
    news_id TEXT PRIMARY KEY,
    canonical_code TEXT,
    stock_codes TEXT NOT NULL,
    stock_name TEXT NOT NULL,
    title TEXT NOT NULL,
    long_text TEXT NOT NULL,
    published_at TEXT,
    file_type TEXT,
    file_info TEXT,
    file_link TEXT,
    file_url TEXT,
    fiscal_year INTEGER,
    year_source TEXT,
    year_confidence TEXT,
    score REAL NOT NULL DEFAULT 0,
    current_listed INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filings_code_year ON filings(canonical_code, fiscal_year);
CREATE INDEX IF NOT EXISTS idx_filings_current ON filings(current_listed, fiscal_year);

CREATE TABLE IF NOT EXISTS downloads (
    news_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'PENDING',
    local_path TEXT,
    bytes INTEGER,
    sha256 TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(news_id) REFERENCES filings(news_id)
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_active(self, rows: Iterable[dict], fetched_at: str) -> int:
        items = [(str(r["i"]), str(r["c"]), str(r.get("n", ""))) for r in rows if r.get("i") is not None and r.get("c")]
        self.conn.executemany(
            "INSERT INTO active_securities(hkex_id,code,name_en,fetched_at) VALUES(?,?,?,?) "
            "ON CONFLICT(code) DO UPDATE SET hkex_id=excluded.hkex_id,name_en=excluded.name_en,fetched_at=excluded.fetched_at",
            [(i, c, n, fetched_at) for i, c, n in items],
        )
        self.conn.commit()
        return len(items)

    def active_codes(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT code FROM active_securities")}

    def active_id_for_code(self, code: str) -> str | None:
        row = self.conn.execute("SELECT hkex_id FROM active_securities WHERE code=?", (code,)).fetchone()
        return str(row[0]) if row else None

    def upsert_filing(self, row: dict) -> None:
        cols = (
            "news_id","canonical_code","stock_codes","stock_name","title","long_text","published_at",
            "file_type","file_info","file_link","file_url","fiscal_year","year_source","year_confidence",
            "score","current_listed","raw_json"
        )
        vals = tuple(row.get(c) for c in cols)
        placeholders = ",".join("?" for _ in cols)
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "news_id")
        self.conn.execute(
            f"INSERT INTO filings({','.join(cols)}) VALUES({placeholders}) ON CONFLICT(news_id) DO UPDATE SET {updates}", vals
        )
        self.conn.execute("INSERT OR IGNORE INTO downloads(news_id) VALUES(?)", (row["news_id"],))

    def commit(self) -> None:
        self.conn.commit()

    def select_primaries(self, start_year: int, end_year: int) -> int:
        self.conn.execute("UPDATE filings SET selected=0")
        rows = self.conn.execute(
            """
            SELECT news_id, canonical_code, fiscal_year, score, published_at
            FROM filings
            WHERE current_listed=1 AND fiscal_year BETWEEN ? AND ? AND canonical_code IS NOT NULL
            ORDER BY canonical_code, fiscal_year, score DESC, published_at DESC
            """, (start_year, end_year)
        ).fetchall()
        seen: set[tuple[str,int]] = set()
        chosen: list[str] = []
        for r in rows:
            key = (r["canonical_code"], int(r["fiscal_year"]))
            if key in seen:
                continue
            seen.add(key)
            chosen.append(r["news_id"])
        self.conn.executemany("UPDATE filings SET selected=1 WHERE news_id=?", [(n,) for n in chosen])
        self.conn.commit()
        return len(chosen)

    def selected_pending(self, limit: int | None = None) -> list[sqlite3.Row]:
        sql = """
        SELECT f.*, d.state, d.local_path, d.attempts
        FROM filings f JOIN downloads d USING(news_id)
        WHERE f.selected=1 AND d.state!='DONE'
        ORDER BY f.canonical_code, f.fiscal_year
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.conn.execute(sql).fetchall()

    def selected_all(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT f.*, d.state, d.local_path, d.bytes, d.sha256, d.error FROM filings f JOIN downloads d USING(news_id) WHERE f.selected=1 ORDER BY f.canonical_code,f.fiscal_year"
        ).fetchall()

    def set_download(self, news_id: str, state: str, *, local_path: str | None = None, bytes_: int | None = None,
                     sha256: str | None = None, http_status: int | None = None, error: str | None = None,
                     increment_attempt: bool = False) -> None:
        self.conn.execute(
            """
            UPDATE downloads SET state=?, local_path=COALESCE(?,local_path), bytes=COALESCE(?,bytes),
              sha256=COALESCE(?,sha256), http_status=?, error=?,
              attempts=attempts+?, updated_at=CURRENT_TIMESTAMP WHERE news_id=?
            """,
            (state, local_path, bytes_, sha256, http_status, error, 1 if increment_attempt else 0, news_id),
        )
        self.conn.commit()

    def reset_in_progress(self) -> None:
        self.conn.execute("UPDATE downloads SET state='PENDING' WHERE state='DOWNLOADING'")
        self.conn.commit()

    def counts(self) -> dict[str, int]:
        q = {
            "active_securities": "SELECT count(*) FROM active_securities",
            "annual_candidates": "SELECT count(*) FROM filings WHERE current_listed=1",
            "selected_reports": "SELECT count(*) FROM filings WHERE selected=1",
            "downloaded": "SELECT count(*) FROM downloads d JOIN filings f USING(news_id) WHERE f.selected=1 AND d.state='DONE'",
            "failed": "SELECT count(*) FROM downloads d JOIN filings f USING(news_id) WHERE f.selected=1 AND d.state='FAILED'",
            "pending": "SELECT count(*) FROM downloads d JOIN filings f USING(news_id) WHERE f.selected=1 AND d.state NOT IN ('DONE','FAILED')",
        }
        return {k: int(self.conn.execute(v).fetchone()[0]) for k, v in q.items()}

    def export_csvs(self, output: Path, start_year: int, end_year: int) -> None:
        output.mkdir(parents=True, exist_ok=True)
        self._export_query(output / "active_securities.csv", "SELECT * FROM active_securities ORDER BY code")
        self._export_query(output / "reports.csv", """
            SELECT f.canonical_code AS stock_code,f.stock_name,f.fiscal_year,f.year_source,f.year_confidence,
                   f.title,f.long_text,f.published_at,f.file_type,f.file_info,f.file_url,f.news_id,f.score,
                   d.state,d.local_path,d.bytes,d.sha256,d.error
            FROM filings f JOIN downloads d USING(news_id)
            WHERE f.selected=1 ORDER BY f.canonical_code,f.fiscal_year
        """)
        self._export_query(output / "ambiguous_years.csv", """
            SELECT canonical_code,stock_name,title,published_at,fiscal_year,year_source,year_confidence,file_url,news_id
            FROM filings WHERE current_listed=1 AND year_confidence!='high' ORDER BY canonical_code,published_at
        """)
        self._export_query(output / "multi_file_candidates.csv", """
            SELECT canonical_code,stock_name,title,published_at,fiscal_year,file_type,file_info,file_url,news_id
            FROM filings WHERE current_listed=1 AND (lower(file_info) LIKE '%multi%' OR lower(file_type) LIKE '%multi%')
            ORDER BY canonical_code,published_at
        """)
        self._export_query(output / "failed_downloads.csv", """
            SELECT f.canonical_code,f.stock_name,f.fiscal_year,f.title,f.file_url,d.state,d.attempts,d.http_status,d.error
            FROM filings f JOIN downloads d USING(news_id) WHERE f.selected=1 AND d.state='FAILED'
            ORDER BY f.canonical_code,f.fiscal_year
        """)

        # Coverage matrix begins at the first observed target-year report for each issuer,
        # avoiding false "missing" flags for obvious pre-listing years.
        rows = self.conn.execute(
            "SELECT canonical_code,stock_name,fiscal_year FROM filings WHERE selected=1 ORDER BY canonical_code,fiscal_year"
        ).fetchall()
        by_code: dict[str, dict] = {}
        for r in rows:
            code = r["canonical_code"]
            by_code.setdefault(code, {"stock_name": r["stock_name"], "years": set()})["years"].add(int(r["fiscal_year"]))
        with (output / "coverage.csv").open("w", newline="", encoding="utf-8-sig") as f:
            fields = ["stock_code","stock_name","first_observed_year"] + [str(y) for y in range(start_year,end_year+1)] + ["missing_after_first_observed"]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for code, info in sorted(by_code.items()):
                years = info["years"]
                first = min(years) if years else None
                row = {"stock_code":code,"stock_name":info["stock_name"],"first_observed_year":first or ""}
                missing: list[str] = []
                for y in range(start_year,end_year+1):
                    row[str(y)] = "YES" if y in years else ""
                    if first is not None and y >= first and y not in years:
                        missing.append(str(y))
                row["missing_after_first_observed"] = ";".join(missing)
                w.writerow(row)

    def _export_query(self, path: Path, sql: str) -> None:
        rows = self.conn.execute(sql).fetchall()
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
