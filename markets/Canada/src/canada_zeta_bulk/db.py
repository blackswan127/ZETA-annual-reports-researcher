from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Candidate, Issuer

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS issuers (
  issuer_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  ticker TEXT NOT NULL,
  exchange_mic TEXT NOT NULL,
  security_type TEXT,
  industry TEXT,
  listing_date TEXT,
  website TEXT,
  isin TEXT,
  lei TEXT,
  sedar_profile TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  eligible INTEGER NOT NULL DEFAULT 1,
  source TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_issuer_exchange_ticker ON issuers(exchange_mic,ticker);
CREATE TABLE IF NOT EXISTS expected_slots (
  issuer_key TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  report_type TEXT NOT NULL DEFAULT 'AR',
  language TEXT NOT NULL DEFAULT 'EN',
  status TEXT NOT NULL DEFAULT 'MISSING',
  selected_candidate_id INTEGER,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  PRIMARY KEY(issuer_key,fiscal_year,report_type,language),
  FOREIGN KEY(issuer_key) REFERENCES issuers(issuer_key)
);
CREATE TABLE IF NOT EXISTS candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issuer_key TEXT NOT NULL,
  fiscal_year INTEGER NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  source TEXT NOT NULL,
  source_priority INTEGER NOT NULL,
  report_type TEXT NOT NULL DEFAULT 'AR',
  language TEXT NOT NULL DEFAULT 'EN',
  published_date TEXT,
  period_end TEXT,
  document_id TEXT,
  score INTEGER NOT NULL DEFAULT 0,
  provenance TEXT,
  selected INTEGER NOT NULL DEFAULT 0,
  UNIQUE(issuer_key,fiscal_year,url),
  FOREIGN KEY(issuer_key) REFERENCES issuers(issuer_key)
);
CREATE INDEX IF NOT EXISTS idx_candidates_slot ON candidates(issuer_key,fiscal_year,report_type,language);
CREATE TABLE IF NOT EXISTS downloads (
  candidate_id INTEGER PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'PENDING',
  staging_path TEXT,
  final_path TEXT,
  bytes INTEGER,
  pages INTEGER,
  sha256 TEXT,
  validation_status TEXT,
  semantic_status TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  completed_at TEXT,
  FOREIGN KEY(candidate_id) REFERENCES candidates(id)
);
CREATE TABLE IF NOT EXISTS source_profiles (
  issuer_key TEXT NOT NULL,
  source TEXT NOT NULL,
  base_url TEXT,
  health TEXT NOT NULL DEFAULT 'UNKNOWN',
  last_success TEXT,
  last_error TEXT,
  notes TEXT,
  PRIMARY KEY(issuer_key,source),
  FOREIGN KEY(issuer_key) REFERENCES issuers(issuer_key)
);
CREATE TABLE IF NOT EXISTS discovery_state (
  issuer_key TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  last_error TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(issuer_key,source)
);
CREATE TABLE IF NOT EXISTS identifier_candidates (
  issuer_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'CANDIDATE',
  note TEXT,
  PRIMARY KEY(issuer_key,kind,value)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
  level TEXT NOT NULL,
  stage TEXT NOT NULL,
  issuer_key TEXT,
  fiscal_year INTEGER,
  message TEXT NOT NULL
);
"""

class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def log(self, level: str, stage: str, message: str, issuer_key: str | None = None, fiscal_year: int | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events(level,stage,issuer_key,fiscal_year,message) VALUES(?,?,?,?,?)",
            (level, stage, issuer_key, fiscal_year, message[:4000]),
        )
        self.conn.commit()

    def upsert_issuers(self, issuers: Iterable[Issuer]) -> int:
        rows = list(issuers)
        self.conn.execute("UPDATE issuers SET active=0")
        self.conn.executemany(
            """INSERT INTO issuers(issuer_key,name,ticker,exchange_mic,security_type,industry,listing_date,
                 website,isin,lei,sedar_profile,active,eligible,source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(issuer_key) DO UPDATE SET
                 name=excluded.name,ticker=excluded.ticker,exchange_mic=excluded.exchange_mic,
                 security_type=excluded.security_type,industry=excluded.industry,listing_date=excluded.listing_date,
                 website=CASE WHEN excluded.website<>'' THEN excluded.website ELSE issuers.website END,
                 isin=CASE WHEN excluded.isin<>'' THEN excluded.isin ELSE issuers.isin END,
                 lei=CASE WHEN excluded.lei<>'' THEN excluded.lei ELSE issuers.lei END,
                 sedar_profile=CASE WHEN excluded.sedar_profile<>'' THEN excluded.sedar_profile ELSE issuers.sedar_profile END,
                 active=excluded.active,eligible=excluded.eligible,source=excluded.source,updated_at=CURRENT_TIMESTAMP""",
            [(
                i.issuer_key,i.name,i.ticker,i.exchange_mic,i.security_type,i.industry,i.listing_date,
                i.website,i.isin,i.lei,i.sedar_profile,1 if i.active else 0,1 if i.eligible else 0,i.source
            ) for i in rows],
        )
        self.conn.commit()
        return len(rows)

    def apply_identity_overrides(self, rows: list[dict[str,str]]) -> int:
        n = 0
        for r in rows:
            key = (r.get("issuer_key") or "").strip()
            ticker = (r.get("ticker") or "").strip().upper()
            mic = (r.get("exchange_mic") or r.get("mic") or "").strip().upper()
            if not key and ticker and mic:
                found = self.conn.execute("SELECT issuer_key FROM issuers WHERE ticker=? AND exchange_mic=?", (ticker,mic)).fetchone()
                key = found[0] if found else ""
            if not key:
                continue
            sets, vals = [], []
            for col in ("lei","isin","website","sedar_profile"):
                v = (r.get(col) or "").strip()
                if v:
                    sets.append(f"{col}=?"); vals.append(v)
            if sets:
                vals.append(key)
                self.conn.execute(f"UPDATE issuers SET {','.join(sets)},updated_at=CURRENT_TIMESTAMP WHERE issuer_key=?", vals)
                n += 1
        self.conn.commit()
        return n

    def init_slots(self, start_year: int, end_year: int, language: str = "EN") -> int:
        issuers = self.conn.execute("SELECT issuer_key,listing_date FROM issuers WHERE active=1 AND eligible=1").fetchall()
        rows = []
        for i in issuers:
            listing_year = None
            if i[1]:
                try: listing_year = int(str(i[1])[:4])
                except Exception: listing_year = None
            for y in range(start_year, end_year + 1):
                if listing_year and y < listing_year:
                    continue
                rows.append((i[0],y,"AR",language))
        self.conn.executemany(
            "INSERT OR IGNORE INTO expected_slots(issuer_key,fiscal_year,report_type,language) VALUES(?,?,?,?)", rows
        )
        self.conn.commit()
        return len(rows)

    def add_candidates(self, candidates: Iterable[Candidate]) -> int:
        rows = list(candidates)
        self.conn.executemany(
            """INSERT INTO candidates(issuer_key,fiscal_year,title,url,source,source_priority,report_type,language,
                 published_date,period_end,document_id,score,provenance)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(issuer_key,fiscal_year,url) DO UPDATE SET
                 title=excluded.title,source_priority=excluded.source_priority,language=excluded.language,
                 published_date=excluded.published_date,period_end=excluded.period_end,document_id=excluded.document_id,
                 score=excluded.score,provenance=excluded.provenance""",
            [(
                c.issuer_key,c.fiscal_year,c.title,c.url,c.source,c.source_priority,c.report_type,c.language,
                c.published_date,c.period_end,c.document_id,c.score,c.provenance
            ) for c in rows],
        )
        self.conn.commit()
        return len(rows)

    def select_best(self, start_year: int, end_year: int, language: str = "EN", include_french: bool = False) -> None:
        self.conn.execute("UPDATE candidates SET selected=0")
        slots = self.conn.execute(
            "SELECT issuer_key,fiscal_year,report_type,language FROM expected_slots WHERE fiscal_year BETWEEN ? AND ?",
            (start_year,end_year),
        ).fetchall()
        for s in slots:
            langs = [language]
            if include_french and "FR" not in langs: langs.append("FR")
            qmarks = ",".join("?" for _ in langs)
            cand = self.conn.execute(
                f"""SELECT id,source_priority,score,language,title FROM candidates
                    WHERE issuer_key=? AND fiscal_year=? AND report_type='AR' AND language IN ({qmarks})
                    ORDER BY CASE WHEN language=? THEN 0 ELSE 1 END, source_priority ASC, score DESC, id ASC""",
                (s[0],s[1],*langs,language),
            ).fetchall()
            if not cand:
                self.conn.execute(
                    "UPDATE expected_slots SET status='MISSING',selected_candidate_id=NULL,candidate_count=0,note='' WHERE issuer_key=? AND fiscal_year=? AND language=?",
                    (s[0],s[1],s[3]),
                )
                continue
            best = cand[0]
            self.conn.execute("UPDATE candidates SET selected=1 WHERE id=?", (best[0],))
            note = "multiple_candidates" if len(cand)>1 else ""
            self.conn.execute(
                """UPDATE expected_slots SET status='FOUND',selected_candidate_id=?,candidate_count=?,note=?
                   WHERE issuer_key=? AND fiscal_year=? AND language=?""",
                (best[0],len(cand),note,s[0],s[1],s[3]),
            )
            self.conn.execute("INSERT OR IGNORE INTO downloads(candidate_id,status) VALUES(?,'PENDING')", (best[0],))
        self.conn.commit()

    def pending_downloads(self):
        return self.conn.execute(
            """SELECT c.*, i.*,
                      d.status AS download_status,d.staging_path,d.final_path
               FROM candidates c JOIN issuers i USING(issuer_key)
               JOIN downloads d ON d.candidate_id=c.id
               WHERE c.selected=1 AND d.status<>'DONE'
               ORDER BY i.exchange_mic,i.ticker,c.fiscal_year"""
        ).fetchall()

    def mark_download(self, candidate_id: int, status: str, *, staging_path: str="", final_path: str="", bytes_: int|None=None,
                      pages: int|None=None, sha256: str="", validation_status: str="", semantic_status: str="", error: str="") -> None:
        self.conn.execute(
            """UPDATE downloads SET status=?,staging_path=?,final_path=?,bytes=?,pages=?,sha256=?,validation_status=?,semantic_status=?,
               attempts=attempts+1,last_error=?,completed_at=CASE WHEN ?='DONE' THEN CURRENT_TIMESTAMP ELSE completed_at END
               WHERE candidate_id=?""",
            (status,staging_path,final_path,bytes_,pages,sha256,validation_status,semantic_status,error[:2000],status,candidate_id),
        )
        if status == "DONE":
            self.conn.execute(
                "UPDATE expected_slots SET status='DONE' WHERE selected_candidate_id=?", (candidate_id,)
            )
        elif status == "FAILED":
            self.conn.execute(
                "UPDATE expected_slots SET status='FAILED' WHERE selected_candidate_id=?", (candidate_id,)
            )
        self.conn.commit()

    def set_source_profile(self, issuer_key: str, source: str, base_url: str = "", health: str = "UNKNOWN", error: str = "", notes: str = "") -> None:
        self.conn.execute(
            """INSERT INTO source_profiles(issuer_key,source,base_url,health,last_success,last_error,notes)
               VALUES(?,?,?,?,CASE WHEN ?='OK' THEN CURRENT_TIMESTAMP ELSE NULL END,?,?)
               ON CONFLICT(issuer_key,source) DO UPDATE SET base_url=excluded.base_url,health=excluded.health,
                 last_success=CASE WHEN excluded.health='OK' THEN CURRENT_TIMESTAMP ELSE source_profiles.last_success END,
                 last_error=excluded.last_error,notes=excluded.notes""",
            (issuer_key,source,base_url,health,health,error[:2000],notes[:2000]),
        )
        self.conn.commit()

    def source_state(self, issuer_key: str, source: str, status: str, error: str="") -> None:
        self.conn.execute(
            """INSERT INTO discovery_state(issuer_key,source,status,last_error) VALUES(?,?,?,?)
               ON CONFLICT(issuer_key,source) DO UPDATE SET status=excluded.status,last_error=excluded.last_error,updated_at=CURRENT_TIMESTAMP""",
            (issuer_key,source,status,error[:2000]),
        )
        self.conn.commit()

    def unresolved_identity(self):
        return self.conn.execute(
            "SELECT * FROM issuers WHERE active=1 AND eligible=1 AND (COALESCE(lei,'')='' OR COALESCE(isin,'')='') ORDER BY exchange_mic,ticker"
        ).fetchall()

    def missing_slots(self):
        return self.conn.execute(
            """SELECT e.*,i.name,i.ticker,i.exchange_mic,i.website,i.isin,i.lei FROM expected_slots e
               JOIN issuers i USING(issuer_key) WHERE e.status IN ('MISSING','FAILED') ORDER BY i.exchange_mic,i.ticker,e.fiscal_year"""
        ).fetchall()

    def export_audits(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        queries = {
            "issuers.csv": "SELECT * FROM issuers ORDER BY exchange_mic,ticker",
            "expected_slots.csv": "SELECT * FROM expected_slots ORDER BY issuer_key,fiscal_year",
            "candidates.csv": "SELECT * FROM candidates ORDER BY issuer_key,fiscal_year,source_priority,score DESC",
            "coverage.csv": """SELECT i.exchange_mic,i.ticker,i.name,i.lei,i.isin,e.fiscal_year,e.status,e.candidate_count,e.note,
                   c.source,c.title,c.url,d.final_path,d.staging_path,d.bytes,d.pages,d.sha256,d.validation_status,d.semantic_status,d.last_error
                   FROM expected_slots e JOIN issuers i USING(issuer_key)
                   LEFT JOIN candidates c ON c.id=e.selected_candidate_id
                   LEFT JOIN downloads d ON d.candidate_id=c.id
                   ORDER BY i.exchange_mic,i.ticker,e.fiscal_year""",
            "missing.csv": """SELECT i.exchange_mic,i.ticker,i.name,i.website,i.lei,i.isin,e.fiscal_year,e.status,e.note
                   FROM expected_slots e JOIN issuers i USING(issuer_key)
                   WHERE e.status IN ('MISSING','FAILED') ORDER BY i.exchange_mic,i.ticker,e.fiscal_year""",
            "identity_missing.csv": """SELECT exchange_mic,ticker,name,website,isin,lei,sedar_profile,source
                   FROM issuers WHERE active=1 AND eligible=1 AND (COALESCE(lei,'')='' OR COALESCE(isin,'')='') ORDER BY exchange_mic,ticker""",
            "source_profiles.csv": "SELECT * FROM source_profiles ORDER BY issuer_key,source",
            "discovery_state.csv": "SELECT * FROM discovery_state ORDER BY issuer_key,source",
            "failed_downloads.csv": """SELECT i.exchange_mic,i.ticker,c.fiscal_year,c.source,c.url,d.status,d.last_error
                   FROM downloads d JOIN candidates c ON c.id=d.candidate_id JOIN issuers i USING(issuer_key)
                   WHERE d.status='FAILED' ORDER BY i.exchange_mic,i.ticker,c.fiscal_year""",
            "events.csv": "SELECT * FROM events ORDER BY id",
        }
        for name,q in queries.items():
            rows = self.conn.execute(q).fetchall()
            with (out/name).open("w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                if rows:
                    w.writerow(rows[0].keys()); w.writerows([tuple(r) for r in rows])
                else:
                    w.writerow([])

        # Human-readable universe summary used by ZETA operators to record the
        # current TSX/TSXV population loaded for this run. Counts are generated
        # from the official universe file at runtime instead of being hard-coded.
        summary_rows = self.conn.execute(
            """SELECT exchange_mic,
                      count(*) AS current_rows,
                      sum(CASE WHEN eligible=1 THEN 1 ELSE 0 END) AS eligible_companies,
                      sum(CASE WHEN eligible=0 THEN 1 ELSE 0 END) AS excluded_products
               FROM issuers WHERE active=1 GROUP BY exchange_mic ORDER BY exchange_mic"""
        ).fetchall()
        with (out/"universe_summary.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w=csv.writer(fh); w.writerow(["exchange_mic","current_rows","eligible_companies","excluded_products"])
            for r in summary_rows: w.writerow(tuple(r))
            total=self.conn.execute(
                "SELECT count(*),sum(CASE WHEN eligible=1 THEN 1 ELSE 0 END),sum(CASE WHEN eligible=0 THEN 1 ELSE 0 END) FROM issuers WHERE active=1"
            ).fetchone()
            w.writerow(["TOTAL",total[0] or 0,total[1] or 0,total[2] or 0])

        # A dedicated machine/action queue for the repair pass.
        repair_rows = self.conn.execute(
            """SELECT i.issuer_key,i.exchange_mic,i.ticker,i.name,i.website,i.lei,i.isin,
                      e.fiscal_year,e.status,e.note
               FROM expected_slots e JOIN issuers i USING(issuer_key)
               WHERE i.active=1 AND i.eligible=1 AND e.status IN ('MISSING','FAILED')
               ORDER BY i.exchange_mic,i.ticker,e.fiscal_year"""
        ).fetchall()
        with (out/"repair_queue.csv").open("w", newline="", encoding="utf-8-sig") as fh:
            w=csv.writer(fh)
            if repair_rows:
                w.writerow(repair_rows[0].keys()); w.writerows([tuple(r) for r in repair_rows])
            else:
                w.writerow(["issuer_key","exchange_mic","ticker","name","website","lei","isin","fiscal_year","status","note"])

    def summary(self) -> dict[str,int]:
        result = {}
        for r in self.conn.execute("SELECT status,count(*) n FROM expected_slots GROUP BY status"):
            result[r[0]] = r[1]
        result["issuers_active_eligible"] = self.conn.execute("SELECT count(*) FROM issuers WHERE active=1 AND eligible=1").fetchone()[0]
        result["identity_missing"] = self.conn.execute("SELECT count(*) FROM issuers WHERE active=1 AND eligible=1 AND (COALESCE(lei,'')='' OR COALESCE(isin,'')='')").fetchone()[0]
        result["candidates"] = self.conn.execute("SELECT count(*) FROM candidates").fetchone()[0]
        return result
