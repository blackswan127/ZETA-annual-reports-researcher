import sqlite3,json
from pathlib import Path
from .models import Issuer,Candidate
SCHEMA="""
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS issuers(
 ticker TEXT PRIMARY KEY,name TEXT NOT NULL,isin TEXT,lei TEXT,website TEXT,financials_url TEXT,
 instrument_type TEXT,board TEXT,category TEXT,sector TEXT,fiscal_year_end TEXT,operational_status TEXT,current INTEGER NOT NULL DEFAULT 1,
 updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS expected_slots(ticker TEXT NOT NULL,fiscal_year INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'MISSING',selected_candidate_id INTEGER,final_path TEXT,error TEXT,PRIMARY KEY(ticker,fiscal_year));
CREATE TABLE IF NOT EXISTS candidates(id INTEGER PRIMARY KEY AUTOINCREMENT,ticker TEXT NOT NULL,fiscal_year INTEGER NOT NULL,title TEXT NOT NULL,url TEXT NOT NULL,source TEXT NOT NULL,publication_date TEXT,announcement_id TEXT,confidence REAL NOT NULL DEFAULT 0,report_type TEXT DEFAULT 'AR',language TEXT DEFAULT 'EN',UNIQUE(ticker,fiscal_year,url));
CREATE TABLE IF NOT EXISTS downloads(candidate_id INTEGER PRIMARY KEY,status TEXT NOT NULL,bytes INTEGER DEFAULT 0,sha256 TEXT,local_path TEXT,attempts INTEGER DEFAULT 0,error TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS source_profiles(source TEXT PRIMARY KEY,priority INTEGER NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,health TEXT DEFAULT 'UNKNOWN',last_error TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS discovery_state(source TEXT NOT NULL,ticker TEXT NOT NULL,fiscal_year INTEGER NOT NULL,status TEXT NOT NULL,detail TEXT,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(source,ticker,fiscal_year));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,level TEXT,event TEXT,payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""
class DB:
    def __init__(self,path:Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(self.path); self.conn.row_factory=sqlite3.Row; self.conn.executescript(SCHEMA)
        for source,priority in [("DSE_AUTHORIZED",100),("DSE_FINANCIAL_LINK",92),("ISSUER_IR",75)]: self.conn.execute("INSERT OR IGNORE INTO source_profiles(source,priority) VALUES(?,?)",(source,priority))
        self.conn.commit()
    def close(self): self.conn.close()
    def upsert_issuer(self,x:Issuer):
        self.conn.execute("""INSERT INTO issuers(ticker,name,isin,lei,website,financials_url,instrument_type,board,category,sector,fiscal_year_end,operational_status,current)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET name=excluded.name,isin=CASE WHEN excluded.isin<>'' THEN excluded.isin ELSE issuers.isin END,lei=CASE WHEN excluded.lei<>'' THEN excluded.lei ELSE issuers.lei END,website=excluded.website,financials_url=excluded.financials_url,instrument_type=excluded.instrument_type,board=excluded.board,category=excluded.category,sector=excluded.sector,fiscal_year_end=excluded.fiscal_year_end,operational_status=excluded.operational_status,current=excluded.current,updated_at=CURRENT_TIMESTAMP""",
        (x.ticker,x.name,x.isin,x.lei,x.website,x.financials_url,x.instrument_type,x.board,x.category,x.sector,x.fiscal_year_end,x.operational_status,1 if x.current else 0)); self.conn.commit()
    def ensure_slots(self,start,end):
        for r in self.conn.execute("SELECT ticker FROM issuers WHERE current=1 ORDER BY ticker"):
            for y in range(start,end+1): self.conn.execute("INSERT OR IGNORE INTO expected_slots(ticker,fiscal_year) VALUES(?,?)",(r['ticker'],y))
        self.conn.commit()
    def add_candidate(self,c:Candidate):
        self.conn.execute("""INSERT OR IGNORE INTO candidates(ticker,fiscal_year,title,url,source,publication_date,announcement_id,confidence,report_type,language) VALUES(?,?,?,?,?,?,?,?,?,?)""",(c.ticker,c.fiscal_year,c.title,c.url,c.source,c.publication_date,c.announcement_id,c.confidence,c.report_type,c.language)); self.conn.commit()
    def select_best(self):
        for s in self.conn.execute("SELECT ticker,fiscal_year FROM expected_slots"):
            r=self.conn.execute("""SELECT c.id,c.confidence,COALESCE(sp.priority,0) p FROM candidates c LEFT JOIN source_profiles sp ON sp.source=c.source WHERE c.ticker=? AND c.fiscal_year=? ORDER BY p DESC,c.confidence DESC,c.id DESC LIMIT 1""",(s['ticker'],s['fiscal_year'])).fetchone()
            if r:self.conn.execute("UPDATE expected_slots SET selected_candidate_id=?,status=CASE WHEN status='DONE' THEN status ELSE 'FOUND' END WHERE ticker=? AND fiscal_year=?",(r['id'],s['ticker'],s['fiscal_year']))
        self.conn.commit()
    def selected(self,statuses=("FOUND","FAILED")):
        q="SELECT s.*,c.*,i.name,i.isin,i.lei,i.website,i.financials_url FROM expected_slots s JOIN candidates c ON c.id=s.selected_candidate_id JOIN issuers i ON i.ticker=s.ticker WHERE s.status IN (%s) ORDER BY s.ticker,s.fiscal_year" % ",".join("?"*len(statuses)); return self.conn.execute(q,statuses).fetchall()
    def mark_done(self,ticker,fy,cid,path,sha,size):
        self.conn.execute("INSERT INTO downloads(candidate_id,status,bytes,sha256,local_path,attempts) VALUES(?,?,?,?,?,1) ON CONFLICT(candidate_id) DO UPDATE SET status='DONE',bytes=excluded.bytes,sha256=excluded.sha256,local_path=excluded.local_path,updated_at=CURRENT_TIMESTAMP",(cid,'DONE',size,sha,str(path))); self.conn.execute("UPDATE expected_slots SET status='DONE',final_path=?,error=NULL WHERE ticker=? AND fiscal_year=?",(str(path),ticker,fy)); self.conn.commit()
    def mark_failed(self,ticker,fy,cid,error):
        self.conn.execute("INSERT INTO downloads(candidate_id,status,attempts,error) VALUES(?,'FAILED',1,?) ON CONFLICT(candidate_id) DO UPDATE SET status='FAILED',attempts=downloads.attempts+1,error=excluded.error,updated_at=CURRENT_TIMESTAMP",(cid,error)); self.conn.execute("UPDATE expected_slots SET status='FAILED',error=? WHERE ticker=? AND fiscal_year=?",(error,ticker,fy)); self.conn.commit()
    def event(self,level,event,payload): self.conn.execute("INSERT INTO events(level,event,payload) VALUES(?,?,?)",(level,event,json.dumps(payload,ensure_ascii=False))); self.conn.commit()
