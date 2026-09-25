from __future__ import annotations

import asyncio
import os
import random
import shutil
from pathlib import Path
from urllib.parse import urlparse, unquote
from urllib.request import url2pathname

import httpx

from .config import USER_AGENT
from .util import AsyncRateLimiter, is_pdf

class Downloader:
    def __init__(self, workers: int=8, rps: float=4.0, timeout: float=60, retries: int=5, chunk_size: int=1024*1024):
        self.sem=asyncio.Semaphore(max(1,workers)); self.rate=AsyncRateLimiter(rps); self.retries=retries; self.chunk_size=chunk_size
        self.client=httpx.AsyncClient(
            timeout=httpx.Timeout(timeout,read=max(timeout,180)),follow_redirects=True,
            headers={"User-Agent":USER_AGENT,"Accept":"application/pdf,application/octet-stream,*/*;q=0.5"},
            limits=httpx.Limits(max_connections=max(workers+6,12),max_keepalive_connections=max(workers,6)),
        )

    async def close(self): await self.client.aclose()

    async def download(self,url: str,dest: Path) -> None:
        dest.parent.mkdir(parents=True,exist_ok=True); part=dest.with_suffix(dest.suffix+".part")
        parsed=urlparse(url)
        if parsed.scheme == "file":
            src = Path(url2pathname(unquote(parsed.path)))
            if not src.exists(): raise RuntimeError(f"local_source_missing:{src}")
            with src.open("rb") as rf, part.open("wb") as wf:
                shutil.copyfileobj(rf,wf,self.chunk_size)
            if not is_pdf(part):
                part.unlink(missing_ok=True); raise RuntimeError("invalid_pdf_signature")
            os.replace(part,dest); return
        async with self.sem:
            last=None
            for attempt in range(self.retries):
                try:
                    offset=part.stat().st_size if part.exists() else 0
                    headers={"Range":f"bytes={offset}-"} if offset else {}
                    if "sec.gov" in parsed.netloc:
                        headers["User-Agent"] = os.environ.get("SEC_USER_AGENT", "blackswan capital khanholdings127@gmail.com")
                    await self.rate.acquire()
                    async with self.client.stream("GET",url,headers=headers) as r:
                        if r.status_code==416 and offset:
                            if is_pdf(part): os.replace(part,dest); return
                            part.unlink(missing_ok=True); continue
                        if r.status_code==429 or 500<=r.status_code<600:
                            ra=r.headers.get("Retry-After",""); delay=float(ra) if ra.isdigit() else min(30,1.7**attempt)
                            await asyncio.sleep(delay+random.random()*.25); continue
                        r.raise_for_status()
                        ctype=r.headers.get("content-type","").lower()
                        if "text/html" in ctype: raise RuntimeError("received_html_instead_of_pdf")
                        mode="ab" if offset and r.status_code==206 else "wb"
                        with part.open(mode) as fh:
                            async for chunk in r.aiter_bytes(self.chunk_size):
                                if chunk: fh.write(chunk)
                    if not is_pdf(part): raise RuntimeError("invalid_pdf_signature")
                    os.replace(part,dest); return
                except Exception as exc:
                    last=exc
                    if "received_html_instead_of_pdf" in str(exc) or "invalid_pdf_signature" in str(exc):
                        break
                    if attempt+1<self.retries: await asyncio.sleep(min(30,1.7**attempt)+random.random()*.25)
            part.unlink(missing_ok=True)
            raise RuntimeError(f"download_failed:{last}")
