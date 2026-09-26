from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

COUNTRY_ISO3 = "CAN"
MIC_TSX = "XTSE"
MIC_TSXV = "XTSX"
MIC_NEX = "XTNX"
DEFAULT_START_YEAR = 2017
DEFAULT_END_YEAR = 2025
USER_AGENT = "ZETA-Canada-Annual-Reports/1.0 (+research data pipeline; contact configured by operator)"


def require_ack(var: str, purpose: str) -> None:
    if os.environ.get(var) != "1":
        raise RuntimeError(
            f"Network access for {purpose} is disabled until {var}=1 is set. "
            "Review the source terms/licence and use only if your intended access is authorized."
        )

@dataclass(slots=True)
class Settings:
    work_dir: Path = Path("work")
    zeta_root: Path = Path("GLOBAL_SUSTAINABILITY_DATABASE")
    start_year: int = DEFAULT_START_YEAR
    end_year: int = DEFAULT_END_YEAR
    language: str = "EN"
    include_french: bool = False
    metadata_workers: int = 8
    download_workers: int = 8
    metadata_rps: float = 2.0
    download_rps: float = 4.0
    timeout: float = 60.0
    retries: int = 5
    chunk_size: int = 1024 * 1024
    min_pdf_bytes: int = 50_000
    min_pages: int = 5
    shard_count: int = 1
    shard_index: int = 0
    obey_robots: bool = True
    max_site_pages: int = 30
    max_site_depth: int = 2

    @property
    def db_path(self) -> Path:
        return self.work_dir / "harvest.sqlite3"

    @property
    def audit_dir(self) -> Path:
        return self.work_dir / "audit"

    @property
    def staging_dir(self) -> Path:
        return self.zeta_root / COUNTRY_ISO3

    @property
    def source_cache(self) -> Path:
        return self.work_dir / "source_cache"
