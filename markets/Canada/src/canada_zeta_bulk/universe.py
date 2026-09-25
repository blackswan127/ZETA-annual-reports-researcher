from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from .config import MIC_NEX, MIC_TSX, MIC_TSXV, USER_AGENT, require_ack
from .models import Issuer
from .util import norm_name, safe_token

NON_COMPANY_PATTERNS = [
    r"\bETF\b", r"EXCHANGE[- ]TRADED", r"\bETP\b", r"\bCDR\b", r"CANADIAN DEPOSITARY RECEIPT",
    r"CLOSED[- ]END FUND", r"INVESTMENT FUND", r"MUTUAL FUND", r"\bSPAC\b", r"CAPITAL POOL COMPANY",
]

def _pick(row: dict[str, object], *aliases: str) -> str:
    low = {str(k).replace("\n", " ").strip().lower(): "" if v is None else str(v).strip() for k,v in row.items()}
    for a in aliases:
        if a.lower() in low and low[a.lower()]: return low[a.lower()]
    return ""

def normalize_exchange(v: str, symbol: str = "") -> str:
    x = (v or "").upper().replace(" ", "")
    if symbol.upper().endswith(".H") or "NEX" in x: return MIC_NEX
    if "VENTURE" in x or x in {"TSXV","XTSX","V"}: return MIC_TSXV
    if x in {"TSX","XTSE","T"} or "TORONTO" in x: return MIC_TSX
    return MIC_TSXV if ".V" in symbol.upper() else MIC_TSX

def eligible_company(name: str, security_type: str, industry: str, include_nex: bool=False, mic: str="") -> bool:
    if mic == MIC_NEX and not include_nex: return False
    text = f"{name} {security_type} {industry}".upper()
    return not any(re.search(p, text, re.I) for p in NON_COMPANY_PATTERNS)

def parse_rows(rows: Iterable[dict[str, object]], source: str="tmx_file", include_nex: bool=False) -> list[Issuer]:
    out: list[Issuer] = []
    seen: set[tuple[str,str]] = set()
    for row in rows:
        name = _pick(row,"company name","issuer name","name","company")
        ticker = _pick(row,"symbol","ticker","root ticker","stock symbol","security symbol").upper()
        if not name or not ticker: continue
        exchange_raw = _pick(row,"exchange","market","listing exchange","marketplace")
        mic = normalize_exchange(exchange_raw,ticker)
        key = (mic,ticker)
        if key in seen: continue
        seen.add(key)
        sec = _pick(row,"security type","instrument type","type","product type")
        industry = _pick(row,"industry","sector","subsector")
        isin = _pick(row,"isin","isin number").upper().replace(" ","")
        lei = _pick(row,"lei","legal entity identifier").upper().replace(" ","")
        website = _pick(row,"website","web site","url","issuer website")
        listing_date = _pick(row,"listing date","date listed","listed date")
        sedar_profile = _pick(row,"sedar profile","sedar+ profile","profile number","profile id")
        eligible = eligible_company(name,sec,industry,include_nex,mic)
        out.append(Issuer(
            issuer_key=f"{mic}:{ticker}", name=name, ticker=ticker, exchange_mic=mic,
            security_type=sec, industry=industry, listing_date=listing_date, website=website,
            isin=isin, lei=lei, sedar_profile=sedar_profile, eligible=eligible, source=source,
        ))
    return out

def parse_csv_bytes(data: bytes, source: str="tmx_csv", include_nex: bool=False) -> list[Issuer]:
    text = data.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    return parse_rows(rows,source,include_nex)

def parse_xlsx(path: Path, source: str="tmx_xlsx", include_nex: bool=False) -> list[Issuer]:
    wb = load_workbook(path, read_only=True, data_only=True)
    all_issuers: list[Issuer] = []
    seen: set[str] = set()
    for ws in wb.worksheets:
        values = list(ws.iter_rows(values_only=True))
        if not values: continue
        header_idx = None
        for idx,row in enumerate(values[:30]):
            vals = [str(x or "").replace("\n", " ").strip().lower() for x in row]
            if any(("symbol" in v or "ticker" in v) for v in vals) and any("name" in v for v in vals):
                header_idx = idx; break
        if header_idx is None: continue
        headers = [str(x or "").replace("\n", " ").strip() for x in values[header_idx]]
        dicts = [dict(zip(headers,row)) for row in values[header_idx+1:] if any(x is not None and str(x).strip() for x in row)]
        parsed = parse_rows(dicts,source,include_nex)
        for i in parsed:
            if i.issuer_key not in seen:
                seen.add(i.issuer_key)
                all_issuers.append(i)
    return all_issuers

def parse_universe_file(path: Path, include_nex: bool=False) -> list[Issuer]:
    ext = path.suffix.lower()
    if ext in {".xlsx",".xlsm"}: return parse_xlsx(path, path.name, include_nex)
    if ext in {".csv",".txt"}: return parse_csv_bytes(path.read_bytes(), path.name, include_nex)
    if ext in {".json",".jsonl"}:
        raw = path.read_text(encoding="utf-8-sig")
        items = [json.loads(x) for x in raw.splitlines() if x.strip()] if ext==".jsonl" else json.loads(raw)
        if isinstance(items,dict):
            items = items.get("data") or items.get("results") or items.get("issuers") or []
        return parse_rows(items,path.name,include_nex)
    raise ValueError(f"Unsupported universe file: {path}")

async def fetch_latest_tmx_list(timeout: float=45.0, include_nex: bool=False) -> tuple[list[Issuer], str]:
    """Best-effort fetch of the official current issuer-list file from TMX.
    Combines both TSX and TSXV equity operating companies.
    """
    require_ack("CANADA_AR_ACKNOWLEDGE_TMX_TERMS", "TMX current issuer list")
    page = "https://www.tsx.com/en/listings/current-market-statistics"
    headers = {"User-Agent": USER_AGENT, "Accept":"text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(timeout=timeout,follow_redirects=True,headers=headers) as c:
        try:
            r = await c.get(page)
            r.raise_for_status()
            soup = BeautifulSoup(r.text,"html.parser")
            href = ""
            for a in soup.find_all("a",href=True):
                text = " ".join(a.stripped_strings).lower()
                if "tsx" in text and "tsxv" in text and "listed" in text and ("compan" in text or "issuer" in text):
                    href = a["href"]; break
        except Exception:
            href = ""
        if not href:
            href = "/en/resource/571"
        from urllib.parse import urljoin
        url = urljoin(page,href)
        rr = await c.get(url)
        rr.raise_for_status()
        cached = Path(__file__).resolve().parents[2] / "input" / "tmx_current.xlsx"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(rr.content)
        return parse_xlsx(cached, "tmx_current", include_nex), url

