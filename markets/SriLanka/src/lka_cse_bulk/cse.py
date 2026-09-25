import asyncio,time
from dataclasses import dataclass
from urllib.parse import quote
import httpx
from .util import base_ticker,prefer_symbol,stable_id
from .fy import resolve_fy
BASE='https://www.cse.lk/api/'; CDN='https://cdn.cse.lk/'
@dataclass
class Issuer:
 issuer_id:str; symbol:str; ticker:str; name:str; isin:str|None=None; lei:str|None=None
@dataclass
class Candidate:
 candidate_id:str; issuer_id:str; symbol:str; fy:int|None; fy_confidence:float; title:str; source_url:str; raw:dict; report_type:str='AR'
class RateLimiter:
 def __init__(self,rps): self.interval=0 if rps<=0 else 1/rps; self.lock=asyncio.Lock(); self.last=0.0
 async def wait(self):
  if not self.interval:return
  async with self.lock:
   now=time.monotonic(); d=self.interval-(now-self.last)
   if d>0:await asyncio.sleep(d)
   self.last=time.monotonic()
class CSEClient:
 def __init__(self,rps=2.0,timeout=45):
  self.rate=RateLimiter(rps)
  self.client=httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=20),follow_redirects=True,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36','Accept':'application/json,text/plain,*/*'})
 async def close(self): await self.client.aclose()
 async def post(self,endpoint,data=None,headers=None):
  last=None
  for attempt in range(5):
   try:
    await self.rate.wait(); r=await self.client.post(BASE+endpoint,data=data or {},headers=headers)
    if r.status_code==429:
     await asyncio.sleep(min(float(r.headers.get('Retry-After','2') or 2),60)); continue
    if 500<=r.status_code<600:
     await asyncio.sleep(min(2**attempt,20)); continue
    r.raise_for_status(); return r.json()
   except (httpx.HTTPError,ValueError) as e:
    last=e; await asyncio.sleep(min(2**attempt,20))
  raise RuntimeError(f'CSE request failed {endpoint}: {last}')
 async def universe(self):
  rows=[]
  for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
   try:
    js=await self.post('alphabetical',{'alphabet':ch}); part=js.get('reqAlphabetical',js if isinstance(js,list) else [])
    if isinstance(part,list):rows.extend(part)
   except Exception:pass
  if not rows:
   js=await self.post('todaySharePrice'); rows=js if isinstance(js,list) else js.get('reqTradeSummery',[])
  by={}
  for row in rows:
   sym=str(row.get('symbol','')).strip(); name=str(row.get('name') or row.get('companyName') or base_ticker(sym)).strip()
   if not sym:continue
   up=sym.upper()
   if '.R' in up or '.W' in up:continue
   by.setdefault(name.upper(),[]).append((sym,name))
  out=[]
  for key,vs in by.items():
   sym=prefer_symbol([x[0] for x in vs]); name=next(n for s,n in vs if s==sym); tick=base_ticker(sym)
   out.append(Issuer(stable_id('LKA','XCOL',tick,key),sym,tick,name))
  return sorted(out,key=lambda x:x.ticker)
 @staticmethod
 def extract_path(rec):
  for k in ('filePath','path','file','url','link','downloadUrl','attachment','fileName','pdfPath'):
   v=rec.get(k)
   if isinstance(v,str) and v.strip() and ('.pdf' in v.lower() or '/' in v):return v.strip()
  for v in rec.values():
   if isinstance(v,str) and ('.pdf' in v.lower() or 'upload_' in v.lower()):return v.strip()
  return ''
 @staticmethod
 def normalize_cdn_url(raw,fy=None):
  if not raw:return ''
  p=raw.strip()
  if p.startswith(('http://','https://')):return p
  p=p.lstrip('/')
  if not p.startswith(('cmt/','pdf/')):p='cmt/'+p
  return CDN+quote(p,safe='/:?=&%')
 async def annual_reports(self,issuer,start_fy,end_fy):
  headers={'Origin':'https://www.cse.lk','Referer':f'https://www.cse.lk/company-profile?symbol={quote(issuer.symbol)}','Content-Type':'application/x-www-form-urlencoded'}
  js=await self.post('financials',{'symbol':issuer.symbol},headers=headers); arr=js.get('infoAnnualData',[]); out=[]
  for rec in arr if isinstance(arr,list) else []:
   fy,conf,_=resolve_fy(rec)
   if fy is not None and not(start_fy<=fy<=end_fy):continue
   title=str(rec.get('fileText') or rec.get('title') or rec.get('name') or f'Annual Report {fy or ""}').strip()
   url=self.normalize_cdn_url(self.extract_path(rec),fy)
   if not url:continue
   rtype='SR' if any(w in title.lower() for w in ['sustainability report','sustainability disclosure','esg report','csr report']) else 'AR'
   out.append(Candidate(stable_id(issuer.issuer_id,str(fy),url,rtype),issuer.issuer_id,issuer.symbol,fy,conf,title,url,rec,rtype))
  other_arr=js.get('infoOtherData',[])
  for rec in other_arr if isinstance(other_arr,list) else []:
   title=str(rec.get('fileText') or rec.get('title') or rec.get('name') or '').strip()
   tl=title.lower()
   if any(w in tl for w in ['sustainab','esg','csr','climate','environment']) and not any(w in tl for w in ['debenture','bond','trust deed','prospectus','errata']):
    fy,conf,_=resolve_fy(rec)
    if fy is not None and not(start_fy<=fy<=end_fy):continue
    url=self.normalize_cdn_url(self.extract_path(rec),fy)
    if not url:continue
    out.append(Candidate(stable_id(issuer.issuer_id,str(fy),url,'SR'),issuer.issuer_id,issuer.symbol,fy,conf,title,url,rec,'SR'))
  return out
