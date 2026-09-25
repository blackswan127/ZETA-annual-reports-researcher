import re
from pathlib import Path
from .config import COUNTRY_ISO3, EXCHANGE_MIC

SAFE = re.compile(r"[^A-Za-z0-9.-]+")

def clean(v: str) -> str:
    v = (v or "").strip()
    return SAFE.sub("", v)

def identity_complete(lei: str, isin: str, ticker: str) -> bool:
    return len(clean(lei)) == 20 and len(clean(isin)) == 12 and bool(clean(ticker))

def company_folder(lei: str, isin: str, ticker: str) -> str:
    return f"{clean(lei)}_{clean(isin)}_{clean(ticker)}"

def report_filename(lei: str, ticker: str, isin: str, fy: int, report_type: str = "AR", lang: str = "EN") -> str:
    return f"{clean(lei)}_{COUNTRY_ISO3}_{EXCHANGE_MIC}_{clean(ticker)}_{clean(isin)}_FY{fy}_{clean(report_type)}_{clean(lang)}.pdf"

def final_path(root: Path, lei: str, isin: str, ticker: str, fy: int, report_type: str = "AR", lang: str = "EN") -> Path:
    return root / COUNTRY_ISO3 / EXCHANGE_MIC / company_folder(lei, isin, ticker) / f"FY{fy}" / report_filename(lei, ticker, isin, fy, report_type, lang)
