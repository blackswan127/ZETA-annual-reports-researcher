from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

NSE_MAIN_CSV = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_SME_CSV = "https://www.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv"
NSE_PRIME_URL = "https://www.nseindia.com/companies-listing/corporate-filings-annual-reports"
NSE_ANNUAL_API = "https://www.nseindia.com/api/annual-reports"
BSE_LIST_API = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
BSE_ANN_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_AR_PAGE = "https://www.bseindia.com/stock-share-price/stockreach_annualreports.aspx"
BSE_GROUPS = (
    "A","B","E","F","FC","GC","I","IF","IP","M","MS","MT","P","R","T","TS","W",
    "X","XD","XT","Y","Z","ZP","ZY"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
    "IndiaAnnualReportsBulk/1.0"
)

@dataclass(slots=True)
class Settings:
    output_dir: Path = Path("output")
    start_year: int = 2017
    end_year: int = 2025
    metadata_workers: int = 6
    nse_rps: float = 1.5
    bse_rps: float = 2.5
    download_workers: int = 8
    download_rps: float = 4.0
    timeout: float = 45.0
    retries: int = 5
    chunk_size: int = 1024 * 1024
    include_sme: bool = True
    use_bse_fallback: bool = True
    deep_bse_fallback: bool = False
    shard_count: int = 1
    shard_index: int = 0

    @property
    def db_path(self) -> Path:
        return self.output_dir / "manifest.sqlite3"
    @property
    def pdf_root(self) -> Path:
        return self.output_dir / "pdfs"
    @property
    def audit_root(self) -> Path:
        return self.output_dir / "audit"
    @property
    def temp_root(self) -> Path:
        return self.output_dir / ".tmp"


def require_terms_acknowledgement() -> None:
    if os.environ.get("INDIA_AR_ACKNOWLEDGE_TERMS", "").strip() != "1":
        raise RuntimeError(
            "Live NSE/BSE access is disabled until you review the exchanges' terms/data policies and set "
            "INDIA_AR_ACKNOWLEDGE_TERMS=1. NSE's terms restrict systematic automated collection without "
            "permission. Use this software only where you have the required authorization. It does not bypass "
            "CAPTCHA, login, paywalls, bot challenges, or other access controls."
        )
