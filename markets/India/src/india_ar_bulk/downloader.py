from __future__ import annotations

import asyncio
import hashlib
import os
import random
import shutil
import zipfile
from pathlib import Path

import httpx

from .config import USER_AGENT
from .util import AsyncRateLimiter, is_pdf, is_zip, safe_name, sha256_file

class ArtifactDownloader:
    def __init__(self, workers=8, rps=4.0, timeout=60.0, retries=5, chunk_size=1024*1024, client=None, proxy: str = ""):
        self.sem = asyncio.Semaphore(max(1, workers))
        self.rate = AsyncRateLimiter(rps)
        self.retries = retries
        self.chunk_size = chunk_size
        self._owned = client is None
        proxy_url = proxy or os.environ.get("INDIA_AR_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=max(timeout, 180)),
            follow_redirects=True,
            proxy=proxy_url if proxy_url else None,
            trust_env=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,application/zip,*/*;q=0.7"},
            limits=httpx.Limits(max_connections=max(12, workers + 4), max_keepalive_connections=max(8, workers)),
        )

    async def close(self):
        if self._owned:
            await self.client.aclose()

    async def fetch(self, url: str, dest: Path, kind: str = "PDF") -> tuple[Path, int, str, int]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        ext = '.zip' if kind.upper() == 'ZIP' or url.lower().split('?')[0].endswith('.zip') else '.pdf'
        raw = dest.with_suffix(ext)
        part = raw.with_suffix(raw.suffix + '.part')

        urls_to_try = [url]
        if "AttachHis" in url:
            urls_to_try.append(url.replace("AttachHis", "AttachLive"))
        elif "AttachLive" in url:
            urls_to_try.append(url.replace("AttachLive", "AttachHis"))

        async with self.sem:
            last = None
            for target_url in urls_to_try:
                for attempt in range(self.retries):
                    try:
                        offset = part.stat().st_size if part.exists() else 0
                        headers = {"Range": f"bytes={offset}-"} if offset else {}
                        await self.rate.acquire()
                        async with self.client.stream('GET', target_url, headers=headers) as r:
                            if r.status_code == 416 and offset:
                                if is_pdf(part) or is_zip(part):
                                    os.replace(part, raw)
                                    return self._finalize(raw, dest)
                                part.unlink(missing_ok=True)
                                continue
                            if r.status_code in (404, 403) and len(urls_to_try) > 1 and target_url == urls_to_try[0]:
                                # Try alternate URL (e.g. AttachLive)
                                break
                            if r.status_code == 429 or 500 <= r.status_code < 600:
                                ra = r.headers.get('Retry-After')
                                delay = float(ra) if ra and ra.replace('.', '', 1).isdigit() else min(30, 1.7 ** attempt)
                                await asyncio.sleep(delay + random.random() * 0.3)
                                continue
                            r.raise_for_status()
                            ctype = r.headers.get('content-type', '').lower()
                            if 'text/html' in ctype:
                                raise RuntimeError('received HTML instead of document')
                            mode = 'ab' if offset and r.status_code == 206 else 'wb'
                            with part.open(mode) as fh:
                                async for chunk in r.aiter_bytes(self.chunk_size):
                                    if chunk:
                                        fh.write(chunk)
                        if not (is_pdf(part) or is_zip(part)):
                            raise RuntimeError('download is neither PDF nor ZIP')
                        os.replace(part, raw)
                        return self._finalize(raw, dest)
                    except Exception as exc:
                        last = exc
                        if attempt + 1 < self.retries:
                            await asyncio.sleep(min(30, 1.7 ** attempt) + random.random() * 0.3)

            raise RuntimeError(f'download failed after {self.retries} attempts: {last}')

    def _finalize(self,raw:Path,dest:Path)->tuple[Path,int,str,int]:
        if is_pdf(raw):
            if raw != dest:
                dest.parent.mkdir(parents=True,exist_ok=True); os.replace(raw,dest)
            return dest,dest.stat().st_size,sha256_file(dest),0
        if not is_zip(raw): raise RuntimeError('invalid artifact')
        parts_dir=dest.parent/'parts'; parts_dir.mkdir(parents=True,exist_ok=True)
        pdfs=[]
        with zipfile.ZipFile(raw) as z:
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.pdf'): continue
                # zip-slip safe: discard directories and write by basename.
                name=safe_name(Path(info.filename).name,140)
                target=parts_dir/name
                with z.open(info) as src,target.open('wb') as dst: shutil.copyfileobj(src,dst,1024*1024)
                if is_pdf(target): pdfs.append(target)
        if not pdfs: raise RuntimeError('ZIP contains no valid PDF')
        primary=max(pdfs,key=lambda p:p.stat().st_size)
        shutil.copy2(primary,dest)
        digest=sha256_file(dest); size=dest.stat().st_size
        raw.unlink(missing_ok=True)
        return dest,size,digest,len(pdfs)
