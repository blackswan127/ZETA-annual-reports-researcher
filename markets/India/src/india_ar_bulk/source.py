from __future__ import annotations

import asyncio
import random
from datetime import date
from typing import Iterable

import httpx

from .config import (BSE_ANN_API, BSE_AR_PAGE, BSE_GROUPS, BSE_LIST_API, NSE_ANNUAL_API,
                     NSE_MAIN_CSV, NSE_PRIME_URL, NSE_SME_CSV, USER_AGENT, require_terms_acknowledgement)
from .models import Candidate, Issuer
from .parsers import (merge_issuers, parse_bse_announcements, parse_bse_annual_html,
                      parse_bse_list, parse_nse_annual_json, parse_nse_csv)
from .util import AsyncRateLimiter

class RetryClient:
    def __init__(self, timeout: float, retries: int, rps: float, headers: dict[str,str] | None = None):
        self.retries=retries
        self.rate=AsyncRateLimiter(rps)
        base={"User-Agent":USER_AGENT,"Accept":"*/*","Accept-Language":"en-US,en;q=0.9"}
        if headers: base.update(headers)
        self.client=httpx.AsyncClient(timeout=httpx.Timeout(timeout,read=max(90,timeout)),follow_redirects=True,
            headers=base,limits=httpx.Limits(max_connections=20,max_keepalive_connections=10))

    async def close(self): await self.client.aclose()

    async def get(self,url:str,**kwargs)->httpx.Response:
        last=None
        for attempt in range(self.retries):
            try:
                await self.rate.acquire()
                r=await self.client.get(url,**kwargs)
                if r.status_code in (401,403):
                    return r
                if r.status_code==429 or 500<=r.status_code<600:
                    ra=r.headers.get("Retry-After")
                    delay=float(ra) if ra and ra.replace('.','',1).isdigit() else min(30,1.7**attempt)
                    await asyncio.sleep(delay+random.random()*.25); continue
                r.raise_for_status(); return r
            except Exception as exc:
                last=exc
                if attempt+1<self.retries: await asyncio.sleep(min(30,1.7**attempt)+random.random()*.25)
        raise RuntimeError(f"GET failed after {self.retries} attempts: {url}: {last}")

class NSESource:
    def __init__(self, timeout: float, retries: int, rps: float):
        self.http=RetryClient(timeout,retries,rps,{"Referer":NSE_PRIME_URL})
        self._primed=False

    async def close(self): await self.http.close()

    async def prime(self, force=False):
        require_terms_acknowledgement()
        if self._primed and not force: return
        r=await self.http.get(NSE_PRIME_URL)
        if r.status_code>=400: r.raise_for_status()
        self._primed=True

    async def universe(self, include_sme=True)->list[Issuer]:
        require_terms_acknowledgement()
        r=await self.http.get(NSE_MAIN_CSV); r.raise_for_status()
        rows=parse_nse_csv(r.text,False)
        if include_sme:
            try:
                s=await self.http.get(NSE_SME_CSV); s.raise_for_status(); rows.extend(parse_nse_csv(s.text,True))
            except Exception:
                # Some environments block the SME CSV; keep mainboard instead of failing all-universe load.
                pass
        # Dedup by symbol+ISIN.
        uniq={}
        for x in rows: uniq[(x.isin,x.nse_symbol)]=x
        return list(uniq.values())

    async def annual_reports(self, issuer: Issuer)->list[Candidate]:
        if not issuer.nse_symbol: return []
        await self.prime()
        params={"index":"sme" if issuer.nse_sme else "equities","symbol":issuer.nse_symbol}
        r=await self.http.get(NSE_ANNUAL_API,params=params)
        if r.status_code in (401,403):
            await self.prime(True); r=await self.http.get(NSE_ANNUAL_API,params=params)
        r.raise_for_status()
        try: payload=r.json()
        except Exception as exc: raise RuntimeError(f"NSE returned non-JSON for {issuer.nse_symbol}: {exc}")
        return parse_nse_annual_json(issuer.issuer_key,payload,"NSE_SME" if issuer.nse_sme else "NSE")

class BSESource:
    def __init__(self, timeout: float, retries: int, rps: float):
        headers={"Referer":"https://www.bseindia.com/","Origin":"https://www.bseindia.com"}
        self.http=RetryClient(timeout,retries,rps,headers)

    async def close(self): await self.http.close()

    async def universe(self)->list[Issuer]:
        require_terms_acknowledgement()
        out=[]
        for group in BSE_GROUPS:
            params={"scripcode":"","Group":group,"industry":"","segment":"Equity","status":"Active"}
            try:
                r=await self.http.get(BSE_LIST_API,params=params); r.raise_for_status()
                out.extend(parse_bse_list(r.json(),group))
            except Exception:
                # One group failure should not throw away all other groups. Audit can expose incomplete BSE count.
                continue
        uniq={}
        for x in out:
            uniq[(x.bse_scrip,x.isin)]=x
        return list(uniq.values())

    async def annual_page(self, issuer: Issuer)->list[Candidate]:
        if not issuer.bse_scrip: return []
        require_terms_acknowledgement()
        r=await self.http.get(BSE_AR_PAGE,params={"scripcode":issuer.bse_scrip}); r.raise_for_status()
        return parse_bse_annual_html(issuer.issuer_key,r.text)

    async def announcement_fallback(self, issuer: Issuer, start_year:int, end_year:int)->list[Candidate]:
        if not issuer.bse_scrip: return []
        require_terms_acknowledgement()
        out=[]
        # Publication may follow FY by up to one year; query a bounded broad window per company, page by page.
        page=1
        while page<=100:
            params={"pageno":page,"strCat":"Company Update","subcategory":"Annual Report",
                    "strPrevDate":f"{start_year}0101","strToDate":f"{end_year+1}1231","strSearch":"P",
                    "strscrip":issuer.bse_scrip,"strType":"C"}
            r=await self.http.get(BSE_ANN_API,params=params); r.raise_for_status(); payload=r.json()
            batch=parse_bse_announcements(issuer.issuer_key,payload); out.extend(batch)
            table=payload.get("Table") or [] if isinstance(payload,dict) else []
            table1=payload.get("Table1") or [] if isinstance(payload,dict) else []
            total=0
            if table1 and isinstance(table1,list) and isinstance(table1[0],dict):
                try: total=int(table1[0].get("ROWCNT") or 0)
                except Exception: total=0
            if not table or (total and page*len(table)>=total): break
            page+=1
        return out

async def current_india_universe(nse:NSESource,bse:BSESource,include_sme=True)->tuple[list[Issuer],dict[str,int]]:
    nse_rows = []
    bse_rows = []
    try:
        nse_rows = await nse.universe(include_sme)
    except Exception as e:
        print(f"[WARN] NSE live universe fetch failed: {e}")
    try:
        bse_rows = await bse.universe()
    except Exception as e:
        print(f"[WARN] BSE live universe fetch failed: {e}")
    merged=merge_issuers(nse_rows,bse_rows)
    dual=sum(1 for x in merged if x.nse_symbol and x.bse_scrip)
    stats={"nse_raw":len(nse_rows),"bse_raw":len(bse_rows),"deduped":len(merged),"dual_listed":dual,
           "nse_only":sum(1 for x in merged if x.nse_symbol and not x.bse_scrip),
           "bse_only":sum(1 for x in merged if x.bse_scrip and not x.nse_symbol)}
    return merged,stats
