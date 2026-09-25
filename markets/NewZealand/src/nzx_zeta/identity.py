import csv, re
from pathlib import Path
from urllib.parse import quote
from .models import Issuer

def load_overrides(path:Path):
    if not path or not Path(path).exists(): return {}
    out={}
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            t=(r.get("ticker") or "").upper().strip()
            if t: out[t]=r
    return out

def apply_override(i:Issuer,row:dict):
    if not row: return i
    i.lei=(row.get("lei") or i.lei or "").strip().upper()
    i.isin=(row.get("isin") or i.isin or "").strip().upper()
    i.website=(row.get("website") or i.website or "").strip()
    return i

def gleif_exact(http, issuer:Issuer):
    # conservative: only accept exactly one active record with exact normalized legal-name match
    def norm(s): return re.sub(r"[^a-z0-9]","",(s or "").lower())
    url="https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]="+quote(issuer.name)
    data=http.get(url,headers={"Accept":"application/vnd.api+json"}).json()
    matches=[]
    for rec in data.get("data",[]):
        a=rec.get("attributes",{}); ent=a.get("entity",{}); reg=a.get("registration",{})
        legal=ent.get("legalName",{}).get("name","")
        status=reg.get("status","")
        if norm(legal)==norm(issuer.name) and status in {"ISSUED","LAPSED"}:
            matches.append(rec.get("id","").upper())
    return matches[0] if len(matches)==1 and len(matches[0])==20 else ""

def load_universe_csv(path:Path):
    out=[]
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            t=(r.get("ticker") or r.get("code") or "").strip().upper()
            name=(r.get("name") or r.get("company") or r.get("company_name") or "").strip()
            if not t or not name: continue
            cur=str(r.get("current") or "1").strip().lower() not in {"0","false","no","n"}
            out.append(Issuer(ticker=t,name=name,isin=(r.get("isin") or "").strip().upper(),lei=(r.get("lei") or "").strip().upper(),website=(r.get("website") or "").strip(),instrument_type=(r.get("instrument_type") or r.get("type") or "Ordinary Shares").strip(),primary_listing_venue=(r.get("primary_listing_venue") or "NZ").strip(),fiscal_year_end=(r.get("fiscal_year_end") or "").strip(),current=cur))
    return out
