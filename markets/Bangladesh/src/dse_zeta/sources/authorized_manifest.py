import csv,json
from pathlib import Path
from ..models import Candidate
from ..classify import annual_report_score,infer_fiscal_year

def _iter(path):
    path=Path(path)
    if path.suffix.lower()==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f:yield from csv.DictReader(f)
    elif path.suffix.lower() in {".jsonl",".ndjson"}:
        for line in path.read_text(encoding="utf8").splitlines():
            if line.strip():yield json.loads(line)
    elif path.suffix.lower()==".json":
        d=json.loads(path.read_text(encoding="utf8"));yield from (d if isinstance(d,list) else d.get("records",[]))
    else:raise ValueError("Authorized manifest must be CSV/JSON/JSONL")
def load_authorized_manifest(path,start,end):
    out=[]
    for r in _iter(path):
        ticker=str(r.get("ticker") or r.get("code") or "").strip().upper();title=str(r.get("title") or r.get("document_title") or "").strip();score=annual_report_score(title,str(r.get("description") or ""))
        if not ticker or score<5:continue
        try:fy=int(str(r.get("fiscal_year") or r.get("fy") or "").replace("FY",""))
        except Exception:fy,_=infer_fiscal_year(title,str(r.get("description") or ""))
        if not fy or not(start<=fy<=end):continue
        url=str(r.get("url") or r.get("document_url") or r.get("pdf_url") or r.get("local_path") or "").strip()
        if url:out.append(Candidate(ticker,fy,title,url,"DSE_AUTHORIZED",str(r.get("publication_date") or ""),str(r.get("announcement_id") or ""),score+5))
    return out
