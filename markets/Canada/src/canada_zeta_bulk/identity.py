from __future__ import annotations

import asyncio
import csv
import io
from pathlib import Path

import httpx

from .config import USER_AGENT
from .util import AsyncRateLimiter, norm_name

class IdentityResolver:
    """Conservative identity helper. It proposes identifiers; it never fabricates them.
    Automatic LEI acceptance requires a unique exact normalized legal-name match.
    OpenFIGI acceptance requires a unique mapping result with an ISIN.
    """
    def __init__(self, timeout: float=45, rps: float=1.0, openfigi_key: str=""):
        self.client=httpx.AsyncClient(timeout=timeout,follow_redirects=True,headers={"User-Agent":USER_AGENT})
        self.rate=AsyncRateLimiter(rps)
        self.openfigi_key=openfigi_key

    async def close(self): await self.client.aclose()

    async def gleif_lei(self,name: str) -> tuple[str,float,str]:
        await self.rate.acquire()
        params={"filter[entity.legalName]":name,"filter[entity.legalAddress.country]":"CA","page[size]":"10"}
        r=await self.client.get("https://api.gleif.org/api/v1/lei-records",params=params); r.raise_for_status()
        data=r.json().get("data",[]); target=norm_name(name)
        exact=[]
        for item in data:
            attrs=item.get("attributes",{}); en=attrs.get("entity",{}).get("legalName",{}).get("name","")
            if norm_name(en)==target: exact.append(item)
        if len(exact)==1:
            return exact[0].get("id","").upper(),1.0,"GLEIF unique exact legal-name match"
        return "",0.0,f"GLEIF exact matches={len(exact)}"

    async def openfigi_isin(self,ticker: str,mic: str) -> tuple[str,float,str]:
        headers={"Content-Type":"application/json","User-Agent":USER_AGENT}
        if self.openfigi_key: headers["X-OPENFIGI-APIKEY"]=self.openfigi_key
        # Do not guess an OpenFIGI exchange code from the MIC. Some TSX/TSXV
        # symbols overlap with other markets, so constrain only to equity and
        # auto-accept solely when the response contains one unique ISIN.
        payload=[{"idType":"TICKER","idValue":ticker,"marketSecDes":"Equity"}]
        await self.rate.acquire()
        r=await self.client.post("https://api.openfigi.com/v3/mapping",json=payload,headers=headers); r.raise_for_status()
        arr=r.json(); data=arr[0].get("data",[]) if arr and isinstance(arr[0],dict) else []
        isins=sorted({str(x.get("isin","")).upper() for x in data if x.get("isin")})
        if len(isins)==1: return isins[0],0.95,"OpenFIGI unique ISIN mapping"
        return "",0.0,f"OpenFIGI ISIN matches={len(isins)}"


def load_overrides(path: Path) -> list[dict[str,str]]:
    if not path.exists(): return []
    with path.open("r",encoding="utf-8-sig",newline="") as fh:
        return list(csv.DictReader(fh))
