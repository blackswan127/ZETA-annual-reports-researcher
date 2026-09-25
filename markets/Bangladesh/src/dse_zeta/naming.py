import re
from pathlib import Path
from .config import COUNTRY_ISO3, EXCHANGE_MIC
SAFE=re.compile(r"[^A-Za-z0-9.-]+")
def clean(v): return SAFE.sub("",(v or "").strip())
def identity_complete(lei,isin,ticker): return len(clean(lei))==20 and len(clean(isin))==12 and bool(clean(ticker))
def company_folder(lei,isin,ticker): return f"{clean(lei)}_{clean(isin)}_{clean(ticker)}"
def report_filename(lei,ticker,isin,fy,report_type="AR",lang="EN"):
    return f"{clean(lei)}_{COUNTRY_ISO3}_{EXCHANGE_MIC}_{clean(ticker)}_{clean(isin)}_FY{fy}_{clean(report_type)}_{clean(lang)}.pdf"
def final_path(root,lei,isin,ticker,fy,report_type="AR",lang="EN"):
    return Path(root)/COUNTRY_ISO3/EXCHANGE_MIC/company_folder(lei,isin,ticker)/f"FY{fy}"/report_filename(lei,ticker,isin,fy,report_type,lang)
