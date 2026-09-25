from __future__ import annotations

from pathlib import Path
from .config import COUNTRY_ISO3
from .models import Issuer
from .util import safe_token

MISSING = {"", "NA", "N/A", "NONE", "UNKNOWN", "NULL"}

def identifiers_complete(issuer: Issuer) -> bool:
    return issuer.lei.upper() not in MISSING and issuer.isin.upper() not in MISSING and bool(issuer.ticker) and bool(issuer.exchange_mic)


def company_folder(issuer: Issuer) -> str:
    if not identifiers_complete(issuer):
        raise ValueError("ZETA final path requires verified LEI, ISIN, ticker and exchange MIC")
    return f"{safe_token(issuer.lei,30)}_{safe_token(issuer.isin,20)}_{safe_token(issuer.ticker,20)}"


def filename(issuer: Issuer, fiscal_year: int, report_type: str = "AR", language: str = "EN") -> str:
    if not identifiers_complete(issuer):
        raise ValueError("ZETA filename requires verified LEI, ISIN, ticker and exchange MIC")
    return f"{safe_token(issuer.lei,30)}_{COUNTRY_ISO3}_{issuer.exchange_mic}_{safe_token(issuer.ticker,20)}_{safe_token(issuer.isin,20)}_FY{fiscal_year}_{report_type}_{language}.pdf"


def final_path(root: Path, issuer: Issuer, fiscal_year: int, report_type: str = "AR", language: str = "EN") -> Path:
    return root / COUNTRY_ISO3 / issuer.exchange_mic / company_folder(issuer) / f"FY{fiscal_year}" / filename(issuer, fiscal_year, report_type, language)


def staging_path(root: Path, issuer: Issuer, fiscal_year: int, language: str = "EN") -> Path:
    return root / "unresolved_identity" / issuer.exchange_mic / safe_token(issuer.ticker,20) / f"FY{fiscal_year}" / f"{safe_token(issuer.ticker,20)}_FY{fiscal_year}_AR_{language}.pdf"
