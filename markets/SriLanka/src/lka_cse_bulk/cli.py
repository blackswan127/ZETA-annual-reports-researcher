import argparse,asyncio,csv
from pathlib import Path
from .cse import CSEClient
from .db import DB
from .downloader import Downloader
from .zeta import final_path,staging_path
from .audit import export
from .util import sha256_file

def overrides(db,path):
 if not path or not path.exists():return
 with path.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   t=(r.get('ticker') or '').upper().strip()
   if t:db.conn.execute("UPDATE issuers SET isin=COALESCE(NULLIF(?,''),isin),lei=COALESCE(NULLIF(?,''),lei) WHERE UPPER(ticker)=?",(r.get('isin','').strip(),r.get('lei','').strip(),t))
 db.conn.commit()
async def discover(a,db):
 c=CSEClient(a.discovery_rps)
 try:
  issuers=await c.universe();issuers=issuers[:a.limit] if a.limit else issuers
  for x in issuers:db.upsert_issuer(x);db.make_slots(x.issuer_id,a.start_year,a.end_year)
  sem=asyncio.Semaphore(a.discovery_workers)
  async def one(x):
   async with sem:
    try:
     cs=await c.annual_reports(x,a.start_year,a.end_year)
     for cand in cs:db.add_candidate(cand)
     if not cs:db.conn.execute("UPDATE expected_slots SET status='MISSING' WHERE issuer_id=? AND status='PENDING'",(x.issuer_id,));db.conn.commit()
    except Exception as e:db.conn.execute("INSERT INTO events(ts,event_type,issuer_id,details) VALUES(datetime('now'),'DISCOVERY_FAILED',?,?)",(x.issuer_id,str(e)));db.conn.commit()
  await asyncio.gather(*(one(x) for x in issuers))
 finally:await c.close()
async def download(a,db,repair=False):
 d=Downloader(a.pdf_workers,a.pdf_rps);work=Path(a.work);root=Path(a.zeta_root)
 try:
  async def one(row):
   _,_,ticker,_,isin,lei,fy,_,cid,url,_=row;dest=final_path(root,lei,isin,ticker,fy);state='DONE'
   if dest is None:dest=staging_path(work,ticker,fy);state='IDENTITY_MISSING'
   if dest.exists():
    try:d.validate_pdf(dest);db.mark_download(cid,state,bytes_downloaded=dest.stat().st_size,sha256=sha256_file(dest),local_path=str(dest),http_status=200);return
    except Exception:pass
   try:
    r=await d.get(url,dest);db.mark_download(cid,state,bytes_downloaded=r['bytes'],sha256=r['sha256'],local_path=str(dest),http_status=r['http_status'])
   except Exception as e:db.mark_download(cid,'FAILED',error=str(e),local_path=str(dest))
  await asyncio.gather(*(one(r) for r in db.selected(repair)))
 finally:await d.close()
async def run(a):
 work=Path(a.work);work.mkdir(parents=True,exist_ok=True);db=DB(work/'harvest.sqlite3')
 try:
  if a.command in ('discover','run'):await discover(a,db);overrides(db,Path(a.identity_overrides) if a.identity_overrides else None)
  if a.command in ('download','run'):overrides(db,Path(a.identity_overrides) if a.identity_overrides else None);await download(a,db)
  if a.command=='repair-missing':overrides(db,Path(a.identity_overrides) if a.identity_overrides else None);await download(a,db,True)
  export(db.conn,work)
 finally:db.close()
def parser():
 p=argparse.ArgumentParser(prog='cse-ar');p.add_argument('command',choices=['discover','download','run','repair-missing','audit']);p.add_argument('--start-year',type=int,default=2017);p.add_argument('--end-year',type=int,default=2025);p.add_argument('--work',default='work');p.add_argument('--zeta-root',default='GLOBAL_SUSTAINABILITY_DATABASE');p.add_argument('--identity-overrides');p.add_argument('--discovery-workers',type=int,default=8);p.add_argument('--discovery-rps',type=float,default=2);p.add_argument('--pdf-workers',type=int,default=16);p.add_argument('--pdf-rps',type=float,default=8);p.add_argument('--limit',type=int);return p
def main():
 a=parser().parse_args()
 if a.command=='audit':
  db=DB(Path(a.work)/'harvest.sqlite3');export(db.conn,Path(a.work));db.close();return
 asyncio.run(run(a))
if __name__=='__main__':main()
