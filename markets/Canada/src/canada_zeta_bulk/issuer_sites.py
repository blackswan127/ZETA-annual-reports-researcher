from __future__ import annotations

import asyncio
import re
import urllib.robotparser
from collections import deque
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .classify import classify_title, detect_language, infer_fiscal_year
from .config import USER_AGENT
from .models import Candidate, Issuer
from .util import AsyncRateLimiter, absolute_url, same_site

COMMON_PATHS = ["/investors", "/investor-relations", "/investor", "/financials", "/financial-information", "/reports", "/annual-reports"]

class IssuerSiteCrawler:
    def __init__(self, timeout: float=45, rps: float=1.0, max_pages: int=30, max_depth: int=2, obey_robots: bool=True):
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(timeout,read=max(timeout,90)),follow_redirects=True,headers={"User-Agent":USER_AGENT})
        self.rate=AsyncRateLimiter(rps)
        self.max_pages=max_pages; self.max_depth=max_depth; self.obey_robots=obey_robots
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def close(self): await self.client.aclose()

    async def _allowed(self,url: str) -> bool:
        if not self.obey_robots: return True
        p=urlparse(url); origin=f"{p.scheme}://{p.netloc}"
        if origin not in self._robots:
            rp=urllib.robotparser.RobotFileParser(); rp.set_url(origin+"/robots.txt")
            try:
                await self.rate.acquire(); r=await self.client.get(origin+"/robots.txt")
                if r.status_code<400: rp.parse(r.text.splitlines())
                else: rp.parse([])
            except Exception: rp.parse([])
            self._robots[origin]=rp
        return self._robots[origin].can_fetch(USER_AGENT,url)

    async def _get(self,url: str):
        if not await self._allowed(url): raise RuntimeError("robots_disallowed")
        await self.rate.acquire(); r=await self.client.get(url,headers={"Accept":"text/html,application/xhtml+xml,*/*;q=0.5"}); r.raise_for_status(); return r

    @staticmethod
    def _interesting_page(text: str, url: str) -> bool:
        t=(text+" "+url).lower()
        return any(x in t for x in ["investor","annual","financial","report","shareholder","filing"])

    async def discover(self, issuer: Issuer, start_year: int, end_year: int) -> list[Candidate]:
        if not issuer.website: return []
        website=issuer.website.strip()
        if not website.startswith(("http://","https://")): website="https://"+website
        p=urlparse(website); root=f"{p.scheme}://{p.netloc}"
        queue=deque([(website,0)] + [(root+x,0) for x in COMMON_PATHS])
        seen=set(); candidates=[]; pages=0
        while queue and pages<self.max_pages:
            url,depth=queue.popleft()
            if url in seen or depth>self.max_depth: continue
            seen.add(url)
            if not same_site(root,url): continue
            try: r=await self._get(url)
            except Exception: continue
            ctype=r.headers.get("content-type","").lower()
            if "pdf" in ctype or r.url.path.lower().endswith(".pdf"): continue
            pages += 1
            soup=BeautifulSoup(r.text,"html.parser")
            for a in soup.find_all("a",href=True):
                href=absolute_url(str(r.url),a["href"])
                label=" ".join(a.stripped_strings).strip() or a.get("title","") or href.rsplit("/",1)[-1]
                if href.lower().startswith(("mailto:","javascript:")): continue
                ispdf=".pdf" in href.lower().split("?")[0] or "pdf" in (a.get("type","").lower())
                if ispdf:
                    ok,score=classify_title(label,href)
                    if not ok: continue
                    fy,method=infer_fiscal_year(label,"","",href)
                    if fy is None:
                        # Context around anchor often contains the year.
                        parent=" ".join(a.parent.stripped_strings) if a.parent else ""
                        fy,method=infer_fiscal_year(parent,"","",href)
                    if fy is None or fy<start_year or fy>end_year: continue
                    lang=detect_language(label,href,"")
                    candidates.append(Candidate(
                        issuer_key=issuer.issuer_key,fiscal_year=fy,title=label[:500],url=href,source="ISSUER_SITE",
                        source_priority=2,language=lang,score=score+20,provenance=f"issuer_site:{r.url};fy={method}",
                    ))
                elif depth<self.max_depth and same_site(root,href) and self._interesting_page(label,href):
                    queue.append((href,depth+1))
        # Stable dedupe by (fy,url)
        best={}
        for c in candidates:
            k=(c.fiscal_year,c.url)
            if k not in best or c.score>best[k].score: best[k]=c
        return list(best.values())
