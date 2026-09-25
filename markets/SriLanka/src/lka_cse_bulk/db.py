import sqlite3,json
from datetime import datetime,timezone

def now():return datetime.now(timezone.utc).isoformat()
SCHEMA='''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS issuers(issuer_id TEXT PRIMARY KEY,symbol TEXT,ticker TEXT,name TEXT,isin TEXT,lei TEXT,active INTEGER DEFAULT 1,updated_at TEXT);
CREATE TABLE IF NOT EXISTS expected_slots(issuer_id TEXT,fy INTEGER,status TEXT DEFAULT 'PENDING',selected_candidate_id TEXT,PRIMARY KEY(issuer_id,fy));
CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY,issuer_id TEXT,fy INTEGER,fy_confidence REAL,title TEXT,source_url TEXT,raw_json TEXT,discovered_at TEXT);
CREATE TABLE IF NOT EXISTS downloads(candidate_id TEXT PRIMARY KEY,state TEXT,attempts INTEGER DEFAULT 0,bytes_downloaded INTEGER DEFAULT 0,sha256 TEXT,local_path TEXT,http_status INTEGER,error TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,ts TEXT,event_type TEXT,issuer_id TEXT,fy INTEGER,details TEXT);
'''
class DB:
 def __init__(self,path):
  path.parent.mkdir(parents=True,exist_ok=True); self.conn=sqlite3.connect(path); self.conn.executescript(SCHEMA); self.conn.commit()
 def close(self):self.conn.close()
 def upsert_issuer(self,x):
  self.conn.execute('''INSERT INTO issuers(issuer_id,symbol,ticker,name,isin,lei,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(issuer_id) DO UPDATE SET symbol=excluded.symbol,ticker=excluded.ticker,name=excluded.name,isin=COALESCE(excluded.isin,issuers.isin),lei=COALESCE(excluded.lei,issuers.lei),updated_at=excluded.updated_at''',(x.issuer_id,x.symbol,x.ticker,x.name,x.isin,x.lei,now())); self.conn.commit()
 def make_slots(self,i,a,b):self.conn.executemany('INSERT OR IGNORE INTO expected_slots(issuer_id,fy) VALUES(?,?)',[(i,y) for y in range(a,b+1)]);self.conn.commit()
 def add_candidate(self,c):
  self.conn.execute('INSERT OR REPLACE INTO candidates VALUES(?,?,?,?,?,?,?,?)',(c.candidate_id,c.issuer_id,c.fy,c.fy_confidence,c.title,c.source_url,json.dumps(c.raw),now()))
  if c.fy:
   row=self.conn.execute('SELECT candidate_id FROM candidates WHERE issuer_id=? AND fy=? ORDER BY fy_confidence DESC,candidate_id LIMIT 1',(c.issuer_id,c.fy)).fetchone()
   if row:self.conn.execute("UPDATE expected_slots SET status='FOUND',selected_candidate_id=? WHERE issuer_id=? AND fy=?",(row[0],c.issuer_id,c.fy))
  self.conn.commit()
 def selected(self,only_missing=False):
  q='''SELECT i.issuer_id,i.symbol,i.ticker,i.name,i.isin,i.lei,s.fy,s.status,c.candidate_id,c.source_url,c.title FROM expected_slots s JOIN issuers i ON i.issuer_id=s.issuer_id LEFT JOIN candidates c ON c.candidate_id=s.selected_candidate_id WHERE s.selected_candidate_id IS NOT NULL'''
  q += " AND s.status IN ('FOUND','FAILED','IDENTITY_MISSING')" if only_missing else " AND s.status<>'DONE'"
  return self.conn.execute(q).fetchall()
 def mark_download(self,cid,state,**kw):
  row=self.conn.execute('SELECT issuer_id,fy FROM candidates WHERE candidate_id=?',(cid,)).fetchone()
  self.conn.execute('''INSERT INTO downloads(candidate_id,state,attempts,bytes_downloaded,sha256,local_path,http_status,error,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET state=excluded.state,attempts=downloads.attempts+1,bytes_downloaded=excluded.bytes_downloaded,sha256=excluded.sha256,local_path=excluded.local_path,http_status=excluded.http_status,error=excluded.error,updated_at=excluded.updated_at''',(cid,state,1,kw.get('bytes_downloaded',0),kw.get('sha256'),kw.get('local_path'),kw.get('http_status'),kw.get('error'),now()))
  if row:self.conn.execute('UPDATE expected_slots SET status=? WHERE issuer_id=? AND fy=?',(state,row[0],row[1])); self.conn.commit()
