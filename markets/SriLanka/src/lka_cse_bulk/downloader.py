import asyncio,os,time
from pathlib import Path
import httpx
from pypdf import PdfReader
from .util import sha256_file
try:
 import fitz
 HAS_PYMUPDF = True
except ImportError:
 HAS_PYMUPDF = False

class Downloader:
 def __init__(self,workers=16,rps=8,timeout=120):
  self.sem=asyncio.Semaphore(workers);self.interval=0 if rps<=0 else 1/rps;self.lock=asyncio.Lock();self.last=0.0
  self.client=httpx.AsyncClient(timeout=httpx.Timeout(timeout,connect=20,read=timeout),follow_redirects=True,headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
 async def close(self):await self.client.aclose()
 async def pace(self):
  if not self.interval:return
  async with self.lock:
   now=time.monotonic();d=self.interval-(now-self.last)
   if d>0:await asyncio.sleep(d)
   self.last=time.monotonic()
 @staticmethod
 def validate_pdf(path,min_bytes=20000):
  path=Path(path)
  if not path.exists() or path.stat().st_size<min_bytes:raise ValueError('PDF too small')
  with path.open('rb') as f:
   if f.read(5)!=b'%PDF-':raise ValueError('Not a PDF signature')
  if HAS_PYMUPDF:
   doc=fitz.open(str(path))
   pages=len(doc)
   doc.close()
   if pages<1:raise ValueError('PDF has zero pages')
  else:
   if len(PdfReader(str(path),strict=False).pages)<1:raise ValueError('PDF has zero pages')
 async def get(self,url,dest):
  async with self.sem:
   dest.parent.mkdir(parents=True,exist_ok=True);part=Path(str(dest)+'.part')
   for attempt in range(5):
    try:
     start=part.stat().st_size if part.exists() else 0;headers={'Range':f'bytes={start}-'} if start else {}
     await self.pace()
     async with self.client.stream('GET',url,headers=headers) as r:
      if r.status_code==429:await asyncio.sleep(min(float(r.headers.get('Retry-After','2') or 2),60));continue
      if r.status_code==416 and start:part.unlink(missing_ok=True);continue
      if r.status_code>=500:await asyncio.sleep(min(2**attempt,20));continue
      r.raise_for_status()
      if start and r.status_code==200:part.unlink(missing_ok=True);start=0
      with part.open('ab' if start and r.status_code==206 else 'wb') as f:
       async for chunk in r.aiter_bytes(262144):f.write(chunk)
     self.validate_pdf(part);os.replace(part,dest);return {'sha256':sha256_file(dest),'bytes':dest.stat().st_size,'http_status':r.status_code}
    except Exception:
     if attempt==4:raise
     await asyncio.sleep(min(2**attempt,20))
