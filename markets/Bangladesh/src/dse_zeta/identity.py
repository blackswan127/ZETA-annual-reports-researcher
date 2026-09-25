import csv,re
from pathlib import Path
from urllib.parse import quote
from difflib import SequenceMatcher
from .models import Issuer

def norm_name(s):
    x=(s or "").lower().replace("&","and")
    x=re.sub(r"\b(public limited company|private limited company|limited|ltd|plc|company|co|bangladesh|bd)\b"," ",x)
    return re.sub(r"[^a-z0-9]","",x)
def load_overrides(path):
    if not path or not Path(path).exists():return {}
    out={}
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            t=(r.get("ticker") or "").upper().strip()
            if t:out[t]=r
    return out
def apply_override(i,row):
    if not row:return i
    i.lei=(row.get("lei") or i.lei or "").strip().upper();i.isin=(row.get("isin") or i.isin or "").strip().upper();i.website=(row.get("website") or i.website or "").strip();i.financials_url=(row.get("financials_url") or i.financials_url or "").strip();return i
def gleif_exact(http,issuer):
    url="https://api.gleif.org/api/v1/lei-records?filter[entity.legalName]="+quote(issuer.name);data=http.get(url,headers={"Accept":"application/vnd.api+json"}).json();matches=[]
    for rec in data.get("data",[]):
        a=rec.get("attributes",{});legal=a.get("entity",{}).get("legalName",{}).get("name","");status=a.get("registration",{}).get("status","")
        if norm_name(legal)==norm_name(issuer.name) and status in {"ISSUED","LAPSED"}:matches.append(rec.get("id","").upper())
    return matches[0] if len(matches)==1 and len(matches[0])==20 else ""
def apply_cdbl_isin(issuers,cdbl_rows):
    idx={}
    for isin,name,stype in cdbl_rows:
        if "securities" not in stype.lower():continue
        idx.setdefault(norm_name(name),[]).append(isin)
    for i in issuers:
        hits=idx.get(norm_name(i.name),[])
        if len(hits)==1:i.isin=hits[0]
    return issuers
def load_universe_csv(path):
    out=[]
    with Path(path).open("r",encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            t=(r.get("ticker") or r.get("code") or "").strip().upper();name=(r.get("name") or r.get("company") or r.get("company_name") or "").strip()
            if not t or not name:continue
            cur=str(r.get("current") or "1").strip().lower() not in {"0","false","no","n"}
            out.append(Issuer(ticker=t,name=name,isin=(r.get("isin") or "").strip().upper(),lei=(r.get("lei") or "").strip().upper(),website=(r.get("website") or "").strip(),financials_url=(r.get("financials_url") or "").strip(),instrument_type=(r.get("instrument_type") or "Equity").strip(),board=(r.get("board") or "PUBLIC").strip(),category=(r.get("category") or "").strip(),sector=(r.get("sector") or "").strip(),fiscal_year_end=(r.get("fiscal_year_end") or "").strip(),operational_status=(r.get("operational_status") or "").strip(),current=cur))
    return out
