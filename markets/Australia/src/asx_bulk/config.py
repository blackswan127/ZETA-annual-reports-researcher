from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ASX_DIR_API = "https://asx.api.markitdigital.com/asx-research/1.0/companies/directory"
ASX_COMPANIES_CSV = "https://www.asx.com.au/asx/research/ASXListedCompanies.csv"
ASX_HISTORY_URL = "https://www.asx.com.au/asx/v2/statistics/announcements.do"
ASX_DISPLAY_BASE = "https://www.asx.com.au"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 "
    "ASXAnnualBulk/1.0"
)

@dataclass(slots=True)
class Settings:
    output_dir: Path = Path("output")
    start_year: int = 2017
    end_year: int = 2025
    metadata_workers: int = 10
    metadata_rps: float = 3.0
    download_workers: int = 6
    download_rps: float = 3.0
    timeout: float = 45.0
    retries: int = 5
    chunk_size: int = 1024 * 1024
    capture_following_year: bool = True
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


def require_terms_acknowledgement() -> None:
    if os.environ.get("ASX_ACKNOWLEDGE_TERMS", "").strip() != "1":
        raise RuntimeError(
            "ASX network access is disabled until you review ASX's terms and set "
            "ASX_ACKNOWLEDGE_TERMS=1. ASX states that commercial use/aggregation "
            "requires its express written authority. This tool does not bypass login, "
            "paywalls, or access controls."
        )
