import csv, json
from pathlib import Path
from ..models import Candidate
from ..classify import annual_report_score, infer_fiscal_year

REQUIRED_MIN={"ticker","title"}

def _iter(path:Path):
    if path.suffix.lower()==".csv":
        with path.open("r",encoding="utf-8-sig",newline="") as f: yield from csv.DictReader(f)
    elif path.suffix.lower() in {".jsonl",".ndjson"}:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip(): yield json.loads(line)
    elif path.suffix.lower()==".json":
        data=json.loads(path.read_text(encoding="utf-8")); yield from (data if isinstance(data,list) else data.get("records",[]))
    else: raise ValueError("Authorized manifest must be CSV/JSON/JSONL")

def load_authorized_manifest(path:Path,start:int,end:int):
    out=[]
    for r in _iter(Path(path)):
        ticker=str(r.get("ticker") or r.get("code") or "").strip().upper()
        title=str(r.get("title") or r.get("document_title") or "").strip()
        typ=str(r.get("announcement_type") or r.get("type") or "")
        body=str(r.get("description") or "")
        score=annual_report_score(title,typ,body)
        if not ticker or score<5: continue
        fy_raw=r.get("fiscal_year") or r.get("fy") or ""
        try: fy=int(str(fy_raw).replace("FY",""))
        except Exception: fy,_=infer_fiscal_year(title,body)
        if not fy or not (start<=fy<=end): continue
        url=str(r.get("url") or r.get("document_url") or r.get("pdf_url") or r.get("local_path") or "").strip()
        if not url: continue
        out.append(Candidate(ticker=ticker,fiscal_year=fy,title=title,url=url,source="NZX_AUTHORIZED",publication_date=str(r.get("publication_date") or ""),announcement_id=str(r.get("announcement_id") or ""),confidence=score+5))
    return out
