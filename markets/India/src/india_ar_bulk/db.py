from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from .models import Candidate, Issuer

SCHEMA="""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS issuers(
 issuer_key TEXT PRIMARY KEY, isin TEXT, name TEXT NOT NULL, nse_symbol TEXT, nse_series TEXT,
 nse_sme INTEGER NOT NULL DEFAULT 0, bse_scrip TEXT, bse_group TEXT, source_flags TEXT, active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS universe_stats(k TEXT PRIMARY KEY,v INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_state(issuer_key TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
 last_error TEXT, PRIMARY KEY(issuer_key,source));
CREATE TABLE IF NOT EXISTS candidates(
 id INTEGER PRIMARY KEY AUTOINCREMENT, issuer_key TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
 source TEXT NOT NULL, source_id TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
 published_at TEXT, from_year INTEGER, to_year INTEGER, file_kind TEXT, score INTEGER NOT NULL,
 selected INTEGER NOT NULL DEFAULT 0, note TEXT,
 UNIQUE(issuer_key,source,source_id)
);
CREATE TABLE IF NOT EXISTS expected_slots(
 issuer_key TEXT NOT NULL, fiscal_year INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'MISSING',
 selected_candidate_id INTEGER, candidate_count INTEGER NOT NULL DEFAULT 0, note TEXT,
 PRIMARY KEY(issuer_key,fiscal_year)
);
CREATE TABLE IF NOT EXISTS downloads(
 candidate_id INTEGER PRIMARY KEY,status TEXT NOT NULL DEFAULT 'PENDING',path TEXT,bytes INTEGER,sha256 TEXT,
 attempts INTEGER NOT NULL DEFAULT 0,last_error TEXT,archive_parts INTEGER NOT NULL DEFAULT 0,
 FOREIGN KEY(candidate_id) REFERENCES candidates(id)
);
CREATE INDEX IF NOT EXISTS idx_candidate_slot ON candidates(issuer_key,fiscal_year);
CREATE INDEX IF NOT EXISTS idx_candidate_selected ON candidates(selected);
"""

class Database:
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True); self.path=path
        self.conn=sqlite3.connect(path); self.conn.row_factory=sqlite3.Row; self.conn.executescript(SCHEMA)
    def close(self): self.conn.close()
    def replace_universe(self,issuers:list[Issuer],stats:dict[str,int]):
        self.conn.execute("UPDATE issuers SET active=0")
        self.conn.executemany("""INSERT INTO issuers(issuer_key,isin,name,nse_symbol,nse_series,nse_sme,bse_scrip,bse_group,source_flags,active)
        VALUES(?,?,?,?,?,?,?,?,?,1) ON CONFLICT(issuer_key) DO UPDATE SET isin=excluded.isin,name=excluded.name,nse_symbol=excluded.nse_symbol,
        nse_series=excluded.nse_series,nse_sme=excluded.nse_sme,bse_scrip=excluded.bse_scrip,bse_group=excluded.bse_group,
        source_flags=excluded.source_flags,active=1""",[(i.issuer_key,i.isin,i.name,i.nse_symbol,i.nse_series,int(i.nse_sme),i.bse_scrip,i.bse_group,i.source_flags) for i in issuers])
        self.conn.executemany("INSERT INTO universe_stats(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",stats.items()); self.conn.commit()
    def init_slots(self,start:int,end:int):
        rows=self.conn.execute("SELECT issuer_key FROM issuers WHERE active=1").fetchall()
        self.conn.executemany("INSERT OR IGNORE INTO expected_slots(issuer_key,fiscal_year) VALUES(?,?)",[(r[0],y) for r in rows for y in range(start,end+1)]); self.conn.commit()
    def active_issuers(self): return self.conn.execute("SELECT * FROM issuers WHERE active=1 ORDER BY name").fetchall()
    def mark_discovery(self,key,source,status,error=""):
        self.conn.execute("INSERT INTO discovery_state VALUES(?,?,?,?) ON CONFLICT(issuer_key,source) DO UPDATE SET status=excluded.status,last_error=excluded.last_error",(key,source,status,error[:1000])); self.conn.commit()
    def discovery_done(self,key,source):
        r=self.conn.execute("SELECT status FROM discovery_state WHERE issuer_key=? AND source=?",(key,source)).fetchone(); return bool(r and r[0]=='DONE')
    def add_candidates(self,items:list[Candidate]):
        self.conn.executemany("""INSERT INTO candidates(issuer_key,fiscal_year,source,source_id,title,url,published_at,from_year,to_year,file_kind,score,selected,note)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(issuer_key,source,source_id) DO UPDATE SET fiscal_year=excluded.fiscal_year,title=excluded.title,url=excluded.url,published_at=excluded.published_at,file_kind=excluded.file_kind,score=excluded.score,note=excluded.note""",
        [(c.issuer_key,c.fiscal_year,c.source,c.source_id,c.title,c.url,c.published_at,c.from_year,c.to_year,c.file_kind,c.score,int(c.selected),c.note) for c in items]); self.conn.commit()
    def select_best(self,start:int,end:int):
        self.conn.execute("UPDATE candidates SET selected=0")
        slots=self.conn.execute("SELECT issuer_key,fiscal_year FROM expected_slots WHERE fiscal_year BETWEEN ? AND ?",(start,end)).fetchall()
        priority="CASE source WHEN 'NSE' THEN 5 WHEN 'NSE_SME' THEN 5 WHEN 'BSE_PAGE' THEN 4 WHEN 'BSE_ANN' THEN 3 WHEN 'BSE_LEGACY' THEN 2 ELSE 1 END"
        for s in slots:
            key,fy=s[0],s[1]
            cs=self.conn.execute(f"SELECT * FROM candidates WHERE issuer_key=? AND fiscal_year=? ORDER BY {priority} DESC, score DESC, CASE file_kind WHEN 'PDF' THEN 2 ELSE 1 END DESC, published_at DESC",(key,fy)).fetchall()
            if not cs:
                self.conn.execute("UPDATE expected_slots SET status='MISSING',selected_candidate_id=NULL,candidate_count=0,note='' WHERE issuer_key=? AND fiscal_year=?",(key,fy)); continue
            best=cs[0]; self.conn.execute("UPDATE candidates SET selected=1 WHERE id=?",(best['id'],))
            note="multiple_candidates" if len(cs)>1 else ""
            self.conn.execute("UPDATE expected_slots SET status='FOUND',selected_candidate_id=?,candidate_count=?,note=? WHERE issuer_key=? AND fiscal_year=?",(best['id'],len(cs),note,key,fy))
            self.conn.execute("INSERT OR IGNORE INTO downloads(candidate_id,status) VALUES(?,'PENDING')",(best['id'],))
        self.conn.commit()
    def missing_for_bse(self,start:int,end:int):
        return self.conn.execute("""SELECT DISTINCT i.* FROM expected_slots e JOIN issuers i USING(issuer_key)
        WHERE e.fiscal_year BETWEEN ? AND ? AND e.status='MISSING' AND i.bse_scrip!='' AND i.active=1 ORDER BY i.name""",(start,end)).fetchall()
    def selected_pending(self):
        return self.conn.execute("""SELECT c.*,i.name,i.isin,i.nse_symbol,i.bse_scrip,d.status download_status,d.path download_path
        FROM candidates c JOIN issuers i USING(issuer_key) LEFT JOIN downloads d ON d.candidate_id=c.id
        WHERE c.selected=1 AND COALESCE(d.status,'PENDING')!='DONE' ORDER BY i.name,c.fiscal_year""").fetchall()
    def mark_download(self,cid,status,path="",size=None,sha256="",error="",archive_parts=0):
        self.conn.execute("""INSERT INTO downloads(candidate_id,status,path,bytes,sha256,attempts,last_error,archive_parts) VALUES(?,?,?,?,?,1,?,?)
        ON CONFLICT(candidate_id) DO UPDATE SET status=excluded.status,path=excluded.path,bytes=excluded.bytes,sha256=excluded.sha256,
        attempts=downloads.attempts+1,last_error=excluded.last_error,archive_parts=excluded.archive_parts""",(cid,status,path,size,sha256,error[:1000],archive_parts))
        if status=='DONE': self.conn.execute("UPDATE expected_slots SET status='DONE' WHERE selected_candidate_id=?",(cid,))
        elif status=='FAILED': self.conn.execute("UPDATE expected_slots SET status='FAILED' WHERE selected_candidate_id=?",(cid,))
        self.conn.commit()
    def export_audits(self,root:Path):
        root.mkdir(parents=True,exist_ok=True)
        queries={
        'issuers.csv':"SELECT * FROM issuers WHERE active=1 ORDER BY name",
        'universe_summary.csv':"SELECT k,v FROM universe_stats ORDER BY k",
        'candidates.csv':"SELECT * FROM candidates ORDER BY issuer_key,fiscal_year,score DESC",
        'coverage.csv':"""SELECT i.issuer_key,i.isin,i.name,i.nse_symbol,i.bse_scrip,e.fiscal_year,e.status,e.candidate_count,e.note,c.source,c.title,c.url,d.path,d.bytes,d.sha256,d.last_error,d.archive_parts FROM expected_slots e JOIN issuers i USING(issuer_key) LEFT JOIN candidates c ON c.id=e.selected_candidate_id LEFT JOIN downloads d ON d.candidate_id=c.id WHERE i.active=1 ORDER BY i.name,e.fiscal_year""",
        'missing.csv':"""SELECT i.issuer_key,i.isin,i.name,i.nse_symbol,i.bse_scrip,e.fiscal_year,e.status FROM expected_slots e JOIN issuers i USING(issuer_key) WHERE i.active=1 AND e.status IN ('MISSING','FAILED') ORDER BY i.name,e.fiscal_year""",
        'multiple_candidates.csv':"""SELECT i.name,i.nse_symbol,i.bse_scrip,e.fiscal_year,e.candidate_count,e.note FROM expected_slots e JOIN issuers i USING(issuer_key) WHERE i.active=1 AND e.candidate_count>1 ORDER BY i.name,e.fiscal_year""",
        'failed_downloads.csv':"""SELECT i.name,c.fiscal_year,c.source,c.url,d.attempts,d.last_error FROM downloads d JOIN candidates c ON c.id=d.candidate_id JOIN issuers i USING(issuer_key) WHERE d.status='FAILED' ORDER BY i.name,c.fiscal_year""",
        'multi_file_archives.csv':"""SELECT i.name,c.fiscal_year,c.source,d.path,d.archive_parts FROM downloads d JOIN candidates c ON c.id=d.candidate_id JOIN issuers i USING(issuer_key) WHERE d.archive_parts>1 ORDER BY i.name,c.fiscal_year""",
        'source_counts.csv':"SELECT source,count(*) AS candidates,sum(selected) AS selected FROM candidates GROUP BY source ORDER BY selected DESC"
        }
        for fn,q in queries.items():
            rows=self.conn.execute(q).fetchall(); p=root/fn
            with p.open('w',newline='',encoding='utf-8-sig') as fh:
                w=csv.writer(fh)
                if rows: w.writerow(rows[0].keys()); w.writerows([tuple(r) for r in rows])
                else: w.writerow(['no_rows'])
