from __future__ import annotations

import csv
import io
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from .classify import annual_report_score, fiscal_year_from_text
from .models import Candidate, Issuer
from .util import infer_kind, normalize_isin, normalize_name


def _field(row: dict, *names: str) -> str:
    norm = {str(k).strip().lower(): (v or "") for k, v in row.items()}
    for name in names:
        if name.lower() in norm:
            return str(norm[name.lower()]).strip()
    return ""


def parse_nse_csv(text: str, sme: bool = False) -> list[Issuer]:
    # utf-8-sig handles BOM; tolerate NSE's changing column names.
    rdr = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    out=[]
    for row in rdr:
        symbol = _field(row, "SYMBOL", "Symbol")
        name = _field(row, "NAME OF COMPANY", "NAME OF THE COMPANY", "Company Name", "NAME")
        isin = normalize_isin(_field(row, "ISIN NUMBER", "ISIN", "ISIN No"))
        series = _field(row, "SERIES", "Series")
        if not symbol or not name:
            continue
        key = isin or f"NSE:{symbol.upper()}"
        out.append(Issuer(key, isin, name.strip(), nse_symbol=symbol.strip().upper(), nse_series=series, nse_sme=sme,
                          source_flags="NSE_SME" if sme else "NSE"))
    return out


def parse_bse_list(payload: dict | list, group: str = "") -> list[Issuer]:
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("Table") or payload.get("table") or payload.get("Data") or payload.get("data") or []
    if not isinstance(rows, list):
        return []
    out=[]
    for row in rows:
        if not isinstance(row, dict):
            continue
        # BSE field names vary across versions.
        scrip = str(row.get("SCRIP_CD") or row.get("Scrip_Code") or row.get("ScripCode") or row.get("scrip_cd") or "").strip()
        name = str(row.get("Scrip_Name") or row.get("SCRIP_NAME") or row.get("Security_Name") or row.get("scrip_name") or row.get("LONG_NAME") or "").strip()
        isin = normalize_isin(str(row.get("ISIN_NUMBER") or row.get("ISIN") or row.get("ISIN_No") or row.get("isin") or ""))
        grp = str(row.get("GROUP") or row.get("Group") or group or "").strip()
        if not scrip or not name:
            continue
        key = isin or f"BSE:{scrip}"
        out.append(Issuer(key, isin, name, bse_scrip=scrip, bse_group=grp, source_flags="BSE"))
    return out


def merge_issuers(nse: list[Issuer], bse: list[Issuer]) -> list[Issuer]:
    by_key: dict[str, Issuer] = {}
    # ISIN first, then normalized-name bridge only when ISIN absent on one side.
    by_name: dict[str, str] = {}
    for src in [*nse, *bse]:
        key = src.isin or src.issuer_key
        existing = by_key.get(key)
        if existing is None and not src.isin:
            nk = normalize_name(src.name)
            bridge = by_name.get(nk)
            if bridge:
                existing = by_key.get(bridge)
                key = bridge
        if existing is None:
            existing = Issuer(key, src.isin, src.name, src.nse_symbol, src.nse_series, src.nse_sme,
                              src.bse_scrip, src.bse_group, src.source_flags)
            by_key[key] = existing
        else:
            if src.isin and not existing.isin: existing.isin = src.isin
            if src.nse_symbol: existing.nse_symbol = src.nse_symbol
            if src.nse_series: existing.nse_series = src.nse_series
            existing.nse_sme = existing.nse_sme or src.nse_sme
            if src.bse_scrip: existing.bse_scrip = src.bse_scrip
            if src.bse_group: existing.bse_group = src.bse_group
            flags=set(filter(None, (existing.source_flags + "," + src.source_flags).split(",")))
            existing.source_flags=",".join(sorted(flags))
            if len(src.name) > len(existing.name): existing.name = src.name
        nk=normalize_name(existing.name)
        if nk: by_name[nk]=key
    # Repair cases where a BSE no-ISIN key was created before an NSE ISIN row with same name.
    # Input normally has NSE first, so this is defensive only.
    return sorted(by_key.values(), key=lambda x: (x.name.upper(), x.issuer_key))


def parse_nse_annual_json(issuer_key: str, payload: dict, source: str = "NSE") -> list[Candidate]:
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    out=[]
    for i,row in enumerate(rows):
        if not isinstance(row, dict): continue
        url=str(row.get("fileName") or row.get("attachment") or row.get("url") or "").strip()
        if not url: continue
        try: fy=int(str(row.get("toYr") or "").strip())
        except ValueError: fy=fiscal_year_from_text(str(row)) or 0
        if not fy: continue
        try: from_y=int(str(row.get("fromYr") or "").strip())
        except ValueError: from_y=None
        title=str(row.get("submission_type") or "Annual Report").strip() or "Annual Report"
        published=str(row.get("broadcast_dttm") or row.get("submissionDate") or "").strip()
        srcid=str(row.get("id") or row.get("announcementId") or f"{fy}:{url}")
        score=200 + (10 if infer_kind(url)=="PDF" else 0)
        out.append(Candidate(issuer_key,fy,source,srcid,title,url,published,from_y,fy,infer_kind(url),score))
    return out


def parse_bse_annual_html(issuer_key: str, html: str, base_url: str = "https://www.bseindia.com") -> list[Candidate]:
    soup=BeautifulSoup(html,"html.parser")
    out=[]; seen=set()
    for a in soup.find_all("a", href=True):
        href=urljoin(base_url, a.get("href",""))
        if ".pdf" not in href.lower() and ".zip" not in href.lower():
            continue
        container=a.find_parent(["tr","li","div"]) or a
        text=" ".join(container.stripped_strings)
        if "annual" not in text.lower() and "annualreport" not in href.lower():
            # Legacy BSE URLs often contain AnnualReport path but not title.
            continue
        fy=fiscal_year_from_text(text)
        if not fy:
            m=re.search(r"(\d{2})(?:\.pdf|\.zip)(?:\?|$)",href,re.I)
            if m:
                yy=int(m.group(1)); fy=2000+yy
        if not fy:
            continue
        title=text[:500] or "Annual Report"
        score=max(130, annual_report_score(title)+40)
        key=(fy,href)
        if key in seen: continue
        seen.add(key)
        out.append(Candidate(issuer_key,fy,"BSE_PAGE",href,title,href,"",None,fy,infer_kind(href),score))
    return out


def parse_bse_announcements(issuer_key: str, payload: dict) -> list[Candidate]:
    rows=[]
    if isinstance(payload,dict):
        rows=payload.get("Table") or payload.get("table") or []
    out=[]
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict): continue
        title=str(row.get("NEWSSUB") or row.get("HEADLINE") or row.get("SUBCATNAME") or row.get("NEWS_SUB") or "").strip()
        score=annual_report_score(title)
        if score < 90: continue
        url=str(row.get("ATTACHMENTNAME") or row.get("ATTACHMENT") or row.get("URL") or "").strip()
        if url and not url.startswith("http"):
            url="https://www.bseindia.com/xml-data/corpfiling/AttachHis/"+url.lstrip("/")
        if not url: continue
        date=str(row.get("NEWS_DT") or row.get("DissemDT") or row.get("DT_TM") or "")
        fy=fiscal_year_from_text(title)
        if not fy:
            # Annual report announcements for FY end Y are usually filed later in Y, but do not guess from date here.
            continue
        srcid=str(row.get("NEWSID") or row.get("SLONGNAME") or url)
        out.append(Candidate(issuer_key,fy,"BSE_ANN",srcid,title,url,date,None,fy,infer_kind(url),100+score))
    return out
