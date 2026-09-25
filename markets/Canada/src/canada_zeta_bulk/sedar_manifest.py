from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable

from .classify import classify_title, detect_language, infer_fiscal_year
from .models import Candidate
from .util import norm_name

ALIASES = {
    "name": ["issuer_name","profile_name","company_name","issuer","profile","name"],
    "ticker": ["ticker","symbol","stock_symbol"],
    "mic": ["exchange_mic","mic","exchange"],
    "isin": ["isin","isin_number"],
    "lei": ["lei","legal_entity_identifier"],
    "title": ["document_type","document_title","title","document_name","filing_type"],
    "url": ["document_url","download_url","url","file_url","href","document_path","file_path","path"],
    "period_end": ["period_end","report_period_end","fiscal_year_end","year_end"],
    "published": ["filing_date","published_date","publication_date","date_filed"],
    "language": ["language","lang"],
    "document_id": ["document_id","filing_id","record_id","id"],
}

def _canon(row: dict[str,object], key: str) -> str:
    low = {str(k).strip().lower(): "" if v is None else str(v).strip() for k,v in row.items()}
    for a in ALIASES[key]:
        if low.get(a): return low[a]
    return ""

def _rows_from_path(path: Path) -> list[dict[str,object]]:
    if path.suffix.lower()==".csv":
        return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig",errors="replace"))))
    if path.suffix.lower()==".jsonl":
        return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    if path.suffix.lower()==".json":
        obj=json.loads(path.read_text(encoding="utf-8-sig"));
        if isinstance(obj,dict): obj=obj.get("data") or obj.get("results") or obj.get("documents") or []
        return obj
    raise ValueError(f"Unsupported SEDAR manifest format: {path}")

def load_rows(path: Path) -> list[dict[str,object]]:
    if path.suffix.lower() != ".zip": return _rows_from_path(path)
    rows=[]
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith(".csv"):
                rows += list(csv.DictReader(io.StringIO(z.read(n).decode("utf-8-sig",errors="replace"))))
            elif n.lower().endswith(".jsonl"):
                rows += [json.loads(x) for x in z.read(n).decode("utf-8-sig",errors="replace").splitlines() if x.strip()]
    return rows

def import_candidates(path: Path, issuer_rows: list[dict], start_year: int, end_year: int) -> tuple[list[Candidate], list[dict]]:
    issuers=[]
    for i in issuer_rows:
        issuers.append({**dict(i),"norm":norm_name(i["name"])})
    out=[]; unmatched=[]
    for row in load_rows(path):
        title=_canon(row,"title"); url=_canon(row,"url")
        if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            local=(path.parent/url).resolve() if not Path(url).is_absolute() else Path(url).resolve()
            if local.exists(): url=local.as_uri()
        ok,score=classify_title(title,url)
        if not ok or not url: continue
        fy,method=infer_fiscal_year(title,_canon(row,"period_end"),_canon(row,"published"),url)
        if fy is None or fy<start_year or fy>end_year: continue
        mic=_canon(row,"mic").upper(); ticker=_canon(row,"ticker").upper(); isin=_canon(row,"isin").upper(); lei=_canon(row,"lei").upper()
        name=_canon(row,"name"); nn=norm_name(name)
        matches=[]
        for i in issuers:
            if mic and ticker and i["exchange_mic"]==mic and i["ticker"]==ticker: matches=[i]; break
            if isin and i["isin"] and i["isin"].upper()==isin: matches=[i]; break
            if lei and i["lei"] and i["lei"].upper()==lei: matches=[i]; break
        if not matches and nn:
            matches=[i for i in issuers if i["norm"]==nn]
        if len(matches)!=1:
            unmatched.append({"name":name,"ticker":ticker,"mic":mic,"isin":isin,"lei":lei,"fiscal_year":fy,"title":title,"url":url})
            continue
        lang=detect_language(title,url,_canon(row,"language"))
        out.append(Candidate(
            issuer_key=matches[0]["issuer_key"],fiscal_year=fy,title=title,url=url,source="SEDAR_DDS",
            source_priority=1,language=lang,published_date=_canon(row,"published"),period_end=_canon(row,"period_end"),
            document_id=_canon(row,"document_id"),score=score+30,provenance=f"authorized_bulk_manifest:{path.name};fy={method}",
        ))
    return out,unmatched
